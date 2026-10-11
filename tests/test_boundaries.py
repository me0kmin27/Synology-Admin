"""Regression expansion of the TDD slices: real middleware and database."""
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from tests.mfa_helpers import Client, TestCase, override_settings
from membership.models import Membership, Tenant, AuditEvent, NasBinding


@override_settings(SECURE_SSL_REDIRECT=False)
class BoundaryTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(max_accounts=100, name="visible-tenant")
        self.other_tenant = Tenant.objects.create(max_accounts=100, name="secret-tenant")
        self.password = "Operator-passphrase-829!"
        self.operator = User.objects.create_user("operator", password=self.password)
        self.operator_member = Membership.objects.create(user=self.operator, tenant=self.tenant, status="approved", role="admin")
        self.subject = Membership.objects.create(user=User.objects.create_user("subject", password=self.password), tenant=self.tenant)
        self.other = Membership.objects.create(user=User.objects.create_user("cross-tenant-secret"), tenant=self.other_tenant, status="approved")
        self.client.force_login(self.operator)

    def test_csrf_and_method_boundaries_for_every_mutation(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.operator)
        for path in ["/signup/", "/login/", "/logout/", f'/manage/groups/{self.tenant.pk}/limits/'] + [f"/manage/{self.subject.pk}/{action}/" for action in ("approve", "revoke", "assign", "link", "role", "quota")]:
            with self.subTest(path=path):
                self.assertEqual(browser.post(path, {"password": self.password}).status_code, 403)
        self.assertEqual(self.client.get(f'/manage/groups/{self.tenant.pk}/limits/').status_code, 405)
        for action in ("approve", "revoke", "assign", "link", "role", "quota"):
            self.assertEqual(self.client.get(f"/manage/{self.subject.pk}/{action}/").status_code, 405)
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.status, "pending")
        self.assertFalse(AuditEvent.objects.exists())

    def test_cross_tenant_reads_writes_and_forged_query_scope(self):
        response = self.client.get(f"/manage/?tenant={self.other_tenant.pk}")
        self.assertNotContains(response, "cross-tenant-secret")
        self.assertNotContains(self.client.get(f"/service/?tenant={self.other_tenant.pk}"), "secret-tenant")
        for action in ("approve", "revoke", "link"):
            self.assertEqual(self.client.post(f"/manage/{self.other.pk}/{action}/", {"password": self.password, "external_id": "external", "ownership_confirmed": "on"}).status_code, 404)
        self.assertEqual(AuditEvent.objects.count(), 0)
        self.assertEqual(NasBinding.objects.count(), 0)

    def test_no_self_mutation_or_staff_flag_escalation(self):
        for action in ("approve", "revoke", "link"):
            self.assertEqual(self.client.post(f"/manage/{self.operator_member.pk}/{action}/", {"password": self.password, "external_id": "self-id", "ownership_confirmed": "on"}).status_code, 403)
        self.operator_member.role = "member"
        self.operator_member.save()
        self.operator.is_staff = True
        self.operator.save()
        self.assertEqual(self.client.get("/manage/").status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get("/manage/").status_code, 403)
        self.assertEqual(self.client.post(f"/manage/{self.subject.pk}/approve/", {"password": self.password, "role": "admin"}).status_code, 403)

    def test_restored_old_session_is_invalid_even_if_status_restored(self):
        self.subject.status = "approved"
        self.subject.save()
        browser = Client()
        browser.force_login(self.subject.user)
        old_session = Session.objects.get(pk=browser.session.session_key)
        self.assertEqual(self.client.post(f"/manage/{self.subject.pk}/revoke/", {"password": self.password}).status_code, 302)
        self.subject.refresh_from_db()
        self.assertEqual(self.subject.session_version, 1)
        self.subject.status = "approved"
        self.subject.save()
        old_session.save(force_insert=True)
        self.assertEqual(browser.get("/service/").status_code, 302)
        self.assertNotIn("_auth_user_id", browser.session)

    def test_input_validation_and_no_audit_secrets(self):
        root = User.objects.create_superuser("root", password=self.password)
        self.client.force_login(root)
        unassigned = Membership.objects.create(user=User.objects.create_user("unassigned"))
        self.assertEqual(self.client.post(f"/manage/{unassigned.pk}/assign/", {"tenant": "not-an-id", "password": self.password}).status_code, 400)
        self.assertEqual(self.client.post(f"/manage/{unassigned.pk}/approve/", {"password": self.password}).status_code, 409)
        self.subject.status = "approved"
        self.subject.save()
        for payload in ({"external_id": "bad/id", "ownership_confirmed": "on"}, {"external_id": "valid-id"}):
            self.assertEqual(self.client.post(f"/manage/{self.subject.pk}/link/", {"password": self.password, **payload}).status_code, 400)
        self.assertFalse(NasBinding.objects.exists())
        self.client.post(f"/manage/{self.subject.pk}/revoke/", {"password": self.password, "reason": "do-not-store-this-secret"})
        audit = str(list(AuditEvent.objects.values()))
        self.assertNotIn(self.password, audit)
        self.assertNotIn("do-not-store-this-secret", audit)

    def test_login_rotates_session_and_rejects_external_redirect(self):
        browser = Client()
        session = browser.session
        session["prelogin"] = "marker"
        session.save()
        old_key = session.session_key
        response = browser.post("/login/?next=https://untrusted.invalid/", {"username": "operator", "password": self.password})
        self.assertEqual(response.url, "/account/")
        self.assertNotEqual(old_key, browser.session.session_key)
        self.assertEqual(browser.get("/account/")["Cache-Control"], "no-store")
