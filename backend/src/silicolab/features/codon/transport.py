"""Cancellable remote HTTP transport for desktop/backend jobs."""
import json
from urllib.error import HTTPError

from silicolab.features.codon import client as codon


async def optimize_remote(payload, *, endpoint=None, timeout=120, max_response_bytes=None):
    # Import only when a remote task actually starts; local-only sessions do not
    # pay the HTTP client import/memory cost or create executor threads.
    import httpx
    url = endpoint or codon.BASE_URL + '/toDnaAjaxCodon'
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=endpoint is None, trust_env=False) as client:
            if max_response_bytes is None:
                response = await client.post(url, json=payload, headers={'Accept': 'application/json'})
            else:
                async with client.stream('POST', url, json=payload, headers={'Accept': 'application/json'}) as stream:
                    chunks, size = [], 0
                    async for chunk in stream.aiter_bytes():
                        size += len(chunk)
                        if size > max_response_bytes:
                            raise codon.OptimizationError('远端响应超过协议上限')
                        chunks.append(chunk)
                    response = httpx.Response(stream.status_code, content=b''.join(chunks), request=stream.request)
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
