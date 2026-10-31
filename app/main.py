
from fastapi import FastAPI

app = FastAPI(title="Tello Backend")


@app.get("/api/health")
def health_check():
    return {"status": "ok"}