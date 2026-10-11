# 핵심 잔여 범위 — 주간 의사결정과 검증 가능한 다음 작업

상태: **2026-10-12 사용자 1A/2A/3A/4A 확정**. 아래 과거 조사·대안은 결정 근거이며 재승인 요청이 아니다. 구현은 관리자 OTP 첫 수직 슬라이스만 별도 검증한다. 운영 배포·전체 인증/복구 완료나 완료율 추가를 뜻하지 않는다.

## 확정 결정 (후속 지시가 과거 제안보다 우선)

- **1A:** 고객사 전용 공유폴더 정책 채택. NAS 모델·파일시스템은 정보표시/회원관리 개발의 선행조건이 아니며 특정 기종이나 Btrfs를 강제하지 않는다. 선택 메타데이터 및 실제 adapter capability/데이터 귀속 검증은 분리한다. 관측 없이 NAS quota enforcement 성공을 주장하지 않는다.
- **2A:** RustDesk 브라우저 UI까지 완전 자가 호스팅. public hosted web client는 채택하지 않는다. 구매·라이선스 계약은 승인하지 않았으며 필요 조건/예산 검증 후 별도 승인한다. 기존 Rustdesk-Quicksupport 저장소 변경 금지.
- **3A:** 포털 자체 관리자 OTP, DB에는 암호화 seed만 보관하고 전용 암호화 키는 DB 밖에서 주입. 전역/그룹 관리자 등록·확인·접근 강제를 먼저 구현한다. 그룹 관리자 복구의 전역 관리자 승인 원칙은 확정. **전역 관리자 복구 승인/보관 책임자 및 키 백업 책임자는 미정**이며 배포 게이트이다. 복구/우회 구현은 이번 범위에서 제외.
- **4A:** 포털과 DB는 NAS와 분리된 별도 서버에 배치. 사용자 지정 배포 서버는 `192.168.1.14`, 계정은 `me0kmin27`로 확정. 실제 접속/배포는 부모의 별도 확인이 필요하며 현재 운영 수정 금지. 비밀번호/키 값은 수집·기록하지 않는다.

네 선택과 배포 호스트는 더 이상 pending이 아니다. 단독/복수 전체Admin을 모두 지원하며 단독 운영 고정이나 반드시 두 사람 복구를 강제하지 않는다. 단독은 지정된 외부 복구 trustee 또는 신뢰된 호스트 관리자 확인, 복수는 지정된 다른 전체Admin 승인 등 선택 가능한 정책 구조를 별도 확정한다. 자동복구/인증 우회는 제공하지 않는다. 남은 운영 입력은 실제 capability 시험, 라이선스/구매 승인, 선택한 복구 승인·키 백업 책임자와 복구 훈련이다.

