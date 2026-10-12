"""Validate operator configuration at startup; no implicit trust expansion."""
import os
from ipaddress import ip_address, ip_network
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured
from django.http.request import split_domain_port


def csv(name, default=''):
    value = os.environ.get(name, default)
    if not value.strip():
        return []
    values = [item.strip() for item in value.split(',')]
    if any(not item for item in values):
        raise ImproperlyConfigured(f'{name}: empty list entry')
    return values


def allowed_hosts():
    hosts = csv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1')
    for host in hosts:
        domain, port = split_domain_port(host)
        if not domain or port or '*' in host or host.startswith('.') or host.endswith('.'):
            raise ImproperlyConfigured('DJANGO_ALLOWED_HOSTS requires exact hostnames without ports')
        if host.startswith('['):
            try:
                ip_address(host[1:-1])
            except ValueError as error:
                raise ImproperlyConfigured('Invalid IPv6 host') from error
    return [host.lower() for host in hosts]


def csrf_origins(hosts):
    origins = csv('DJANGO_CSRF_TRUSTED_ORIGINS')
    normalized = []
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            host = parsed.hostname
            port = parsed.port
            exact_host = f'[{host}]' if host and ':' in host else host
            canonical = f'https://{exact_host}' + (f':{port}' if port is not None else '')
            valid = (parsed.scheme == 'https' and exact_host in hosts
                     and origin.lower() == canonical
                     and (port is None or 1 <= port <= 65535))
        except ValueError:
            valid = False
        if not valid:
            raise ImproperlyConfigured('CSRF origins must be exact HTTPS origins of allowed hosts')
        normalized.append(origin.lower())
    return normalized


def trusted_networks():
    networks = []
    for value in csv('DJANGO_TRUSTED_PROXY_IPS'):
        try:
            network = ip_network(value, strict=True)
            if network.prefixlen == 0 or '%' in value:
                raise ValueError('Unbounded/scoped trust')
        except ValueError as error:
            raise ImproperlyConfigured('Trusted proxies require explicit IPs or canonical bounded CIDRs') from error
        networks.append(str(network))
    return networks
