# 관리 포털 UI

## 구현 범위

- 기존 11개 페이지 템플릿을 실제 Django 공통 레이아웃으로 전환했다. 로그인과 가입은 같은 폼 템플릿을 사용한다.
- 랜딩, 로그인/가입, 회원 상태, 스토리지, 회원/그룹 관리, OTP 등록/검증, 지원 목록/작성/상세, 채팅 목록/상세를 포함한다.
- 주요 구성은 작업 중심 **Operate** 화면이다. Vercel 참조의 중립색·정밀한 간격 원칙만 차용하고, 자체 사이드바/헤더/작업 패널을 구성했다. 검증되지 않은 통계, 온라인 상태, 읽음 여부, NAS 관측값을 만들지 않는다.
- 데스크톱 사이드바는 모바일에서 항상 보이는 2행 메뉴가 된다. 메뉴 토글 JavaScript가 필요 없다. 시스템 한글 글꼴을 의도적으로 사용하여 외부 폰트 요청을 없앴다.
- 키보드 건너뛰기 링크, `main` 포커스, 현재 메뉴 표시, 입력 레이블, 44px 주요 터치 대상, 긴 내용 줄바꿈과 오류 스타일을 제공한다. 폼 도움말/검증 오류는 Django의 기존 한국어 번역을 사용한다.

## 로컬 자산 / 컨테이너

이 저장소는 `django.contrib.staticfiles` 또는 정적 파일 서버를 설정하지 않는다. 따라서 새 정적 URL을 가정하지 않고 `templates/ui/portal.css`를 `base.html`의 `<style>`에 템플릿 include한다. CSS는 저장소 안의 공통 자산이며 최종 HTML에 포함된다. 폰트/CDN/추적기/외부 이미지 요청이 없다. 기존 채팅 JS는 바이트 단위로 동일하고, 공통 레이아웃의 `scripts` 블록으로 이동했을 뿐이다.

`Dockerfile`, Compose, Gunicorn 설정, LAN 바인딩, 모델/뷰/권한 코드는 변경하지 않았다. PR #13의 main `c0dc45af74b4c23a1e7190b095ff9ece94863a42`를 작업 브랜치에 통합했다. 원격 운영 서버에는 배포하지 않았다.

`.github/workflows/portal-ui.yml`은 기존 Dockerfile을 빌드한 뒤, 격리된 CI SQLite 테스트 볼륨과 루프백 포트에서 공개 3개 화면의 **실제 Chromium 계산 스타일**을 검증한다. 이는 운영 SQLite 승인이 아니다. 기존 PostgreSQL CI에는 인증된 전체 UI 시나리오를 추가했다. 컨테이너 배포 워크플로/Compose는 수정하지 않았다.

## 다른 계정 화면과의 통합 계약

새 프로필/자격증명 화면은 다음 공통 인터페이스를 사용한다. 추가 엔드포인트를 이 PR에서 임의로 만들지 않았다.

```django
{% extends "base.html" %}
{% block title %}계정 설정{% endblock %}
{% block nav_account %}aria-current="page"{% endblock %}
{% block breadcrumb %}내 계정 / 설정{% endblock %}
{% block content_class %}auth-layout{% endblock %}
{% block content %}
<div class="page-heading"><h1>계정 설정</h1></div>
<section class="panel">
  <form method="post">
    {% csrf_token %}
    {% include "ui/fields.html" %}
    <button type="submit">저장</button>
  </form>
</section>
{% endblock %}
```

- `ui/fields.html`에는 `form`을 전달한다. 숨김 필드, 필드 오류, 비필드 오류, helptext ID와 Django 위젯을 보존한다. 일반 `{{ form.as_p }}`도 공통 CSS와 호환된다.
- `field.help_text|safe`는 Django 기본 폼 렌더러와 같은 신뢰 경계다. 이 속성에 사용자 작성 HTML을 전달해서는 안 된다.
- `panel`, `page-heading`, `actions`, `button secondary`, `notice`, `data-list`, `pagination`, `form-field`를 재사용할 수 있다.
- `title`, `breadcrumb`, `content_class`, `content`, `scripts` 블록과 `nav_home/account/service/support/chat/manage` 블록을 제공한다.
- 기본 레이아웃은 인증 context processor에 의존하지 않는다. 메뉴는 경로 안내일 뿐 권한을 부여하지 않으며 기존 서버 권한 검사가 그대로 적용된다.

