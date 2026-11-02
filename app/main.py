from fastapi import FastAPI

from app.api.sessions import router as sessions_router
from app.api.stores import router as stores_router
from app.api.messages import router as messages_router

app = FastAPI(title="Tello Backend")

app.include_router(sessions_router)
app.include_router(stores_router)
app.include_router(messages_router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}
