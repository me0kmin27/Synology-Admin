"""Readable normal navigation failures; retain status and API response bodies."""
from django.shortcuts import render


class NavigationErrorMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        api = request.path.endswith('/events/') or 'application/json' in request.headers.get('Accept', '')
        if (not api and response.status_code in (400, 403, 404, 409, 503)
                and response.get('Content-Type', '').startswith('text/html')
                and (not response.content or response.status_code == 403)):
            messages = {
                400: ('입력 확인', '입력한 값이 올바르지 않습니다. 이전 화면에서 값을 확인하세요.'),
                403: ('접근 권한 확인', '승인 상태와 역할을 확인하세요. 변경 작업에는 현재 비밀번호와 적용되는 OTP 인증이 필요합니다.'),
                404: ('항목을 찾을 수 없음', '이 항목을 표시할 수 없습니다. 목록에서 다시 선택하세요.'),
                409: ('정책 충돌', '현재 상태, 중복 이름·slug 또는 그룹 한도와 충돌합니다. 관리 화면에서 상태를 확인하세요.'),
                503: ('일시적으로 이용 불가', '보안 정책 또는 서비스 구성을 확인해야 합니다. 관리자에게 문의하세요.'),
            }
            title, explanation = messages[response.status_code]
            rendered = render(request, 'navigation_error.html', {'title': title, 'explanation': explanation}, status=response.status_code)
            response.content = rendered.content
            response['Content-Length'] = str(len(response.content))
        return response
