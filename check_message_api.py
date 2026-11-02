
"""Gemini message API integration test."""

from fastapi.testclient import TestClient

from app.main import app
from app.core.firebase import get_db_reference
from app.services.sessions import create_session

session_id = None

with TestClient(app) as client:
    try:
        session = create_session("store_001")
        session_id = session["sessionId"]
        token = session["sessionToken"]

        url = f"/api/sessions/{session_id}/messages"

        # 1. Missing token
        response = client.post(
            url,
            json={"text": "아메리카노 두 잔 주세요"},
        )
        assert response.status_code == 401, response.text
        print("PASS 1: Missing token rejected")

        # 2. Invalid token
        response = client.post(
            url,
            headers={"Authorization": "Bearer invalid-token"},
            json={"text": "아메리카노 두 잔 주세요"},
        )
        assert response.status_code == 401, response.text
        print("PASS 2: Invalid token rejected")

        # 3. Valid token and Gemini analysis
        response = client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"text": "아메리카노 두 잔 주세요"},
        )

        assert response.status_code == 200, response.text

        result = response.json()

        assert result["intent"] == "add_item"
        assert len(result["items"]) == 1
        assert result["items"][0]["menu_id"] == "americano"
        assert result["items"][0]["quantity"] == 2

        print("PASS 3: Gemini analysis via HTTP")

        # 4. Cart must remain unchanged
        cart = get_db_reference(
            f"sessions/{session_id}/cart/items"
        ).get()

        assert not cart
        print("PASS 4: Cart unchanged")

    finally:
        if session_id is not None:
            get_db_reference(
                f"sessions/{session_id}"
            ).delete()
