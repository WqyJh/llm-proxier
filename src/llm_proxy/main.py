import gradio as gr
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from llm_proxy.database import init_db
from llm_proxy.proxy import router as proxy_router
from llm_proxy.admin import create_admin_interface, auth_check
from llm_proxy.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    if settings.AUTO_MIGRATE_DB:
        await init_db()
    yield
    # Shutdown


app = FastAPI(title="LLM Proxy", lifespan=lifespan)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("src/llm_proxy/assets/icon.svg")

# Mount Static Files
app.mount("/assets", StaticFiles(directory="src/llm_proxy/assets"), name="assets")

# Mount Proxy Router
app.include_router(proxy_router)

# Mount Gradio Admin Dashboard
# We mount it under /admin
admin_app = create_admin_interface()
app = gr.mount_gradio_app(
    app,
    admin_app,
    path="/admin",
    auth=auth_check,
    auth_message='<div style="display: flex; align-items: center; justify-content: center; margin-bottom: 20px;"><div class="app-logo"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><defs><linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" style="stop-color:#6366f1;stop-opacity:1" /><stop offset="100%" style="stop-color:#8b5cf6;stop-opacity:1" /></linearGradient></defs><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="url(#grad1)" fill="none"/></svg></div><h1 style="margin: 0; font-size: 24px; font-weight: 600; background: linear-gradient(to right, #6366f1, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">LLM Proxy Admin</h1></div><div style="text-align: center; margin-bottom: 10px;"><p>Welcome to the admin panel. Please log in to continue.</p></div>',
    allowed_paths=["/"]  # Sometimes needed for resources
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
