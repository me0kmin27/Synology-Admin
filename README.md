# Synology-Admin

Synology NAS 고객 포털·운영자 관리 시스템의 **초기 개발 기반**입니다.
가입 승인, NAS 권한/용량, 티켓/채팅, RustDesk 원격지원은 향후 구현 대상이며 현재 제공하지 않습니다.
별도 저장소 `me0kmin27/Rustdesk-Quicksupport`는 변경하지 않습니다.

## 구현된 범위
- Django 5.2.18 / Python 3.14 최소 웹 앱, 사실에 기반한 한국어 안내 페이지
- 실제 DB 연결 `/health/` (NAS는 `not_configured`), Django 기본 DB migration
- 보안 기본값, 고정 의존성, 테스트, GitHub Actions CI 정의
- 요구사항·보안·데이터 모델·가중 로드맵·검증 증거·배포 설계

운영 배포/실제 NAS 연결/컨테이너 빌드를 수행하지 않았습니다. 단계 전체 완료나 프로젝트 100% 완료를 의미하지 않습니다.

## 설치와 검증
Python 3.14 설치 후 저장소 루트에서:
```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python scripts/verify.py
```
검증 스크립트는 임시 secret을 메모리에서 생성하고 `.runtime/` 아래 일회 DB를 생성/제거합니다.
보안 설정 검사 → 테스트 → 실제 migration → migration drift 검사 → loopback HTTP 요청을 수행합니다.
외부 서비스/NAS에 연결하지 않으며 종료 시 검증 서버를 정리합니다.

## 로컬 실행 (개발 전용)
```sh
export DJANGO_SECRET_KEY="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(64))')"
export DJANGO_LOCAL_HTTP=1
export DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8000
```
브라우저에서 `http://127.0.0.1:8000/`, health는 `/health/`.
이 DB에는 운영 데이터를 넣지 마세요. 기본 `db.sqlite3`는 Git 제외입니다.
`.env.example`는 문서 예시이며 자동 로드하지 않습니다. secret 없이 실행하면 실패합니다.
SECRET_KEY는 재시작 간 유지가 필요한 실제 서비스에서 secret store에 별도 보관해야 합니다.
로컬 HTTP 예외를 해제하면 HTTPS redirect/secure cookies가 기본 적용됩니다. DEBUG는 항상 꺼져 있습니다.

## 문서
- `docs/requirements-security-data.md`: 역할, 격리, 승인, 데이터·개인정보·동의 설계
- `docs/roadmap.md`: 가중치 10/15/20/25/15/5/10, 수용 기준·의사결정 게이트·알림 시간
- `docs/progress.json`: 기계 판독 증거 상태; 최종 완료율 승인은 부모의 독립 검증 책임
- `docs/evidence/`: 실제 검증과 TDD 기록
- `docs/deployment-design.md`: 미배포 설계와 health 한계

Git에는 소스/문서/비밀 없는 설정만 저장합니다. 회원·티켓·채팅·NAS 파일·운영 DB·접속 비밀은 금지입니다.
NAS 모델/DSM/API, 그룹 quota 의미, 배포 호스트, 인증 연동, RustDesk 웹 capability/라이선스는 미확정입니다.
