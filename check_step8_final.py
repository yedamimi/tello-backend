
"""8번 LLM 주문 분석 최종 통합 테스트."""

from app.repositories.store_repository import (
    get_store,
    get_store_menus,
)
from app.services.llm import analyze_order_text
from app.services.messages import (
    validate_order_analysis,
    generate_clarification_question,
    resolve_followup,
)

STORE_ID = "store_001"

passed = 0
failed = []


def check(name, condition, detail=""):
    global passed

    if condition:
        passed += 1
        print(f"PASS: {name}")
    else:
        failed.append(name)
        print(f"FAIL: {name}")
        if detail:
            print("  ", detail)


def analyze(text):
    analysis = analyze_order_text(
        store_id=STORE_ID,
        text=text,
    )
    result = validate_order_analysis(
        STORE_ID,
        analysis,
    )
    result["question"] = (
        generate_clarification_question(result)
    )
    return analysis, result


def has_issue(result, code):
    return any(
        issue["code"] == code
        for issue in result["issues"]
    )


def run(name, func):
    try:
        func()
    except Exception as exc:
        failed.append(name)
        print(f"ERROR: {name}: {type(exc).__name__}: {exc}")


def test_firebase():
    store = get_store(STORE_ID)
    menus = get_store_menus(STORE_ID)

    check(
        "Firebase 매장 조회",
        bool(store),
    )
    check(
        "Firebase 메뉴 조회",
        bool(menus),
    )


def test_multiple_items():
    analysis, _ = analyze(
        "아메리카노 한 잔이랑 카페라떼 두 잔 주세요"
    )

    check(
        "다중 메뉴 분석",
        analysis.intent == "add_item"
        and len(analysis.items) == 2,
    )


def test_different_options():
    analysis, _ = analyze(
        "아이스 아메리카노 한 잔이랑 "
        "뜨거운 아메리카노 한 잔 주세요"
    )

    temperatures = {
        item.options.temperature
        for item in analysis.items
    }

    check(
        "동일 메뉴 서로 다른 옵션 분리",
        len(analysis.items) == 2
        and temperatures == {"hot", "ice"},
        str(analysis.model_dump()),
    )


def test_options():
    analysis, _ = analyze(
        "아이스 아메리카노 라지 사이즈 "
        "한 잔, 얼음 적게 주세요"
    )

    item = analysis.items[0]

    check(
        "크기·온도·얼음 추출",
        item.options.size == "large"
        and item.options.temperature == "ice"
        and item.options.ice == "less",
        str(item.model_dump()),
    )


def test_intents():
    cases = [
        ("아메리카노를 두 잔으로 변경해 주세요", "update_item"),
        ("아메리카노 삭제해 주세요", "remove_item"),
        ("장바구니 전부 비워 주세요", "clear_cart"),
        ("지금 주문한 내역 보여줘", "review_order"),
    ]

    for text, expected in cases:
        analysis, _ = analyze(text)

        check(
            f"의도 분류: {expected}",
            analysis.intent == expected,
            f"실제 결과: {analysis.intent}",
        )


def test_unknown_menu():
    _, result = analyze(
        "달에서 만든 무지개 라떼 한 잔 주세요"
    )

    check(
        "존재하지 않는 메뉴 검증",
        has_issue(result, "MENU_UNKNOWN"),
        str(result["issues"]),
    )


def test_missing_options():
    _, result = analyze(
        "아메리카노 주세요"
    )

    check(
        "모호한 주문 추가 질문",
        result["needsClarification"]
        and bool(result["question"]),
        str(result),
    )


def test_followup():
    pending = {
        "items": [{
            "menu_text": "아메리카노",
            "menu_id": "americano",
            "quantity": None,
            "options": {
                "size": None,
                "temperature": None,
                "ice": None,
            },
        }],
        "issues": [{
            "itemIndex": 0,
            "code": "QUANTITY_REQUIRED",
            "field": "quantity",
        }],
        "question": "몇 잔 드릴까요?",
    }

    analysis = resolve_followup(
        pending,
        "두 잔이요",
    )

    check(
        "후속 답변 수량 병합",
        analysis is not None
        and analysis.items[0].quantity == 2,
    )


def test_sold_out_and_invalid_options():
    menus = get_store_menus(STORE_ID) or {}

    sold_out = next(
        (
            menu_id
            for menu_id, menu in menus.items()
            if menu.get("isAvailable") is False
        ),
        None,
    )

    if sold_out:
        from app.schemas.messages import OrderAnalysis

        analysis = OrderAnalysis.model_validate({
            "intent": "add_item",
            "items": [{
                "menu_text": "품절 메뉴",
                "menu_id": sold_out,
                "quantity": 1,
                "options": {
                    "size": None,
                    "temperature": None,
                    "ice": None,
                },
            }],
        })

        result = validate_order_analysis(
            STORE_ID,
            analysis,
        )

        check(
            "품절 메뉴 검증",
            has_issue(result, "MENU_SOLD_OUT"),
        )
    else:
        print(
            "SKIP: 실제 DB에 품절 메뉴가 없어 "
            "품절 테스트 별도 필요"
        )

    from app.schemas.messages import OrderAnalysis

    analysis = OrderAnalysis.model_validate({
        "intent": "add_item",
        "items": [{
            "menu_text": "아메리카노",
            "menu_id": "americano",
            "quantity": 1,
            "options": {
                "size": "large",
                "temperature": "hot",
                "ice": "more",
            },
        }],
    })

    result = validate_order_analysis(
        STORE_ID,
        analysis,
    )

    check(
        "지원하지 않는 얼음 옵션 조합 검증",
        has_issue(result, "OPTION_INVALID"),
        str(result["issues"]),
    )


if __name__ == "__main__":
    run("Firebase", test_firebase)
    run("다중 메뉴", test_multiple_items)
    run("동일 메뉴 옵션 분리", test_different_options)
    run("옵션 추출", test_options)
    run("의도 분류", test_intents)
    run("없는 메뉴", test_unknown_menu)
    run("모호한 주문", test_missing_options)
    run("후속 답변", test_followup)
    run("품절·옵션 검증", test_sold_out_and_invalid_options)

    print()
    print(f"PASSED: {passed}")
    print(f"FAILED: {len(failed)}")

    if failed:
        print("미통과 항목:", ", ".join(failed))
        raise SystemExit(1)

    print("ALL EXECUTED CHECKS PASSED")
