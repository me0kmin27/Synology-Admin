class SupportPrivacyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith(('/mfa/', '/account/settings/', '/manage/mfa-policy/')):
            request.sensitive_post_parameters = '__ALL__'
        response = self.get_response(request)
        if request.path.startswith(('/support/', '/chat/', '/mfa/', '/manage/mfa-policy/')):
            response['Cache-Control'] = 'no-store'
        return response