## 검증 / 증거

- `browser_tests/portal_ui.py`: 실제 HTTP와 Chromium에서 가입, 잘못된 로그인 오류, 정상 로그인, 대기/승인 계정, OTP 등록/검증, 지원 요청/답변, 채팅 송수신, 로그아웃 검증. 모든 계정과 내용은 폐기 가능한 테스트 데이터다.
- 화면 19개 상태를 1440px/390px에서 각각 검사하고 38개 스크린샷을 생성한다. 가로 넘침, 레이블, 페이지 제목/주요 영역, 외부 요청, JS 오류를 검사한다. OTP seed/비밀번호/코드 입력은 캡처에서 마스킹한다.
- `docs/evidence/ui-screenshots/manifest.json`: 파일별 목록과 코드로 계산한 개수.
- `docs/evidence/ui-browser-final.txt`: 새 UI/기존 스토리지/기존 MFA 브라우저 검사 결과.
- `docs/evidence/ui-regression-final.txt`: 전체 Django 회귀, 보안 설정, 마이그레이션, HTTP 검사.
- `docs/evidence/ui-gunicorn.txt`: 기존 Gunicorn 설정을 이용한 로컬 패키지 공개 화면 확인. Docker는 로컬에 없어 컨테이너 검증은 CI가 수행한다.
- `docs/evidence/ui-static-review.json`: 변경 페이지 수, CSRF/명시적 form action 보존, 기존 채팅 JS 동일성.
- `ui-shell-red.txt`, `ui-pages-red.txt`, `ui-labels-red.txt`, `ui-korean-red.txt`: 구현 전 실패 기록. 첫 폼 디자인에서 지연 로딩된 티켓 날짜를 읽어 N+1이 발생했으며 기존 쿼리 예산 테스트가 탐지했다. 목록의 날짜 접근을 제거하고 회귀 통과를 확인했다.
- `ui-browser-sqlite-failure.txt`: SQLite로 기존 동시 채팅 브라우저 검사를 합쳐 실행했을 때 실패한 기록을 숨기지 않고 보존한다. UI 픽스처 승인 상태 변경의 동시 쓰기를 제거했다. 동시성 판정은 PostgreSQL CI 결과로 한다.

시각 검토: 스토리지 데스크톱, 계정/채팅 모바일, 가입 모바일, 로그인 오류 데스크톱, 랜딩 모바일, 관리 폼을 이미지로 직접 확인했다. 가로 잘림 없음. 관리 화면은 기존 전체 목록 구조를 유지하여 회원 수에 따라 길어진다. 디자인 자체 점검은 0/10: 그라디언트, 가짜 지표, 동등한 장식 카드 그리드, 유리 효과, 중심 정렬 대시보드를 사용하지 않는다. 시스템 폰트는 한글/오프라인 제약에 따른 의도적 선택이다.

## 재현

```sh
python -m pip install -r requirements.txt -r requirements-browser.txt
python -m playwright install chromium
python scripts/verify.py
# 테스트 실행용 임시 SECRET_KEY를 환경에 주입한 뒤:
python manage.py test browser_tests.portal_ui browser_tests.storage browser_tests.mfa -v 2
# 기존 전체 브라우저/경합 검사는 PostgreSQL 테스트 환경에서 실행한다.
# 스크린샷을 재생성하려면 UI_SCREENSHOT_DIR를 지정한다 (기본 .runtime/ui-screenshots).
```

## 남은 경계

- 독립 리뷰와 최종 HEAD의 CI 확인은 별도 병합 게이트다. 구현자는 스스로 병합하지 않는다.
- NAS/RustDesk 연결, 운영 계정 생성, 사용자 자격증명 변경 엔드포인트, 서버 배포는 이 UI PR의 범위가 아니다.
- 일부 기존 변경 실패 응답은 뷰가 반환하는 일반 400/403/409 응답이다. 이를 새 오류 화면/메시지 시스템으로 바꾸려면 별도 동작 변경과 테스트가 필요하다.
- 실제 운영 사용자 비밀번호 없이 테스트 픽스처만 사용했다. 화면 테스트는 보조 접근성 검사이며 전체 스크린리더 인증을 주장하지 않는다.
