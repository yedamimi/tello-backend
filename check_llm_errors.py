
"""Gemini 타임아웃 및 API 오류 처리 테스트."""

from unittest.mock import MagicMock, patch

import httpx

from google.genai._gaos.lib.compat_errors import (
    APIConnectionError,
    APITimeoutError,
)

from app.services.llm import analyze_order_text


request = httpx.Request(
    "POST",
    "https://generativelanguage.googleapis.com",
)


def run_error_test(name, error, expected_code):
    with (
        patch(
            "app.services.llm.get_store",
            return_value={"name": "테스트 매장"},
        ),
        patch(
            "app.services.llm.get_store_menus",
            return_value={
                "americano": {
                    "name": "아메리카노",
                    "isAvailable": True,
                }
            },
        ),
        patch(
            "app.services.llm.genai.Client",
        ) as mock_client,
        patch.dict(
            "os.environ",
            {
                "GEMINI_API_KEY": "test-key",
                "GEMINI_MODEL": "test-model",
            },
        ),
    ):
        client = MagicMock()
        client.interactions.create.side_effect = error

        mock_client.return_value.__enter__.return_value = client

        try:
            analyze_order_text(
                "store_001",
                "아메리카노 한 잔 주세요",
            )
        except ValueError as exc:
            assert str(exc) == expected_code, (
                f"Expected {expected_code}, got {exc}"
            )
            print(f"PASS: {name}")
        else:
            raise AssertionError(
                f"{name}: 예외가 발생하지 않았음"
            )


run_error_test(
    "Gemini timeout",
    APITimeoutError(request=request),
    "LLM_TIMEOUT",
)

run_error_test(
    "Gemini connection error",
    APIConnectionError(request=request),
    "LLM_API_ERROR",
)

print("\nALL LLM ERROR TESTS PASSED")
