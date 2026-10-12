"""CI only: prove source trust across Docker's published HTTP port.

Uses the disposable container workflow project. Never run against live state.
No inspect/config output includes credentials. Probe IP is discovered, not trusted
as a subnet; the same source fails with the production example's different IP.
"""
import json
import os
import subprocess


def run(*args, env=None):
    return subprocess.check_output(args, env=env, text=True).strip()


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Disposable GitHub Actions runtime only')
    host = json.loads(run('ip', '-j', '-4', 'route', 'get', '1.1.1.1'))[0]['prefsrc']
    env = {**os.environ, 'COMPOSE_FILE': 'compose.internal.json:compose.proxy.json',
           'INTERNAL_BIND_HOST': host, 'DJANGO_ALLOWED_HOSTS': 'localhost,127.0.0.1,Test.keiminem.com',
           'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://Test.keiminem.com', 'DJANGO_LOCAL_HTTP': '0'}
    image = 'synology-admin-internal:' + os.environ['SOURCE_REVISION']
    # Model an ingress client outside the web bridge. A client on the same
    # bridge hairpins through the published port and may be SNATed to a gateway;
    # trusting that shared gateway would erase the source identity boundary.
    probe = run('docker', 'run', '-d', '--network', 'host',
                '--entrypoint', 'python', image, '-c', 'import time; time.sleep(180)')
    try:
        peer = host
        import ipaddress
        ipaddress.ip_address(peer)
        for trusted, expected in [('192.168.1.142', 301), (peer, 200), ('', 301)]:
            env['DJANGO_TRUSTED_PROXY_IPS'] = trusted
            subprocess.run(['docker', 'compose', 'up', '-d', '--no-build', '--no-deps',
                            '--wait', '--wait-timeout', '120', 'web'], env=env, check=True)
            program = '''
import http.client,sys
host,expected=sys.argv[1],int(sys.argv[2])
for value in ['https','https,http']:
    conn=http.client.HTTPConnection(host,18080,timeout=10,source_address=(host,0))
    conn.request('GET','/login/',headers={'Host':'Test.keiminem.com','X-Forwarded-Proto':value})
    response=conn.getresponse()
    want=400 if value=='https,http' and expected==200 else expected
    assert response.status==want,(response.status,want)
    if want==200:
        assert '; Secure' in response.getheader('Set-Cookie','')
    response.read();conn.close()
print('published-port peer trust verified')
'''
            print(run('docker', 'exec', probe, 'python', '-c', program, host, str(expected)))
        print(json.dumps({'docker_published_port': 'verified', 'peer_ip': peer,
                          'production_peer': 'not_contacted', 'external_tls': 'not_tested'}))
    finally:
        run('docker', 'rm', '-f', probe)


if __name__ == '__main__':
    main()
