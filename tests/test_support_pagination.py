from django.contrib.auth.models import User
from django.db import connection
from tests.mfa_helpers import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from membership.models import Membership, Tenant
from support.models import Ticket, TicketReply


@override_settings(SECURE_SSL_REDIRECT=False, MEMBERSHIP_ALLOW_UNSAFE_SQLITE=True)
class SupportPaginationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name='Pagination')
        self.user = User.objects.create_user('pagination-owner')
        self.member = Membership.objects.create(user=self.user, tenant=self.tenant, status='approved')
        self.ticket = Ticket.objects.create(tenant=self.tenant, author=self.user, title='Help', body='Question')
        self.path = f'/support/{self.ticket.pk}/'
        self.client.force_login(self.user)

    def replies(self, count):
        return TicketReply.objects.bulk_create([
            TicketReply(ticket=self.ticket, author=self.user, body=f'answer-{i}') for i in range(count)
        ])

    def test_every_cursor_reapplies_scope_and_revocation(self):
        from chat.models import Conversation
        other_tenant = Tenant.objects.create(name='Other pagination tenant')
        peer = User.objects.create_user('pagination-peer')
        outsider = User.objects.create_user('pagination-outsider')
        manager = User.objects.create_user('pagination-manager')
        staff = User.objects.create_user('pagination-staff', is_staff=True)
        root = User.objects.create_superuser('pagination-root')
        Membership.objects.create(user=peer, tenant=self.tenant, status='approved')
        Membership.objects.create(user=outsider, tenant=other_tenant, status='approved', role='admin')
        Membership.objects.create(user=manager, tenant=self.tenant, status='approved', role='admin')
        own, peers, foreign = [], [], []
        for i in range(28):
            for owner, tenant, records in ((self.user, self.tenant, own), (peer, self.tenant, peers), (outsider, other_tenant, foreign)):
                records.append(Ticket.objects.create(tenant=tenant, author=owner, title=f'{owner.username}-{i}', body='B').pk)
        self.replies(28)
        conversation = Conversation.objects.create(tenant=self.tenant, owner=self.user)
        other_conversation = Conversation.objects.create(tenant=other_tenant, owner=outsider)
        for actor, expected in ((self.user, own + [self.ticket.pk]), (peer, peers),
                                (manager, own + peers + [self.ticket.pk]), (outsider, foreign),
                                (root, own + peers + foreign + [self.ticket.pk])):
            self.client.force_login(actor)
            cursor, seen = None, []
            while True:
                response = self.client.get('/support/', {'before': cursor} if cursor else {})
                self.assertEqual(response.status_code, 200)
                seen.extend(row.pk for row in response.context['page'])
                cursor = response.context['next_cursor']
                if not cursor:
                    break
            self.assertEqual(seen, sorted(expected, reverse=True))
            detail = self.client.get(self.path, {'after': '0', 'tenant': other_tenant.pk, 'author': outsider.pk})
            self.assertEqual(detail.status_code, 200 if actor in (self.user, manager, root) else 404)
        self.client.force_login(staff)
        self.assertEqual(self.client.get('/support/?before=9223372036854775807').status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual([c.pk for c in self.client.get('/chat/?before=9223372036854775807').context['page']], [conversation.pk])
        self.assertEqual(self.client.get(f'/chat/{other_conversation.pk}/events/?after=0').status_code, 404)
        self.member.tenant = other_tenant
        self.member.save()
        self.assertEqual(self.client.get(self.path).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.path + '?after=0').status_code, 404)
        self.assertEqual(self.client.get('/support/?before=9223372036854775807').context['page'], [])
        self.assertEqual(self.client.get('/chat/?before=9223372036854775807').context['page'], [])
        self.member.status = 'suspended'
        self.member.save()
        self.client.force_login(self.user)
        for path in ('/support/?before=0', self.path + '?after=0', '/chat/?before=0', f'/chat/{conversation.pk}/events/?after=0'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 403)
            self.assertIn('no-store', response.headers['Cache-Control'])
        self.member.session_version += 1
        self.member.save()
        self.assertEqual(self.client.get(self.path + '?after=0').status_code, 302)

    def test_chat_history_retains_bounded_no_loss_cursor_contract(self):
        from uuid import uuid4
        from chat.models import Conversation, Message
        conversation = Conversation.objects.create(tenant=self.tenant, owner=self.user)
        original = Message.objects.bulk_create([
            Message(conversation=conversation, author=self.user, body=str(i), nonce=uuid4()) for i in range(107)
        ])
        path = f'/chat/{conversation.pk}/events/'
        after, seen = '0', []
        expected = [m.pk for m in original]
        page = {'has_more': True}
        for iteration in range(3):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(path, {'after': after, 'limit': '999999'})
            self.assertEqual(response.status_code, 200)
            page = response.json()
            self.assertLessEqual(len(page['messages']), 50)
            reads = [q['sql'] for q in queries if 'FROM "chat_message"' in q['sql']]
            self.assertEqual(len(reads), 1)
            self.assertIn('LIMIT 51', reads[0])
            self.assertNotIn('OFFSET', reads[0])
            self.assertLessEqual(len([q for q in queries if 'FROM "auth_user"' in q['sql']]), 3)
            seen.extend(int(m['id']) for m in page['messages'])
            after = page['cursor']
            if iteration == 0:
                new = Message.objects.create(conversation=conversation, author=self.user, body='arrival', nonce=uuid4())
                expected.append(new.pk)
        self.assertEqual(seen, expected)
        self.assertFalse(page['has_more'])
        self.assertEqual(self.client.get(path, {'after': after}).json(), {'messages': [], 'cursor': after, 'has_more': False})

    def test_empty_exact_and_deleted_cursor_boundaries(self):
        self.assertEqual(self.client.get(self.path).context['replies'], [])
        rows = self.replies(25)
        response = self.client.get(self.path)
        self.assertEqual(len(response.context['replies']), 25)
        self.assertIsNone(response.context['next_cursor'])
        # A cursor is a value, not a required row lookup; sequence gaps are valid.
        midpoint = rows[12].pk
        rows[12].delete()
        response = self.client.get(self.path, {'after': str(midpoint)})
        self.assertEqual([r.pk for r in response.context['replies']], [r.pk for r in rows[13:]])
        self.assertEqual(self.client.get(self.path, {'after': str(rows[-1].pk)}).context['replies'], [])

    def test_scope_and_cursor_columns_have_composite_indexes(self):
        from chat.models import Conversation
        for model, columns in ((Ticket, ['tenant_id', 'id']),
                               (Ticket, ['tenant_id', 'author_id', 'id']),
                               (TicketReply, ['ticket_id', 'id']),
                               (Conversation, ['tenant_id', 'id'])):
            with self.subTest(model=model.__name__, columns=columns):
                with connection.cursor() as cursor:
                    constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
                self.assertTrue(any(c['index'] and c['columns'] == columns for c in constraints.values()))

    def test_lists_use_bounded_keysets_not_offset_or_count(self):
        from chat.models import Conversation
        self.member.role = 'admin'
        self.member.save()
        self.client.force_login(self.user)
        tickets = [self.ticket] + Ticket.objects.bulk_create([
            Ticket(tenant=self.tenant, author=self.user, title=f'Ticket {i}', body='secret body') for i in range(52)
        ])
        owners = User.objects.bulk_create([User(username=f'conversation-owner-{i}') for i in range(54)])
        conversations = Conversation.objects.bulk_create([
            Conversation(tenant=self.tenant, owner=user) for user in owners[:53]
        ])
        for path, original, table in (('/support/', tickets, 'support_ticket'), ('/chat/', conversations, 'chat_conversation')):
            with self.subTest(path=path):
                with CaptureQueriesContext(connection) as queries:
                    response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context['page']), 25)
                self.assertIn('next_cursor', response.context)
                cursor = response.context['next_cursor']
                self.assertEqual(cursor, str(original[-25].pk))
                self.assertContains(response, f'?before={cursor}')
                reads = [q['sql'] for q in queries if f'FROM "{table}"' in q['sql']]
                self.assertEqual(len(reads), 1)
                self.assertIn('LIMIT 26', reads[0])
                self.assertNotIn('COUNT(', reads[0])
                self.assertNotIn('OFFSET', reads[0])
                if path == '/support/':
                    self.assertNotIn('"body"', reads[0])
                    Ticket.objects.create(tenant=self.tenant, author=self.user, title='New', body='B')
                else:
                    self.assertIn('JOIN "auth_user"', reads[0])
                    Conversation.objects.create(tenant=self.tenant, owner=owners[-1])
                seen = [row.pk for row in response.context['page']]
                while cursor:
                    with CaptureQueriesContext(connection) as queries:
                        response = self.client.get(path, {'before': cursor, 'limit': '999999'})
                    self.assertLessEqual(len(response.context['page']), 25)
                    self.assertFalse(any('OFFSET' in q['sql'] or 'COUNT(' in q['sql'] for q in queries))
                    seen.extend(row.pk for row in response.context['page'])
                    cursor = response.context['next_cursor']
                self.assertEqual(seen, [row.pk for row in reversed(original)])
                for value in ('-1', '', '١', '9223372036854775808', '<script>'):
                    self.assertEqual(self.client.get(path, {'before': value}).status_code, 400)
                self.assertEqual(self.client.get(path, {'page': '999999999'}).status_code, 400)
                self.assertEqual(self.client.get(path, {'before': '0'}).context['page'], [])

    def test_reply_cursor_is_strict_ascii_bigint_and_invalid_pages_are_private(self):
        self.client.raise_request_exception = False
        for value in ('', '-1', '+1', '1.0', '١', '1e2', '9223372036854775808', '9' * 1000, '<script>'):
            with self.subTest(value=value):
                response = self.client.get(self.path, {'after': value})
                self.assertEqual(response.status_code, 400)
                self.assertIn('no-store', response.headers['Cache-Control'])
        for value in ('0', '9223372036854775807'):
            self.assertEqual(self.client.get(self.path, {'after': value}).status_code, 200)

    def test_reply_render_cost_is_constant_including_invalid_post(self):
        self.replies(1)
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.path)
        self.replies(79)
        for method, path, data in (('get', self.path, {}), ('post', self.path + 'replies/', {'body': ''})):
            with self.subTest(method=method):
                with CaptureQueriesContext(connection) as queries:
                    response = getattr(self.client, method)(path, data)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.context['replies']), 25)
                user_reads = [q['sql'] for q in queries if 'FROM "auth_user"' in q['sql']]
                small_reads = [q['sql'] for q in small if 'FROM "auth_user"' in q['sql']]
                self.assertLessEqual(len(user_reads), len(small_reads))
                reply_reads = [q['sql'] for q in queries if 'FROM "support_ticketreply"' in q['sql']]
                self.assertEqual(len(reply_reads), 1)
                self.assertIn('LIMIT 26', reply_reads[0])
                self.assertIn('JOIN "auth_user"', reply_reads[0])
                self.assertNotIn('OFFSET', reply_reads[0])
                self.assertNotIn('COUNT(', reply_reads[0])

    def test_reply_pages_are_bounded_and_new_arrivals_do_not_shift_cursor(self):
        original = self.replies(53)
        first = self.client.get(self.path)
        self.assertEqual(len(first.context['replies']), 25)
        self.assertEqual(first.context['next_cursor'], str(original[24].pk))
        self.assertContains(first, f'?after={original[24].pk}')
        newer = TicketReply.objects.create(ticket=self.ticket, author=self.user, body='new arrival')
        seen = [r.pk for r in first.context['replies']]
        cursor = first.context['next_cursor']
        while cursor:
            response = self.client.get(self.path, {'after': cursor})
            self.assertLessEqual(len(response.context['replies']), 25)
            seen.extend(r.pk for r in response.context['replies'])
            cursor = response.context['next_cursor']
        self.assertEqual(seen, [r.pk for r in original] + [newer.pk])
        self.assertEqual(len(seen), len(set(seen)))
