# 회원 기능 운영 경계와 로컬 확인

## 구현 결정
Django 기본 User를 유지하고 OneToOne Membership을 사용한다. 운영 데이터가 있는 custom User 전환을 가정하지 않는다. 현재 사용자당 하나의 tenant만 지원한다. 공개 가입은 tenant 미배정 pending/member만 만든다. 클라이언트의 status/role/tenant/is_staff/is_superuser는 수용하지 않는다.

전역 관리자는 로컬 CLI로 생성한 Django superuser이다. 이 계정은 전체 tenant 관리 권한이 있는 별도 운영 주체이며 일반 membership 승인을 통해 만들어지지 않는다. tenant 관리자 권한은 approved Membership.role=admin에서만 파생한다. staff 또는 Django 기본 모델 permission만으로는 포털 관리 권한이 생기지 않는다. 웹 역할 승격/tenant 변경/공개 관리자 bootstrap은 없다.

웹 흐름: `/signup/` → `/login/` → `/account/` pending. 전역 관리자가 `/manage/`에서 테넌트 배정(미배정 pending만) → 별도 승인. tenant 관리자는 자신의 tenant 신청자만 승인/취소/매핑. 모든 변경은 CSRF POST와 현재 포털 비밀번호 재인증. 자기 객체 변경 거부. 이미 수행된 승인/취소/매핑은 409. suspended 재승인/이전/매핑 삭제·교체는 아직 제공하지 않는다.

승인 취소는 같은 DB 트랜잭션에서 status suspended, session_version 증가, 감사 이벤트와 해당 사용자의 DB 세션 삭제를 수행한다. 요청마다 DB membership 상태와 version을 읽으며 별도 권한 캐시를 쓰지 않는다. 삭제 전 세션 데이터가 복원돼도 version 불일치로 로그아웃한다. 이미 처리 중인 읽기 응답의 소급 취소는 보장하지 않는다. future NAS/웹소켓/worker에는 별도 실행 시 권한 검사가 필요하다.

NAS 링크는 **실제 연동 성공이 아닌 관리자 확인 식별자 매핑**이다. 관리자가 외부 경로로 소유 관계를 확인했다는 checkbox를 제출해야 한다. NAS 비밀번호/주소/API 토큰을 입력받거나 NAS를 호출하지 않는다. 식별자는 ASCII `[A-Za-z0-9_.@-]` 최대 128자, 전역 unique(단일 NAS namespace를 보수적으로 가정), 회원당 하나. multi-NAS와 DSM 대소문자/정규화 정책은 장비 확인 후 별도 설계한다. 미수집 용량을 0으로 표시하지 않는다. 매핑 감사는 actor/subject/action/time을 남기고 자유형 이유/비밀번호를 기록하지 않는다.

## 로컬 bootstrap (운영 배포 지시가 아님)
README의 개발 환경변수와 migrate 완료 후, 사람이 신뢰된 로컬 터미널에서:
```sh
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py shell
```
비밀번호는 CLI의 숨김 프롬프트에만 입력한다. 명령행/환경변수/문서/CI artifact에 비밀번호를 쓰지 않는다. shell에서 개발 tenant를 만든다:
```python
from membership.models import Tenant
Tenant.objects.get_or_create(name="local-development")
```
`/login/`에서 전역 관리자 로그인 → `/manage/`. tenant scoped 관리자 bootstrap은 운영 정책/독립 리뷰 후 신뢰된 CLI에서만 별도 수행하고 감사 절차를 확정한다. 일반 가입만으로는 관리자를 만들 수 없다. 실제 계정/고객 식별자를 Git에 쓰지 않는다.

## 보안 기본값과 미완료 수용 기준
- 비밀번호 최소 12자 및 유사도/흔한 비밀번호/숫자-only 검사. Django 해시와 로그인 세션 회전, 30분 세션/브라우저 종료 쿠키, 기본 HTTPS/secure cookies, no-store 회원 응답.
- DB 기반 15분 fixed-window, 경로군별 IP와 계정 각각 20회 POST 제한. 성공 요청도 포함, 여러 프로세스가 공유. forwarded 헤더 신뢰 안 함. 프록시 배포 시 신뢰된 실제 IP 설정 및 공유 IP 오탐/계정 잠금 DoS/분산 공격 정책을 별도 검증해야 한다. 로그인 제한은 MFA를 대체하지 않는다.
- **관리자 MFA 미구현 — 운영 공개 금지/3단계 전체 수용 미충족**. 관리자 재인증은 비밀번호만 사용한다.
- 이메일을 가입 필수로 수집하지 않음; 이메일 소유 검증/웹 비밀번호 변경·복구/탈퇴·개인정보 보존 정책 미구현. 복구가 필요하면 신원 확인 후 신뢰된 로컬 CLI `manage.py changepassword USERNAME`을 사람이 사용한다(메일 복구가 있다는 뜻 아님).
- 개발 SQLite만 검증. PostgreSQL/다중 worker 동시 승인·취소 경합/DB lock 복구·부하·운영 백업 복구 미검증. 조건부 update/unique 제약은 중복 성공을 막지만 SQLite lock contention의 UX는 별도 검증 대상이다.
- 대량 회원/DB 세션 순회 비용, 목록 pagination, 감사 보존/내보내기/DB 접근자에 대한 tamper resistance 미해결. 현재 감사는 앱 UI에서 수정 불가하나 DB 관리자는 변경 가능하다.
- 독립 리뷰, 관리자 MFA 및 운영 정책 수용 전 완료율에 반영하지 않는다. NAS/지원/원격지원은 별도 단계이다.
