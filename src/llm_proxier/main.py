import importlib.resources
import sys
from contextlib import asynccontextmanager

import gradio as gr
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from llm_proxier.admin import auth_check, create_admin_interface
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


def create_app():
    """Create and configure the FastAPI application."""
    # Mount Gradio Admin Dashboard
    # We mount it under /admin
    admin_app = create_admin_interface()
    configured_app = gr.mount_gradio_app(
        app,
        admin_app,
        path="/admin",
        auth=auth_check,
        auth_message='<div style="display: flex; align-items: center; justify-content: center; margin-bottom: 20px;"><div class="app-logo"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><defs><linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" style="stop-color:#6366f1;stop-opacity:1" /><stop offset="100%" style="stop-color:#8b5cf6;stop-opacity:1" /></linearGradient></defs><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="url(#grad1)" fill="none"/></svg></div><h1 style="margin: 0; font-size: 24px; font-weight: 600; background: linear-gradient(to right, #6366f1, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">LLM Proxier Admin</h1></div><div style="text-align: center; margin-bottom: 10px;"><p>Welcome to the admin panel. Please log in to continue.</p></div>',
        allowed_paths=["/"],  # Sometimes needed for resources
    )
    return configured_app


def main():
    """Main entry point for the llm-proxier command."""
    # Parse command line arguments for host and port
    host = "0.0.0.0"
    port = 8000

    # Simple argument parsing
    args = sys.argv[1:]
    show_help = False

    for i, arg in enumerate(args):
        if arg == "--host" and i + 1 < len(args):
            host = args[i + 1]
        elif arg == "--port" and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                print(f"Invalid port number: {args[i + 1]}")
                sys.exit(1)
        elif arg in ("-h", "--help"):
            show_help = True

    if show_help:
        print("Usage: llm-proxier [--host HOST] [--port PORT]")
        print("Options:")
        print("  --host HOST    Bind to this address (default: 0.0.0.0)")
        print("  --port PORT    Bind to this port (default: 8000)")
        print("  -h, --help     Show this help message")
        sys.exit(0)

    # Create the full application with admin interface
    full_app = create_app()
    uvicorn.run(full_app, host=host, port=port)


if __name__ == "__main__":
    main()
