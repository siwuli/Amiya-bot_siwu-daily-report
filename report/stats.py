# -*- coding: utf-8 -*-
"""本地统计：消息总数 / 参与人数 / 字符数 / 表情数 / 最活跃时段 / 群友行为数据"""

import re

from collections import Counter
from datetime import datetime

# 常见 emoji 区段（含 QQ 表情码单独计数，见 face_count）
EMOJI_PATTERN = re.compile(
    '[\U0001F000-\U0001FAFF\U00002600-\U000027BF\uFE0F\u2B50\u2764\u203C\u2049\u00A9\u00AE\u2122\u2190-\u21FF\u2B00-\u2BFF]'
)

# 「回复」启发式：距上一条其他发言者的消息 ≤ REPLY_WINDOW 秒，视为互动/回复
REPLY_WINDOW = 120


def count_emojis(text: str) -> int:
    return len(EMOJI_PATTERN.findall(text or ''))


def compute_stats(messages):
    """从当天消息列表计算报告所需统计。

    返回 dict：
      total, participants, total_chars, emoji_total, most_active_hour,
      users: {user_id: {name, msg_count, chars, emoji, reply_count, ...}}
    """
    users = {}
    hour_counter = Counter()
    total_chars = 0
    emoji_total = 0

    prev_ts = None
    prev_user = None

    for m in messages:
        uid = str(m.get('user_id') or '')
        content = str(m.get('content') or '')
        ts = int(m.get('ts') or 0)
        hour = datetime.fromtimestamp(ts).hour if ts else 0
        hour_counter[hour] += 1

        chars = len(content)
        emoji = count_emojis(content) + int(m.get('face_count') or 0)
        total_chars += chars
        emoji_total += emoji

        if uid:
            u = users.setdefault(
                uid,
                {
                    'name': '',
                    'msg_count': 0,
                    'chars': 0,
                    'emoji': 0,
                    'reply_count': 0,
                },
            )
            u['name'] = str(m.get('nickname') or '') or u['name'] or uid
            u['msg_count'] += 1
            u['chars'] += chars
            u['emoji'] += emoji
            # 互动启发式
            if (
                prev_ts is not None
                and prev_user is not None
                and prev_user != uid
                and ts - prev_ts <= REPLY_WINDOW
            ):
                u['reply_count'] += 1

        prev_ts = ts
        prev_user = uid

    # 参与人数 = 有发言的非空用户
    participants = len(users)

    most_active_hour = 0
    if hour_counter:
        most_active_hour = hour_counter.most_common(1)[0][0]

    return {
        'total': len(messages),
        'participants': participants,
        'total_chars': total_chars,
        'emoji_total': emoji_total,
        'most_active_hour': most_active_hour,
        'users': users,
    }
