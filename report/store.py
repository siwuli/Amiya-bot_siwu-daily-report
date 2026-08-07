# -*- coding: utf-8 -*-
"""消息记录存储：SQLite（stdlib sqlite3，无第三方依赖）。

数据落在 AmiyaBot 根目录的 data/siwu_daily_report.db（与 mai 插件同约定）。
按 (msg_date, bot_id, group_id) 索引，报告生成后由 retention 策略清理旧数据。
"""

import os
import sqlite3
import threading

from datetime import datetime


class ReportStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id     TEXT NOT NULL DEFAULT '',
                group_id   TEXT NOT NULL,
                user_id    TEXT NOT NULL DEFAULT '',
                nickname   TEXT NOT NULL DEFAULT '',
                content    TEXT NOT NULL DEFAULT '',
                face_count INTEGER NOT NULL DEFAULT 0,
                ts         INTEGER NOT NULL,
                msg_date   TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_msg_date ON messages(msg_date, bot_id, group_id)'
        )
        self._conn.commit()

    def add_message(
        self,
        bot_id: str,
        group_id: str,
        user_id: str,
        nickname: str,
        content: str,
        face_count: int = 0,
        ts: int = None,
    ):
        content = (content or '').strip()
        if not group_id or (not content and not face_count):
            return
        if ts is None:
            ts = int(datetime.now().timestamp())
        msg_date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
        with self._lock:
            self._conn.execute(
                'INSERT INTO messages(bot_id, group_id, user_id, nickname, content, face_count, ts, msg_date) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (bot_id, group_id, user_id, nickname, content, int(face_count), int(ts), msg_date),
            )
            self._conn.commit()

    def groups_with_messages(self, msg_date: str):
        """返回当天有消息的 (bot_id, group_id) 列表"""
        with self._lock:
            cur = self._conn.execute(
                'SELECT DISTINCT bot_id, group_id FROM messages WHERE msg_date=? ORDER BY group_id',
                (msg_date,),
            )
            return list(cur.fetchall())

    def load_day(self, bot_id: str, group_id: str, msg_date: str):
        """加载某群某天全部消息（按时间升序）"""
        with self._lock:
            cur = self._conn.execute(
                'SELECT user_id, nickname, content, face_count, ts FROM messages '
                'WHERE msg_date=? AND bot_id=? AND group_id=? ORDER BY ts ASC, id ASC',
                (msg_date, bot_id, group_id),
            )
            rows = cur.fetchall()
        return [
            {
                'user_id': r[0],
                'nickname': r[1],
                'content': r[2],
                'face_count': int(r[3] or 0),
                'ts': int(r[4]),
            }
            for r in rows
        ]

    def cleanup(self, before_date: str):
        """删除早于 before_date（含）的历史数据"""
        with self._lock:
            self._conn.execute('DELETE FROM messages WHERE msg_date <= ?', (before_date,))
            self._conn.commit()

    def close(self):
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
