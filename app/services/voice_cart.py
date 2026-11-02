
"""음성 명령으로 장바구니 항목을 식별하고 변경한다."""

from app.schemas.messages import AnalyzedItem, OrderAnalysis
from app.services.sessions import (
    clear_cart,
    delete_cart_item,
    get_session_cart,
    update_cart_item,
)


def _options(item: AnalyzedItem) -> dict:
    """사용자가 말한 옵션만 반환한다."""
    return item.options.model_dump(exclude_none=True)


def _candidates(items: list[dict]) -> list[dict]:
    """프론트에서 선택할 수 있는 후보 정보를 만든다."""
    return [
        {
            "itemId": item["itemId"],
            "name": item.get("name"),
            "quantity": item.get("quantity"),
            "selectedOptions": item.get("selectedOptions") or {},
        }
        for item in items
    ]


def find_cart_target(
    cart: dict,
    analyzed_item: AnalyzedItem,
    intent: str = "remove_item",
) -> dict:
    """음성 명령의 수정·삭제 대상을 찾는다.

    삭제: 언급한 옵션을 기존 항목 검색 조건으로 사용.
    수정: 언급한 옵션을 새로운 변경값으로 해석하므로
          기존 항목 검색에는 사용하지 않음.
    """

    menu_id = analyzed_item.menu_id

    if not menu_id:
        return {
            "status": "menu_unknown",
            "itemId": None,
            "candidates": [],
        }

    matches = [
        item
        for item in cart.get("items", [])
        if item.get("menuId") == menu_id
    ]

    if intent == "remove_item":
        requested_options = _options(analyzed_item)

        if requested_options:
            matches = [
                item
                for item in matches
                if all(
                    (item.get("selectedOptions") or {}).get(key)
                    == value
                    for key, value in requested_options.items()
                )
            ]

    if not matches:
        return {
            "status": "not_found",
            "itemId": None,
            "candidates": [],
        }

    if len(matches) > 1:
        return {
            "status": "ambiguous",
            "itemId": None,
            "candidates": _candidates(matches),
        }

    return {
        "status": "matched",
        "itemId": matches[0]["itemId"],
        "candidates": [],
    }


def _response(intent: str, analysis: OrderAnalysis) -> dict:
    return {
        "intent": intent,
        "items": [
            item.model_dump()
            for item in analysis.items
        ],
        "issues": [],
        "needsClarification": False,
        "question": None,
        "cart": None,
        "nextAction": None,
        "candidates": [],
    }


def process_voice_cart_command(
    session_id: str,
    session_token: str,
    analysis: OrderAnalysis,
) -> dict:
    """Gemini가 분석한 변경·삭제 명령을 장바구니에 적용한다."""

    intent = analysis.intent
    cart = get_session_cart(session_id, session_token)
    response = _response(intent, analysis)

    if intent == "clear_cart":
        response["needsClarification"] = True
        response["question"] = "장바구니를 모두 비울까요?"
        response["nextAction"] = "confirm_clear"
        return response

    if intent not in ("update_item", "remove_item"):
        return response

    if len(analysis.items) != 1:
        response["needsClarification"] = True
        response["question"] = "변경할 메뉴를 하나씩 말씀해 주세요."
        response["nextAction"] = "clarification"
        return response

    item = analysis.items[0]

    target = find_cart_target(
        cart,
        item,
        intent=intent,
    )

    if target["status"] == "ambiguous":
        response["needsClarification"] = True
        response["question"] = (
            "같은 메뉴가 여러 개 있어요. "
            "화면에서 변경할 메뉴를 선택해 주세요."
        )
        response["nextAction"] = "select_cart_item"
        response["candidates"] = target["candidates"]
        return response

    if target["status"] != "matched":
        response["needsClarification"] = True
        response["question"] = (
            "장바구니에서 해당 메뉴를 찾지 못했어요. "
            "주문 내역을 확인해 주세요."
        )
        response["nextAction"] = "review_cart"
        return response

    item_id = target["itemId"]

    if intent == "remove_item":
        response["cart"] = delete_cart_item(
            session_id,
            session_token,
            item_id,
        )
        response["question"] = "메뉴를 삭제했어요."
        response["nextAction"] = "cart_updated"
        return response

    # 수정 명령: 기존 항목을 찾은 뒤 변경값을 구성한다.
    changes = {}

    if item.quantity is not None:
        changes["quantity"] = item.quantity

    changed_options = _options(item)

    if changed_options:
        changes["selectedOptions"] = changed_options

    if not changes:
        response["needsClarification"] = True
        response["question"] = (
            "수량이나 변경할 옵션을 말씀해 주세요."
        )
        response["nextAction"] = "clarification"
        return response

    # 핫 → 아이스 변경 시 얼음 선택이 빠졌다면
    # 임의로 기본값을 적용하지 않는다.
    if (
        changed_options.get("temperature") == "ice"
        and "ice" not in changed_options
    ):
        response["needsClarification"] = True
        response["question"] = (
            "얼음 양은 어떻게 할까요? "
            "적게, 보통, 많이 중에서 골라 주세요."
        )
        response["nextAction"] = "clarification"
        return response

    response["cart"] = update_cart_item(
        session_id,
        session_token,
        item_id,
        changes,
    )

    response["question"] = "주문 내용을 변경했어요."
    response["nextAction"] = "cart_updated"

    return response


def confirm_voice_clear(
    session_id: str,
    session_token: str,
    confirmed: bool,
) -> dict:
    """사용자가 동의한 경우에만 전체 삭제한다."""

    if confirmed:
        cart = clear_cart(session_id, session_token)
        question = "장바구니를 모두 비웠어요."
    else:
        cart = get_session_cart(session_id, session_token)
        question = "장바구니를 그대로 유지할게요."

    return {
        "intent": "answer",
        "items": [],
        "issues": [],
        "needsClarification": False,
        "question": question,
        "cart": cart,
        "nextAction": "cart_updated",
    }
