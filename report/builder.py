# -*- coding: utf-8 -*-
"""报告生成：LLM 提示词 / 结果归一化 / 本地降级 / Markdown 渲染。

LLM 只负责「理解」（话题聚类、称号起名、金句点评），
统计数字一律由 stats.compute_stats 本地计算，保证准确。
未配置 LLM 或调用失败时逐段回退到本地规则版本，日报始终可发。
"""

import re

from collections import Counter

try:
    import jieba

    _HAS_JIEBA = True
except Exception:  # pragma: no cover
    _HAS_JIEBA = False

from .stats import count_emojis

STOPWORDS = {
    '的', '了', '是', '在', '我', '你', '他', '她', '它', '们', '这', '那', '个',
    '就', '都', '也', '很', '会', '说', '去', '来', '到', '和', '与', '跟', '对',
    '从', '被', '把', '让', '给', '有', '没', '不', '要', '能', '可以', '一下',
    '什么', '怎么', '为什么', '这个', '那个', '这样', '那样', '因为', '所以',
    '但是', '然后', '还是', '已经', '现在', '今天', '我们', '你们', '他们',
    '大家', '就是', '一个', '真的', '感觉', '觉得', '知道', '好像', '时候',
    '多少', '以及', '或者', '如果', '虽然', '而且', '其实', '应该', '可能',
}

LOCAL_TITLE_RULES = [
    # (判定函数, 称号, MBTI, 理由模板)
    (
        lambda u: u['msg_count'] >= 3 and (u['emoji'] / u['msg_count']) >= 0.2,
        '表情包军火库', 'ESFP',
        '发言里表情比例较高，是个喜欢用表情包表达自己的人',
    ),
    (
        lambda u: u['msg_count'] <= 10 and u['avg_len'] >= 20,
        '沉默终结者', 'INTJ',
        '发言频率低，但每次平均字数较多，可能是个深思熟虑的人',
    ),
    (
        lambda u: u['avg_len'] >= 15,
        '评论家', 'ENTJ',
        '平均字数较长，喜欢深入评论和讨论',
    ),
    (
        lambda u: u['reply_ratio'] >= 0.35,
        '互动达人', 'ENFP',
        '回复比例较高，喜欢与他人互动',
    ),
    (
        lambda u: u['avg_len'] < 8 and u['emoji'] == 0,
        '技术专家', 'INTJ',
        '发言简洁直接、没有表情，可能专注于技术干货',
    ),
]
LOCAL_TITLE_DEFAULT = ('群聊水怪', 'ESTP', '发言稳定、活跃度不错，是群聊的常驻选手')


def downsample(messages, limit: int = 150):
    """对话样本过多时均匀采样 + 保留结尾，避免超出 LLM 上下文。"""
    if limit <= 0 or len(messages) <= limit:
        return list(messages)
    step = max(1, len(messages) // limit)
    sampled = messages[::step][: limit - 5]
    tail = messages[-5:]
    seen = {id(m) for m in sampled}
    for m in tail:
        if id(m) not in seen:
            sampled.append(m)
    return sampled


def bible_candidates(messages, limit: int = 20):
    """本地预筛「名场面」候选：按 长度 + 被回复加成 排序，去重。"""
    seen = set()
    scored = []
    for m in messages:
        content = str(m.get('content') or '').strip()
        if not content or len(content) < 4:
            continue
        if content in seen:
            continue
        seen.add(content)
        score = len(content)
        if int(m.get('reply', 0)) or m.get('face_count'):
            score += 8
        scored.append((score, content, str(m.get('nickname') or '群友')))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {'quote': c, 'speaker': n, 'score': s}
        for s, c, n in scored[:limit]
    ]


