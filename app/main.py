from fastapi import FastAPI

from app.api.sessions import router as sessions_router

app = FastAPI(title="Tello Backend")

app.include_router(sessions_router)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}