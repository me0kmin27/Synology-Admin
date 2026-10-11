"""Run ONLY on the deployment host; exclusive creation, never print secrets."""
import os
import secrets

fd = os.open('.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write(f'DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}\n')
    stream.write(f'POSTGRES_PASSWORD={secrets.token_urlsafe(48)}\n')
print('Created .env with mode 0600; no administrator account created.')
