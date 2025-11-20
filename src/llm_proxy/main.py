import gradio as gr
from fastapi import FastAPI
from contextlib import asynccontextmanager

from llm_proxy.database import init_db
from llm_proxy.proxy import router as proxy_router
from llm_proxy.admin import create_admin_interface, auth_check


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    yield
    # Shutdown


app = FastAPI(title="LLM Proxy", lifespan=lifespan)

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
