# 관리자 OTP와 전역 등록 정책

## 변경된 사용자 요구사항

관리자 OTP의 무조건 필수 등록 요구는 이번 사용자 지시로 대체됐다.
DB singleton `AdminMFAPolicy(pk=1)`의 `required` 기본값은 **FALSE**다.
환경변수나 프로세스 캐시가 아닌 DB 전역 정책이며 migration 0014가 한 번
생성한다. 누락된 행을 런타임에서 선택 정책으로 자동 복구하지 않는다.

- 선택 정책: OTP 미등록 관리자는 비밀번호 로그인과 초기 비밀번호 변경 후
  관리 기능을 사용할 수 있다. OTP device를 자동 생성하지 않는다.
- 확인 완료한 device가 있으면 선택 정책에서도 OTP는 계속 필수다.
  정책 해제는 기존 등록·seed·replay 상태를 변경/삭제하지 않는다.
- 필수 정책: superuser(globalAdmin), staff, 승인된 그룹관리자 모두 대상이다.
  일반 회원의 기존 역할·tenant·승인 경계는 바뀌지 않는다.
- bootstrap의 초기 비밀번호 변경은 여전히 필수다. 선택 정책에서 OTP 등록은
  초기 로그인/비밀번호 변경의 선행조건이 아니다.

## 전역 정책 설정

`/manage/mfa-policy/`는 활성 globalAdmin만 사용한다. 관리 콘솔에 링크가 있다.
GET은 정책을 바꾸지 않으며 POST는 CSRF와 account/IP throttle로 보호한다.

1. fresh DB 사용자·세션·역할·membership epoch·정책 version을 재검사한다.
2. 현재 비밀번호를 실제 hash와 대조하고 Django 강도 검증도 통과해야 한다.
3. 필수로 켜려면 행위자의 확인 완료 OTP device가 반드시 있어야 한다.
4. 행위자에게 device가 있거나 이전 정책이 필수이면 **새로운 일회 OTP**를
   검증한다. 최근 세션 OTP stamp만으로 정책 변경을 승인하지 않는다.
5. 끄기도 이전 필수 정책 아래 새 OTP를 요구한다. replay 실패/throttle는
   rollback하지 않고 commit한다. 미확인 device로 정책을 켤 수 없다.
6. 변경 시 단조 증가하는 version과 metadata-only `MFAPolicyAudit`를 같은
   트랜잭션에 기록한다. actor ID, 이전/현재 boolean, version, 시간만 보관한다.

동일한 global PostgreSQL transaction advisory lock(7310462901)을 middleware의
fresh DB 조회부터 synchronous response까지, 정책 변경, 계정 변경 및 관리
mutation 내부 재검사에 사용한다. 활성화 전 세션은 모든 관리 경로에서 추가
OTP 인증/등록을 요구한다. 행위자의 세션만 방금 소비한 OTP로 새 version을
받는다. 직접 view 호출/대기 중 cached session도 mutation boundary에서 옛
version으로 거부한다. 이후 선택 정책이 되더라도 옛 version을 조용히 신뢰하지
않고 미등록 관리자는 재로그인, 등록 관리자는 OTP 재인증한다.

PostgreSQL READ COMMITTED + DB sessions 계약이다. SQLite 변경은 기존의
명시적 disposable 개발 opt-in 외에는 503이다. 직접 SQL/CLI 역할·device·정책
writer도 같은 advisory lock을 먼저 취득해야 한다. global lock은 처리량을
제한한다. 이 경계 안에 외부 I/O나 streaming response를 추가하지 말 것.

## 등록과 로컬 QR

로그인한 관리자가 `/mfa/enroll/`에서 현재 비밀번호를 POST하여 5분짜리
미확인 device를 생성한다. 생성 세션에서 OTP를 확인해야 opt-in이 완료된다.
확인된 device를 덮어쓰기/초기화/삭제하는 웹 경로는 없다.

- `qrcode==8.2`의 `SvgPathFillImage`로 서버 내부에서 흰 배경/quiet border가
  있는 SVG를 만든다. 외부 QR 서비스, 외부 이미지/JS, data-image 허용은 없다.
- QR과 수동 입력용 seed는 인증된 생성 POST의 `no-store` 응답에서만 제공한다.
  GET·다른 세션·재등록 응답에서는 재공개하지 않는다.
