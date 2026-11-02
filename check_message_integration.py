
"""8번 LLM 주문 분석 기능 통합 사전 점검."""

import importlib
import inspect

from app.main import app

REQUIRED_FUNCTIONS = {
    "app.services.sessions": [
        "_get_authenticated_session",
        "_validate_quantity",
        "_calculate_unit_price",
        "get_session_cart",
    ],
    "app.services.messages": [
        "validate_order_analysis",
        "generate_clarification_question",
        "get_pending_order",
        "save_pending_order",
        "clear_pending_order",
        "resolve_followup",
        "add_analyzed_items",
        "process_order_message",
    ],
    "app.services.llm": [
        "analyze_order_text",
    ],
}

failures = []

for module_name, names in REQUIRED_FUNCTIONS.items():
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        print(f"FAIL import {module_name}: {exc}")
        failures.append(module_name)
        continue

    for name in names:
        func = getattr(module, name, None)

        if not callable(func):
            print(f"FAIL {module_name}.{name}")
            failures.append(name)
        else:
            print(
                f"PASS {name}"
                f"{inspect.signature(func)}"
            )

paths = app.openapi()["paths"]

message_path = "/api/sessions/{sessionId}/messages"

if (
    message_path in paths
    and "post" in paths[message_path]
):
    print("PASS message API route")
else:
    print("FAIL message API route")
    failures.append("message API route")

if failures:
    print(f"\nFAILED: {len(failures)} issue(s)")
    raise SystemExit(1)

print("\nALL IMPORT AND ROUTE CHECKS PASSED")
