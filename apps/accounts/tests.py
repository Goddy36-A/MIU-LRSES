"""Phase 1 tests: authentication, roles, access control, user management, audit.

All accounts below are synthetic test fixtures, not real people.
"""
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import AuditLog, Role, User

PW = "Sup3r-Secret-Test-pw"


def make_user(username, role, **extra):
    return User.objects.create_user(username=username, password=PW, role=role,
                                    email=f"{username}@example.test", first_name="Test", last_name=username.title(), **extra)


class RoleFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("adm", Role.ADMIN)
        cls.lecturer = make_user("lec", Role.LECTURER)
        cls.student = make_user("stu", Role.STUDENT)
        cls.researcher = make_user("res", Role.RESEARCHER)


class UserModelTests(TestCase):
    def test_default_role_is_student(self):
        self.assertEqual(User.objects.create_user("x", password=PW).role, Role.STUDENT)

    def test_superuser_is_admin_role_and_staff(self):
        su = User.objects.create_superuser("root", "r@example.test", PW)
        self.assertEqual(su.role, Role.ADMIN)
        self.assertTrue(su.is_staff)

    def test_superuser_flag_forces_admin_role(self):
        u = User(username="y", is_superuser=True, role=Role.STUDENT)
        u.set_password(PW)
        u.save()
        self.assertEqual(u.role, Role.ADMIN)

    def test_only_admin_role_gets_staff_access(self):
        self.assertTrue(make_user("a1", Role.ADMIN).is_staff)
        for role in (Role.LECTURER, Role.STUDENT, Role.RESEARCHER):
            self.assertFalse(make_user(f"u-{role}", role).is_staff, role)

    def test_researcher_is_not_admin(self):
        r = make_user("r1", Role.RESEARCHER)
        self.assertFalse(r.is_system_admin)
        self.assertFalse(r.is_superuser)

    def test_role_groups_created_after_migrate(self):
        call_command("migrate", verbosity=0)
        names = set(Group.objects.values_list("name", flat=True))
        self.assertTrue({"System Administrator", "Lecturer", "Student", "Researcher"} <= names)


class AuthenticationTests(RoleFixtureMixin, TestCase):
    def test_login_page_renders(self):
        self.assertContains(self.client.get(reverse("accounts:login")), "Sign in")

    def test_login_success_redirects_to_role_dashboard(self):
        expected = {
            "adm": "accounts:dashboard_admin", "lec": "accounts:dashboard_lecturer",
            "stu": "accounts:dashboard_student", "res": "accounts:dashboard_researcher",
        }
        for username, route in expected.items():
            self.client.logout()
            resp = self.client.post(reverse("accounts:login"), {"username": username, "password": PW}, follow=True)
            self.assertEqual(resp.redirect_chain[-1][0], reverse(route), username)
            self.assertEqual(resp.status_code, 200)

    def test_login_wrong_password_fails_and_is_audited(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "stu", "password": "wrong"})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        entry = AuditLog.objects.get(action="login_failed")
        self.assertEqual(entry.target, "stu")
        self.assertNotIn("wrong", entry.details + entry.target)

    def test_inactive_user_cannot_login(self):
        User.objects.filter(username="stu").update(is_active=False)
        self.client.post(reverse("accounts:login"), {"username": "stu", "password": PW})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        self.client.login(username="stu", password=PW)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_and_logout_are_audited(self):
        self.client.post(reverse("accounts:login"), {"username": "lec", "password": PW})
        self.client.post(reverse("accounts:logout"))
        actions = list(AuditLog.objects.values_list("action", flat=True))
        self.assertIn("login", actions)
        self.assertIn("logout", actions)

    def test_passwords_are_hashed(self):
        self.assertNotEqual(self.student.password, PW)
        self.assertTrue(self.student.password.startswith(("pbkdf2_", "argon2", "bcrypt")))

    def test_password_change_flow(self):
        self.client.login(username="stu", password=PW)
        new = "An0ther-Strong-pw-77"
        resp = self.client.post(reverse("accounts:password_change"),
                                {"old_password": PW, "new_password1": new, "new_password2": new})
        self.assertRedirects(resp, reverse("accounts:password_change_done"))
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(new))

    def test_password_reset_request_sends_console_email(self):
        from django.core import mail
        resp = self.client.post(reverse("accounts:password_reset"), {"email": "stu@example.test"})
        self.assertRedirects(resp, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/password/reset/", mail.outbox[0].body)

    def test_csrf_enforced_on_login(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(reverse("accounts:login"), {"username": "stu", "password": PW}).status_code, 403)


class AccessControlTests(RoleFixtureMixin, TestCase):
    PROTECTED = [
        "accounts:home", "accounts:dashboard_admin", "accounts:dashboard_lecturer",
        "accounts:dashboard_student", "accounts:dashboard_researcher",
        "accounts:user_list", "accounts:user_add", "accounts:audit_list", "accounts:password_change",
    ]

    def test_anonymous_redirected_to_login(self):
        for name in self.PROTECTED:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn(reverse("accounts:login"), resp["Location"], name)

    def test_anonymous_cannot_open_django_admin(self):
        self.assertEqual(self.client.get("/django-admin/").status_code, 302)

    def test_dashboards_are_role_restricted(self):
        route = {"adm": "accounts:dashboard_admin", "lec": "accounts:dashboard_lecturer",
                 "stu": "accounts:dashboard_student", "res": "accounts:dashboard_researcher"}
        for username in route:
            self.client.login(username=username, password=PW)
            for owner, name in route.items():
                expected = 200 if owner == username else 403
                self.assertEqual(self.client.get(reverse(name)).status_code, expected, f"{username}->{name}")
            self.client.logout()

    def test_non_admins_cannot_manage_users_or_view_audit(self):
        target = reverse("accounts:user_edit", args=[self.student.pk])
        for username in ("lec", "stu", "res"):
            self.client.login(username=username, password=PW)
            for url in (reverse("accounts:user_list"), reverse("accounts:user_add"), target, reverse("accounts:audit_list")):
                self.assertEqual(self.client.get(url).status_code, 403, f"{username} GET {url}")
            self.assertEqual(self.client.post(target, {"role": "admin"}).status_code, 403)
            self.client.logout()
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, Role.STUDENT)

    def test_non_admin_cannot_open_django_admin(self):
        for username in ("lec", "stu", "res"):
            self.client.login(username=username, password=PW)
            self.assertEqual(self.client.get("/django-admin/").status_code, 302, username)
            self.client.logout()

    def test_admin_can_open_django_admin(self):
        self.client.login(username="adm", password=PW)
        self.assertEqual(self.client.get("/django-admin/").status_code, 200)

    def test_nav_shows_admin_links_only_to_admin(self):
        self.client.login(username="adm", password=PW)
        self.assertContains(self.client.get(reverse("accounts:dashboard_admin")), reverse("accounts:user_list"))
        self.client.logout()
        self.client.login(username="res", password=PW)
        self.assertNotContains(self.client.get(reverse("accounts:dashboard_researcher")), reverse("accounts:user_list"))

    def test_researcher_has_no_admin_permissions(self):
        self.assertFalse(self.researcher.has_perm("accounts.view_user"))
        self.assertFalse(self.researcher.has_perm("accounts.view_auditlog"))


