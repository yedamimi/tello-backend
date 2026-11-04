"""관리자 로그인 API."""

import os
import requests

from dotenv import load_dotenv
from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.repositories.admin_repository import get_admin


BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
)


class AdminLoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def admin_login(request: AdminLoginRequest):

    api_key = os.getenv("FIREBASE_WEB_API_KEY")

    if not api_key:
        return JSONResponse(
            status_code=500,
            content={"detail": "FIREBASE_API_KEY_MISSING"},
        )

    url = (
        "https://identitytoolkit.googleapis.com/v1/"
        f"accounts:signInWithPassword?key={api_key}"
    )

    try:
        response = requests.post(
            url,
            json={
                "email": request.email,
                "password": request.password,
                "returnSecureToken": True,
            },
            timeout=10,
        )

        if response.status_code != 200:
            return JSONResponse(
                status_code=401,
                content={"detail": "LOGIN_FAILED"},
            )

        auth_data = response.json()

        uid = auth_data.get("localId")
        id_token = auth_data.get("idToken")

        admin = get_admin(uid)

        if not admin:
            return JSONResponse(
                status_code=403,
                content={"detail": "ADMIN_NOT_FOUND"},
            )

        if admin.get("role") != "admin":
            return JSONResponse(
                status_code=403,
                content={"detail": "ADMIN_PERMISSION_DENIED"},
            )

        if admin.get("isActive") is not True:
            return JSONResponse(
                status_code=403,
                content={"detail": "ADMIN_INACTIVE"},
            )

        return {
            "storeId": admin.get("storeId"),
            "role": admin.get("role"),
            "isActive": admin.get("isActive"),
            "createdAt": admin.get("createdAt"),
            "idToken": id_token,
        }

    except requests.RequestException:
        return JSONResponse(
            status_code=503,
            content={"detail": "FIREBASE_AUTH_UNAVAILABLE"},
        )