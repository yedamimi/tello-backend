
"""Gemini 주문 분석 결과 검증 및 장바구니 연동 서비스."""

import re
from uuid import uuid4

from app.core.firebase import get_db_reference
from app.repositories.store_repository import get_store_menus
from app.schemas.messages import (
    AnalyzedItem,
    OrderAnalysis,
)
from app.services.sessions import (
    _get_authenticated_session,
    _calculate_unit_price,
    _validate_quantity,
    get_session_cart,
)
from app.services.llm import analyze_order_text


OPTION_FIELDS = ("size", "temperature", "ice")


def validate_order_analysis(
    store_id: str,
    analysis: OrderAnalysis,
) -> dict:
    """Gemini 분석 결과의 메뉴·수량·옵션을 검증한다."""

    items = [
        item.model_dump()
        for item in analysis.items
    ]

    result = {
        "intent": analysis.intent,
        "items": items,
        "issues": [],
        "needsClarification": False,
    }

    if analysis.intent != "add_item":
        return result

    menus = get_store_menus(store_id) or {}
    issues = result["issues"]

    for index, item in enumerate(items):
        menu_id = item.get("menu_id")

        if not menu_id or menu_id not in menus:
            issues.append({
                "itemIndex": index,
                "code": "MENU_UNKNOWN",
                "field": "menuId",
            })
            continue

        menu = menus[menu_id]

        if menu.get("isAvailable") is not True:
            issues.append({
                "itemIndex": index,
                "code": "MENU_SOLD_OUT",
                "field": "menuId",
            })
            continue

        if item.get("quantity") is None:
            issues.append({
                "itemIndex": index,
                "code": "QUANTITY_REQUIRED",
                "field": "quantity",
            })

        options = item.get("options") or {}

        for field, db_field in (
            ("size", "sizeOptions"),
            ("temperature", "temperatureOptions"),
        ):
            allowed = menu.get(db_field) or {}
            value = options.get(field)

            if allowed and value is None:
                issues.append({
                    "itemIndex": index,
                    "code": "OPTION_REQUIRED",
                    "field": field,
                })

            elif value is not None and value not in allowed:
                issues.append({
                    "itemIndex": index,
                    "code": "OPTION_INVALID",
                    "field": field,
                })

        ice = options.get("ice")
        ice_options = menu.get("iceOptions") or {}

        if options.get("temperature") == "ice":
            if ice_options and ice is None:
                issues.append({
                    "itemIndex": index,
                    "code": "OPTION_REQUIRED",
                    "field": "ice",
                })

            elif ice is not None and ice not in ice_options:
                issues.append({
                    "itemIndex": index,
                    "code": "OPTION_INVALID",
                    "field": "ice",
                })

        elif ice is not None:
            issues.append({
                "itemIndex": index,
                "code": "OPTION_INVALID",
                "field": "ice",
            })

        # 기존 장바구니 검증 함수를 재사용한다.
        if not any(
            issue["itemIndex"] == index
            for issue in issues
        ):
            try:
                _validate_quantity(item["quantity"])

                selected_options = {
                    key: value
                    for key, value in options.items()
                    if value is not None
                }

                _calculate_unit_price(
                    menu,
                    selected_options,
                )

            except (ValueError, KeyError, TypeError):
                issues.append({
                    "itemIndex": index,
                    "code": "OPTION_INVALID",
                    "field": "options",
                })

    result["needsClarification"] = bool(issues)

    return result


