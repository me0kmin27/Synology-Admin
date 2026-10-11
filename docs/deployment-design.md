# 배포·복구 설계 — 실행하지 않음

## 현재 개발 구성
Python 3.14 + Django 5.2.18, 서버 렌더링, 로컬 SQLite. requirements.txt는 직접/전이 의존성 모두 고정.
설치 시 선택한 버전 공식 릴리스 노트와 배포 체크리스트를 확인했다(2026-10-11).
공식 문서: `https://docs.djangoproject.com/en/5.2/releases/5.2.18/`,
`https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/`.
Python 패치 버전/OS 전체를 hermetic 고정한 빌드는 아니다. 운영 OS 확정 후 잠금/해시/취약점 점검 추가.
GitHub Actions action 참조는 검증한 commit SHA로 고정하고 read-only 권한/credential 미보존을 사용한다.
CI는 설치·의존성 검사·보안 설정 검사·테스트·일회 DB migration·loopback HTTP만 수행하며 배포 자격증명이 없다.

## 제안 운영 경로 (승인 필요)
승인된 별도 서버 → TLS reverse proxy → production WSGI/ASGI server → 앱 → 사설 DB.
NAS는 인터넷 공개 관리 API 대신 제한된 네트워크의 최소 권한 adapter로만 접근.
현재 runserver/wsgiref는 개발/검증용이며 운영용이 아니다. Dockerfile/이미지 빌드는 제공하거나 검증하지 않았다.
운영 DB PostgreSQL 전환, WSGI 서버 선택, 도메인, TLS, 방화벽, 배포 사용자, secret store는 미결정.
HTTPS redirect/secure cookies/HSTS는 기본 활성화. LOCAL_HTTP=1은 loopback 개발 전용 예외.
HSTS includeSubDomains/preload는 기존 도메인 하위 서비스까지 영향 있으므로 대상 승인 전 반드시 검토.
프록시 헤더 신뢰 설정은 의도적으로 없음: 실제 TLS 종료 구조 확정 후 신뢰 프록시만 헤더를 재작성하도록 설정.
`check --deploy` 통과는 설정 점검일 뿐 TLS·실운영 보안 인증이 아니다.

## 승인 후 배포 절차
1. 작업 브랜치 CI/독립 리뷰 → 승인된 main 병합(이번 작업 제외).
2. 버전별 artifact·취약점 검사, staging에서 실제 운영 DB migration와 부하·권한 테스트.
3. DB/파일 암호화 백업 및 복원 테스트. 복구 목표(RPO/RTO)는 사용자 승인 필요.
4. 점검 시간·롤백 대상 확정, migration 호환성 확인 후 승인 배포.
5. 내부 DB 연결 health + migration 상태 + 실제 사용자 권한·NAS 읽기 검증. 이상 시 트래픽 전환/이전 앱 복원.
6. 비가역 schema 변경은 자동 역 migration 금지. 복구 승인 뒤 검증된 DB backup 복원.

## health 계약과 한계
`GET /health/`: 실제 DB `SELECT 1` 성공이면 HTTP 200, DB 오류면 상세정보 없는 503.
NAS 상태는 항상 `not_configured`. health는 NAS·migration 최신성·백업·인증·전체 readiness를 보증하지 않는다.
응답은 no-store. 이 엔드포인트만 보고 운영 단계 완료를 선언하지 않는다.
`/`는 실제 기능 미제공 사실만 표시하고 가입·지원·관리 링크를 제공하지 않는다.