기준: `me0kmin27/Synology-Admin`의 refreshed `origin/main` = `5af1f14bc0e79e6d31a634fc9069ba75e1ac42e6` (PR #8 병합 확인).
조사는 2026-10-11 23시대 KST에 시작했으며 자정을 넘긴 조회는 2026-10-12로 기록한다. 출처별 정확한 UTC 조회시각·방법·본문 해시는 `evidence/next-decisions-sources.json` 참조.

## 결정 요약 (이후 상세 조사는 역사적 근거)

| 확정 | 채택 정책 | 별도 운영 입력 / 경계 |
|---|---|---|
| 1A | 고객사 전용 공유폴더; 개인/고객사 용량 의미 분리 | 모델/파일시스템은 선택 메타데이터. portal 개발 선행조건 아님. 실제 capability/쓰기 관측 없이 NAS quota 강제 성공 주장 금지 |
| 2A | RustDesk 브라우저 UI까지 완전 자가 호스팅 | 구매/라이선스 계약 미승인; 권리·예산 별도 검증. 기존 RustDesk 저장소/운영 변경 없음 |
| 3A | 자체 OTP + encrypted DB seed + DB 외부 키 | 단독/복수 전체Admin 모두 지원. 복구 정책 선택·책임자/키 백업·훈련 미완료; 우회/자동복구 없음 |
| 4A | NAS와 분리된 포털/DB 서버 `192.168.1.14`, 계정 `me0kmin27` | 호스트 확정. 실제 접속/배포는 부모 별도 확인 전 금지 |

기존 독립 포털 계정 결정을 다시 묻지 않는다. 비밀, NAS 비밀번호, 라이선스 키를 채팅으로 요청하지 않는다. 야간 알림·cron·canonical 진행 JSON을 변경하지 않는다.

## D1 — 공식 지원 범위와 실제 용량 의미

### 최신 DSM 주장 재검증

이전 리뷰의 요약을 재사용하지 않고 Synology 공식 release-note JSON을 새로 GET했다. 최상위 항목은 **7.4.1-90080**, 공개일 **2026-07-23**, `is_rc=false`, `is_rolling=true`였고 공식 archive 첫 항목과 일치했다.[1][2]
개발 문서의 기준 계열로 사용할 수 있으나 배포 대상 모델 지원·설치된 빌드·API 지원 증명은 아니다. 릴리스 노트에는 모델별 배포 제한과 downgrade 제한이 있으므로 업그레이드를 자동 승인하지 않는다.[1]

### 문서화된 API와 문서화되지 않은 관리 동작 구분

검토한 공식 File Station API Guide는 112 PDF pages이다. 아래는 그 문서 범위의 지원 계약이며 DSM 전체 관리 API가 모두 공개되었다는 뜻이 아니다.[6]

| 확인한 계약 | 사용할 수 있는 정보 | 이 정보만으로 주장할 수 없는 것 |
|---|---|---|
| `SYNO.API.Info` / `SYNO.API.Auth` | API path·지원 version 조회 및 FileStation session 인증 | 발견된 endpoint의 장기 호환·최소 권한·quota 의미 보장 |
| `SYNO.FileStation.List`의 `list_share`, `getinfo`, `additional` | 파일/공유폴더 metadata, owner, permission, volume status | 다른 사용자의 완전한 유효 ACL·quota 정책/사용량 관리 |
| `volume_status.freespace`, `totalspace`, `readonly` | 공유폴더가 위치한 **volume** 상태 | 고객사 할당 잔여량 또는 쓰기 가능 보장 |
| `SYNO.FileStation.DirSize`의 start/status/stop | 비동기 경로 크기 계산·완료 상태 | 파일시스템 quota accounting, 예약 용량, 즉시 정확한 물리 사용량 |
| `SYNO.FileStation.CheckPermission.write` | **로그인한 사용자**의 해당 경로 쓰기 가능 검사 | 임의 회원 권한 변경 API나 전체 ACL export |
| `SYNO.FileStation.Sharing` | 공유 링크 관리 | DSM 사용자/그룹 공유폴더 접근권한 관리 |

위 표 근거: Guide의 Base API, List, DirSize, CheckPermission, Sharing 절. 이 문서에는 `SYNO.Core.*` 항목이 없고 quota 언급은 오류 코드뿐이다. 이번 조사에서 사용자/그룹 quota read/write 및 전체 DSM 권한 변경에 대한 공개·안정 관리 API 계약은 확보하지 못했다. **없다는 보편적 증명은 아니며**, DSM UI 내부 endpoint를 자동으로 공식 API로 분류하지 않는다.[6]

### 그룹 quota ≠ 고객사 공동 용량

공식 DSM 도움말은 그룹 quota가 **각 회원에게 상속되고 공동으로 나누어 쓰는 quota가 아니라고 명시**한다. 해당 페이지는 약 4 TB(4095 GB) 입력 제한과 공유폴더별 그룹 quota의 모델 architecture 제약도 명시한다. 이를 모든 새 모델의 확정 한계로 외삽하지 말고 선택 모델에서 재검증한다.[3]
사용자 quota는 그룹 quota보다 우선하며, Btrfs는 공유폴더별 사용자 quota, ext4는 volume 단위 사용자 quota라는 차이가 있다. 도움말의 “가장 큰 제한” 설명은 **전송 속도** 문맥이므로 중복 그룹의 저장 quota 결합 규칙으로 전용하지 않는다.[5]
공유폴더 자체 quota는 Btrfs에서 제공되며, `homes` 상한은 모든 home 디렉터리의 합에 적용된다. 따라서 고객사별 격리를 원할 때 전역 `homes` 상한을 고객사 quota로 취급하지 않는다.[4]
공유폴더 권한 충돌 우선순위는 No Access > Read/Write > Read Only로 설명되어 있다. 포털 그룹 role만으로 NAS 유효권한을 추정하지 않는다.[3][5]

**설계 제안/추론:** 고객사 하나가 전용 공유폴더 하나를 소유하는 정책은 공동 상한의 의미를 단순화한다. 하지만 다른 폴더에도 쓸 수 있는 회원, 서비스 계정이 소유한 파일, 공유 소유·중복 그룹, snapshot/휴지통/압축/metadata 및 다른 고객사의 쓰기 때문에 “quota 여유 = 실제 volume 여유 = 저장 보장”이라고 할 수 없다. 이 항목들은 승인된 실험의 관측 대상이며 이번 문서에서 측정 결과로 주장하지 않는다.

현재 `membership/groups.py`의 `allocated_bytes()`는 `Membership.quota_bytes`의 합이고 `Tenant.storage_limit_bytes`와 비교한다. 모듈 자체가 portal policy only라고 명시한다. **이것은 배분 장부이지 NAS 사용량/강제 집행이 아니다.** 기존 부하·경합 테스트를 NAS quota 검증으로 재사용하지 않는다.

**지금 가능한 안전한 작업:**
- 네트워크 없는 adapter interface와 결과 schema: `source_kind`, `subject_scope`, `nas_id`, `volume_id`, `share_id`, bytes, `collected_at`, `last_success_at`, stale/error/unsupported 구분.
- 정책 배분량, NAS가 보고한 quota/사용량, volume free를 별도 필드로 유지. `unknown`을 0으로 표시하지 않으며 다른 범위의 값을 빼서 잔여량을 만들지 않음.
- 문서 예시를 **synthetic contract fixture**로 명확히 표시하고 재시도/timeout/version mismatch/권한 거부/중복 volume 합산 방지 테스트. 이를 실제 NAS 응답 증거라고 부르지 않음.
- 관리 변경은 disabled capability. 승인 후 discovery → 최소 권한 읽기 → 테스트 공유폴더에서 before/after ACL·quota·실제 쓰기 관측 → 실패/보상 검증 순서. 문서 밖 endpoint 채택은 별도 ADR·버전 pin·보안 검토 필요.

## D2 — 기존 빌드센터, 서버, 브라우저 제어는 서로 다름

읽기 전용 확인 대상은 **`me0kmin27/Rustdesk-Quicksupport`**, private, default branch `main`, SHA `7d14a63c4a30ad11a23b18f038921a4537b04a85`이다. 이 저장소는 수정/실행하지 않았다.[13]

| 읽은 근거 | 확인한 범위 / 한계 |
|---|---|
| `README.md`, `SEGANG-README.md` | RustDesk OSS 1.4.9 기반 Windows x64 QS 패치·빌드, 고객 클릭 승인, 별도 Pro API/login 불필요라는 저장소 설명. 이것은 현재 운영 서버의 바이너리/라이선스 검사 결과가 아님.[13][15] |
| `portal/README.md` | 사내 웹앱은 EXE 빌드 요청·상태·다운로드용 **빌드센터**. 브라우저 원격 화면을 제공한다는 증거가 아님.[14] |
| tree metadata만 | `portal/compose.yaml`, `portal/.env.example`, `build-configs/*.json`, `.github/workflows/portal-windows.yml` 존재. 설정 값·비밀 파일·배포 보고서 내용은 열지 않음 |
| 문서의 검증 상태 | README의 2026-10-02 사용자 정상 동작 기록과 SEGANG 문서의 실제 Windows/원격/UAC 미검증 문구가 공존한다. 범위가 다를 수 있으므로 브라우저 제어 검증으로 통합 해석하지 않음.[13][15] |

공식 문서에서 OSS는 `hbbs`/`hbbr`, Pro는 web console/API/OIDC 등 중앙 관리 기능을 구분한다. WebSocket 전송 지원과 Pro web console 보유는 같은 조건이 아니다.[7][8]
공식 web-client 안내는 **public web client를 자기 ID/relay 서버에 연결하는 방식**과 **Pro에서 web client 자체를 자가 호스팅하는 방식**을 구분한다. 전자는 WSS와 적절한 CORS 구성이 필요하고, 브라우저는 제어하는 쪽이지 무인 접속을 받는 host가 아니다.[9]
같은 안내는 자가 호스팅 web client의 요금제 조건을 `(users × 10) + devices ≥ 400`으로 기재한다. 확인 시점 문구이지 구매 견적/권리 부여는 아니며, 계약 전 현재 공식 조건과 공급자 확인이 필요하다. **“모든 브라우저 연결에 Pro 필수” 또는 “OSS니까 무료 자가 호스팅 웹 UI 포함” 모두 성립하지 않는다.**[9]

**권장 검증 순서(운영 승인 전에는 테스트 설계만):**
1. 포털의 티켓 담당자·tenant·MFA와 유효한 고객 동의를 모두 검사한 뒤 연결 intent 발급. consent TTL, 철회, 일회 소비와 감사 metadata를 테스트.
2. 승인된 별도 시험 환경에서 QS 실제 버전과 public web client의 화면/키보드/clipboard/file transfer/UAC/종료를 확인. WSS 인증서·origin/CORS allowlist·프록시 설정 검증. 임의 `*` 허용이나 운영 포트 개방 금지.
3. 동의 만료/철회 시 **포털 launch 거부**와 **이미 열린 외부 세션 종료**는 다른 보장이다. 후자는 실제 서버/client API 증거가 필요하다. 지원되지 않으면 사용자 Quit와 운영 절차의 한계를 명시; 링크 버튼만으로 강제 종료 완료 판정 금지.
4. 원격지원 ID나 비밀을 URL query로 전달하지 않음. 기존 빌드센터 admin/API token을 Synology-Admin에 복사하지 않음. 두 프로젝트 별도 소유·배포 유지.

**확정:** 웹 UI 완전 자가 호스팅. 남은 입력: 라이선스 권리/예산 승인 및 실제 동의 철회·세션 종료 인수 조건. public web client 제안은 폐기한다.

## D3 — 최소 배포 가능한 MFA 설계 제안

조사 당시에는 MFA가 미구현이었다. 3A 확정 후 첫 등록·확인·접근 강제 구현 계약과 검증은 `admin-mfa.md` 및 `evidence/mfa-implementation.md`로 갱신한다. 기존 비밀번호 재인증만을 2차 인증으로 계산하지 않는다.
django-otp TOTPDevice는 hex seed `CharField`, `last_t`, drift와 실패 throttle을 가진다. hex는 암호화가 아니다. `django_otp.verify_token()`은 transaction과 `for_verify=True` device load를 사용한다.[10][11]
cryptography의 Fernet은 인증된 암호화와 MultiFernet 키 회전을 제공한다. 키 유출 시 복호화가 가능하고 키 분실 시 복구가 불가능하므로 DB 암호화만으로 운영 보안이 완성되지 않는다.[12]

### 확정 3A — encrypted seed DB + 독립 키 주입

아래는 **구현 제안**이며 검증된 코드/운영 보장이 아니다. 패키지 버전 pin과 Django 5.2/Python 3.14 호환 검증을 별도 수행한다.

- `django_otp.models.Device` 기반 전용 encrypted TOTP device를 만들고 django-otp의 TOTP primitive·throttle/timestamp mixin·transaction-aware 검증 경로를 재사용한다. OTP 암호 알고리즘을 직접 만들지 않는다. concrete stock `TOTPDevice`를 상속해 평문 parent key column을 남기거나, `bin_key`만 재정의하고 평문 저장을 방치하는 구현은 금지한다.
- DB에는 versioned ciphertext와 `last_t`/drift/throttle 상태만 저장. 암호문 내부 payload에 device/user 식별자를 포함하여 복호화 후 일치 확인(다른 row로 ciphertext 이식 거부). 평문은 등록 QR/검증 순간의 process memory에만 필요한 범위로 취급한다.
- seed 암호화는 cryptography Fernet/MultiFernet. 키는 `DJANGO_SECRET_KEY`와 분리한 런타임 secret-store 주입 또는 보호된 환경변수로 전달한다. Git·DB·이미지·명령행 인자·로그·브라우저로 전달하지 않는다. 누락/오류/복호화 실패는 fail-closed, 시작 시 임시 키 자동 생성 금지.
- 키 버전별 복구 가능성을 확인한 뒤 회전: 새 키로 쓰기 → 기존 ciphertext 재암호화 검증 → DB/키 별도 백업의 복구 훈련 → 구키 폐기 승인. 앱 process/호스트가 탈취되면 seed를 보호한다고 주장하지 않는다. DB 복원에 따른 `last_t`/session rollback 위험도 복구 절차에서 다룬다.

### 등록과 접근 제어

- 전역·그룹 관리자 모두 MFA 필수. role별 privileged URL뿐 아니라 admin·API·지원 운영 기능에도 중앙 gate 적용; password-only 세션은 MFA setup/verify/logout 등 제한된 경로만 허용한다. 최종 mutation transaction에서도 actor 상태/역할/검증 상태 재검사.
- 최근 비밀번호 재인증 → 만료되는 unconfirmed device 생성 → 직접 제공되는 same-origin QR → OTP 확인 성공 후 confirmed. 등록 전 관리자 권한 사용 금지. 외부 QR 생성 서비스 금지, QR/seed 응답 `no-store`, CSRF·민감 POST redaction, APM/프록시 body 수집 제외.
- PostgreSQL row lock 아래 replay/동시 replay 방지. **실패 throttle update도 commit**되어야 하며 오류 응답을 예외로 rollback해 횟수를 지우면 안 된다. 전역 계정/IP 시도 제한도 유지.
- 등록 완료/로그인 검증 시 session rotate, session의 OTP device와 별도 MFA version 연결. 관리자 role 철회·device 삭제/교체/복구 시 모든 세션 무효화. 파괴적 관리 작업에는 최근 password+OTP step-up을 요구하는 정책과 만료 시간을 확정.

### 복구는 인증과 별도 승인 게이트

**초기 최소안:** 웹의 이메일-only MFA reset과 자동 bypass는 제공하지 않는다. 운영자가 별도 채널에서 신원을 확인하고 지정 승인자의 승인을 얻은 뒤, 접근 제한된 management command로 기존 device·session 폐기 및 기한 있는 재등록 상태만 허용한다. 명령은 세션 로그인/즉시 관리자 권한을 발급하지 않으며 OTP 등록 확인까지 관리 기능은 잠긴다.

- 전역 관리자 복구의 승인자가 본인 한 명뿐인 상황을 사전에 정한다. 권장: 별도 복구 책임자/오프라인 보관자. 단독 운영을 선택하면 2인 승인을 보장한다고 쓰지 않고 신뢰된 호스트 관리자라는 trust boundary와 수동 확인 기록을 명시한다.
- 후속 self-service recovery code를 택하면 강한 랜덤 일회 코드의 **hash**만 저장, 원자적 소비·rate limit·전부 재발급/폐기·오프라인 보관을 검증한다. recovery code는 다른 자격증명이므로 복구 **승인**이나 동의 증거로 간주하지 않는다. stock 평문 static-token 저장을 검토 없이 채택하지 않는다.
- MFA 분실 복구와 seed 암호화 키 분실 복구는 별개. 키 백업이 없으면 seed를 되살리는 기능을 약속하지 않는다. 승인된 재등록 또는 서비스 중단 절차를 사용한다.

**대안 B:** seed 자체를 외부 secret store에 두고 Device에는 secret reference만 저장. key custody 요구에 더 직접적이지만 store 선택/배포·권한·장애 대응이 선행한다. 추가 인프라가 이미 존재한다고 가정하지 않는다.

**과거 승인 전 작업 목록 (현재 등록·검증·접근 강제는 승인됨):** enrollment/verify/recovery 상태 머신과 gate 부정 테스트, synthetic key를 쓰는 암호화 wrapper spike, PostgreSQL 동시 replay/실패 throttle commit/키 누락·변조·row swap/QR 누출·세션 폐기 테스트 설계. 실제 비밀 생성·migration 적용·운영 공개는 하지 않는다. 관리자 MFA 수용 점수는 구현·독립 리뷰·복구 훈련 전 부여하지 않는다.

## 세분화 로드맵 제안 — 합계 100 유지, 점수 반영 아님

`roadmap.md`의 기존 단계 가중치와 수용 기준을 유지한다. 아래 배점은 **부모 승인용 제안**이며 `roadmap.md`, `docs/progress.json`, 부모 canonical 값은 바꾸지 않는다. 기존 coarse 15%를 재계산/자기 승인하지 않는다. 각 소항목은 merge SHA·독립 테스트·의사결정 승인·운영 증거 중 필요한 항목을 부모가 확인한 뒤에만 인정한다.

| 기존 단계 | 제안 소항목과 배점 | 독립 검증 게이트 |
|---|---|---|
| 1 (10) | 요구·역할·데이터 4 / quota·MFA·원격지원 정책 승인 3 / 배포·보존·복구 정책 승인 3 | 문서 존재 ≠ 사용자 승인 |
| 2 (15) | 앱·고정 의존성 5 / DB migration·실행 검증 5 / CI·독립 검토 5 | 기존 부모 완료 판정을 임의 변경하지 않음 |
| 3 (20) | 가입·승인·격리 6 / 그룹·한도·폐기·세션 경합 6 / 관리자 MFA·등록·복구 6 / 인증 운영 정책·통합 인수 2 | 부분 기능과 전체 인증 완료 분리 |
| 4 (25) | adapter 계약·오류/신선도 4 / 실장비 read capability 6 / quota·사용량 귀속 검증 6 / 승인된 권한·quota 변경 5 / 보상·회귀·최소 권한 인수 4 | synthetic fixture에는 실장비 점수 없음 |
| 5 (15) | 티켓·reply 격리 5 / 채팅·재연결·경합 5 / 보존·삭제·통합 인수 5 | 폴링/페이지네이션만으로 전체 완료 아님 |
| 6 (5) | 방식·라이선스 승인 1 / 실제 브라우저 연결 검증 2 / 동의·철회·접근·감사 인수 2 | 빌드센터·링크 존재는 브라우저 제어 증거 아님 |
| 7 (10) | 승인 호스트·TLS 배포 3 / 보안·백업 복구·rollback 훈련 4 / 운영 관측·인수 3 | CI 통과 ≠ 운영 배포 |

## 이번 PR의 수용 범위와 다음 순서

- 원 조사 PR은 문서만 다뤘다. 현재 후속 PR은 확정된 네 선택 반영과 `admin-mfa.md`의 bounded OTP slice를 구현·검증한다. 복구나 전체 단계 완료를 주장하지 않는다.
- 부모: 문서 주장·원본 근거·배점 제안 검토, exact head CI 확인 후 병합 판단. 본 작업자는 병합하지 않음.
- 후속: 확정된 1A/2A/3A/4A를 다시 묻지 않는다. MFA 등록·검증·강제는 사용자 승인 범위. 복구 trustee/키 백업 책임자, 구매 승인, 실제 접속/배포 승인 등 남은 운영 입력만 별도 확정한다.
- 운영 NAS/원격지원 서버 접속, credential 사용, 포트/인프라 변경, 결제, 알림 전송은 이번 작업에 포함하지 않았다.

## Sources

[1] https://www.synology.com/api/releaseNote/findChangeLog?identify=DSM&lang=en-global
[2] https://archive.synology.com/download/Os/DSM
[3] https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/file_group_edit?version=7
[4] https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/file_share_create?version=7
[5] https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/file_user_create?version=7
[6] https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf
[7] https://raw.githubusercontent.com/rustdesk/doc.rustdesk.com/master/content/self-host/_index.en.md
[8] https://raw.githubusercontent.com/rustdesk/doc.rustdesk.com/master/content/self-host/rustdesk-server-pro/_index.en.md
[9] https://raw.githubusercontent.com/rustdesk/doc.rustdesk.com/master/v3/src/content/post/en/web-client-v2-preview.mdx
[10] https://raw.githubusercontent.com/django-otp/django-otp/master/src/django_otp/plugins/otp_totp/models.py
[11] https://raw.githubusercontent.com/django-otp/django-otp/master/src/django_otp/__init__.py
[12] https://raw.githubusercontent.com/pyca/cryptography/main/docs/fernet.rst
[13] https://github.com/me0kmin27/Rustdesk-Quicksupport/blob/7d14a63c4a30ad11a23b18f038921a4537b04a85/README.md
[14] https://github.com/me0kmin27/Rustdesk-Quicksupport/blob/7d14a63c4a30ad11a23b18f038921a4537b04a85/portal/README.md
[15] https://github.com/me0kmin27/Rustdesk-Quicksupport/blob/7d14a63c4a30ad11a23b18f038921a4537b04a85/SEGANG-README.md
