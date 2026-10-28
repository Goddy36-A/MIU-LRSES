"""Project-wide verification tests (Phase 8 checks). They discover pages automatically, so
routes and menu items added in later phases are covered without editing this file."""
import re

from django.core.management import call_command
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.accounts.models import Role, User

PW = "Sup3r-Secret-Test-pw"
# Public by design: sign-in and password-reset pages (the admin site has its own login page).
PUBLIC_PREFIXES = ("login/", "password/reset/", "django-admin/login/", "django-admin/logout/", "logout/")


def iter_routes(patterns=None, prefix=""):
    patterns = get_resolver().url_patterns if patterns is None else patterns
    for p in patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from iter_routes(p.url_patterns, route)
        elif isinstance(p, URLPattern):
            yield route


def concrete(route):
    """Turn a route template into a path, or None if it needs values we cannot guess."""
    route = re.sub(r"<int:\w+>", "1", route)
    return None if "<" in route else "/" + route.lstrip("/")


class AuthenticationRequiredEverywhereTests(TestCase):
    def test_every_route_redirects_anonymous_users_to_login(self):
        checked = []
        for route in iter_routes():
            if route.startswith(PUBLIC_PREFIXES) or route.startswith("static"):
                continue
            path = concrete(route)
            if path is None:
                continue
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 302, f"{path} should require login (got {resp.status_code})")
            self.assertIn("login", resp["Location"], path)
            checked.append(path)
        self.assertGreater(len(checked), 30)  # guard: the discovery really found the application's routes

    def test_state_changing_routes_reject_get_or_login(self):
        # Logout must not accept GET (it would allow forced logout via a link).
        User.objects.create_user("u", password=PW, role=Role.STUDENT)
        self.client.login(username="u", password=PW)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)


class NavigationLinkTests(TestCase):
    """Every link in the sidebar and user menu works for every role (no 404/500/403, no bounce to login)."""

    @classmethod
    def setUpTestData(cls):
        for role in Role.values:
            User.objects.create_user(f"nav_{role}", password=PW, role=role, email=f"{role}@example.test",
                                     first_name="Nav", last_name=role.title())

    def links_for(self, role):
        self.client.login(username=f"nav_{role}", password=PW)
        resp = self.client.get(reverse("accounts:home"), follow=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        nav = re.search(r'<nav class="sidebar.*?</nav>', html, re.S).group(0)
        menu = re.search(r'<ul class="dropdown-menu.*?</ul>', html, re.S).group(0)
        hrefs = set(re.findall(r'href="(/[^"#]*)"', nav + menu))
        return sorted(hrefs)

    def test_every_menu_link_opens_for_each_role(self):
        for role in Role.values:
            links = self.links_for(role)
            self.assertGreaterEqual(len(links), 2, role)
            for href in links:
                # Some pages redirect by design (e.g. "create a study first"); the chain must end on a working page,
                # stay inside the application, and never bounce a signed-in user to the login page.
                resp = self.client.get(href, follow=True)
                self.assertEqual(resp.status_code, 200, f"{role}: {href} -> {resp.status_code}")
                for url, _code in resp.redirect_chain:
                    self.assertTrue(url.startswith("/"), f"{role}: {href} redirected outside the app: {url}")
                    self.assertNotIn("/login/", url, f"{role}: {href} sent a signed-in user to login")
            self.client.logout()

    def test_menus_never_offer_pages_the_role_cannot_open(self):
        admin_only = {reverse("accounts:user_list"), reverse("accounts:audit_list")}
        for role in (Role.LECTURER, Role.STUDENT, Role.RESEARCHER):
            self.assertFalse(admin_only & set(self.links_for(role)), role)
            self.client.logout()

    def test_researcher_menu_has_no_administrator_links(self):
        links = self.links_for(Role.RESEARCHER)
        self.assertFalse([l for l in links if l.startswith(("/academics/", "/manage/", "/django-admin/"))], links)

    def test_page_titles_and_dashboard_role_labels_render(self):
        for role in Role.values:
            self.client.login(username=f"nav_{role}", password=PW)
            html = self.client.get(reverse("accounts:home"), follow=True).content.decode()
            self.assertIn("MIU-LRSES", html)
            self.assertIn(Role(role).label, html)
            self.client.logout()


class DemoDataCommandTests(TestCase):
    def test_seed_is_labelled_idempotent_and_removable(self):
        from apps.timetables.models import LectureSession
        call_command("seed_demo_data", "--password", PW, verbosity=0)
        users = User.objects.filter(username__startswith="demo_").count()
        sessions = LectureSession.objects.count()
        self.assertEqual(users, 11)  # 2 lecturers + 8 students + 1 researcher
        self.assertGreater(sessions, 0)
        self.assertTrue(all("SYNTHETIC" in s.topic for s in LectureSession.objects.all()))
        call_command("seed_demo_data", "--password", PW, verbosity=0)  # second run adds nothing
        self.assertEqual((User.objects.filter(username__startswith="demo_").count(), LectureSession.objects.count()), (users, sessions))
        self.assertTrue(User.objects.get(username="demo_student01").check_password(PW))
        call_command("seed_demo_data", "--remove", verbosity=0)
        self.assertEqual(User.objects.filter(username__startswith="demo_").count(), 0)
        self.assertEqual(LectureSession.objects.count(), 0)

    def test_password_is_required(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command("seed_demo_data", verbosity=0)

    def test_demo_lectures_have_no_conflicts(self):
        from apps.timetables.models import LectureSession
        from apps.timetables.services import find_conflicts
        call_command("seed_demo_data", "--password", PW, verbosity=0)
        for s in LectureSession.objects.all():
            self.assertEqual(find_conflicts(offering=s.offering, lecturer=s.lecturer, venue=s.venue, start=s.start_at,
                                            end=s.end_at, exclude_pk=s.pk), [], s)


class OneClickSetupFilesTests(TestCase):
    """Guards for the double-click setup files (they cannot be run by this suite on Windows)."""

    ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]

    def test_python_launchers_are_valid_python(self):
        import ast
        for name in ("setup_local.py", "run_server.py"):
            ast.parse((self.ROOT / name).read_text(encoding="utf-8"), filename=name)

    def test_batch_files_are_crlf_ascii_and_point_at_real_files(self):
        for name in ("start.bat", "setup.bat", "run_tests.bat"):
            raw = (self.ROOT / name).read_bytes()
            self.assertNotIn(b"\n", raw.replace(b"\r\n", b""), f"{name} must use Windows line endings")
            raw.decode("ascii")  # non-ASCII text can break cmd.exe
        start = (self.ROOT / "start.bat").read_text()
        self.assertIn("setup.bat", start)
        self.assertIn("run_server.py", start)
        self.assertIn("setup_local.py", (self.ROOT / "setup.bat").read_text())
        for name in ("setup.bat", "setup_local.py", "run_server.py", "requirements.txt", "manage.py"):
            self.assertTrue((self.ROOT / name).exists(), name)

    def test_setup_state_and_virtualenv_are_not_committed(self):
        ignore = (self.ROOT / ".gitignore").read_text()
        for entry in (".setup_done", "venv/", "db.sqlite3"):
            self.assertIn(entry, ignore)
