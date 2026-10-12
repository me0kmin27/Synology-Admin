"""Local-only enrollment QR. Never persist/log the provisioning URI."""
import base64
from urllib.parse import quote, urlencode
import qrcode
from qrcode.image.svg import SvgPathFillImage
from django.utils.safestring import mark_safe
from django.views.decorators.debug import sensitive_variables

ISSUER = 'Synology-Admin'


@sensitive_variables()
def enrollment_qr(seed, username):
    secret = base64.b32encode(seed).decode('ascii').rstrip('=')
    label = quote(ISSUER, safe='') + ':' + quote(username, safe='')
    uri = 'otpauth://totp/' + label + '?' + urlencode({
        'secret': secret, 'issuer': ISSUER, 'algorithm': 'SHA1', 'digits': 6, 'period': 30,
    }, quote_via=quote)
    qr = qrcode.QRCode(image_factory=SvgPathFillImage, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    svg = qr.make_image(attrib={'id': 'otp-qr', 'role': 'img', 'aria-label': '인증 앱 등록 QR'}).to_string(encoding='unicode')
    # Only the library's numeric geometry is marked safe, never URI/user input.
    return mark_safe(svg)
