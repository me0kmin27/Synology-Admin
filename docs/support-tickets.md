# 고객지원 티켓 1차 범위 / 부모 독립 리뷰 인계

## 구현
- `/support/`, `/support/new/`, `/support/<id>/`: 로그인 후 생성·목록·상세. 계정 화면 링크.
- 승인·활성 일반 회원: 현재 그룹에 속한 **본인 작성 티켓만**. 동일 그룹 타 회원 티켓도 거부.
- 승인·활성 그룹관리자: 자신의 그룹 전체. 활성 전역 superuser: 전체 읽기. 단순 is_staff는 권한 아님.
- 생성은 전역 관리자도 승인된 그룹 membership 필요. 임의 그룹 대리 생성은 제공하지 않음.
- tenant/author는 서버에서 결정. 요청의 위조 필드 무시. pending/suspended/retired/비회원 거부, 범위 밖 상세 404.
- 제목 160자/본문 10,000자 검증, HTML 자동 escape, 25건 pagination, no-store(오류/CSRF 포함).
- CSRF POST 생성과 원자적 TicketAudit(created) 기록. 감사에는 제목/본문/접속 비밀을 저장하지 않음.
- 사용자/API를 통한 작성자·tenant·본문·감사 변경/삭제 경로 없음. FK PROTECT로 작성자/티켓 삭제 시 이력 보호.
- **불변 경계는 웹 애플리케이션 권한 경계**이며 DB 소유자/직접 SQL에 대한 변조 방지·WORM 보관은 아님. 운영 DB 계정 권한/외부 감사 보관 정책은 미완료.
- 첨부파일 입력 UI/저장 경로 없음. 파일 POST는 400으로 거부. 요청 크기/업로드 임시 버퍼/프록시 제한은 배포 전 별도 점검 필요.

## 동시성 / MFA 분리
생성은 기존 membership 정책 advisory lock 안에서 User·membership·session epoch를 다시 읽고 생성/감사를 함께 commit한다. 기존 membership 인증·MFA 코드/마이그레이션 변경 없음. PostgreSQL READ COMMITTED 및 모든 권한 writer의 동일 잠금 계약을 재사용한다. SQLite 쓰기는 명시적 일회 개발 opt-in 외 503. 읽기는 최신 권한 확인 시점 기준이며 이미 전달된 응답 회수는 보장하지 않는다.

## 검증 증거
- 기존 baseline 47 tests 통과 후 시작. `support-create-red/green.txt`: 없는 생성 URL 404 → 생성/감사 통과.
- `support-read-red/green.txt`: 없는 목록 URL 404 → 역할별 목록/상세·autoescape 통과.
- `support-cache-red/green.txt`: no-store 누락 → middleware 추가 통과.
- `support-upload-red/green.txt`: 업로드가 302로 허용됨 → 400 거부 통과.
- `support-link-red.txt` 및 `support-final-local.txt`: 계정 링크 부재 → 링크 및 전체 회귀 통과.
- 추가 권한/CSRF/감사 rollback/형식 검증/세션 epoch/삭제 보호 테스트는 기존 보호에 대한 회귀 검증이며 별도 RED를 주장하지 않음.
- 최종 로컬 `scripts/verify.py`: **58 tests**, **26 migrations**, migration drift 없음, deploy check 및 실제 HTTP cookie/CSRF 티켓 흐름, health/Host smoke 통과. pip check / diff check 통과.
- `concurrency/support_races.py`: 생성 승인 후 정지 → 실제 별도 PostgreSQL 연결 retirement가 pg_blocking_pids로 대기함을 검증 → 생성/감사 commit 후 폐기 → 이후 생성 불가. CI 명시 라벨; SQLite skip으로 대체하지 않음. 최종 원격 head와 CI는 인계 시 별도 readback.

## 미완료 / 금지 범위
부모 독립 코드 리뷰와 병합 판단 대기. 이 구현자는 티켓 PR을 병합하지 않음.
**라이브 채팅·메시지·답변/담당자 배정·상태 전이·알림·첨부·보존/삭제 정책·외부 불변 감사·MFA·운영 배포는 미완료. 5단계 또는 전체 완료 아님.** 지원 담당자 역할은 구현하지 않음.
NAS/운영/RustDesk/부모 canonical progress는 수정하지 않음. rate limit·부하/저장량 정책은 운영 공개 전 검증 필요.

## 선행 문서 병합 readback
문서 전용 PR #4: reviewed head `b64d4156d5c57badcd9cd3f8f91a2e2b8953e052`, push CI `38142890929` / PR CI `38142895624`의 verify/postgres-races 모두 SUCCESS.
head guard squash, admin bypass 없이 병합. readback `state=MERGED`, `mergedAt=2026-10-11T13:24:10Z`, merge commit `c9f9b242afa53a749aee5d68b819d2e90d569ee2`. main refresh 후 별도 support branch 시작.
