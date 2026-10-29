"""Cancellable remote HTTP transport for desktop/backend jobs."""
import json
from urllib.error import HTTPError

from silicolab.features.codon import client as codon


async def optimize_remote(payload):
    # Import only when a remote task actually starts; local-only sessions do not
    # pay the HTTP client import/memory cost or create executor threads.
    import httpx
    url = codon.BASE_URL + '/toDnaAjaxCodon'
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.post(url, json=payload, headers={'Accept': 'application/json'})
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        cause = HTTPError(url, exc.response.status_code, exc.response.reason_phrase, {}, None)
        raise codon.OptimizationError(f'接口返回 HTTP {exc.response.status_code}：/toDnaAjaxCodon') from cause
    except httpx.RequestError as exc:
        raise codon.OptimizationError(f'请求失败：{type(exc).__name__}；请确认网络后再重试') from exc
    try:
        return json.loads(response.content.decode('utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise codon.OptimizationError('接口未返回有效 JSON，网站的接口或登录要求可能已改变') from exc
