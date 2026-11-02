"""주문 문장 분석을 직접 확인하는 임시 실행 파일."""

from app.services.llm import analyze_order_text


if __name__ == "__main__":
    customer_text = input("주문 문장: ")

    result = analyze_order_text(
        store_id="store_001",
        text=customer_text,
    )

    print(result.model_dump_json(indent=2))