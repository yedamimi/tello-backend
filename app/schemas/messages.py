
"""음성 주문 분석 및 메시지 API 스키마."""

from typing import Literal

from pydantic import BaseModel, Field


OrderIntent = Literal[
    "add_item",
    "update_item",
    "remove_item",
    "clear_cart",
    "browse_menu",
    "recommend",
    "answer",
    "review_order",
    "request_help",
    "unknown",
]


class AnalyzedOptions(BaseModel):
    """Gemini가 추출한 메뉴 옵션."""

    size: Literal["regular", "large"] | None = Field(
        description="메뉴 크기. 언급하지 않았다면 null"
    )
    temperature: Literal["hot", "ice"] | None = Field(
        description="음료 온도. 언급하지 않았다면 null"
    )
    ice: Literal["more", "regular", "less"] | None = Field(
        description="얼음 양. 언급하지 않았다면 null"
    )


class AnalyzedItem(BaseModel):
    """Gemini가 추출한 개별 주문 항목."""

    menu_text: str = Field(
        description="고객이 말한 메뉴 이름"
    )
    menu_id: str | None = Field(
        description="실제 매장 메뉴 ID. 찾지 못했다면 null"
    )
    quantity: int | None = Field(
        ge=1,
        description="주문 수량. 언급하지 않았다면 null"
    )
    options: AnalyzedOptions


class OrderAnalysis(BaseModel):
    """Gemini 주문 분석 결과."""

    intent: OrderIntent
    items: list[AnalyzedItem]


class MessageRequest(BaseModel):
    """고객 메시지 요청."""

    text: str = Field(
        min_length=1,
        max_length=1000,
    )


class MessageResponse(BaseModel):
    """주문 분석 및 처리 응답."""

    intent: OrderIntent
    items: list[AnalyzedItem] = Field(default_factory=list)
    issues: list[dict] = Field(default_factory=list)
    needsClarification: bool = False
    question: str | None = None
    cart: dict | None = None
