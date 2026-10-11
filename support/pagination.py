"""Fixed-size ID keyset pages; cursors never confer authorization."""
import re

PAGE_SIZE = 25


def cursor_page(queryset, raw=None, *, descending=False):
    if raw is not None:
        if not re.fullmatch(r'[0-9]{1,19}', raw) or int(raw) > 9223372036854775807:
            raise ValueError('Invalid cursor')
        queryset = queryset.filter(**{'pk__lt' if descending else 'pk__gt': int(raw)})
    rows = list(queryset.order_by('-pk' if descending else 'pk')[:PAGE_SIZE + 1])
    return {
        'page': rows[:PAGE_SIZE],
        'next_cursor': str(rows[PAGE_SIZE - 1].pk) if len(rows) > PAGE_SIZE else None,
    }
