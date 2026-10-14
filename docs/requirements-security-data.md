# 요구사항·보안·데이터 설계 (초안, 승인 게이트 포함)

최신 결정: 2026-10-12 1A/2A/3A/4A 사용자 확정 (`next-decisions.md`). 관리자 OTP 등록·확인·강제의 첫 구현은 `admin-mfa.md` 참조. 배포 서버 `192.168.1.14`/계정 `me0kmin27`은 확정이고 부모 SSH 접속 검증 성공. 후속 사용자 승인으로 Docker 준비와 해당 서버의 loopback 검증 배포만 허용됐다. 공개 포트/운영 개방은 금지이며 `internal-container-deployment.md`의 경계를 따른다. 단독/복수 전체Admin 모두 지원하며 복구 승인 정책 선택·키 백업/훈련은 별도 운영 게이트이고 이전 문구의 custody/hosting 미결정을 대체한다.

## 범위와 경계
Synology-Admin(me0kmin27/Synology-Admin)은 별도 고객 포털이다.
me0kmin27/Rustdesk-Quicksupport는 향후 연동 대상이며 이번 작업에서 수정하지 않는다.
현재 안내/health 및 독립 포털 가입·로그인·회원 상태·범위 제한 관리 UI를 구현했다. 최신 구현 경계는 `membership-operations.md`와 `evidence/membership-tdd.md` 참조.
Django 내장 auth 테이블 설치는 회원 승인 기능 완성을 뜻하지 않는다.

## 확정 요구사항 / 제안 / 미결정
확정: 가입 신청→관리자 승인, 회원 관리, NAS 공유폴더 사용자/그룹 권한,
계정/그룹별 할당·사용·잔여 용량, 고객지원 티켓/채팅, 동의 기반 원격지원.
구현: Django 단일 앱, 일회 개발 SQLite. 그룹 정책 동시성의 운영 계약은 PostgreSQL READ COMMITTED + DB sessions 필수이며 SQLite 관리 변경은 기본 fail-closed. NAS 연결은 별도 adapter/worker 제안.
미결정: NAS 모델·DSM·파일시스템·API capability, 사용자/그룹 quota 지원 및 중복 그룹 집계,
갱신 주기·SLO, 그룹 사용량 열람 범위, NAS 연결 상세 절차, 보존기한·RPO/RTO·과금.
인증 방식 확정: authentik 선택 OIDC + 기존 로컬 비상 로그인 유지 → 포털 관리자 승인 → NAS 계정 연결. Synology SSO 제안은 대체되었다. issuer+subject 고유 매핑, 이메일 자동 연결 금지, IdP 그룹에 의한 권한 승격 금지, 신규 pending 승인, 기존 MFA/재인증 경계 유지. DSM 비밀번호로 포털 로그인하지 않는다. `authentik-oidc.md`와 `membership-auth-decision.md` 참조.
구현 데이터: OIDCIdentity(issuer, subject, unique user), OIDCLoginAttempt(state hash, browser/config binding, 5분 만료, 원자적 1회 소비, 서버측 tenant/PKCE/nonce). 토큰은 저장하지 않으며 IdP provider 설정/운영 활성화는 별도 게이트이다.
어떠한 API 지원이나 웹 원격지원 가능 여부도 아직 입증되지 않았다.

## 역할과 격리 수용 기준 (회원 일부 구현, 전체 수용 미완료)
- 방문자: 안내/신청만. 신청자: 승인 전 NAS/다른 회원 정보 접근 금지.
- 승인 회원: 자신의 tenant와 허용된 자원만. tenant ID는 요청 입력을 신뢰하지 않고 세션 membership에서 결정.
- 지원 담당: 배정 티켓에만 접근, NAS 관리 권한 없음. 관리자: 승인된 관리 범위만.
- 모든 object 접근에 tenant+membership 권한 확인; ID 추측/직접 URL/검색/파일/웹소켓 교차 tenant 거부 테스트 필수.
- 승인 원자성·중복 방지·승인 취소 시 세션/캐시 무효화. 앱 승인과 NAS 프로비저닝 상태는 별도 기록.
- NAS 변경은 재인증/명시 승인, 최소 권한 서비스 계정, TLS 검증, timeout, 재시도 제한,
  idempotency key, 실행 전후 감사, 실패 시 보상 또는 수동 복구. DB 성공을 NAS 성공으로 표시 금지.
- 관리 계정 MFA, rate limit, 비밀번호 정책, CSRF, 세션 회전/만료는 인증 단계 필수 수용 기준.

## 추가 확정 요구 (2026-10-11)
전역 admin 아래 고객사 그룹별 관리자 지정, 그룹 선택 가입 신청, 그룹 총 용량·최대 계정 수 한도, 접근 비활성화·세션 폐기·감사 유지 방식의 계정 폐기를 확정했다. 상세 수용 기준은 `membership-group-acceptance.md`를 따른다. 기존 scoped 승인/취소만으로 신규 요구를 충족했다고 주장하지 않는다. 최신 정식 DSM 기준으로 개발하며 모델 미정은 개발 차단이 아닌 실제 연동 검증 게이트이다. 공식 버전 직접 조회 결과와 MFA 미완료 판정은 `evidence/membership-security-review.md` 참조.

## 논리 데이터 모델 (회원 테이블 일부 구현; 나머지 설계)
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
