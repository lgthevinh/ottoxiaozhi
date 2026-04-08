from fastapi import FastAPI

from app.api.routes import router
from app.api.websocket.audio import router as websocket_router


app = FastAPI(title="Otto Xiaozhi API", version="0.1.0")
app.include_router(router)
app.include_router(websocket_router)
