<p align="center">
  <img width="200" alt="Tello 로고" src="https://github.com/user-attachments/assets/2c860183-360a-46a9-a4af-f3eb01bbce28" />
</p>

<div align="center">

# Tello Backend

**장벽 없는 주문의 시작, 내 손 안의 배리어프리 키오스크**

📌 프로젝트 소개 · 화면 · 시연 영상은 [Tello 메인 레포](https://github.com/omwlsoi/Tello)에서 볼 수 있어요.

</div>

## 💻 기술 스택

<p>
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=Python&logoColor=white"/>
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=FastAPI&logoColor=white"/>
  <img src="https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=Pydantic&logoColor=white"/>
  <img src="https://img.shields.io/badge/Uvicorn-499848?style=for-the-badge&logo=Gunicorn&logoColor=white"/>
  <img src="https://img.shields.io/badge/Firebase-FFCA28?style=for-the-badge&logo=Firebase&logoColor=black"/>
  <img src="https://img.shields.io/badge/Gemini-8E75B2?style=for-the-badge&logo=GoogleGemini&logoColor=white"/>
</p>

| 역할 | 사용 |
|---|---|
| API 서버 | FastAPI + Uvicorn |
| 데이터베이스 | Firebase Realtime Database (매장 · 메뉴 · 장바구니 · 주문 · 직원 호출) |
| 인증 | Firebase Authentication (사장님 로그인) |
| 주문 분석 | 룰베이스로 먼저 처리 → 자유로운 말투는 Gemini로 메뉴 · 수량 · 옵션 분석 |

## 🚀 실행 방법

```bash
# 1. 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경 변수 설정 (.env) — 키 값은 팀 노션에서 확인
#    FIREBASE_CREDENTIALS_PATH=  Firebase 서비스 계정 키 파일 경로
#    FIREBASE_DATABASE_URL=      Firebase Realtime Database 주소
#    FIREBASE_WEB_API_KEY=       Firebase 웹 API 키 (사장님 로그인)
#    GEMINI_API_KEY=             Gemini API 키
#    GEMINI_MODEL=               사용할 Gemini 모델명

# 4. 시연용 메뉴 등록 (최초 1회)
python seed_menus.py

# 5. 서버 실행 → http://localhost:8000
uvicorn app.main:app --reload --port 8000
```

> 📖 서버 실행 후 **http://localhost:8000/docs** 에서 전체 API를 바로 테스트할 수 있어요 (FastAPI Swagger).

## 📡 API

| 구분 | Method | Endpoint | 설명 |
|---|---|---|---|
| 상태 | `GET` | `/api/health` | 서버 상태 확인 |
| 매장 | `GET` | `/api/stores/{storeId}` | 매장 정보 조회 |
| 매장 | `GET` | `/api/stores/{storeId}/menu` | 메뉴 · 품절 여부 조회 |
| 세션 | `POST` | `/api/sessions` | 주문 세션 시작 |
| 세션 | `POST` | `/api/sessions/{sessionId}/end` | 주문 세션 종료 |
| 장바구니 | `GET` | `/api/sessions/{sessionId}/cart` | 장바구니 조회 |
| 장바구니 | `POST` | `/api/sessions/{sessionId}/cart/items` | 메뉴 담기 |
| 장바구니 | `PATCH` · `DELETE` | `/api/sessions/{sessionId}/cart/items/{itemId}` | 수량 변경 · 메뉴 삭제 |
| 장바구니 | `DELETE` | `/api/sessions/{sessionId}/cart` | 장바구니 비우기 |
| 음성 주문 | `POST` | `/api/sessions/{sessionId}/messages` | 말한 내용을 분석해 주문 · 되묻기 · 추천 응답 |
| 음성 주문 | `DELETE` | `/api/sessions/{sessionId}/pending-order` | 진행 중인 음성 주문 취소 |
| 주문 | `POST` | `/api/orders` | 주문 확정 |
| 주문 | `GET` | `/api/orders/{orderId}` | 주문 상태 조회 |
| 직원 호출 | `POST` | `/api/help-requests` | 직원 호출 요청 |
| 관리자 | `POST` | `/api/admin/login` | 사장님 로그인 |
| 관리자 | `GET` | `/api/admin/orders` · `/api/admin/orders/{orderId}` | 주문 목록 · 상세 조회 |
| 관리자 | `PATCH` | `/api/admin/orders/{orderId}/status` | 주문 상태 변경 (접수 → 제조 → 완료) |
| 관리자 | `GET` · `PATCH` | `/api/admin/help-requests` · `/{requestId}` | 직원 호출 조회 · 처리 |

## 📂 폴더 구조

```
tello-backend/
├── app/
│   ├── api/            # 라우터 (sessions, stores, messages, orders, help_requests, admin)
│   ├── core/           # Firebase 연결, 보안
│   ├── repositories/   # DB 접근 레이어
│   ├── schemas/        # 요청 · 응답 Pydantic 모델
│   ├── services/       # 비즈니스 로직 (주문 분석 · 음성 장바구니 · 메뉴 추천 · 주문 · 직원 호출)
│   └── main.py         # FastAPI 앱 진입점
├── seed_menus.py       # 시연용 메뉴 등록 스크립트
└── requirements.txt
```

## 👩‍💻 Backend

| <img src="https://github.com/yedamimi.png" width="100"/> | <img src="https://github.com/jiyun232.png" width="100"/> |
|:---:|:---:|
| [예담](https://github.com/yedamimi) | [지윤](https://github.com/jiyun232) |
| 음성 주문 분석(룰베이스 + Gemini) · 장바구니 · 메뉴 추천 · 세션 | 매장·메뉴 조회 · 주문 API · 직원 호출 · 관리자 로그인 |
