# 회원 단계 독립 보안 리뷰 / 경계 커밋 인계

확인일: 2026-10-11. 대상 기준 SHA: `5df8ce8ae84a2303225ab45a11548076f59c3e92`, 브랜치 `feat/stage-3-membership`.

## 판정
**기존 부분 구현의 독립 검토는 수행했으나 3단계 전체 수용은 불가. 운영 공개 금지.** 관리자 MFA와 새 고객사 그룹 요구가 미구현이다. 전체 프로젝트 완료율은 계산하지 않는다. 최신 사용자 지시에 따라 안전한 보안 수정 경계에서 멈추고 확대 구현을 부모에게 반환한다. 이 패치도 부모의 독립 재검토 대상이다.

원격 PR #2는 이 세션의 변경 전 기준 SHA를 대상으로 이미 `2026-10-11T12:16:18Z`에 병합되어 있었다(merge SHA `702e163777713bb406d1544b4dfea8bad07ada69`). 이 리뷰 세션에서는 main 병합/배포를 수행하지 않았다. 새 요구 수용 및 부모 확인 전 후속 PR 병합 금지.

## 재현 후 수정 — 순차 RED→GREEN

1. **로그인 대상 계정 rate limit 정규화 우회**: Django 인증은 NFKC 정규화하지만 기존 throttle은 원문을 키로 사용했다. 서로 다른 IP에서 `Alice`/전각 변형을 번갈아 보내면 동일 인증 대상의 제한을 나눌 수 있었다. Django `UsernameField`를 재사용해 정규화/strip 후 키 생성. `review-throttle-nfkc-red.txt`의 `200 != 429` → `review-throttle-nfkc-green.txt` 통과.
2. **기존 로그인 세션을 이용한 대상 계정 제한 우회**: 로그인 POST의 키가 제출 username이 아닌 현재 session user PK가 되어 다른 로그인 사용자/IP마다 피해 대상 버킷이 분산됐다. 로그인/가입은 제출 대상, manage만 현재 actor로 분리. `review-throttle-authenticated-red.txt`의 `200 != 429` → `review-throttle-authenticated-green.txt` 통과.
3. **커스텀 회원 view의 오류 보고 POST 노출**: signup/approve/revoke/assign/link에 민감 POST 표시가 없어 Django 오류 보고 필터가 원문을 반환했다. `sensitive_post_parameters()`로 전체 POST를 표시. `review-error-redaction-red.txt`의 5개 view subtest 실패 → `review-error-redaction-green.txt` 통과. DEBUG=False 기본 필터 범위의 검증이며 reverse proxy/외부 APM/임의 로그까지 보호한다고 주장하지 않는다.

신규 테스트: `tests/test_security_review.py` 3개. mock은 시간 고정에만 사용, 실제 Django auth/DB/middleware/filter를 실행했다. 합계 **31 tests 통과**, skip/expectedFailure 없음. 전체 기준선 28 tests도 먼저 통과했다. 최종 로컬 결과 `membership-security-review-verification.txt`: 21 migrations, migration drift 없음, deploy check 통과, 실제 loopback HTTP 200/200/400 및 기존 회원 form flow 통과. `pip check` 통과.

## 검토 영역과 미해결 위험

- **tenant 격리 / CSRF**: 모든 현재 manage mutation에서 scoped queryset과 CSRF POST, 비밀번호 재인증, 자기 객체 변경 거부 확인. 교차 tenant/위조 query/권한 필드/기본 staff 승격 거부 테스트 통과. 이는 신규 그룹 권한 위임 UI나 한도 구현 검증이 아니다.
- **승인/취소/세션**: subject 조건부 update·audit 같은 transaction, session_version 및 session 삭제/복원 재생 거부 확인. suspended 사용자는 다시 로그인하여 상태 화면을 볼 수 있다. 새 요구의 계정 폐기(User 비활성화)와 같지 않다.
- **동시성 잔여 위험**: `managed_members()`의 actor 승인/역할 조회는 actor 행 잠금 없이 subject 잠금보다 먼저 수행된다. 관리자 권한 철회와 이미 진행 중인 mutation 사이 직렬화는 입증되지 않았고 PostgreSQL 실경합 검증도 없다. 기존 단일 대상 조건부 update만으로 actor 철회 경합 또는 새 그룹 최대계정 제한 충족을 주장하지 않는다. 새 그룹별 잠금/한도 설계에서 함께 해결해야 한다.
- **rate storage**: DB HMAC 키/원자 증가로 프로세스 간 공유. 평문 username/IP 저장 없음. 15분 fixed-window 경계 burst, 계정 lockout DoS, 프록시 IP 설정, 대량 IP로 인한 DB row 증가와 매 요청 과거-window 삭제 비용은 운영 게이트다. 추가 캐시나 Redis를 임의 도입하지 않았다.
- **감사**: allowlist 형태의 actor/subject/action/state만 저장, 제출 reason/password는 감사에 없음. append-only DB/tamper-proof/보존 정책은 미구현. 예외 수집 경로 전체의 비밀 보호는 추가 운영 검증 필요.
- **bootstrap**: 전역 관리자 신뢰 CLI 생성, 공개 역할 승격 없음. 실제 관리자/OTP/복구 비밀을 생성하거나 출력하지 않음. 그룹관리자 지정·교체·마지막 관리자 보호는 새 요구로 미구현.
- **NAS 매핑**: external_id와 ownership 확인만, 실제 NAS 인증/프로비저닝/파일 삭제 없음. 회원당 1개 및 전역 unique는 단일 namespace 가정이다. DSM case/Unicode 정규화, multi-NAS, identifier 소유권 검증과 NAS quota 강제 집행은 별도 단계다.
- **메일**: 이메일 검증/웹 비밀번호 복구 미구현. 메일 대상/전달 검증이 없으므로 배포 게이트로 명시적으로 유예하며 메일 구현 완료로 계산하지 않는다.