def _user_rows(stats):
    """把统计转成便于排序/筛选的用户行列表"""
    rows = []
    for uid, u in stats.get('users', {}).items():
        if u['msg_count'] <= 0:
            continue
        avg_len = u['chars'] / u['msg_count']
        rows.append(
            {
                'user_id': uid,
                'name': u['name'] or uid,
                'msg_count': u['msg_count'],
                'avg_len': avg_len,
                'emoji_ratio': u['emoji'] / u['msg_count'],
                'reply_ratio': u['reply_count'] / u['msg_count'],
                'emoji': u['emoji'],
            }
        )
    rows.sort(key=lambda r: (r['msg_count'], r['avg_len']), reverse=True)
    return rows


# ---------------- 本地降级 ----------------

def local_topics(messages, count: int = 5):
    """无 LLM 时的热门话题：jieba 高频词聚类。"""
    if not _HAS_JIEBA:
        return [{'title': '今日群聊', 'participants': [], 'summary': '群聊整体氛围活跃。'}]
    word_counter = Counter()
    word_msgs = {}
    for m in messages:
        content = str(m.get('content') or '').strip()
        if not content:
            continue
        words = set()
        for w in jieba.lcut(content.lower()):
            w = w.strip()
            if len(w) < 2 or w in STOPWORDS or w.isdigit():
                continue
            if re.fullmatch(r'[\w_.\-/@%]+', w) and not re.search(r'[\u4e00-\u9fff]', w):
                # 纯英文/数字词：保留较长的（>=4），避免噪音
                if len(w) < 4:
                    continue
            words.add(w)
        for w in words:
            word_counter[w] += 1
            word_msgs.setdefault(w, []).append(m)

    topics = []
    for word, _ in word_counter.most_common(max(1, count * 3)):
        related = word_msgs.get(word, [])
        participants = []
        seen = set()
        for m in related:
            name = str(m.get('nickname') or '群友')
            if name not in seen:
                seen.add(name)
                participants.append(name)
        rep = max((str(m.get('content') or '') for m in related), key=len, default='')
        rep = re.sub(r'\s+', ' ', rep)[:40]
        summary = f'群友围绕「{word}」相关话题展开讨论'
        if rep:
            summary += f'，例如「{rep}…」'
        summary += '。'
        topics.append(
            {
                'title': f'关于「{word}」',
                'participants': participants[:6],
                'summary': summary,
            }
        )
        if len(topics) >= count:
            break
    if not topics:
        topics.append(
            {
                'title': '今日群聊',
                'participants': [],
                'summary': '群聊整体氛围活跃，具体话题可开启 LLM 生成更详细的分析。',
            }
        )
    return topics


def local_titles(stats, count: int = 6):
    """无 LLM 时的群友称号：按行为特征规则匹配。"""
    rows = [r for r in _user_rows(stats) if r['msg_count'] >= 3][:count]
    titles = []
    for r in rows:
        title, mbti, reason = LOCAL_TITLE_DEFAULT
        for check, t, m, why in LOCAL_TITLE_RULES:
            if check(r):
                title, mbti, reason = t, m, why
                break
        titles.append(
            {
                'name': r['name'],
                'title': title,
                'mbti': mbti,
                'reason': f'发言{r["msg_count"]}条，{reason}，适合「{title}」称号。',
            }
        )
    return titles


def local_bible(messages, count: int = 3):
    """无 LLM 时的群圣经：取长度+热度最高的几句。"""
    candidates = bible_candidates(messages, limit=max(6, count * 4))
    comments = [
        '这句话言简意赅，却把全场气氛拉满，成为今日群圣经。',
        '一句话信息量拉满，今天被大家反复品味。',
        '精准戳中今天群聊的情绪点，堪称金句。',
    ]
    bible = []
    for i, c in enumerate(candidates[:count]):
        bible.append(
            {
                'quote': c['quote'],
                'speaker': c['speaker'],
                'comment': comments[i % len(comments)],
            }
        )
    if not bible:
        bible.append(
            {
                'quote': '（今天没有特别突出的金句）',
                'speaker': '群聊',
                'comment': '开启 LLM 后可以挖掘更多有梗的发言。',
            }
        )
    return bible


# ---------------- LLM 提示词 ----------------

