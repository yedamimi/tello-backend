from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.sessions import router as sessions_router
from app.api.stores import router as stores_router
from app.api.messages import router as messages_router
from app.api.orders import (
    router as orders_router,
    admin_router as admin_orders_router,
)
from app.api.help_requests import (
    router as help_requests_router,
    admin_router as admin_help_requests_router,
)
from app.api.admin import router as admin_router
app = FastAPI(title="Tello Backend")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "ngrok-skip-browser-warning",
    ],
)


app.include_router(sessions_router)
app.include_router(stores_router)
app.include_router(admin_orders_router, prefix="/api")
app.include_router(messages_router)
app.include_router(orders_router, prefix="/api")
app.include_router(help_requests_router)
app.include_router(admin_help_requests_router)
app.include_router(admin_router, prefix="/api")

@app.get("/api/health")
def health_check():
    return {"status": "ok"}
