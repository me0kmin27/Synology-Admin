# 고객사 그룹 관리 — 포털 정책 수용 기준

2026-10-11 확정 요구의 포털 구현. 관리자 MFA는 별도 미해결 배포 게이트이며 이 문서는 3단계 전체 완료 선언이 아니다. 실제 RED/GREEN 및 PostgreSQL 경합 결과는 `evidence/groups-implementation.md` 참조. 최종 PR 판정은 정확한 HEAD의 CI와 부모 독립 리뷰에 따른다.

## 확정 정책

- 전역 관리자는 Django superuser, 고객사 그룹관리자는 활성 User + approved Membership(role=admin)이다. 전역 관리자만 그룹관리자 지정/해제 및 그룹 최대치를 변경한다.
- 가입 시 공개(signup_enabled) 그룹을 반드시 선택한다. 이 값은 신청 대상일 뿐 승인 권한이 아니다. pending은 service/manage 접근 불가. 선택 후 그룹 이전은 제공하지 않는다. 기존 미배정 pending만 전역 관리자가 배정할 수 있다.
- 최대 계정 수는 해당 그룹의 **User.is_active=True + Membership.status=approved** 행 수다. 그룹관리자와 승인 일반회원 모두 포함, pending/폐기 제외. 일반 전역 운영계정은 Membership 없이 운용한다. 전역 계정에 Membership을 수동 부여했다면 동일 집계식에 포함된다.
- 새 그룹의 한도는 0(입장 차단)이다. 전역 관리자가 한도를 설정한 뒤 승인한다. migration 0010은 기존 활성 승인 계정 수만큼 초기 최대치를 보전하며 계정/파일을 삭제하지 않는다. 이후 감소는 현재 계정 수보다 작으면 409로 거부한다.
- storage_limit_bytes는 **포털 예약 용량 합계의 상한**이다. 개별 quota_bytes를 전역/해당 그룹관리자가 배정할 수 있으며 다른 그룹은 404. 음수/비정수/64-bit 범위 초과 거부. 현재 예약 합계 미만으로 그룹 한도 감소 시 409. 트랜잭션 내 검사·저장·감사를 수행한다.
- 폐기는 로그인 비활성화 + session_version 증가 + 모든 DB 세션 삭제 + 감사 유지다. pending/approved/기존 suspended 모두 폐기 가능, 완료된 폐기 재시도는 성공 redirect이며 중복 감사 없음. 자기 폐기/전역 계정 폐기 금지. 마지막 활성 그룹관리자는 전역 관리자도 폐기/강등할 수 없다.
- 교체는 기존 승인 회원을 그룹관리자로 지정한 다음 이전 관리자를 강등/폐기한다. 자리가 부족하면 기존 승인 회원을 승격하거나 전역 관리자가 최대치를 먼저 늘린다. 마지막 관리자 보호를 우회하는 root 예외는 없다.
- 폐기 후에도 NAS 매핑, 감사, 예약 quota는 유지한다. NAS 파일·계정 삭제, quota 적용, 실제 사용량 수집은 **수행하지 않는다**. 폐기 계정의 예약 회수/재활성화/tenant 이동은 현재 제공하지 않는다.

## 구현·검증 구분

| 기준 | 구현/증거 | 남은 경계 |
|---|---|---|
| 그룹 선택 신청·승인 전 차단 | forms, signup, invalid/hidden 그룹 및 위조 role 테스트 | 공개 그룹 목록은 의도된 가입 UI |
| 전역 전용 관리자 지정/한도 | role/limits POST, 재인증·CSRF·감사·UI/부정 테스트 | 관리자 MFA 별도 |
| 그룹 내 승인·폐기·예약 배정 | scoped queryset, 교차 그룹 GET/POST/위조 입력 거부 | 페이지네이션/대량 처리 별도 |
| 최대 계정·예약 용량 | 실제 PostgreSQL 동시 승인/동시 quota/한도 감소 경합 검증 | NAS quota 강제 집행과 동일하지 않음 |
| 마지막 관리자·자기 보호 | 단일 요청 및 상호 폐기/동시 강등 PostgreSQL 검증 | 비상 복구 운영 절차 별도 |
| actor 권한 철회 경합 | PostgreSQL transaction advisory lock 후 fresh User/권한 조회; RED 재현 후 수정 | 직접 SQL/신뢰 CLI도 같은 lock 계약 필요 |
| 폐기·세션 | 비활성화/기존·복원 세션/동시 로그인 경합 검증 | 이미 전송된 읽기 응답의 소급 회수 불가 |
| 비밀·감사 | POST 오류 보고 redaction 확장, allowlist 감사 | APM/프록시·tamper-proof 보존 정책 별도 |

## 동시성 계약

운영 정책 변경은 PostgreSQL READ COMMITTED와 Django DB session backend가 필수다. 전체 포털 정책에 고정 transaction advisory lock을 먼저 얻고 → fresh actor User row → subject/tenant 순서로 잠근다. 승인·폐기·역할·한도·예약·기존 배정/매핑 모두 같은 계약을 사용한다. 로그인 session 게시도 같은 lock 안에서 현재 User 활성 상태를 재확인하고 DB session을 저장한다.

이 보수적인 전역 직렬화는 교차 actor/그룹 잠금 순서 역전과 마지막 관리자 경합을 피한다. 처리량 최적화나 tenant별 세분화는 별도 실제 부하/경합 테스트 후에만 변경한다. SQLite select_for_update는 행 잠금을 제공하지 않으므로 완료 증거가 아니다. 기본 SQLite 관리 변경은 503 fail-closed; 일회 로컬 검증만 `DJANGO_ALLOW_UNSAFE_SQLITE=1`로 허용한다.

## 독립 게이트

관리자 MFA secret custody/등록/복구 정책, 이메일 검증·웹 복구, 실제 NAS quota·모델별 capability, 배포·백업·부하 시험은 미완료다. 이 PR의 포털 그룹 정책 변경을 독립 리뷰 후 병합할 수 있는지와 운영 공개/3단계 전체 완료는 별도 판정이다. DSM 공식 근거(`evidence/dsm-official-review.json`, 기존 보안 리뷰 Sources)는 변경하지 않았다.
