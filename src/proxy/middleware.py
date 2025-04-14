import json
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from .cache import Cache


async def caching_middleware(request: Request, call_next, cache: Cache):
    if request.method != "GET":
        return await call_next(request)

    cache_key = f"cache:{request.url.path}"

    # Check for cached content
    if cached := await cache.get(cache_key):
        return JSONResponse(content=cached)

    # Process request and retrieve response
    response = await call_next(request)
    if response.status_code != 200:
        return response

    # Collect response body
    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    # Check content type
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    try:
        # Parse JSON and cache the content
        content = json.loads(body.decode("utf-8"))
        await cache.set(cache_key, content)
        return JSONResponse(content=content, status_code=200)
    except (ValueError, TypeError, UnicodeDecodeError) as e:
        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
