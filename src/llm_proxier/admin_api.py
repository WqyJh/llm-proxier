"""Admin API endpoints for the HTML admin interface."""

import json
import math
import os
import secrets
import tempfile
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from llm_proxier.config import settings
from llm_proxier.database import RequestLog, async_session

router = APIRouter(prefix="/api/admin")

# Pagination constants
MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 10

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


def escape_fts5_query(query: str) -> str:
    """Escape a search query for FTS5 MATCH syntax.

    FTS5 has special operators that can cause parsing errors if not handled:
    - Hyphens (-) are interpreted as column reference operators
    - Quotes (") are used for phrase search
    - Parentheses () are used for grouping
    - AND/OR/NOT are boolean operators

    This function:
    1. Wraps the entire query in quotes if it contains special characters
    2. Escapes any existing quotes in the query
    3. Returns the query ready for FTS5 MATCH

    Args:
        query: Raw search query from user

    Returns:
        FTS5-safe query string

    Examples:
        "full-text search" -> "\"full-text search\""
        "simple" -> "simple"
        "test \"quoted\"" -> "\"test \\\"quoted\\\"\""
    """
    if not query:
        return query

    # Check if query needs quoting (contains special chars or spaces)
    needs_quoting = (
        " " in query
        or "-" in query
        or "(" in query
        or ")" in query
        or '"' in query
        or any(op in query.upper() for op in [" AND ", " OR ", " NOT "])
    )

    if needs_quoting:
        # Escape any existing double quotes
        escaped = query.replace('"', '""')
        # Wrap in double quotes for phrase search
        return f'"{escaped}"'

    return query


async def get_total_count(session: AsyncSession, search_query: str | None = None) -> int:
    """Get total count of logs, optionally filtered by FTS5 search.

    Args:
        session: Async database session
        search_query: Optional FTS5 search query. If provided, counts matching
                     results from the FTS5 virtual table. Otherwise counts all
                     logs in the main table.

    Returns:
        Total count of matching logs

    Note:
        When search_query is provided, uses FTS5 MATCH operator for efficient
        counting. Without search, uses standard COUNT query on main table.
    """
    if search_query:
        # Escape query for FTS5 syntax
        safe_query = escape_fts5_query(search_query)

        # Count FTS search results
        fts_stmt = text(
            """
            SELECT COUNT(*) FROM request_logs_fts
            WHERE request_logs_fts MATCH :query
        """
        )
        result = await session.execute(fts_stmt, {"query": safe_query})
        count = result.scalar() or 0
    else:
        # For large tables, use estimated count or limit to recent logs
        # This avoids full table scan which is slow on large datasets
        stmt = select(func.count()).select_from(RequestLog)
        result = await session.execute(stmt)
        count = result.scalar() or 0

    return count or 0


async def get_total_pages(
    session: AsyncSession, page_size: int = DEFAULT_PAGE_SIZE, search_query: str | None = None
) -> int:
    """Calculate total pages for pagination.

    Args:
        session: Async database session
        page_size: Number of items per page
        search_query: Optional FTS5 search query

    Returns:
        Total number of pages (rounded up)

    Note:
        Uses get_total_count() internally, which handles both search and
        non-search scenarios efficiently.
    """
    count = await get_total_count(session, search_query)
    return math.ceil(count / page_size) if count > 0 else 0


async def fetch_logs(
    session: AsyncSession, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE, search_query: str | None = None
) -> list[RequestLog]:
    """Fetch logs for a specific page, optionally filtered by FTS5 search.

    Args:
        session: Async database session
        page: Page number (1-indexed)
        page_size: Number of items per page
        search_query: Optional FTS5 search query

    Returns:
        List of RequestLog objects, ordered by timestamp (descending)

    Algorithm:
        Without search:
            SELECT * FROM request_logs ORDER BY timestamp DESC LIMIT ? OFFSET ?

        With search:
            1. Query FTS5 table for matching rowids with ranking
               SELECT rowid FROM request_logs_fts WHERE MATCH ? ORDER BY rank LIMIT ? OFFSET ?
            2. Fetch full log objects by rowids
               SELECT * FROM request_logs WHERE id IN (rowids) ORDER BY timestamp DESC

    Note:
        When searching, results are ranked by FTS5 relevance, then ordered by
        timestamp for consistent pagination.
    """
    offset = (page - 1) * page_size

    if search_query:
        # Escape query for FTS5 syntax
        safe_query = escape_fts5_query(search_query)

        # Use FTS5 search
        # First get matching rowids from FTS table
        fts_stmt = text(
            """
            SELECT rowid FROM request_logs_fts
            WHERE request_logs_fts MATCH :query
            ORDER BY rank
            LIMIT :limit OFFSET :offset
        """
        )

        fts_result = await session.execute(fts_stmt, {"query": safe_query, "limit": page_size, "offset": offset})
        rowids = [row[0] for row in fts_result.fetchall()]

        if not rowids:
            return []

        # Get full log objects by rowids
        stmt = select(RequestLog).where(RequestLog.id.in_(rowids)).order_by(desc(RequestLog.timestamp))
        result = await session.execute(stmt)
        return list(result.scalars().all())
    else:
        # Original pagination without search
        stmt = select(RequestLog).order_by(desc(RequestLog.timestamp)).offset(offset).limit(page_size)
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
    page_size: int = DEFAULT_PAGE_SIZE,
    tz: int = 0,
    search: str | None = None,
):
    """Get paginated logs with timezone adjustment and optional FTS5 search.

    Args:
        request: FastAPI request object (for session verification)
        page: Page number (1-indexed)
        page_size: Items per page (1-100)
        tz: Timezone offset in minutes (positive for east of UTC)
        search: Optional FTS5 search query

    Returns:
        {
            "logs": [...],           # List of log entries for current page
            "page": 1,               # Current page number
            "total_pages": 5,        # Total pages
            "total_count": 47        # Total matching logs
        }

    Search Syntax:
        - Basic: "keyword" - matches any field containing keyword
        - Phrase: "exact phrase" - matches exact phrase
        - Boolean: "word1 AND word2" - both words required
        - OR: "word1 OR word2" - either word
        - NOT: "NOT word" - exclude results

    Example:
        GET /api/admin/logs?page=1&page_size=20&search=weather&tz=480

    Note:
        - Requires valid session token via X-Session-Token header
        - Timezone offset adjusts displayed timestamps
        - Search uses FTS5 for high-performance full-text search
    """
    # Verify session
    get_current_user(request)

    # Validate page_size
    if page_size < MIN_PAGE_SIZE or page_size > MAX_PAGE_SIZE:
        raise HTTPException(status_code=400, detail=f"page_size must be between {MIN_PAGE_SIZE} and {MAX_PAGE_SIZE}")

    async with async_session() as session:
        total_count = await get_total_count(session, search)
        total_pages = await get_total_pages(session, page_size, search)
        logs = await fetch_logs(session, page, page_size, search)

    if not logs:
        return {
            "logs": [],
            "page": page,
            "total_pages": total_pages,
            "total_count": total_count,
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

    # Return only one page of data; total_pages computed from count
    return {
        "logs": data,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
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