- URI는 `otpauth://totp/` + URL 인코딩한 issuer/account label이며 query에는
  base32 secret, issuer=`Synology-Admin`, algorithm=SHA1, digits=6, period=30을
  명시한다. username은 SVG text/markup에 삽입하지 않고 QR geometry로만 변환한다.
- seed/URI/비밀번호/OTP는 로그·감사·세션에 넣지 않는다. view 이전 CSRF/throttle
  오류에도 POST redaction과 no-store를 적용한다. proxy/APM body 수집도 운영자가
  금지해야 한다. synthetic test QR 외 운영 등록 화면은 캡처하지 않는다.

## 기존 암호 및 OTP 계약 유지

`django-otp==1.7.4`의 TOTP/Device/ThrottlingMixin/TimestampMixin을 사용한다.
SHA1, 6자리, 30초, ±1 step, 마지막 수용 timestep 이후만 허용한다.
OTP 성공 시 session key 회전과 device UUID+ciphertext HMAC, 15분 stamp를
저장한다. 역할/활성/membership epoch/device 변경은 기존 세션을 거부한다.

`cryptography==50.0.2` Fernet/MultiFernet은 user/device-bound seed envelope를
암호화한다. 기존 외부 `MFA_ENCRYPTION_KEYS`를 그대로 보존한다. 기본 키나
자동 키 생성은 없다. key 누락/변조는 fail-closed이며 선택 정책은 확인 완료
device의 키 장애를 우회하지 않는다. DB에는 평문 seed column이 없다.

## 검증과 작업 경계

- `tests/test_optional_mfa.py`: 선택 bootstrap, 정책 활성화, 로컬 QR, UI 진입.
- `tests/test_mfa_policy_security.py`: confirmed opt-in 유지, 강한 재인증,
  globalAdmin/CSRF/replay/throttle, 모든 admin role/route, stale 내부 mutation,
  계정 변경 downgrade 거부, 정책 누락 및 stale 선택 세션.
- 이전 mandatory-negative 테스트는 명시적으로 DB 정책을 TRUE로 설정한다.
  기존 테스트의 부정 assertion을 없애지 않는다. legacy transaction/browser
  fixture도 필수 정책을 명시하며 새 선택 테스트는 FALSE를 명시한다.
- `concurrency.optional_policy_races.OptionalPolicyRaces`: 실제 PostgreSQL
  `pg_blocking_pids`로 session read/inner mutation과 toggle의 양방향 대기,
  독립 globalAdmin들의 동시 toggle을 입증한다. 비PG는 skip 대신 실패한다.
- `browser_tests.optional_qr.OptionalQRBrowserTests`: 실제 Chromium의 생성 POST
  SVG 픽셀을 zxing-cpp로 decode하여 고정 **가짜 seed** URI 전 필드를 대조한다.
  강화된 CSP, 외부 요청 없음, 생성 GET 비노출, 선택 등록 후 재로그인도 검사한다.
- CI에 위 PG/QR label을 별도 이름의 필수 실행 step으로 등록했다.
  실제 실행 결과는 `evidence/optional-otp-tdd.txt`와 최종 PR checks로 확인한다.

이 작업은 서버/운영 계정/키/DB에 접근하거나 배포하지 않는다. 독립 검토·병합은
부모 담당이며 작업자는 PR을 병합하지 않는다. 기존 `evidence/mfa-*`와 과거
bootstrap/배포 문서는 **당시 mandatory 정책의 역사적 증거**이지 현 요구의
등록 필수 조건이 아니다. 선택 bootstrap에 OTP를 가짜 차단조건으로 제시하지 않는다.
TLS, 승인된 배포, 백업·복구 훈련 및 실제 NAS 연동 검증은 별도 운영 범위다.
복구/reset 기능은 추가하지 않았다.

## 직접 확인한 primary 문서

- https://github.com/lincolnloop/python-qrcode/blob/v8.2/README.rst
  SVG factories, white background, border, attrib 및 to_string API 확인.
- 기존 OTP/암호 근거:
  https://django-otp-official.readthedocs.io/en/stable/extend.html
  https://django-otp-official.readthedocs.io/en/stable/_modules/django_otp/plugins/otp_totp/models.html
  https://cryptography.io/en/latest/fernet/