def generate_clarification_question(
    result: dict,
) -> str | None:
    """누락 정보에 대한 추가 질문을 생성한다."""

    issues = result.get("issues") or []

    if not issues:
        return None

    issue = issues[0]
    index = issue["itemIndex"]

    item = result["items"][index]
    name = item.get("menu_text") or "해당 메뉴"

    code = issue["code"]
    field = issue["field"]

    if code == "MENU_UNKNOWN":
        return (
            f"{name} 메뉴를 찾지 못했어요. "
            "다른 메뉴를 말씀해 주세요."
        )

    if code == "MENU_SOLD_OUT":
        return (
            f"{name}는 품절이에요. "
            "다른 메뉴를 말씀해 주세요."
        )

    if code == "QUANTITY_REQUIRED":
        return (
            f"{name}는 몇 잔 또는 "
            "몇 개 주문하시겠어요?"
        )

    if code == "OPTION_REQUIRED":
        questions = {
            "size": (
                f"{name}는 보통 크기와 큰 크기 중 "
                "어떤 걸로 드릴까요?"
            ),
            "temperature": (
                f"{name}는 따뜻한 것과 차가운 것 중 "
                "어떤 걸로 드릴까요?"
            ),
            "ice": (
                f"{name}의 얼음은 많이, 보통, 적게 중 "
                "어떻게 드릴까요?"
            ),
        }

        return questions.get(
            field,
            "옵션을 선택해 주세요.",
        )

    field_names = {
        "size": "크기",
        "temperature": "온도",
        "ice": "얼음",
    }

    field_name = field_names.get(field, field)

    return (
        f"{name}의 {field_name} 선택을 "
        "다시 말씀해 주세요."
    )


def get_pending_order(
    session_id: str,
) -> dict | None:
    """Firebase의 미완성 주문을 조회한다."""

    return get_db_reference(
        f"sessions/{session_id}/pendingOrder"
    ).get()


def save_pending_order(
    session_id: str,
    result: dict,
) -> None:
    """추가 질문이 필요한 주문을 임시 저장한다."""

    if result["intent"] != "add_item":
        return

    pending_ref = get_db_reference(
        f"sessions/{session_id}/pendingOrder"
    )

    if not result["needsClarification"]:
        pending_ref.delete()
        return

    pending_ref.set({
        "intent": result["intent"],
        "items": result["items"],
        "issues": result["issues"],
        "question": result.get("question"),
    })


def clear_pending_order(
    session_id: str,
) -> None:
    """미완성 주문 정보를 삭제한다."""

    get_db_reference(
        f"sessions/{session_id}/pendingOrder"
    ).delete()


def _read_followup_value(
    text: str,
    field: str,
):
    """짧고 명확한 후속 답변의 값을 추출한다."""

    normalized = re.sub(
        r"\s+",
        "",
        text.strip(),
    )

    if field == "quantity":
        match = re.fullmatch(
            (
                r"(하나|한|둘|두|셋|세|넷|네|[1-9][0-9]*)"
                r"(잔|장|개|잔이요|장이요|개요|"
                r"이요|요|잔주세요|개주세요|"
                r"개만|잔만|장만)?"
            ),
            normalized,
        )

        if match is None:
            return None

        numbers = {
            "하나": 1,
            "한": 1,
            "둘": 2,
            "두": 2,
            "셋": 3,
            "세": 3,
            "넷": 4,
            "네": 4,
        }

        word = match.group(1)

        if word.isdigit():
            return int(word)

        return numbers.get(word)

    values = {
        "size": {
            "큰걸로": "large",
            "큰걸로요": "large",
            "라지": "large",
            "라지요": "large",
            "큰사이즈": "large",
            "큰사이즈요": "large",
            "보통": "regular",
            "보통이요": "regular",
            "레귤러": "regular",
            "레귤러요": "regular",
        },
        "temperature": {
            "아이스": "ice",
            "아이스요": "ice",
            "차가운거": "ice",
            "차가운거요": "ice",
            "차갑게": "ice",
            "따뜻하게": "hot",
            "따뜻한거": "hot",
            "따뜻한거요": "hot",
            "핫": "hot",
            "핫이요": "hot",
        },
        "ice": {
            "적게": "less",
            "적게요": "less",
            "얼음적게": "less",
            "보통": "regular",
            "보통이요": "regular",
            "얼음보통": "regular",
            "많이": "more",
            "많이요": "more",
            "얼음많이": "more",
        },
    }

    return values.get(field, {}).get(normalized)


