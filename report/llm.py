# -*- coding: utf-8 -*-
"""OpenAI 兼容聊天客户端（默认 DeepSeek），仅用于日报生成。

未配置 API Key 时不创建实例，报告走本地降级；调用失败由上层兜底，
保证日报始终能发出来。
"""

import asyncio
import json
import re

from typing import List, Dict, Optional


class ReportLLM:
    def __init__(
        self,
        api_key: str,
        base_url: str = 'https://api.deepseek.com',
        model: str = 'deepseek-chat',
    ):
        if not api_key:
            raise ValueError('API Key 不能为空')
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self._session = None
        self._sem = asyncio.Semaphore(2)

    def _get_session(self):
        if self._session is None:
            import aiohttp

            self._session = aiohttp.ClientSession(
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json',
                },
                timeout=aiohttp.ClientTimeout(total=120),
            )
        return self._session

    async def chat(self, messages: List[Dict], max_tokens: int = 1500) -> str:
        session = self._get_session()
        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': 0.4,
            'max_tokens': max_tokens,
        }
        async with self._sem:
            async with session.post(f'{self.base_url}/chat/completions', json=payload) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f'LLM API error {resp.status}: {text[:300]}')
                data = json.loads(text)
                choices = data.get('choices') or []
                if not choices:
                    return ''
                message = choices[0].get('message') or {}
                content = message.get('content')
                if isinstance(content, list):
                    content = ''.join(
                        str(p.get('text') or '')
                        for p in content
                        if isinstance(p, dict) and p.get('type') != 'reasoning'
                    )
                return str(content or '').strip()

    async def chat_json(self, messages: List[Dict], max_tokens: int = 1500) -> Dict:
        """请求 JSON 结果并解析；失败返回 {} 由调用方逐段兜底。"""
        try:
            text = await self.chat(messages, max_tokens=max_tokens)
        except Exception:
            return {}
        return extract_json(text)

    async def close(self):
        if self._session:
            try:
                await self._session.close()
            except Exception:
                pass
            self._session = None


def extract_json(text: str) -> Dict:
    """从模型输出中提取 JSON 对象：优先整体解析，失败则截取首个 {...}"""
    text = (text or '').strip()
    if not text:
        return {}

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass

    # 去掉 markdown 代码块围栏后重试
    stripped = re.sub(r'```(?:json)?', '', text).strip()
    try:
        obj = json.loads(stripped)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass

    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            obj = json.loads(match.group(0))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}
