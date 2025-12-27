import importlib.resources
import sys
import time
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from llm_proxier.admin_api import router as admin_api_router
from llm_proxier.config import settings
from llm_proxier.database import init_db
from llm_proxier.proxy import router as proxy_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if settings.AUTO_MIGRATE_DB:
        await init_db()
    yield
    # Shutdown


app = FastAPI(title="LLM Proxier", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Use importlib.resources to access packaged assets
    assets_path = importlib.resources.files("llm_proxier") / "assets" / "icon.svg"
    return FileResponse(str(assets_path))


# Mount Static Files
# Use importlib.resources to access packaged assets
assets_path = importlib.resources.files("llm_proxier") / "assets"
app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

# Mount Proxy Router
app.include_router(proxy_router)

# Mount Admin API Router
app.include_router(admin_api_router)


@app.get("/admin", include_in_schema=False)
async def admin_page():
    """Serve the HTML admin page."""
    # Use importlib.resources to access packaged templates
    templates_path = importlib.resources.files("llm_proxier") / "templates" / "admin.html"
    with open(templates_path, encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@app.get("/admin/start", include_in_schema=False)
async def admin_start():
    """Admin start page with helpful information."""
    # Use importlib.resources to access packaged templates
    templates_path = importlib.resources.files("llm_proxier") / "templates" / "admin_start.html"
    with open(templates_path, encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@app.get("/api/health", include_in_schema=False)
async def health_check():
    """Health check endpoint."""
    return JSONResponse(
        content={"status": "healthy", "service": "LLM Proxier", "admin_url": "/admin", "api_url": "/api/admin"}
    )


def create_app():
    """Create and configure the FastAPI application."""
    return app


def _parse_args():
    """Parse command line arguments."""
    host = "0.0.0.0"
    port = 8000
    open_browser = True
    show_help = False

    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--host" and i + 1 < len(args):
            host = args[i + 1]
        elif arg == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                print(f"Invalid port number: {args[i + 1]}")
                sys.exit(1)
        elif arg == "--no-browser":
            open_browser = False
        elif arg in ("-h", "--help"):
            show_help = True

    return host, port, open_browser, show_help


def _print_help():
    """Print help message."""
    print("Usage: llm-proxier [--host HOST] [--port PORT] [--no-browser]")
    print("Options:")
    print("  --host HOST      Bind to this address (default: 0.0.0.0)")
    print("  --port PORT      Bind to this port (default: 8000)")
    print("  --no-browser     Don't automatically open browser")
    print("  -h, --help       Show this help message")
    sys.exit(0)


def _print_welcome(host, port):
    """Print welcome message with server URLs."""
    display_host = "localhost" if host == "0.0.0.0" else host

    admin_url = f"http://{display_host}:{port}/admin/start"
    api_url = f"http://{display_host}:{port}/api/admin"
    health_url = f"http://{display_host}:{port}/api/health"

    print("\n" + "=" * 60)
    print("🚀 LLM Proxier Admin Server")
    print("=" * 60)
    print(f"📊 Admin Dashboard: {admin_url}")
    print(f"🔌 API Endpoints:   {api_url}")
    print(f"❤️  Health Check:    {health_url}")
    print("-" * 60)
    print("🔐 Default credentials:")
    print(f"   Username: {settings.ADMIN_USERNAME}")
    print(f"   Password: {settings.ADMIN_PASSWORD}")
    print("=" * 60)
    print("\nStarting server...")

    return admin_url


def _open_browser_if_needed(open_browser, admin_url):
    """Open browser if requested."""
    if not open_browser:
        return

    try:
        time.sleep(1.5)
        webbrowser.open(admin_url)
        print("🌐 Browser opened automatically")
    except Exception as e:
        print(f"⚠️  Could not open browser: {e}")


def main():
    """Main entry point for the llm-proxier command."""
    host, port, open_browser, show_help = _parse_args()

    if show_help:
        _print_help()

    admin_url = _print_welcome(host, port)
    _open_browser_if_needed(open_browser, admin_url)

    print("\nPress Ctrl+C to stop the server\n")

    full_app = create_app()
    uvicorn.run(full_app, host=host, port=port)


if __name__ == "__main__":
    main()