def resolve_followup(
    pending: dict,
    answer: str,
) -> OrderAnalysis | None:
    """후속 답변을 미완성 주문의 해당 항목에 반영한다."""

    issues = pending.get("issues") or []
    items = pending.get("items") or []

    if not issues or not items:
        return None

    issue = issues[0]

    index = issue.get("itemIndex")
    code = issue.get("code")
    field = issue.get("field")

    if (
        type(index) is not int
        or not 0 <= index < len(items)
    ):
        return None

    if code not in (
        "QUANTITY_REQUIRED",
        "OPTION_REQUIRED",
        "OPTION_INVALID",
    ):
        return None

    if (
        code == "OPTION_INVALID"
        and field not in OPTION_FIELDS
    ):
        return None

    value = _read_followup_value(
        answer,
        field,
    )

    if value is None:
        return None

    updated_items = []

    for position, old_item in enumerate(items):
        data = dict(old_item)
        options = dict(data.get("options") or {})

        if position == index:
            if field == "quantity":
                data["quantity"] = value
            else:
                options[field] = value

                if (
                    field == "temperature"
                    and value == "hot"
                ):
                    options["ice"] = None

        data["options"] = {
            key: options.get(key)
            for key in OPTION_FIELDS
        }

        updated_items.append(
            AnalyzedItem.model_validate(data)
        )

    return OrderAnalysis(
        intent="add_item",
        items=updated_items,
    )


def add_analyzed_items(
    session_id: str,
    session_token: str,
    items: list[dict],
) -> dict:
    """검증된 주문 항목을 하나의 트랜잭션으로 추가한다."""

    session = _get_authenticated_session(
        session_id,
        session_token,
    )

    store_id = session["storeId"]
    menus = get_store_menus(store_id) or {}

    additions = {}

    for item in items:
        menu_id = item.get("menu_id")
        menu = menus.get(menu_id)

        if (
            not menu
            or menu.get("isAvailable") is not True
        ):
            raise ValueError("CART_MENU_UNAVAILABLE")

        quantity = item.get("quantity")
        _validate_quantity(quantity)

        selected_options = {
            key: value
            for key, value in (
                item.get("options") or {}
            ).items()
            if value is not None
        }

        _calculate_unit_price(
            menu,
            selected_options,
        )

        item_id = uuid4().hex

        additions[item_id] = {
            "menuId": menu_id,
            "quantity": quantity,
            "selectedOptions": (
                selected_options or None
            ),
        }

    if not additions:
        raise ValueError("MESSAGE_NO_ITEMS")

    items_ref = get_db_reference(
        f"sessions/{session_id}/cart/items"
    )

    def apply_add(current_items):
        updated = dict(current_items or {})
        updated.update(additions)
        return updated

    items_ref.transaction(apply_add)

    return get_session_cart(
        session_id,
        session_token,
    )


def process_order_message(
    session_id: str,
    session_token: str,
    text: str,
) -> dict:
    """고객 메시지를 분석하여 장바구니에 반영한다."""

    session = _get_authenticated_session(
        session_id,
        session_token,
    )

    store_id = session["storeId"]
    pending = get_pending_order(session_id)

    if pending:
        analysis = resolve_followup(
            pending,
            text,
        )

        if analysis is None:
            return {
                "intent": "answer",
                "items": pending.get("items") or [],
                "issues": pending.get("issues") or [],
                "needsClarification": True,
                "question": (
                    pending.get("question")
                    or "다시 말씀해 주세요."
                ),
                "cart": None,
            }

    else:
        analysis = analyze_order_text(
            store_id=store_id,
            text=text,
        )

    result = validate_order_analysis(
        store_id,
        analysis,
    )

    result["question"] = (
        generate_clarification_question(result)
    )

    result["cart"] = None

    # 변경·삭제·확인 의도는 아직 자동 처리하지 않는다.
    if result["intent"] != "add_item":
        return result

    if result["needsClarification"]:
        save_pending_order(
            session_id,
            result,
        )

        return result

    # 검증된 메뉴를 기존 장바구니에 반영
    result["cart"] = add_analyzed_items(
        session_id,
        session_token,
        result["items"],
    )

    clear_pending_order(session_id)

    return result
