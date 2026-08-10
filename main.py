# -*- coding: utf-8 -*-
"""
siwu-daily-report 入口（群聊日报）

工作方式：
1. message_created 全量记录每个群的当日消息到 data/siwu_daily_report.db
2. timed_task 每分钟检查 report_time（默认 23:00），到点后对每个有消息的群生成日报
3. 统计（消息数/人数/字符/表情/活跃时段/行为数据）本地计算；
   热门话题 / 群友称号 / 群圣经 优先用 LLM（OpenAI 兼容接口）生成，
   未配置 Key 或调用失败时逐段回退本地规则版本，日报始终能发出来
4. 通过 main_bot 主动推送，不依赖任何消息事件
"""

import os
import asyncio

from datetime import datetime, timedelta

from core import AmiyaBotPluginInstance, Message, Chain, log, bot as main_bot

from .report.store import ReportStore
from .report.stats import compute_stats
from .report.builder import (
    downsample,
    bible_candidates,
    build_llm_prompt,
    normalize_result,
    local_topics,
    local_titles,
    local_bible,
    render,
)

curr_dir = os.path.dirname(os.path.abspath(__file__))

bot = AmiyaBotPluginInstance(
    name='群聊日报',
    version='1.1.1',
    plugin_id='siwu-daily-report',
    plugin_type='functional',
    description='每天定时（默认 23:00）自动生成当日群聊统计、热门话题、群友称号与群圣经报告；群内发送「兔兔今日日报」可手动触发',
    document=f'{curr_dir}/README.md',
    global_config_default=f'{curr_dir}/config_default.yaml',
    global_config_schema=f'{curr_dir}/jsonSchema.json',
)

DATA_DIR = os.path.abspath(os.path.join(curr_dir, '..', '..', 'data'))
store = ReportStore(os.path.join(DATA_DIR, 'siwu_daily_report.db'))

_llm = None
_reported_dates = set()


def _cfg(key: str, default=None):
    val = bot.get_config(key, channel_id=None)
    return default if val is None else val


def _report_enabled() -> bool:
    return bool(_cfg('report_enabled', True))


def _report_log(msg: str, force: bool = False):
    if force or bool(_cfg('report_debug_log', True)):
        log.info(f'[日报] {msg}')


def _get_llm():
    global _llm
    api_key = (_cfg('report_llm_api_key', '') or '').strip()
    if not api_key:
        return None
    if _llm is None:
        from .report.llm import ReportLLM

        base_url = (
            (_cfg('report_llm_base_url', 'https://api.deepseek.com') or 'https://api.deepseek.com').rstrip('/')
        )
        model = (_cfg('report_llm_model', 'deepseek-chat') or 'deepseek-chat').strip()
        _llm = ReportLLM(api_key, base_url=base_url, model=model)
    return _llm


def _report_time_minutes() -> tuple:
    raw = str(_cfg('report_time', '23:00') or '23:00').strip()
    try:
        hh, mm = raw.split(':')
        return (int(hh), int(mm))
    except Exception:
        return (23, 0)


def _group_allowed(group_id: str) -> bool:
    """群聊白名单/黑名单过滤：黑名单优先；白名单为空时放行所有群"""
    gid = str(group_id or '')
    blacklist = [str(g) for g in (_cfg('report_group_blacklist', []) or [])]
    if gid in blacklist:
        return False
    whitelist = [str(g) for g in (_cfg('report_group_whitelist', []) or [])]
    if whitelist and gid not in whitelist:
        return False
    return True


def _now_str(now: datetime) -> str:
    return now.strftime('%Y年%m月%d日')


@bot.message_created
async def _record_message(data: Message, _):
    """记录群消息（含机器人自己的），供当日日报统计"""
    if not _report_enabled():
        return
    if getattr(data, 'is_direct', False):
        return

    group_id = str(data.channel_id or '')
    if not group_id:
        return

    bot_id = str(getattr(getattr(data, 'instance', None), 'appid', '') or '')
    user_id = str(data.user_id or '')
    original = (getattr(data, 'text_original', None) or data.text or '').strip()
    face_count = len(getattr(data, 'face', None) or [])

    if not original and not face_count:
        return

    if user_id == bot_id:
        nickname = '兔兔'
    else:
        nickname = getattr(data, 'nickname', None) or '群友'

    try:
        store.add_message(
            bot_id=bot_id,
            group_id=group_id,
            user_id=user_id,
            nickname=nickname,
            content=original,
            face_count=face_count,
            ts=getattr(data, 'time', None) or int(datetime.now().timestamp()),
        )
    except Exception as e:
        log.warning(f'[日报] 记录消息失败: {e}')


