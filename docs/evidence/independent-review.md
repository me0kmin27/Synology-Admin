# Foundation 독립 보안·품질 리뷰

검토일: 2026-10-11 (Asia/Seoul). 구현자와 분리된 리뷰 subagent가 수행했다.
검토 대상: `58cde91a94e5c3f9fa043721ddf3be531aead411`, `feat/stages-1-2-foundation`.

## 판정

**2단계 개발 기반 승인. 운영 배포 승인이나 전체 프로젝트 완료 판정이 아니다.**
현재 제공되는 안내 페이지와 DB 연결 health 범위에서 차단할 보안/논리 결함은 발견하지 않았다.
프로덕션 코드 수정은 필요하지 않았으며 이번 변경은 리뷰 증거·진행 상태·다음 결정 문서뿐이다.
기존 TDD 기록은 `tdd.md`에 있으며 이번 독립 실행은 회귀 검증이다. RED 이력을 새로 수행했다고 주장하지 않는다.

## 직접 확인한 증거

- settings, urls, views, WSGI, manage.py, template, 모든 테스트, 검증 스크립트, CI, 의존성, gitignore, 요구사항/로드맵/배포 문서 전부 검사.
- `.venv/bin/python -m pip check`: No broken requirements found.
- `.venv/bin/python scripts/verify.py`: exit 0. deploy check 경고 없음, 11 tests OK, 실제 임시 DB migration 15개, drift 없음, 실제 loopback HTTP 200/200/400. 재실행 원문: `independent-verification.txt`.
- Python 3.14.7 / Django 5.2.18. NAS 네트워크 접근·배포 없음.
- `git diff fd79947..HEAD --check` 통과. 추가 코드의 literal secret, shell execution, eval/exec, pickle, formatted SQL 패턴 0건. 이는 전체 취약점 부재 증명이 아닌 제한된 정적 검사다.
- 원격 branch ref와 검토 SHA 일치. GitHub Actions run `38137264465`, head `58cde91a94e5c3f9fa043721ddf3be531aead411`: completed/success, verify job의 설치/pip check/verify 단계 모두 success. `ci.json` 참조.
- 공개 라우트는 `/`, `/health/`뿐. DEBUG off, secret 미설정/짧은 값 거부, CSRF middleware, HTTPS/secure-cookie 기본값, Host 거부, 보안 헤더 적용 확인. DB 장애는 상세정보 없는 503, 응답 no-store.
- CI는 읽기 권한, action SHA pin, credential 미보존, timeout을 사용하고 운영 secret을 요구하지 않는다.

## 비차단 한계 및 후속 수용 기준

- `SELECT 1`은 DB 연결만 증명한다. migration readiness, NAS, 회원 승인, 백업 상태를 보증하지 않는다.
- `DJANGO_LOCAL_HTTP=1`은 운영 보호를 끄는 명시적 개발 옵션이며 loopback 바인딩을 강제하지는 않는다. 현재 문서와 검증은 loopback만 사용한다. 운영 배포 단계에서 이 옵션 금지/검사 필요.
- HSTS includeSubDomains/preload, TLS 프록시 헤더 신뢰, production server, 운영 DB, dependency hash/취약점 스캔은 배포 승인 전에 검증해야 한다. 현재 외부 배포 없음.
- secret 길이 검사는 엔트로피를 증명하지 않는다. 실제 서비스는 무작위 secret 생성·보관·회전 절차가 필요하다.
- verifier는 Python assert와 현재 15개 migration 기준을 사용한다. `-O` 없이 실행해야 하며, 도메인 모델 추가 시 migration 기준을 함께 갱신해야 한다.
- 현재 테스트는 동작 회귀를 확인하나 인증·권한·격리는 아직 구현/검증되지 않았다. 현 foundation 승인은 해당 기능 승인과 무관하다.
- 1단계 NAS/그룹 용량·운영 정책 승인 미완료는 유지한다. 3단계 인증 방식은 사용자 선택 ①(독립 포털 계정, 관리자 승인 후 NAS 연결)로 확정됐다. `../membership-auth-decision.md` 참조. 구현은 부모의 후속 위임 범위이며 이번 리뷰에서는 수행하지 않았다.

문서 변경 commit의 최종 CI는 커밋에 자기 SHA를 넣을 수 없으므로 부모 handoff에서 별도로 제공한다. `ci.json`은 실제 검토한 코드 SHA의 CI 증거이며 최신 문서 commit CI로 오인하지 않는다.
