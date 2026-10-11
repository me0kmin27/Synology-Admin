# 관리자 OTP — 첫 수직 슬라이스 (운영 배포 아님)

사용자 3A 확정: 포털 자체 OTP, encrypted seed DB + DB 외부 전용 키.
1A/2A/4A와 남은 운영 입력은 `next-decisions.md` 상단 참조.

## 구현 계약

- `django-otp==1.7.4`의 Device/ThrottlingMixin/TimestampMixin/TOTP 사용.
  stock TOTPDevice/평문 key column은 설치하지 않음. SHA1, 6자리, 30초,
  허용 ±1 step; 마지막 수용 timestep보다 큰 token만 수용한다. drift를
  영구 자동 확대하지 않는다. 암호 구현은 django-otp에 위임한다.
- cryptography 50.0.2 Fernet/MultiFernet으로 `{v,user,device UUID,seed}`
  envelope를 인증 암호화. row/user 이식 거부. DB에는 ciphertext와 replay/
  throttle metadata만 보관. `MFA_ENCRYPTION_KEYS`는 쉼표 구분된 Fernet 키를
  보호된 런타임 환경/secret injector로 전달하며 첫 키로 암호화한다.
  값은 Git/DB/이미지/명령행/로그에 두지 않는다. `DJANGO_SECRET_KEY`와
  분리하며 기본/자동 생성 키 없음. 누락·오류·변조는 503 fail-closed.
- 등록: 로그인 + 현재 비밀번호 POST 재인증 → 5분 unconfirmed device →
  생성 세션에서 OTP 성공 후 confirmed. seed는 그 POST 응답의 same-origin
  HTML에서 **직접 입력용**으로만 제공; 외부 QR/JS/이미지 호출 없음.
  QR는 이 슬라이스에 없음. 새로고침/타 세션에 seed를 다시 공개하지 않음.
  미확인 device는 만료 후 password 재인증으로 재시작 가능. 확인된 device의
  overwrite/reset/delete 웹 경로 없음. 복구 우회 기능도 없음.
- 확인/로그인 challenge: policy advisory lock → fresh User/scope → device
  select_for_update → library TOTP 검증. 실패를 응답으로 반환하여 DB throttle
  commit. device exponential throttle와 account/IP 15분 고정-window 제한 병행.
- OTP 성공 시 session key 회전, device UUID+ciphertext HMAC 식별자와 검증
  시각 저장. 관리자 access는 15분 내 OTP 필요; 각 관리 mutation은 여전히
  현재 password POST도 필요. 새 로그인은 OTP stamp를 제거한다.
- 전역/그룹 관리자 및 staff는 정확한 enroll/verify/login/logout/health 이외
  **모든 경로**에 중앙 gate 적용. GET/HEAD는 setup/challenge redirect,
  mutation은 403. 새 관리 URL도 기본 보호된다. 익명/일반 회원은 기존
  scoped 권한 검사를 유지한다. 이 앱에는 Django admin URL이 없다.
- fresh auth scope(active/staff/superuser/membership role/status/tenant/epoch)
  또는 verified device 변경·삭제·unconfirm 때 기존 세션은 다음 요청에서
  flush된다. DB 소유자가 상태를 원복하는 공격/WORM 보장은 아니다.
  권한 writer와 gate 전체 synchronous response가 동일 policy lock 아래
  실행되어 검증 이후 권한 철회와 경쟁하지 않음. 관리 mutation boundary는
  별도로 MFA를 재검사한다. streaming/외부 I/O를 이 lock 안에 추가하지 말 것.
- PostgreSQL READ COMMITTED + DB sessions 운영 계약. SQLite mutation은
  기존 disposable opt-in 외 거부한다. 직접 SQL/CLI 권한·device writer도
  반드시 같은 policy advisory lock을 먼저 취득해야 한다. global lock은
  처리량 제한이며 대규모 서비스의 fine-grained 설계라고 주장하지 않는다.
- MFA 응답은 no-store; CSRF 및 view 이전 sensitive POST redaction 적용.
  runtime/APM/proxy는 request/response body 수집을 별도로 금지해야 한다.
  seed는 등록 응답/검증 순간 메모리에 존재하므로 앱 호스트 탈취 방어 아님.

## 배포 차단 / 별도 후속 복구

그룹 관리자 복구에 globalAdmin 승인이 필요하다는 원칙은 확정이다.
단독/복수 globalAdmin 모델을 모두 지원하며 수량을 하나로 고정하지 않는다.
복구는 단독 운영의 지정 trustee/신뢰된 호스트 관리자 확인 또는 복수 운영의
지정된 다른 globalAdmin 승인 중 명시적인 정책 선택 구조로 후속 구현한다.
두 사람 승인을 모든 배포의 필수조건으로 강제하거나 단독 운영의 이중 승인을
거짓 보장하지 않는다. **globalAdmin 복구 책임자, 신원 확인/승인 절차, 암호화 키 백업 책임자와
별도 보관·복원 훈련은 미정**. 이번 PR에는 복구 명령/코드/reset endpoint가
없다. 이를 self-service bypass로 대체하지 않는다. 실제 키 provisioning도
하지 않았다. 키/DB 복구는 replay/session rollback 위험까지 검증해야 한다.
키 회전 API 가능성과 운영 회전/재암호화 훈련 완료는 다르다.

NAS와 분리된 포털/DB 서버는 `192.168.1.14`, 계정 `me0kmin27`로 확정.
접속/배포는 부모 별도 확인 전 금지하며 이번 작업에서는 접속하지 않는다.
NAS 기종/파일시스템은 정보표시·회원관리 개발의 선행조건이 아니다.
특정 기종/Btrfs를 강제하지 않고 선택 메타데이터·연동 capability를 분리한다.
관측 없는 NAS 실제 quota enforcement 성공 주장은 금지한다.
운영 TLS/키·백업/복구 승인·부하 검증 전 공개 배포 금지. MFA 첫 slice의
독립 검토와 전체 인증 단계·복구·운영 준비 완료는 별도이다.

## 검증

`tests/test_mfa.py`는 password-only Django Client로 gate 부정을 검사한다.
기존 관리 테스트는 `tests/mfa_helpers.py`의 synthetic encrypted device와
**실제 HTTP OTP challenge**를 통과하는 명시적 fixture Client를 사용한다.
production MFA disable 옵션/자동검증 middleware는 없다.
`tests/test_membership_http.py`는 실제 cookie/CSRF 등록·확인 후 관리한다.
`browser_tests/mfa.py` 및 기존 chat/storage Chromium도 실제 등록을 수행한다.
`concurrency/mfa_races.py`는 PostgreSQL pg_blocking_pids로 실제 대기 overlap,
단일 replay winner와 failure commit/등록 경쟁을 검증하며 SQLite skip 없음.
RED/GREEN, 회귀, 브라우저 기록은 `evidence/mfa-*.txt` 참조.

## 직접 확인한 공식 문서 (2026-10-12)

- https://django-otp-official.readthedocs.io/en/stable/extend.html
- https://django-otp-official.readthedocs.io/en/stable/_modules/django_otp/plugins/otp_totp/models.html
- https://cryptography.io/en/latest/fernet/

공식 문서의 검증 primitive/mixin과 authenticated-encryption 계약만 재사용.
라이브러리 기본 평문 seed 보관을 포털 저장 정책으로 오인하지 않는다.
