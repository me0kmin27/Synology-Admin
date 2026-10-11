"""Authenticated seed envelope; encryption keys never come from the DB."""
import json
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from django.conf import settings
from django.views.decorators.debug import sensitive_variables


class SeedUnavailable(Exception):
    pass


@sensitive_variables()
def cipher():
    try:
        return MultiFernet([Fernet(key) for key in settings.MFA_ENCRYPTION_KEYS])
    except (ValueError, TypeError):
        raise SeedUnavailable from None


@sensitive_variables()
def seal(device, seed):
    payload = json.dumps({'v': 1, 'user': device.user_id, 'device': str(device.identity), 'seed': seed.hex()})
    return cipher().encrypt(payload.encode()).decode()


@sensitive_variables()
def unseal(device):
    try:
        payload = json.loads(cipher().decrypt(device.ciphertext.encode()))
        if (payload['v'], payload['user'], payload['device']) != (1, device.user_id, str(device.identity)):
            raise SeedUnavailable
        seed = bytes.fromhex(payload['seed'])
        if len(seed) != 20:
            raise SeedUnavailable
        return seed
    except (InvalidToken, ValueError, TypeError, KeyError):
        raise SeedUnavailable from None
