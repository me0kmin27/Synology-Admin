"""Peer-authenticated forwarding; never trust headers as peer identity."""
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.http import JsonResponse
from django.utils.module_loading import import_string


@override_settings(TRUSTED_PROXY_NETWORKS=['192.168.1.142/32'])
class ProxyTests(SimpleTestCase):
    def call(self, peer='192.168.1.142', **headers):
        middleware = import_string('config.proxy.TrustedProxyMiddleware')
        request = RequestFactory().get('/', REMOTE_ADDR=peer, **headers)
        return middleware(lambda r: JsonResponse({'secure': r.is_secure(), 'ip': r.META['REMOTE_ADDR']}))(request)

    def test_forwarding_headers_are_consumed_not_exposed(self):
        middleware = import_string('config.proxy.TrustedProxyMiddleware')
        request = RequestFactory().get('/', REMOTE_ADDR='192.168.1.141', HTTP_X_FORWARDED_PROTO='https', HTTP_X_FORWARDED_HOST='evil.invalid', HTTP_X_FORWARDED_PORT='443', HTTP_X_FORWARDED_FOR='192.168.1.142', HTTP_FORWARDED='proto=https', HTTP_X_FORWARDED_SSL='on')
        response = middleware(lambda r: JsonResponse({'remaining': [key for key in r.META if key.startswith('HTTP_X_FORWARDED_') or key == 'HTTP_FORWARDED']}))(request)
        import json
        self.assertEqual(json.loads(response.content)['remaining'], [])

    @override_settings(ALLOWED_HOSTS=['test.keiminem.com'], SECURE_SSL_REDIRECT=True)
    def test_forwarding_runs_before_redirect_and_host_validation(self):
        response = self.client.get('/login/', HTTP_HOST='Test.keiminem.com:443', REMOTE_ADDR='192.168.1.142', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cookies['csrftoken']['secure'])
        bad = self.client.get('/login/', HTTP_HOST='evil.invalid', REMOTE_ADDR='192.168.1.142', HTTP_X_FORWARDED_PROTO='https', HTTP_X_FORWARDED_HOST='Test.keiminem.com')
        self.assertEqual(bad.status_code, 400)
        direct = self.client.get('/login/', HTTP_HOST='Test.keiminem.com', REMOTE_ADDR='192.168.1.141', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(direct.status_code, 301)
        self.assertEqual(direct['Location'], 'https://Test.keiminem.com/login/')

    def test_only_single_client_ip_from_trusted_peer(self):
        import json
        self.assertEqual(json.loads(self.call(HTTP_X_FORWARDED_FOR='203.0.113.7').content)['ip'], '203.0.113.7')
        for value in ['203.0.113.7, 10.0.0.1', 'unknown', '203.0.113.7:12', '']:
            with self.subTest(value=value):
                self.assertEqual(self.call(HTTP_X_FORWARDED_FOR=value).status_code, 400)

    def test_untrusted_and_invalid_peers_ignore_forwarding(self):
        import json
        for peer in ['192.168.1.141', '127.0.0.1', '', 'bad', '192.168.1.142%eth0']:
            with self.subTest(peer=peer):
                data = json.loads(self.call(peer, HTTP_X_FORWARDED_PROTO='https', HTTP_X_FORWARDED_FOR='203.0.113.7').content)
                self.assertEqual(data, {'secure': False, 'ip': peer})

    def test_ipv4_mapped_peer_matches_ipv4_allowlist(self):
        import json
        self.assertTrue(json.loads(self.call('::ffff:192.168.1.142', HTTP_X_FORWARDED_PROTO='https').content)['secure'])

    def test_malformed_trusted_scheme_is_rejected(self):
        for value in ['https,http', 'https,https', 'HTTPS', ' https', '', 'ftp']:
            with self.subTest(value=value):
                self.assertEqual(self.call(HTTP_X_FORWARDED_PROTO=value).status_code, 400)

    def test_trusted_peer_can_assert_https(self):
        import json
        response = self.call(HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(json.loads(response.content), {'secure': True, 'ip': '192.168.1.142'})
