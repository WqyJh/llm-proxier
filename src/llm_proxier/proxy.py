import json
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from llm_proxier.config import settings
from llm_proxier.database import RequestLog, async_session

router = APIRouter()


@dataclass
class LogData:
    method: str
    path: str
    request_body: dict | None
    response_body: str
    status_code: int
    fail: int = 0


# HTTP status code constants
HTTP_STATUS_BAD_REQUEST = 400


async def verify_api_key(request: Request):
    """Verify API key from downstream requests

    Supports two authentication methods:
    - Authorization: Bearer {PROXY_API_KEY}
    - api-key: {PROXY_API_KEY}
    """
    # Try Authorization: Bearer header first
    auth_header = request.headers.get("Authorization")
    if auth_header:
        scheme, _, param = auth_header.partition(" ")
        if scheme.lower() == "bearer" and param == settings.PROXY_API_KEY:
            return True
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authorization header",
            )

    # Try api-key header
    api_key_header = request.headers.get("x-api-key") or request.headers.get("api-key")
    if api_key_header:
        if api_key_header == settings.PROXY_API_KEY:
            return True
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid api-key header",
            )

    # No valid authentication found
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication header (Authorization: Bearer or api-key)",
    )


async def log_interaction(db: AsyncSession, data: LogData):
    log_entry = RequestLog(**data.__dict__)
    db.add(log_entry)
    await db.commit()


async def _proxy_request(path: str, request: Request, upstream_prefix: str = "/v1"):
    """通用的请求转发函数

    Args:
        path: 请求路径
        request: FastAPI 请求对象
        upstream_prefix: 上游路径前缀 (/v1 或 /anthropic)
    """
    # Read body
    body_bytes = await request.body()
    try:
        request_json = json.loads(body_bytes)
    except json.JSONDecodeError:
        request_json = None

    base = settings.UPSTREAM_BASE_URL.rstrip("/")
    upstream_url = f"{base}{upstream_prefix}/{path}"

    headers = {
        "Content-Type": "application/json",
    }

    # 根据上游路径前缀设置不同的认证头
    if settings.UPSTREAM_API_KEY:
        if upstream_prefix == "/anthropic":
            headers["api-key"] = settings.UPSTREAM_API_KEY
        else:  # /v1
            headers["Authorization"] = f"Bearer {settings.UPSTREAM_API_KEY}"

    # 直接透传下游的原始 body,避免 JSON 重新编码带来的任何改动
    body_bytes = await request.body()

    client = httpx.AsyncClient()
    req = client.build_request(
        method=request.method,
        url=upstream_url,
        headers=headers,
        content=body_bytes,
        timeout=60.0,
    )

    r = await client.send(req, stream=True)

    async def stream_wrapper():
        full_response = []
        try:
            async for chunk in r.aiter_bytes():
                full_response.append(chunk)
                yield chunk
        finally:
            await r.aclose()
            await client.aclose()

            response_text = b"".join(full_response).decode("utf-8", errors="replace")
            fail_flag = 1 if r.status_code >= HTTP_STATUS_BAD_REQUEST else 0

            # Log
            # Create a new session to ensure thread safety and scope validity
            async with async_session() as session:
                await log_interaction(
                    session,
                    LogData(
                        method=request.method,
                        path=path,
                        request_body=request_json,
                        response_body=response_text,
                        status_code=r.status_code,
                        fail=fail_flag,
                    ),
                )

    return StreamingResponse(
        stream_wrapper(),
        status_code=r.status_code,
        media_type=r.headers.get("content-type"),
        background=None,  # Logging is handled in finally block of generator
    )


@router.get("/v1/models", dependencies=[Depends(verify_api_key)])
async def proxy_models(request: Request):
    """Proxy /v1/models endpoint to upstream /v1/models"""
    return await _proxy_request("models", request, "/v1")


@router.post("/v1/{path:path}", dependencies=[Depends(verify_api_key)])
async def proxy_openai(path: str, request: Request):
    """Proxy /v1/{path} endpoint to upstream /v1/{path}"""
    return await _proxy_request(path, request, "/v1")


@router.post("/anthropic/{path:path}", dependencies=[Depends(verify_api_key)])
async def proxy_anthropic(path: str, request: Request):
    """Proxy /anthropic/{path} endpoint to upstream /anthropic/{path}"""
    return await _proxy_request(path, request, "/anthropic")
