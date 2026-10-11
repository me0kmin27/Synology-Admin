"""Deployment-host-only independent Fernet key; never overwrite or print."""
import base64
import os
import secrets

fd = os.open('.mfa.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii')
    stream.write(f'MFA_ENCRYPTION_KEYS={key}\n')
print('Created independent .mfa.env mode 0600; backup/recovery not verified.')
