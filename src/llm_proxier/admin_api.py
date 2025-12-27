"""Admin API endpoints for the HTML admin interface."""

import json
import math
import os
import secrets
import tempfile
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from llm_proxier.config import settings
from llm_proxier.database import RequestLog, async_session

router = APIRouter(prefix="/api/admin")

# Simple in-memory session store (in production, use Redis or database)
_active_sessions = {}


def generate_session_token():
    """Generate a secure session token."""
    return secrets.token_urlsafe(32)


def verify_session(token: str | None = None):
    """Verify session token."""
    if not token:
        return False

    session_data = _active_sessions.get(token)
    if not session_data:
        return False

    # Check if session expired (24 hours)
    if datetime.now(UTC) > session_data["expires_at"]:
        del _active_sessions[token]
        return False

    # Extend session
    session_data["expires_at"] = datetime.now(UTC) + timedelta(hours=24)
    return True


def get_current_user(request: Request):
    """Get current user from session token."""
    token = request.headers.get("X-Session-Token")
    if not verify_session(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    return _active_sessions[token]["username"]


async def get_total_pages(session: AsyncSession) -> int:
    """Get total pages of logs."""
    stmt = select(func.count()).select_from(RequestLog)
    result = await session.execute(stmt)
    count = result.scalar() or 0
    return math.ceil(count / 10)  # PAGE_SIZE = 10


async def fetch_logs(session: AsyncSession, page: int = 1) -> list[RequestLog]:
    """Fetch logs for a specific page."""
    offset = (page - 1) * 10
    stmt = select(RequestLog).order_by(desc(RequestLog.timestamp)).offset(offset).limit(10)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def parse_streaming_response(response_body: str | None) -> list[dict] | None:
    """Parse SSE streaming response format."""
    if response_body is None or not isinstance(response_body, str):
        return None

    if not (response_body.startswith("data: ") and "\n\n" in response_body):
        return None

    lines = response_body.split("\n\n")
    chunks: list[dict] = []
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if not stripped_line.startswith("data: "):
            return None
        json_str = stripped_line[6:].strip()
        if json_str == "[DONE]":
            continue
        try:
            chunk = json.loads(json_str)
        except json.JSONDecodeError:
            return None
        if not isinstance(chunk, dict | list):
            return None
        chunks.append(chunk)

    return chunks or None


@router.get("/check")
async def check_auth(request: Request):
    """Check if authentication is valid using session token."""
    token = request.headers.get("X-Session-Token")
    if verify_session(token):
        return {"status": "ok", "user": _active_sessions[token]["username"]}
    raise HTTPException(status_code=401, detail="Invalid session")


@router.post("/login")
async def login(request: Request):
    """Login endpoint - creates session token."""
    body = await request.json()
    username = body.get("username")
    password = body.get("password")

    if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
        token = generate_session_token()
        _active_sessions[token] = {"username": username, "expires_at": datetime.now(UTC) + timedelta(hours=24)}
        return {"status": "success", "token": token, "message": "Logged in successfully"}

    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/logs")
async def get_logs(
    request: Request,
    page: int = 1,
    tz: int = 0,
):
    """Get paginated logs with timezone adjustment."""
    # Verify session
    get_current_user(request)

    async with async_session() as session:
        total_pages = await get_total_pages(session)
        logs = await fetch_logs(session, page)

    if not logs:
        return {
            "logs": [],
            "page": page,
            "total_pages": total_pages,
            "total_count": 0,
        }

    # Format data
    data = []
    for log in logs:
        # Apply timezone offset
        adjusted_timestamp = log.timestamp.replace(tzinfo=None)
        adjusted_timestamp = adjusted_timestamp.replace(tzinfo=UTC)
        adjusted_timestamp = adjusted_timestamp + timedelta(minutes=tz)

        data.append(
            {
                "id": log.id,
                "timestamp": adjusted_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "method": log.method,
                "path": log.path,
                "status_code": log.status_code,
                "fail": log.fail,
                "request_body": log.request_body,
                "response_body": log.response_body,
            }
        )

    return {
        "logs": data,
        "page": page,
        "total_pages": total_pages,
        "total_count": len(data),
    }


@router.post("/export/selected")
async def export_selected(
    request: Request,
):
    """Export selected logs."""
    # Verify session
    get_current_user(request)

    body = await request.json()
    ids = body.get("ids", [])
    tz = body.get("tz", 0)

    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided")

    async with async_session() as session:
        stmt = select(RequestLog).where(RequestLog.id.in_(ids)).order_by(desc(RequestLog.timestamp))
        result = await session.execute(stmt)
        logs = result.scalars().all()

    if not logs:
        raise HTTPException(status_code=404, detail="No logs found for provided IDs")

    # Prepare export data
    export_data = []
    for log in logs:
        adjusted_timestamp = log.timestamp.replace(tzinfo=None)
        adjusted_timestamp = adjusted_timestamp.replace(tzinfo=UTC)
        adjusted_timestamp = adjusted_timestamp + timedelta(minutes=tz)

        export_data.append(
            {
                "id": log.id,
                "timestamp": adjusted_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "method": log.method,
                "path": log.path,
                "status_code": log.status_code,
                "fail": log.fail,
                "request_body": log.request_body,
                "response_body": log.response_body,
            }
        )

    # Create temporary file
    fd, path = tempfile.mkstemp(suffix=".json", prefix="export_")
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    # Return download URL
    return {"download_url": f"/api/admin/download/{path.split('/')[-1]}"}


@router.get("/export/all")
async def export_all(
    request: Request,
    tz: int = 0,
):
    """Export all logs."""
    # Verify session
    get_current_user(request)

    async with async_session() as session:
        stmt = select(RequestLog).order_by(desc(RequestLog.timestamp))
        result = await session.execute(stmt)
        logs = result.scalars().all()

    if not logs:
        raise HTTPException(status_code=404, detail="No logs found")

    # Prepare export data
    export_data = []
    for log in logs:
        adjusted_timestamp = log.timestamp.replace(tzinfo=None)
        adjusted_timestamp = adjusted_timestamp.replace(tzinfo=UTC)
        adjusted_timestamp = adjusted_timestamp + timedelta(minutes=tz)

        export_data.append(
            {
                "id": log.id,
                "timestamp": adjusted_timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "method": log.method,
                "path": log.path,
                "status_code": log.status_code,
                "fail": log.fail,
                "request_body": log.request_body,
                "response_body": log.response_body,
            }
        )

    # Create temporary file
    fd, path = tempfile.mkstemp(suffix=".json", prefix="export_all_")
    with open(fd, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)

    # Return download URL
    return {"download_url": f"/api/admin/download/{path.split('/')[-1]}"}


@router.get("/download/{filename}")
async def download_file(
    request: Request,
    filename: str,
):
    """Download exported file."""
    # Verify session
    get_current_user(request)

    # Get all temp files and find matching one
    temp_dir = tempfile.gettempdir()
    for root, _, files in os.walk(temp_dir):
        for file in files:
            if file == filename:
                file_path = os.path.join(root, file)
                return FileResponse(
                    path=file_path,
                    media_type="application/json",
                    filename=filename,
                )

    raise HTTPException(status_code=404, detail="File not found")
