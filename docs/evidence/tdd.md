# RED → GREEN 실행 증거 (2026-10-11)

설정/scaffold는 configuration이며 기능은 아래 수직 단위로 테스트를 먼저 실행했다.

| 순서 | 테스트 | RED 실제 관찰 | 최소 구현 후 GREEN |
|---|---|---|---|
| 1 | test_health_checks_real_database | 404 != 200, 1 test / 1 failure | SELECT 1 + health route, 1 OK |
| 2 | test_landing_is_truthful | 404 != 200, 2 tests / 1 failure | render + 안내 template, 2 OK |
| 3 | test_database_failure_is_sanitized | 처음 exception 전달; client exception 비활성화 후 500 != 503, 3 tests / 1 failure | DatabaseError 처리, 3 OK |
| 4 | test_weak_secret_is_rejected | subprocess returncode 0 == 0, 4 tests / 1 failure | 짧은 secret 거부, 4 OK |
| 5 | test_health_is_not_cacheable | no-store not found in empty header, 5 tests / 1 failure | never_cache, 5 OK |

그 뒤 기존 Django 보안 설정에 대한 회귀검사 6개를 추가했다. 이 6개는 새 기능 TDD cycle로 계산하지 않는다.
DB 장애 분기만 OperationalError fault injection을 사용한다. 성공 경로는 실제 SQLite를 사용한다.
NAS 가짜 데이터나 NAS 성공 mock은 없다. 최종 실행 원문은 local-verification.txt 참조.