## 관리자 MFA — 공식 자료 확인, 아키텍처 결정 미완료

`django-otp`는 검증된 OTP device와 로그인/검증 상태 구분, middleware 및 OTP 필수 접근 제어를 제공하며 등록 흐름은 애플리케이션이 구성해야 한다.[1] 내장 TOTP model에는 원문에 해당하는 hex key 필드, 재생 방지를 위한 `last_t`, 검증 실패 throttle이 존재한다.[2] PyOTP는 비밀 보관, 재생 방지 상태 저장, 시도 제한을 애플리케이션 책임으로 명시한다.[3]

**권고(미승인)**: 직접 OTP 암호 구현 금지, 유지보수 패키지의 TOTP 및 transaction-aware 검증 경로 재사용. 단순 PyOTP `verify()` 추가만으로 MFA 완료 처리 금지.

부모/사용자 결정이 필요한 경계: 기존 ‘런타임 secret store’ 요구를 유지할지, 별도 암호화 키 관리/백업 정책 아래 DB secret 저장을 승인할지; 전역/그룹 관리자 최초 등록과 device 분실 복구 담당/신원 확인 정책. stock device를 그대로 설치하면 이 저장 정책을 암묵 변경하게 된다. 본 경계 커밋은 패키지 설치/secret migration/복구 우회 경로를 임의 추가하지 않는다. 관리자 MFA는 **미구현이며 인증 단계 완료 credit 없음**.

MFA 후속 필수 테스트: 미등록 관리자 fail-closed, 등록 확인 전 권한 없음, 올바른 password+OTP, 잘못된/만료 OTP, replay/동시 replay, throttle, OTP device 교체·삭제와 session 폐기, CSRF/no-store, secret·recovery token 로그/응답/감사 누출 금지. 운영 복구 비밀은 채팅/CI/Git에 출력하지 않는다.

## DSM 기준 직접 재확인

앞서 전달된 검증 없는 버전값을 근거로 사용하지 않고 공식 release note 페이지의 AJAX endpoint를 직접 조회했다.[4][5]

2026-10-11 조회 결과 최상위 DSM은 **7.4.1-90080**, `publish_date=2026-07-23`, `is_rc=false`, `is_rolling=true`이며 공식 archive 최상위와도 일치했다.[5][6]

확인된 공식 최신 정식 계열을 개발 기준으로 삼되 단계적 배포·모델별 제한이 있으므로 모든 NAS에서 지원된다는 뜻은 아니다.[5]

모델 미정은 포털/adapter 설계 개발의 차단 사유가 아니며, 실제 선택 장비의 지원 버전·API capability·quota 의미 확인은 연동 수용 게이트다. NAS 업데이트/접속은 수행하지 않았다.

조회 메타데이터: `dsm-official-review.json`. 출처 본문 전체나 자격증명은 저장하지 않는다.

## 새 그룹 요구

`../membership-group-acceptance.md`의 모든 신규 수용 기준은 별도로 미충족 상태를 유지한다. 기존 31개 통과 테스트를 그룹 한도/폐기/마지막 관리자/MFA의 통과 증거로 재사용하지 않는다.

## Sources

[1] https://raw.githubusercontent.com/django-otp/django-otp/master/docs/source/overview.rst
[2] https://raw.githubusercontent.com/django-otp/django-otp/master/src/django_otp/plugins/otp_totp/models.py
[3] https://pyauth.github.io/pyotp
[4] https://www.synology.com/en-global/releaseNote/DSM
[5] https://www.synology.com/api/releaseNote/findChangeLog?identify=DSM&lang=en-global
[6] https://archive.synology.com/download/Os/DSM
