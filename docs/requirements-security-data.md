# 요구사항·보안·데이터 설계 (초안, 승인 게이트 포함)

## 범위와 경계
Synology-Admin(me0kmin27/Synology-Admin)은 별도 고객 포털이다.
me0kmin27/Rustdesk-Quicksupport는 향후 연동 대상이며 이번 작업에서 수정하지 않는다.
현재 공개 URL은 정적 상태 안내와 DB 연결 health뿐이다. 가입/승인/관리 API는 없다.
Django 내장 auth 테이블 설치는 회원 승인 기능 완성을 뜻하지 않는다.

## 확정 요구사항 / 제안 / 미결정
확정: 가입 신청→관리자 승인, 회원 관리, NAS 공유폴더 사용자/그룹 권한,
계정/그룹별 할당·사용·잔여 용량, 고객지원 티켓/채팅, 동의 기반 원격지원.
제안: Django 단일 앱, 초기 개발 SQLite, 운영 PostgreSQL 검토, NAS 연결은 별도 adapter/worker.
미결정: NAS 모델·DSM·파일시스템·API capability, 사용자/그룹 quota 지원 및 중복 그룹 집계,
갱신 주기·SLO, 그룹 사용량 열람 범위, NAS 연결 상세 절차, 보존기한·RPO/RTO·과금.
인증 방식 확정: 독립 포털 계정으로 웹 가입·관리자 승인 후 NAS 계정 연결. DSM 비밀번호로 포털 로그인하지 않는다. `membership-auth-decision.md` 참조.
어떠한 API 지원이나 웹 원격지원 가능 여부도 아직 입증되지 않았다.

## 역할과 격리 수용 기준 (미구현)
- 방문자: 안내/신청만. 신청자: 승인 전 NAS/다른 회원 정보 접근 금지.
- 승인 회원: 자신의 tenant와 허용된 자원만. tenant ID는 요청 입력을 신뢰하지 않고 세션 membership에서 결정.
- 지원 담당: 배정 티켓에만 접근, NAS 관리 권한 없음. 관리자: 승인된 관리 범위만.
- 모든 object 접근에 tenant+membership 권한 확인; ID 추측/직접 URL/검색/파일/웹소켓 교차 tenant 거부 테스트 필수.
- 승인 원자성·중복 방지·승인 취소 시 세션/캐시 무효화. 앱 승인과 NAS 프로비저닝 상태는 별도 기록.
- NAS 변경은 재인증/명시 승인, 최소 권한 서비스 계정, TLS 검증, timeout, 재시도 제한,
  idempotency key, 실행 전후 감사, 실패 시 보상 또는 수동 복구. DB 성공을 NAS 성공으로 표시 금지.
- 관리 계정 MFA, rate limit, 비밀번호 정책, CSRF, 세션 회전/만료는 인증 단계 필수 수용 기준.

## 논리 데이터 모델 (설계만; 운영 도메인 테이블 미생성)
Tenant 1:N Membership(N:1 User), Membership(status=pending/approved/suspended),
Approval(actor, subject, previous/next status, reason, timestamp),
NasBinding(tenant, external ID, provisioning state; secret reference only),
ResourceGrant(subject user/group, folder ID, permission, operation ID),
QuotaPolicy(scope, byte limit nullable, semantics version),
UsageSnapshot(subject, measured bytes, collected_at, source, freshness/error),
Ticket(tenant, requester, assigned staff), Message(ticket, sender, body, timestamp),
RemoteConsent(ticket, user, scope, expires_at, revoked_at), RemoteSession(consent, operator, start/end),
AuditEvent(actor, tenant, action, target ID, outcome, correlation ID, timestamp).
FK/unique/check 제약과 상태 전이 트랜잭션은 해당 단계에서 migration/test로 확정한다.
사용량 조회는 마지막 성공 시각·stale 상태·수집 실패를 구분; 미수집을 0바이트로 바꾸지 않는다.
그룹 사용량 합산은 중복 멤버와 shared folder 소유권 의미 확정 전 구현하지 않는다.

## 개인정보·비밀·감사
Git: 소스/설계/가짜 값이 없는 설정 예시/검증 메타데이터만.
운영 DB, 사용자/티켓/채팅/파일, NAS 주소·계정·토큰, 원격 세션 암호는 Git/CI artifact 금지.
감사에는 접속 비밀/메시지 본문/비밀번호를 기록하지 않는다. 비밀은 런타임 secret store.
암호화된 백업, 제한된 조회권한, 삭제/보존 정책 및 법적 검토는 운영 승인 전 확정.
원격지원은 사용자 명시 동의, 제한 시간, 철회, 운영자 신원 확인, 세션 종료 및 감사가 선행.
브라우저에 NAS 관리 자격증명을 전달하거나 RustDesk 비밀을 URL에 넣지 않는다.

## 주요 위험
교차 tenant 노출, 과권한 NAS 계정, 잘못된 quota 해석, stale 수치 오인,
지원 담당자 권한 상승, 원격지원 동의 누락, DB/NAS 상태 불일치, 백업 내 개인정보.
각 위험의 부정 테스트·복구 훈련 없이는 관련 단계 완료로 계산하지 않는다.
