"""Read-only Chromium smoke against an already-running packaged app.

No customer accounts, credentials, writes, or NAS calls. Default is CI loopback.
"""
import os

from playwright.sync_api import expect, sync_playwright


def main():
    base = os.environ.get('UI_BASE_URL', 'http://127.0.0.1:18081').rstrip('/')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        failures, external = [], []
        page.on('pageerror', lambda error: failures.append(str(error)))
        page.on('request', lambda request: external.append(request.url) if not request.url.startswith(base + '/') else None)
        for width in (1440, 390):
            page.set_viewport_size({'width': width, 'height': 960})
            for path in ('/', '/login/', '/signup/'):
                response = page.goto(base + path)
                assert response.status == 200, (path, response.status)
                expect(page.locator('main#main-content')).to_be_visible()
                assert page.locator('body').evaluate("e => getComputedStyle(e).backgroundColor") == 'rgb(247, 248, 250)'
                assert page.locator('.portal-shell').evaluate("e => getComputedStyle(e).display") == ('grid' if width == 1440 else 'block')
                assert page.evaluate('document.documentElement.scrollWidth') <= width
                assert page.locator('link[rel=stylesheet],script[src],iframe').count() == 0
                if path == '/':
                    expect(page.locator('main')).to_contain_text('NAS 연결 안 됨')
                else:
                    assert page.locator('[name=csrfmiddlewaretoken]').input_value()
        assert not failures, failures
        assert not external, external
        browser.close()
    print('PACKAGED UI PASS: 3 public routes x desktop/mobile; rendered local CSS, responsive computed styles, CSRF forms, no external requests or JS errors')


if __name__ == '__main__':
    main()