def _user_stat_lines(stats):
    lines = []
    for r in _user_rows(stats):
        lines.append(
            f'- {r["name"]}: 发言{r["msg_count"]}条, 平均每句{r["avg_len"]:.0f}字, '
            f'表情比例{r["emoji_ratio"] * 100:.0f}%, 回复比例{r["reply_ratio"] * 100:.0f}%'
        )
    return lines


def build_llm_prompt(stats, messages, candidates, date_str, topics_count, titles_count, bible_count):
    hour = stats['most_active_hour']
    lines = [f'你是群聊日常分析助手。请根据 {date_str} 当天的群聊数据生成日报的分析部分。']
    lines.append('')
    lines.append('<基础统计>')
    lines.append(f'- 消息总数: {stats["total"]}')
    lines.append(f'- 参与人数: {stats["participants"]}')
    lines.append(f'- 总字符数: {stats["total_chars"]}')
    lines.append(f'- 表情数量: {stats["emoji_total"]}')
    lines.append(f'- 最活跃时段: {hour:02d}:00-{hour + 1:02d}:00')
    lines.append('')
    lines.append('<群友行为数据>')
    lines.extend(_user_stat_lines(stats))
    lines.append('')
    lines.append('<对话样本（已截断，仅作话题参考）>')
    for m in messages:
        content = re.sub(r'\s+', ' ', str(m.get('content') or ''))[:60]
        if content:
            lines.append(f'{m.get("nickname") or "群友"}: {content}')
    lines.append('')
    lines.append('<候选名场面>')
    for i, c in enumerate(candidates[:20]):
        lines.append(f'{i + 1}. "{c["quote"]}" —— {c["speaker"]}')
    lines.append('')
    lines.append(
        f'请只输出一个 JSON 对象（不要 markdown 代码块，不要任何多余文字）：'
        f'{{"topics": [{{"title": "话题标题", "participants": ["参与人昵称"], "summary": "2~3句摘要"}}], '
        f'"titles": [{{"name": "昵称", "title": "称号", "mbti": "四字母人格", "reason": "用统计数字支撑的一句理由"}}], '
        f'"bible": [{{"quote": "原话", "speaker": "昵称", "comment": "一句点评"}}]}}'
    )
    lines.append('')
    lines.append(f'要求：topics 恰好 {topics_count} 个；titles 恰好 {titles_count} 个；bible 恰好 {bible_count} 条。')
    lines.append('participants 必须使用对话样本中出现过的昵称；称号要贴合群友行为特征、有梗；reason 用统计数字支撑。')
    return '\n'.join(lines)


# ---------------- 结果归一化 ----------------

def _as_list(value):
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    return []


def _clean_text(value, default=''):
    if value is None:
        return default
    text = re.sub(r'\s+', ' ', str(value)).strip()
    return text or default


def normalize_result(data, stats, messages, topics_count, titles_count, bible_count):
    """校验/清洗 LLM 结果；缺失或非法的段落回退本地实现。"""
    result = {'topics': None, 'titles': None, 'bible': None}

    topics = _as_list(data.get('topics'))
    if topics:
        result['topics'] = [
            {
                'title': _clean_text(t.get('title'), '未命名话题'),
                'participants': [
                    _clean_text(p)
                    for p in (t.get('participants') if isinstance(t.get('participants'), list) else [])
                    if _clean_text(p)
                ][:8],
                'summary': _clean_text(t.get('summary'), ''),
            }
            for t in topics[:topics_count]
        ]
        result['topics'] = [t for t in result['topics'] if t['title']]
    if not result['topics']:
        result['topics'] = local_topics(messages, topics_count)

    titles = _as_list(data.get('titles'))
    known = {r['name'] for r in _user_rows(stats)}
    if titles:
        cleaned = []
        for t in titles[:titles_count]:
            name = _clean_text(t.get('name'))
            if not name or name not in known:
                continue
            cleaned.append(
                {
                    'name': name,
                    'title': _clean_text(t.get('title'), '群聊之星'),
                    'mbti': _clean_text(t.get('mbti'), 'UNKNOWN')[:4].upper(),
                    'reason': _clean_text(t.get('reason'), ''),
                }
            )
        if cleaned:
            result['titles'] = cleaned
    if not result['titles']:
        result['titles'] = local_titles(stats, titles_count)

    bible = _as_list(data.get('bible'))
    if bible:
        result['bible'] = [
            {
                'quote': _clean_text(b.get('quote')),
                'speaker': _clean_text(b.get('speaker'), '群友'),
                'comment': _clean_text(b.get('comment')),
            }
            for b in bible[:bible_count]
        ]
        result['bible'] = [b for b in result['bible'] if b['quote']]
    if not result['bible']:
        result['bible'] = local_bible(messages, bible_count)

    return result


