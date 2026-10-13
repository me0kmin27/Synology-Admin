# 전체 메뉴 감사 수정 — 2026-10-12

기준 revision: `a7bf7a5bf261e242fc7524c73706c8e7d02b6dac`.

## 실제 운영에서 재현한 문제

- Membership 없는 전역 관리자: 내 계정에 사용자 이름/역할 누락, 스토리지 빈 403.
- 로그인 상태 홈에 로그인/가입 CTA, 선택 OTP 정책과 모순되는 필수 인증 문구.
- 전역 관리자 지원 목록의 새 요청 CTA가 403으로 연결됨. 회원이 시작해야 하는 채팅의 빈 목록 안내도 부정확.
- 빈 DB의 관리 콘솔에 그룹 생성 기능이 없어 가입→승인 흐름을 UI로 시작할 수 없음.
- 그룹관리자 역할 선택이 현재 역할 대신 일반 회원으로 초기화됨.

실제 소유자 Safari 지정 창/탭에서 메뉴 이동, 지원 답변 작성, 채팅 전송 및 새로고침 readback, 티켓/답변/대화 페이지네이션을 검증했다. 운영 HTTPS의 별도 합성 계정으로 가입, 승인, 그룹 배정, 한도, 역할 지정/해제, quota, 식별자 매핑, 지원 생성/답변, 채팅 생성/전송/중복방지/수신, 계정 변경, 로그아웃, 폐기와 다른 tenant 접근 거부를 검증했다. 실제 소유자의 비밀번호/OTP/권한/정책은 변경하지 않았다. 합성 매핑은 포털 DB 테스트이며 실제 NAS 접근이 아니다.

## 변경

- 인증된 사용자 자체를 계정 표시의 원천으로 사용. 전역 역할과 회원 역할 구분.
- Membership 없는 전역 관리자에게 실제 그룹 정책 및 NAS 미연결 상태 표시. 회원 범위/승인/세션 검사는 유지.
- 로그인 상태별 홈 CTA와 정확한 OTP 안내. 생성 권한 없는 전역 검토 역할에 지원/채팅 안내.
- 전역 관리자 전용 POST `/manage/groups/new/`: 기존 공유 정책 lock·현재 비밀번호·MFA·CSRF 경계 재사용. 이름/slug 유효성 및 유일성, 0~2^63-1 한도, atomic 감사 기록. NAS 프로비저닝 없음.
- migration 0016: nullable unique slug 추가, 기존 그룹은 `legacy-PK`로 backfill. ID/관계/기존 설정 보존.
- 빈 HTML 오류를 복구 링크가 있는 안내로 표시하되 상태 코드 및 JSON/events API 유지. 변환한 본문의 Content-Length 재계산.
- 역할 select의 현재 역할 선택 표시.

## RED → GREEN 및 검증

최초 8개 회귀 테스트 실패 후 수정, 지원 목록 populated 안내 추가 RED→GREEN. 구현 agent의 sandbox에서는 loopback bind가 금지되어 소켓 관련 6개 오류가 났으며 이를 성공으로 처리하지 않았다. 상위 실행 환경에서 동일 코드를 실제 소켓으로 재검증했다.

- Content-Length: `0 != 14347` RED → 본문 길이와 일치 GREEN.
- 역할 선택: `[] != ['admin']` RED → 현재 역할 선택 GREEN.
- 최종 `scripts/verify.py`: **177 tests OK**, 보안 배포 검사, 실제 migration 38개, drift 없음, loopback HTTP 200/200/400.
- 실제 Chromium 포털: 22 상태 / 44 desktop·mobile 캡처, 입력/오류/지원/메시지/OTP/로그아웃, 외부 요청·JS 오류 없음.
- optional QR, storage, MFA 브라우저 테스트 통과. 합성 QR만 로컬에서 검증; 운영 QR/seed 수집 없음.
- 동시 채팅 브라우저 첫 SQLite run은 `database table is locked`로 실패. 재시도 및 PostgreSQL CI 결과는 별도로 확인하며 SQLite를 동시성 수용 근거로 삼지 않음.
- 독립 Codex read-only 검토: passed=true, security_concerns=[], logic_errors=[]; migration/endpoint-specific MFA 추가 coverage 제안은 비차단.

명령(일회 테스트용 secret만 사용):

```sh
PY=/Users/myeong-gyeongmin/.hermes/cache/scratch/synology-optional-otp/.venv/bin/python
"$PY" scripts/verify.py
"$PY" manage.py test browser_tests.portal_ui browser_tests.optional_qr browser_tests.chat browser_tests.storage browser_tests.mfa -v 2
```

상세 운영 증거/전체 UI 및 route inventory/RED·GREEN·최종 테스트/독립검토 로그:
`/Users/myeong-gyeongmin/.hermes/evidence/synology-menu-audit-20261012/`.
최종 병합 SHA·CI·배포·정리/readback은 해당 외부 증거에 기록한다. 이 문서 자체는 아직 미수행한 배포 성공을 주장하지 않는다.

## 구분해야 하는 제한

NAS 실제 사용량·quota 집행·파일/계정 프로비저닝, RustDesk 원격 세션은 미연동이다. 포털 예약값을 실제 NAS 관측값으로 대체하지 않았다. 소유자 비밀번호 재인증이 필요한 변경은 소유자 세션에서 누르지 않고 합성 HTTPS 세션과 로컬 isolated 브라우저로 검증했다. 전역 OTP 정책을 운영에서 토글하면 다른 사용자에게 영향이 있으므로 운영 정책 변경은 하지 않는다.
