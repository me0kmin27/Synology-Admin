"""Read-only portal presentation. No NAS mapping, credentials or network I/O."""
from datetime import timedelta

from django.utils import timezone
from nas_usage import NotConfiguredReader, Subject


def usage_card(member, *, kind='account'):
    # Portal IDs are placeholders, NOT verified DSM identifiers or quota scopes.
    subject = Subject(str(member.tenant_id), kind,
                      str(member.pk if kind == 'account' else member.tenant_id),
                      'portal-unmapped')
    observation = NotConfiguredReader().read_usage(subject)
    if observation.subject != subject:
        raise ValueError('Usage subject mismatch')
    return {
        'kind': kind,
        'values': observation.display(now=timezone.now(), max_age=timedelta(0)),
        'observed_at': observation.observed_at,
        'source': observation.source,
    }