# ---------------- 渲染 ----------------

def render(stats, result, date_str):
    hour = stats['most_active_hour']
    lines = [
        '🎯 群聊日常分析报告',
        f'📅 {date_str}',
        '',
        '📊 基础统计',
        f'• 消息总数: {stats["total"]}',
        f'• 参与人数: {stats["participants"]}',
        f'• 总字符数: {stats["total_chars"]}',
        f'• 表情数量: {stats["emoji_total"]}',
        f'• 最活跃时段: {hour:02d}:00-{hour + 1:02d}:00',
        '',
        '💬 热门话题',
    ]
    for i, t in enumerate(result['topics'], 1):
        lines.append(f'{i}. {t["title"]}')
        lines.append(f'   参与者: {"、".join(t["participants"]) if t["participants"] else "—"}')
        if t.get('summary'):
            lines.append(f'   {t["summary"]}')
    lines.append('')
    lines.append('🏆 群友称号')
    for t in result['titles']:
        lines.append(f'• {t["name"]} - {t["title"]} ({t.get("mbti", "")})')
        if t.get('reason'):
            lines.append(f'   {t["reason"]}')
    lines.append('')
    lines.append('💬 群圣经')
    for i, b in enumerate(result['bible'], 1):
        lines.append(f'{i}. "{b["quote"]}" —— {b["speaker"]}')
        if b.get('comment'):
            lines.append(f'   {b["comment"]}')
    return '\n'.join(lines)


# ---------------- 合并转发渲染 ----------------

def render_forward(stats, result, date_str, nickname='兔兔'):
    """把日报拆成多条消息，用于 QQ 聊天记录合并转发。

    返回 node 列表：[{'nickname': str, 'text': str}, ...]
    每条 node 以 nickname 名义作为独立气泡展示，避免超长单条消息。
    """
    hour = stats['most_active_hour']

    def node(text):
        return {'nickname': nickname, 'text': text}

    nodes = [
        node('🎯 群聊日常分析报告\n' f'📅 {date_str}'),
        node(
            '📊 基础统计\n'
            f'• 消息总数: {stats["total"]}\n'
            f'• 参与人数: {stats["participants"]}\n'
            f'• 总字符数: {stats["total_chars"]}\n'
            f'• 表情数量: {stats["emoji_total"]}\n'
            f'• 最活跃时段: {hour:02d}:00-{hour + 1:02d}:00'
        ),
    ]

    if result.get('topics'):
        nodes.append(node('💬 热门话题'))
        for i, t in enumerate(result['topics'], 1):
            text = f'{i}. {t["title"]}'
            if t.get('participants'):
                text += f'\n参与者: {"、".join(t["participants"])}'
            if t.get('summary'):
                text += f'\n{t["summary"]}'
            nodes.append(node(text))

    if result.get('titles'):
        nodes.append(node('🏆 群友称号'))
        for t in result['titles']:
            text = f'{t["name"]} - {t["title"]} ({t.get("mbti", "")})'
            if t.get('reason'):
                text += f'\n{t["reason"]}'
            nodes.append(node(text))

    if result.get('bible'):
        nodes.append(node('💬 群圣经'))
        for i, b in enumerate(result['bible'], 1):
            text = f'{i}. "{b["quote"]}" —— {b["speaker"]}'
            if b.get('comment'):
                text += f'\n{b["comment"]}'
            nodes.append(node(text))

    return nodes
