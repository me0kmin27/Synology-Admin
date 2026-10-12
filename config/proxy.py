"""Explicit peer trust boundary before Django security middleware."""
from ipaddress import ip_address, ip_network

from django.conf import settings
from django.http import HttpResponseBadRequest


def address(value):
    # Zones and chains are not single, unambiguous Internet addresses.
    if '%' in value:
        raise ValueError('Scoped addresses are unsupported')
    parsed = ip_address(value)
    return getattr(parsed, 'ipv4_mapped', None) or parsed


class TrustedProxyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.networks = tuple(ip_network(net) for net in settings.TRUSTED_PROXY_NETWORKS)

    def __call__(self, request):
        try:
            peer = address(request.META.get('REMOTE_ADDR', ''))
            trusted = any(peer in net for net in self.networks)
        except ValueError:
            trusted = False
        if trusted:
            if 'HTTP_X_FORWARDED_PROTO' in request.META:
                scheme = request.META['HTTP_X_FORWARDED_PROTO']
                if scheme not in ('http', 'https'):
                    return HttpResponseBadRequest('Invalid forwarding header')
                request.META['wsgi.url_scheme'] = scheme
            if 'HTTP_X_FORWARDED_FOR' in request.META:
                try:
                    client = address(request.META['HTTP_X_FORWARDED_FOR'])
                except ValueError:
                    return HttpResponseBadRequest('Invalid forwarding header')
                request.META['REMOTE_ADDR'] = str(client)
        for key in list(request.META):
            if key.startswith('HTTP_X_FORWARDED_') or key == 'HTTP_FORWARDED':
                del request.META[key]
        return self.get_response(request)
