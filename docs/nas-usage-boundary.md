# NAS 사용량 데이터 경계 — 오프라인 계약 준비

최신 결정: 2026-10-12 1A/2A/3A/4A 사용자 확정 (`next-decisions.md`). 관리자 OTP 등록·확인·강제의 첫 구현은 `admin-mfa.md` 참조. 배포 서버 `192.168.1.14`/계정 `me0kmin27`은 확정이나 접속·배포는 부모 별도 확인 전 금지. 단독/복수 전체Admin 모두 지원하며 복구 승인 정책 선택·키 백업/훈련은 별도 운영 게이트이고 이전 문구의 custody/hosting 미결정을 대체한다.

이 변경은 **순수 Python 값 검증·표시·읽기 protocol**만 제공한다. NAS 연동,
사용량 수집, 그룹 공동 quota 정책, 권한 강제 집행 또는 배포 완료가 아니다.
`docs/next-decisions.md`의 D1/D2/D3은 계속 미승인이다. 공유폴더·quota 귀속,
RustDesk 완전 자가 호스팅과 MFA encrypted DB seed custody는 1A/2A/3A/4A로 확정. 복구 trustee·키 백업 책임자/구매·호스트 선정 등 운영 입력은 별도 게이트이다.

## 값의 의미

- `Subject`: `tenant_id`, `kind` (`account` 또는 `group`), `subject_id`,
  `accounting_scope`가 모두 명시된다. ID를 정규화/추정하지 않는다.
  `accounting_scope`는 앞으로 검증할 accounting 계약의 불투명 식별자이지
  공유폴더를 만들거나 특정 NAS 구조를 선택하는 설정이 아니다.
- `UsageObservation`: immutable snapshot. `assigned_bytes`, `used_bytes`,
  `remaining_bytes`는 독립된 nullable 값이며 **자동 뺄셈·합산하지 않는다**.
  같은 subject/scope/source/관측시각의 값만 담는 것은 향후 adapter의 책임이다.
  portal 예약량이나 volume free를 여기의 NAS 잔여량으로 복사하지 않는다.
- `limit_kind=unknown`: 한도와 잔여량은 null; 사용량은 관측되었다면 존재 가능.
  `limited`: 명시적 정수 한도 필요(0도 실제 유한 한도).
  `unlimited`: 한도와 잔여량은 null이며 **사용량 0 또는 물리 여유 무제한을 뜻하지 않는다**.
- `state=not_configured`: adapter 미설정. `unknown`: 설정은 있어도 관측 없음.
  두 상태 모두 실제 수치·관측시각·관측 source를 지어내지 않는다.
  `observed`: timezone-aware `observed_at`과 비어 있지 않은 `source` 필수.
  source는 비밀/주소가 아닌 비민감 provenance 식별자로 사용해야 한다.
- bytes는 bool/float/string/음수를 거부한다. 사용량이 한도를 넘는 관측은
  허용하며 값 수정·clamp 또는 쓰기 허용 여부를 결정하지 않는다.

## 오래된 값과 표시

`freshness(now=..., max_age=...)`는 호출자가 시계와 허용 나이를 명시해야 한다.
기본 TTL을 선택하지 않는다. 나이가 max_age와 같으면 fresh, 초과하면 stale.
미래 관측시각, naive clock, 음수 TTL은 오류이며 최신으로 통과시키지 않는다.
오래된 snapshot의 값/원본 관측시각은 지우거나 현재 시각으로 갱신하지 않는다.

`display(...)`는 plain-text 표시용 딕셔너리이며 다음을 구분한다.

| 입력 | 표시 |
|---|---|
| 미설정 | 설정 안 됨 / 각 값 알 수 없음 |
| 미수집 | 미수집 / 각 값 알 수 없음 |
| null 수치 | 알 수 없음 (0 B 아님) |
| 관측한 0 | 0 B |
| 무제한 한도 | 무제한 / 잔여량 해당 없음 (무제한) |
| 오래된 관측 | 오래된 관측 / 알려진 값에 `(오래된 값)` |

이번 PR은 이 표시 함수를 실제 회원/관리 페이지에 연결하지 않는다.
새 UI·HTTP endpoint·migration·DB cache가 없고 기존 NAS 미연결 표시는 유지한다.
향후 UI는 status, source, observed_at을 함께 표시하고 null을 0으로 대체하면 안 된다.

## adapter 경계와 남은 게이트

`UsageReader.read_usage(subject)`는 앱 내부 read-only Protocol이다.
`NotConfiguredReader`만 제공하며 I/O 없이 요청 subject 그대로 미설정을 반환한다.
`runtime_checkable`은 메서드 존재만 확인한다. 권한 검사, 반환 subject 일치,
실제 vendor 계약, 수치 출처를 보증하는 장치가 아니다.

네트워크 adapter, endpoint/credential/config, write API, 자동 그룹 합산은 없다.
다음 별도 작업에는 승인된 데이터 귀속 정책, 정확한 모델/DSM/filesystem/API 계약,
최소 권한, tenant/subject 응답 일치 검증, 권한 거부/timeout/unsupported 오류 모델,
실장비 관측과 감사·보존 정책이 필요하다. 실제 외부 응답 증거는 이번에 생성하지 않았다.

## 검증 범위

`tests/test_nas_usage.py`는 synthetic domain 입력으로 실제 순수 함수를 실행한다.
각 동작을 RED → GREEN으로 순차 추가했다: 미설정, subject 검증, 관측 invariant,
신선도, 표시, 미설정 reader. mock NAS/API 성공 응답을 사용하지 않았다.
기존 `scripts/verify.py`의 전체 suite에서도 자동 발견된다.
CI와 독립 리뷰의 최종 head는 PR에서 확인해야 하며, 이 문서 자체는 병합 승인이 아니다.
canonical 진행률·로드맵 배점과 NAS/운영/Rustdesk-Quicksupport 저장소는 변경하지 않았다.
