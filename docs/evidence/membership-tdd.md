# 3단계 회원 구현 증거 (독립 검토 대기)

기준 SHA: `0ff871874e300c4ddbe1768ed5879d318b5da0e9`; 작업 브랜치 `feat/stage-3-membership`. main 병합 없음.

로그는 stdout/stderr를 합쳐 저장했으며 일부 줄 끝 공백만 정리했다. 테스트 비밀번호/식별자는 폐기 DB의 테스트 fixture이고 운영 비밀이 아니다.

## 수직 TDD 기록
- 가입: 첫 GET `/signup/` 404 → pending/tenant 미배정/member 및 비권한 User 생성 → 1 test OK. 최초 RED/GREEN은 실행 도구 출력에 있으며 별도 raw 파일은 당시 저장하지 않았다.
- 로그인/상태/로그아웃: POST `/login/` 404 → Django 내장 로그인/POST 로그아웃, pending 서비스 403 → 2 tests OK. 위와 동일하게 최초 raw 파일은 없음.
- 승인: `membership-approval-red.txt` 404≠403 → `membership-approval-green.txt` 3 tests OK.
- 취소: `membership-revoke-red.txt` 404≠302 → `membership-revoke-green.txt` 4 tests OK.
- 관리 UI/테넌트 배정: `membership-management-red.txt` 404 → 구현. 최초 green 시도에서 테스트 문자열 `hidden`이 CSRF hidden input과 충돌. `<h2>hidden</h2>`로 정확히 고쳐 `membership-management-green-corrected.txt` 5 tests OK. 실패한 시도도 보존.
- NAS 식별자 매핑: `membership-link-red.txt` 404≠302 → `membership-link-green.txt` 6 tests OK.
- 비밀번호 정책: 약한 비밀번호 가입이 302였음 → Django validators → `membership-password-green.txt`.
- 로그인 제한: 네 번째 요청 200≠429 → DB 공유 fixed-window 제한 → `membership-throttle-green.txt`.
- DB 제약: invalid status/role/tenant 없는 approved가 모두 허용됨. 초기 테스트 중복 username 오염을 고친 `membership-constraints-red-corrected.txt`의 3개 실패 확인 → check constraints migration → green.
- 랜딩: 이전 미구현 문구에 대한 RED → 현재 기능/미제공 기능 구분 → `membership-landing-green.txt`.
- 세션 만료: 기본 1209600초 > 1800초 RED → 30분/브라우저 종료 설정 → `membership-expiry-green.txt`.
- verifier: 전체 26 tests 통과 후 `assert migrations == 15`가 실제 21에서 실패 → migration graph leaf/적용 이력/미적용 plan 검증으로 교체.

`test_boundaries.py`와 실제 loopback HTTP/HTML 폼 `test_membership_http.py`는 기존 수직 구현의 회귀 확장이다. 이 추가 테스트들을 별도 기능 RED/GREEN으로 계산하지 않는다. HTTP 테스트 첫 실행은 LiveServer static handler의 STATIC_URL=None(urlparse bytes)로 실패했다. 설치된 Django 소스 추적 후 테스트 전용 STATIC_URL/MEDIA_URL을 설정, 같은 HTTP 흐름 통과. production 정적 파일 기능을 추가하지 않았다.

## 주장 경계
- 실제 DB migrations와 실제 HTTP 쿠키/CSRF/HTML 폼 흐름 실행. JS 브라우저 엔진 렌더링/시각 QA는 별도 증거가 없는 한 주장하지 않는다.
- 외부 NAS/RustDesk/운영 시스템 호출 없음. 식별자와 관리자 확인만 저장; 자동 소유 검증, NAS 프로비저닝, quota 없음.
- 관리자 MFA, 이메일 검증/웹 비밀번호 복구 미구현. 3단계 전체 완료나 운영 준비 완료로 표시하지 않는다.
- canonical 진행 파일/cron/다른 저장소 변경 없음. 가중치나 퍼센트 부여 없음.
