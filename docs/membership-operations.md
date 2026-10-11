# 회원 기능 운영 경계와 로컬 확인

최신 결정: 2026-10-12 1A/2A/3A/4A 사용자 확정 (`next-decisions.md`). 관리자 OTP 등록·확인·강제의 첫 구현은 `admin-mfa.md` 참조. 배포 서버 `192.168.1.14`/계정 `me0kmin27`은 확정이고 부모 SSH 접속 검증 성공. 후속 사용자 승인으로 Docker 준비와 해당 서버의 loopback 검증 배포만 허용됐다. 공개 포트/운영 개방은 금지이며 `internal-container-deployment.md`의 경계를 따른다. 단독/복수 전체Admin 모두 지원하며 복구 승인 정책 선택·키 백업/훈련은 별도 운영 게이트이고 이전 문구의 custody/hosting 미결정을 대체한다.

포털 그룹 정책 구현/수용 기준은 `membership-group-acceptance.md`, TDD·실제 PostgreSQL 증거는 `evidence/groups-implementation.md` 참조. 이전 보안 리뷰(`evidence/membership-security-review.md`)는 당시 기준선 기록이다. 관리자 OTP 첫 slice 후에도 복구·운영 게이트가 남아 운영 공개와 3단계 전체 수용은 금지다.

## 지원 흐름

Django User + OneToOne Membership, 사용자당 하나의 고객사 그룹. `/signup/`에서 공개 그룹 선택 → pending/member → `/login/` 상태 확인 → 그룹관리자 승인 → 서비스 접근. 제출 role/status/is_staff/is_superuser는 무시한다. 선택한 tenant 변경은 제공하지 않는다.

전역 superuser만 `/manage/`에서 그룹 최대 활성 계정 수/포털 총 예약 용량을 설정하고 이미 승인된 회원을 그룹관리자로 지정/해제한다. 그룹관리자는 자신의 그룹 신청 승인, 계정 폐기, 한도 내 개별 포털 예약 용량 배정만 수행한다. 전역/그룹 관리 모두 CSRF POST와 현재 비밀번호 재인증이 필요하다. 비밀번호 재인증은 MFA가 아니다.

계정 폐기는 pending/approved/기존 suspended에서 가능하며 User 비활성화, suspended, session_version 증가, DB 세션 삭제, 감사 기록이 한 트랜잭션이다. 재시도는 중복 감사 없이 성공한다. 자기/전역 계정 폐기 금지, 마지막 활성 그룹관리자 폐기/강등 금지. 전역 관리자는 후임을 먼저 지정한다. 재활성화·tenant 이동·NAS 삭제·폐기 계정의 예약 용량 회수는 제공하지 않는다.

NAS 링크는 **소유 관계를 관리자가 별도 확인한 식별자 매핑**일 뿐 프로비저닝이 아니다. NAS 비밀번호/주소/API 토큰 입력이나 NAS 호출 없음. 식별자는 ASCII `[A-Za-z0-9_.@-]` 최대 128자, 전역 unique, 회원당 하나이다. NAS 실제 사용량은 미수집이며 예약 용량과 혼동하지 않는다.

## 데이터베이스와 잠금 계약

운영은 PostgreSQL READ COMMITTED + Django DB sessions 필수. PostgreSQL 17 CI 서비스에서 실제 독립 연결/transaction 경합을 실행한다. 로컬 SQLite 관리 변경은 기본 503; `DJANGO_ALLOW_UNSAFE_SQLITE=1`은 일회 단일 프로세스 개발/테스트 전용이며 동시성 보장이 없다.

환경: `DJANGO_DB_ENGINE=postgresql`, `PGDATABASE`, `PGUSER`, `PGHOST`, `PGPORT`, 필요 시 런타임 secret store의 `PGPASSWORD`. 운영 값은 Git/채팅/CI에 넣지 않는다. CI trust 인증은 폐기되는 전용 테스트 컨테이너에만 한정한다.

모든 정책 변경 및 로그인 session 게시는 `membership.locking.policy_transaction()`을 사용한다. 고정 advisory transaction lock → fresh actor User → subject/tenant 순서다. 요청 시작 시 캐시된 User 권한을 재사용하지 않는다. 외부 CLI/DB 관리자가 운영 User 활성 상태/권한/회원/한도를 직접 변경할 때도 같은 lock 계약과 감사 절차를 지켜야 한다. 직접 SQL을 웹 정책 검증의 우회 수단으로 지원하지 않는다. 대량 세션 순회와 전역 직렬화의 처리량/timeout/복구 부하 시험은 별도 운영 게이트다.

로그인 signal은 lock 안에서 현재 활성 상태를 다시 확인하고 session을 DB에 저장한다. 폐기 뒤 늦게 완료된 인증은 logout 처리한다. 이후 삭제된 session의 middleware 저장은 재생성 대신 실패하며, 복원된 과거 session도 inactive/version 검사로 거부한다. 이미 전송된 읽기 응답 소급 취소, NAS/웹소켓/worker 권한 검사는 별도 책임이다.

## 신뢰된 로컬 bootstrap (운영 배포 명령 아님)

README 개발 설정·migrate 후 사람이 신뢰된 터미널에서 `manage.py createsuperuser`를 실행한다. 비밀번호는 숨김 프롬프트에만 입력한다. 그룹 생성은 신뢰된 로컬 shell에서 `Tenant.objects.get_or_create(name="local-development")`; 기본 한도는 0이다. 이후 전역 관리자 웹 로그인 → 한도 설정 → 신청 승인 → 역할 지정 순서로 사용한다. 공개 관리자 bootstrap은 없다. migration 0010은 기존 활성 승인 계정 수를 초기 한도로 보전한다.

## 계속 미완료인 별도 게이트

- MFA custody/최초 등록은 3A와 `admin-mfa.md`로 갱신. 전역 복구 승인자·키 백업 책임자/복구 구현·훈련은 미완료. stock 평문 seed 저장 없음.
- 이메일 소유 검증, 웹 비밀번호 복구, 개인정보/감사 보존·백업 정책.
- 실제 NAS 모델/API capability, quota 적용·실사용량, 부분 실패 보상.
- 다중 프로세스 lock timeout·장애/부하·백업 복구 시험, 목록 pagination, 감사 tamper resistance.
- DB throttle은 15분 fixed window, IP/계정 각각 20 POST 제한(성공 포함). 프록시 실제 IP, 공유 IP 오탐/lockout DoS 정책은 별도 검증한다.
- 부모의 정확한 최종 HEAD 독립 리뷰. PR 병합과 운영 배포·전체 단계 완료를 동일시하지 않는다.
