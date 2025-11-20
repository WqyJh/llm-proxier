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
    allowed_paths=["/"]  # Sometimes needed for resources
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
