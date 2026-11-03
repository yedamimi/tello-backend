# Firebase Realtime Database 명세

## 1. 기존 확정 구조

### stores/{storeId}
- 기존 매장 데이터 유지

### menus/{storeId}/{menuId}
- 기존 메뉴 데이터 유지

### sessions/{sessionId}
- storeId: 매장 ID
- status: 세션 상태 (active / ordered / ended 등)
- tokenHash: 고객 세션 인증용 해시
- orderId: 주문 확정 시 세션 ID와 동일
- order: 확정 주문 객체

### sessions/{sessionId}/order
- orderId: 주문 ID
- orderNumber: 주문번호
- sessionId: 고객 세션 ID
- storeId: 매장 ID
- status: pending / preparing / completed
- imageId: order_complete / preparing / ready
- items: 주문 메뉴 목록
- totalPrice: 총금액
- createdAt: Unix 밀리초

주문 상태 전환:
pending -> preparing -> completed

## 2. 관리자 권한 데이터 (설계안)

경로: admins/{adminId}

- storeId: string
- role: string (admin)
- isActive: boolean

주의:
- 실제 로그인 인증 방식은 7번 담당 구현에 맞춰 확정
- 비밀번호 평문 저장 금지
- 관리자 API의 인증 및 매장별 권한 검증 필수

## 3. 직원 호출 데이터 (설계안)

경로: help_requests/{requestId}

- requestId: string
- sessionId: string
- storeId: string
- status: pending / completed
- createdAt: Unix 밀리초
- completedAt: Unix 밀리초 (처리 완료 시)

주의:
- 호출 데이터는 POST /api/help-requests에서 생성
- 완료 처리는 PATCH /api/admin/help-requests/{requestId}
- 중복 호출 방지 및 관리자 매장별 권한 확인 필요

## 4. 검증 현황

- 기존 주문 1건 Firebase 조회 성공
- 관리자 주문 목록 조회 성공
- 관리자 주문 상세 데이터 확인 성공
- 관리자 상태 변경 및 고객 조회 연동 성공
- 직원 호출 데이터 생성/조회/상태변경/삭제 성공
- 테스트 데이터 정리 완료

## 5. 미완료

- 관리자 로그인 및 인증 DB 연동
- 관리자 주문 API 인증·매장 권한 적용
- 직원 호출 API 실제 연동
- 프론트엔드 통합 테스트

기존에 협의한 API 주소와 HTTP 메서드는 변경하지 않는다.