class UserManagementTests(RoleFixtureMixin, TestCase):
    def setUp(self):
        self.client.login(username="adm", password=PW)

    def form(self, **over):
        data = {"username": "newlec", "first_name": "New", "last_name": "Lecturer", "email": "newlec@example.test",
                "role": Role.LECTURER, "is_active": "on", "password1": "Valid-Pass-9931", "password2": "Valid-Pass-9931"}
        data.update(over)
        return data

    def test_admin_creates_user_and_action_audited(self):
        resp = self.client.post(reverse("accounts:user_add"), self.form())
        self.assertRedirects(resp, reverse("accounts:user_list"))
        u = User.objects.get(username="newlec")
        self.assertEqual(u.role, Role.LECTURER)
        self.assertTrue(u.check_password("Valid-Pass-9931"))
        entry = AuditLog.objects.get(action="user_created")
        self.assertEqual(entry.target, "newlec")
        self.assertEqual(entry.actor, self.admin)
        self.assertNotIn("Valid-Pass", entry.details)

    def test_create_rejects_mismatched_and_weak_passwords(self):
        r1 = self.client.post(reverse("accounts:user_add"), self.form(password2="different"))
        self.assertContains(r1, "do not match")
        r2 = self.client.post(reverse("accounts:user_add"), self.form(password1="12345678", password2="12345678"))
        self.assertEqual(r2.status_code, 200)
        self.assertFalse(User.objects.filter(username="newlec").exists())

    def test_create_rejects_duplicate_username(self):
        self.assertContains(self.client.post(reverse("accounts:user_add"), self.form(username="stu")), "already exists")

    def test_admin_updates_role(self):
        url = reverse("accounts:user_edit", args=[self.student.pk])
        resp = self.client.post(url, {"username": "stu", "first_name": "Test", "last_name": "Stu",
                                      "email": "stu@example.test", "role": Role.RESEARCHER, "is_active": "on"})
        self.assertRedirects(resp, reverse("accounts:user_list"))
        self.student.refresh_from_db()
        self.assertEqual(self.student.role, Role.RESEARCHER)
        self.assertTrue(AuditLog.objects.filter(action="user_updated", target="stu").exists())

    def test_admin_cannot_demote_or_deactivate_self(self):
        url = reverse("accounts:user_edit", args=[self.admin.pk])
        base = {"username": "adm", "first_name": "Test", "last_name": "Adm", "email": "adm@example.test"}
        r1 = self.client.post(url, {**base, "role": Role.STUDENT, "is_active": "on"})
        r2 = self.client.post(url, {**base, "role": Role.ADMIN})
        self.assertContains(r1, "cannot remove your own")
        self.assertContains(r2, "cannot remove your own")
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, Role.ADMIN)
        self.assertTrue(self.admin.is_active)

    def test_search_filter_and_pagination(self):
        for i in range(20):
            make_user(f"bulk{i:02d}", Role.STUDENT)
        url = reverse("accounts:user_list")
        self.assertEqual(len(self.client.get(url).context["users"]), 15)
        self.assertEqual(len(self.client.get(url, {"page": 2}).context["users"]), 9)  # 24 users total
        self.assertEqual(len(self.client.get(url, {"q": "bulk07"}).context["users"]), 1)
        res = self.client.get(url, {"role": Role.RESEARCHER}).context["users"]
        self.assertEqual([u.username for u in res], ["res"])
        User.objects.filter(username="lec").update(is_active=False)
        self.assertEqual([u.username for u in self.client.get(url, {"status": "inactive"}).context["users"]], ["lec"])

    def test_admin_dashboard_shows_real_counts(self):
        ctx = self.client.get(reverse("accounts:dashboard_admin")).context
        self.assertEqual(ctx["total_users"], 4)
        self.assertEqual(ctx["chart_values"], [1, 1, 1, 1])

    def test_audit_log_is_read_only_in_django_admin(self):
        self.client.logout()
        su = User.objects.create_superuser("root", "r@example.test", PW)
        self.client.force_login(su)
        self.assertEqual(self.client.get("/django-admin/accounts/auditlog/add/").status_code, 403)
