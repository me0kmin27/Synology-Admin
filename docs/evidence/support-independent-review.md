# PR #5 독립 리뷰

검토 application head: `deea4e505da18b5a561c562addc515290fe43f2d`.
판정: 현재 생성/목록/상세 범위에서 차단 보안·정합성 결함 없음. 구현 코드 수정 없음.

- 문서, 전체 support diff, 기존 membership 정책 잠금/폐기/session middleware를 독립 확인.
- 일반 회원은 현재 tenant + 본인 author, 그룹 관리자는 현재 tenant, 활성 superuser는 전역 읽기. staff flag만으로 접근 불가. 생성은 승인된 membership 필요하며 tenant/author는 서버 결정.
- pending/suspended/inactive/stale epoch와 위조 입력, 다른 작성자/tenant 읽기, 변경/삭제 경로 부재의 실제 회귀 테스트 통과.
- 생성은 정책 advisory lock 획득 뒤 fresh actor/membership/session epoch 확인. Ticket과 metadata-only TicketAudit가 같은 transaction에 있으며 감사 실패 rollback 테스트 통과.
- CSRF, 허용 method, HTML autoescape, 입력 길이, 파일 POST 거부, 지원 응답 no-store 확인. DB-owner 변조 방지나 업로드 임시 버퍼 차단으로 과장하지 않음.
- 로컬 `.venv/bin/python scripts/verify.py` 실제 재실행: 58 tests OK, 26 migrations, drift 없음, deploy check, 실제 HTTP cookie/CSRF 생성→상세→목록 및 health/Host smoke 통과. pip check, diff check 통과. 원문은 `support-independent-local.txt`.
- 원격 application head CI `38143490840` 및 `38143486509` verify/postgres-races 모두 성공 확인. `38143490840` 로그에서 PostgreSQL 58 tests 및 명시 race 8 tests OK 확인. 티켓 생성과 폐기 overlap은 pg_blocking_pids 기반 테스트 통과. 로컬 PostgreSQL 재실행으로 주장하지 않음.
- 이 문서 추가 후 새 최종 head의 CI를 다시 확인하고 head guard squash, admin bypass 없이 병합해야 함. 최종 head/CI/merge readback은 PR 기록과 인계 결과로 남김.

## 후속 인계 (이번 범위 차단 아님)
다음 작은 slice는 기존 ticket에 대한 답변 생성·조회: 동일 author/tenant 접근 경계, 서버 actor, 원자 감사, 폐기 race, CSRF/XSS/no-store를 재사용하고 담당자 권한을 먼저 명시한다. 이후 별도 livechat transport/reconnect/권한 재검증 범위를 설계한다. 이번 리뷰에서 후속 구현은 시작하지 않음.

MFA, NAS/운영 배포, rate limit/저장량·프록시 제한, 보존/삭제 및 외부 불변 감사는 운영 공개 전 별도 gate. 운영/NAS/RustDesk와 부모 canonical progress는 변경하지 않음. 전체 5단계 완료 또는 배포 완료를 의미하지 않음.
