import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from llm_proxy.config import settings
from llm_proxy.database import RequestLog, get_db

router = APIRouter()


async def verify_api_key(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Header",
        )
    
    scheme, _, param = auth_header.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization Scheme",
        )
    
    if param != settings.PROXY_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )


async def log_interaction(
    db: AsyncSession,
    method: str,
    path: str,
    request_body: dict | None,
    response_body: str,
    status_code: int,
    fail: int = 0,
):
    log_entry = RequestLog(
        method=method,
        path=path,
        request_body=request_body,
        response_body=response_body,
        status_code=status_code,
        fail=fail,
    )
    db.add(log_entry)
    await db.commit()


@router.post("/v1/{path:path}", dependencies=[Depends(verify_api_key)])
async def proxy_openai(path: str, request: Request, db: AsyncSession = Depends(get_db)):
    # Read body
    body_bytes = await request.body()
    try:
        request_json = json.loads(body_bytes)
    except json.JSONDecodeError:
        request_json = None  # Should probably handle this, but task says "OpenAI Compatible" which implies JSON

    base = settings.UPSTREAM_BASE_URL.rstrip("/")
    if base.endswith("/v1"):
        upstream_url = f"{base}/{path}"
    else:
        upstream_url = f"{base}/v1/{path}"
    
    headers = {
        "Content-Type": "application/json",
    }
    if settings.UPSTREAM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.UPSTREAM_API_KEY}"

    # 直接透传下游的原始 body，避免 JSON 重新编码带来的任何改动
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
            fail_flag = 1 if r.status_code >= 400 else 0
            
            # Log
            # Create a new session to ensure thread safety and scope validity
            from llm_proxy.database import async_session
            async with async_session() as session:
                await log_interaction(
                    session,
                    request.method,
                    path,
                    request_json,
                    response_text,
                    r.status_code,
                    fail_flag,
                )
                
    return StreamingResponse(
        stream_wrapper(),
        status_code=r.status_code,
        media_type=r.headers.get("content-type"),
        background=None # Logging is handled in finally block of generator
    )
