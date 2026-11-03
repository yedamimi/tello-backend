
"""주문 확정·조회 요청 및 응답 데이터 모델."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class OrderCreateRequest(BaseModel):
    """주문 확정 요청."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(
        alias="sessionId",
        min_length=32,
        max_length=32,
        pattern=r"^[a-f0-9]{32}$",
    )

class OrderItemResponse(BaseModel):
    """주문에 포함된 메뉴 정보."""

    item_id: str = Field(alias="itemId")
    menu_id: str = Field(alias="menuId")
    name: str
    quantity: int = Field(gt=0)
    selected_options: dict = Field(alias="selectedOptions")
    unit_price: int = Field(alias="unitPrice", ge=0)
    subtotal: int = Field(ge=0)

class OrderCreateResponse(BaseModel):
    """주문 확정 결과."""

    order_id: str = Field(alias="orderId")
    order_number: str = Field(alias="orderNumber")
    status: Literal[
        "pending",
        "preparing",
        "completed",
    ]
    image_id: Literal[
        "order_complete",
        "preparing",
        "ready",
    ] = Field(alias="imageId")
    items: list[OrderItemResponse]
    total_price: int = Field(alias="totalPrice")
    created_at: int = Field(alias="createdAt")


class OrderReadResponse(BaseModel):
    """주문 상태 조회 결과."""

    order_id: str = Field(alias="orderId")
    order_number: str = Field(alias="orderNumber")
    status: Literal[
        "pending",
        "preparing",
        "completed",
    ]
    image_id: Literal[
        "order_complete",
        "preparing",
        "ready",
    ] = Field(alias="imageId")
    items: list[OrderItemResponse]
    total_price: int = Field(alias="totalPrice")
    created_at: int = Field(alias="createdAt")

class OrderStatusUpdateRequest(BaseModel):
    """주문 상태 변경 요청."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["preparing", "completed"]


class OrderStatusUpdateResponse(BaseModel):
    """주문 상태 변경 결과."""

    order_id: str = Field(alias="orderId")
    status: Literal["preparing", "completed"]
    image_id: Literal[
        "preparing",
        "ready",
    ] = Field(alias="imageId")

class OrderListResponse(BaseModel):
    """매장 주문 목록 조회 결과."""

    orders: list[OrderReadResponse]