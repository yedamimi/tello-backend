from fastapi import FastAPI

from app.api.sessions import router as sessions_router
from app.api.stores import router as stores_router

app = FastAPI(title="Tello Backend")

app.include_router(sessions_router)

app.include_router(stores_router)

@app.get("/api/health")
def health_check():
    return {"status": "ok"}