def _resolve_instance(bot_id: str):
    """多账号时取对应实例；单账号直接返回全局 bot"""
    try:
        return main_bot[bot_id]
    except Exception:
        return main_bot


async def _report_group(bot_id: str, group_id: str, msg_date: str, now: datetime):
    messages = store.load_day(bot_id, group_id, msg_date)
    if not messages:
        return

    stats = compute_stats(messages)
    topics_count = max(1, int(_cfg('report_topics_count', 5)))
    titles_count = max(1, int(_cfg('report_titles_count', 6)))
    bible_count = max(1, int(_cfg('report_bible_count', 3)))
    max_transcript = max(10, int(_cfg('report_max_transcript', 150)))

    result = None
    llm = _get_llm()
    if llm is not None:
        try:
            prompt = build_llm_prompt(
                stats,
                downsample(messages, max_transcript),
                bible_candidates(messages),
                _now_str(now),
                topics_count,
                titles_count,
                bible_count,
            )
            data = await llm.chat_json([{'role': 'user', 'content': prompt}], max_tokens=8000)
            if data:
                result = normalize_result(
                    data, stats, messages, topics_count, titles_count, bible_count
                )
        except Exception as e:
            log.warning(f'[日报] LLM 生成失败，回退本地: {e}')

    if result is None:
        result = {
            'topics': local_topics(messages, topics_count),
            'titles': local_titles(stats, titles_count),
            'bible': local_bible(messages, bible_count),
        }

    report_text = render(stats, result, _now_str(now))
    await _send_report(bot_id, group_id, report_text)
    _report_log(f'日报已生成 group={group_id} msgs={stats["total"]} len={len(report_text)}', force=True)


async def _send_report(bot_id: str, group_id: str, text: str):
    instance = _resolve_instance(bot_id)
    if instance is None:
        log.warning(f'[日报] 找不到可用的 bot 实例，跳过 group={group_id}')
        return
    try:
        await instance.send_message(Chain().text(text), channel_id=group_id)
    except Exception as e:
        log.warning(f'[日报] 发送失败 group={group_id}: {e}')


@bot.on_message(keywords=['今日日报'], check_prefix=['兔兔'], level=5)
async def _manual_report(data: Message):
    """手动触发：在群里发送「兔兔今日日报」立即生成并推送本群当日日报"""
    if not _report_enabled():
        return
    if getattr(data, 'is_direct', False):
        return

    bot_id = str(getattr(getattr(data, 'instance', None), 'appid', '') or '')
    group_id = str(data.channel_id or '')
    if not group_id:
        return

    # 忽略机器人自己转发的消息
    user_id = str(getattr(data, 'user_id', '') or '')
    if user_id == bot_id or user_id == 'bot':
        return

    if not _group_allowed(group_id):
        return

    now = datetime.now()
    msg_date = now.strftime('%Y-%m-%d')
    if not store.load_day(bot_id, group_id, msg_date):
        await _send_report(bot_id, group_id, '今天还没有任何消息记录，无法生成日报～')
        return

    await _report_group(bot_id, group_id, msg_date, now)


@bot.timed_task(each=60, sub_tag='daily_report')
async def _report_tick(_):
    if not _report_enabled():
        return

    now = datetime.now()
    hh, mm = _report_time_minutes()
    if (now.hour, now.minute) != (hh, mm):
        return

    msg_date = now.strftime('%Y-%m-%d')
    if msg_date in _reported_dates:
        return
    _reported_dates.add(msg_date)
    # 防内存无限增长：只保留最近 30 天标记
    if len(_reported_dates) > 30:
        for d in sorted(_reported_dates)[:-30]:
            _reported_dates.discard(d)

    # 定期清理过期历史数据
    try:
        retention = max(1, int(_cfg('report_retention_days', 7)))
        cutoff = (now - timedelta(days=retention)).strftime('%Y-%m-%d')
        store.cleanup(cutoff)
    except Exception as e:
        log.warning(f'[日报] 历史清理失败: {e}')

    groups = store.groups_with_messages(msg_date)
    groups = [(b, g) for b, g in groups if _group_allowed(g)]
    _report_log(f'到点触发日报 date={msg_date} groups={len(groups)}', force=True)
    if not groups:
        return

    for bot_id, group_id in groups:
        try:
            await _report_group(bot_id, group_id, msg_date, now)
        except Exception as e:
            log.warning(f'[日报] 群 {group_id} 报告生成失败: {e}')
