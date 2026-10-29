"""Tests for the load_institution_data command."""
import re
from io import StringIO
from pathlib import Path

from django.apps import apps
from django.core.management import call_command
from django.test import TestCase

from apps.academics.management.commands import load_institution_data as cmd
from apps.academics.models import AcademicYear, Course, Enrolment, LecturerProfile, Programme, Semester, StudentProfile
from apps.accounts.models import AuditLog, User
from apps.research.models import Measurement, OutcomeDefinition, Participant, ResearchStudy
from apps.timetables.models import Venue

ROOT = Path(__file__).resolve().parents[2]


def run(*args):
    out = StringIO()
    call_command("load_institution_data", *args, stdout=out)
    return out.getvalue()


class InstitutionDataTests(TestCase):
    def test_loads_the_verified_programmes(self):
        run()
        expected = {code: (name, years) for code, name, years in cmd.PROGRAMMES}
        self.assertEqual(set(Programme.objects.values_list("code", flat=True)), set(expected))
        for p in Programme.objects.all():
            self.assertEqual((p.name, p.duration_years), expected[p.code])
            self.assertTrue(p.is_active)
            p.full_clean()  # passes the model's own validation

    def test_running_again_adds_nothing_and_never_overwrites_edits(self):
        run()
        Programme.objects.filter(code="BIT").update(name="Edited by an administrator", duration_years=4)
        ResearchStudy.objects.update(title="Edited title")
        counts = (Programme.objects.count(), ResearchStudy.objects.count(), OutcomeDefinition.objects.count())
        output = run()
        self.assertEqual(counts, (Programme.objects.count(), ResearchStudy.objects.count(), OutcomeDefinition.objects.count()))
        self.assertIn("0 added", output)
        bit = Programme.objects.get(code="BIT")
        self.assertEqual((bit.name, bit.duration_years), ("Edited by an administrator", 4))
        self.assertEqual(ResearchStudy.objects.get().title, "Edited title")

    def test_existing_programme_with_same_code_is_left_alone(self):
        Programme.objects.create(code="BBA", name="Locally named programme", duration_years=3)
        run()
        self.assertEqual(Programme.objects.get(code="BBA").name, "Locally named programme")
        self.assertEqual(Programme.objects.count(), len(cmd.PROGRAMMES))

    def test_study_profile_uses_the_proposal_title_and_claims_no_approval_or_dates(self):
        run()
        study = ResearchStudy.objects.get()
        self.assertEqual(study.title, cmd.STUDY_TITLE)
        self.assertIn("Biharwe Division, Mbarara City", study.title)
        self.assertEqual((study.population_size, study.target_sample_size, study.target_intervention, study.target_control,
                          study.intervention_weeks), (350, 156, 78, 78, 8))
        self.assertEqual((study.status, study.ethics_status, study.ethics_reference), ("planning", "not_recorded", ""))
        self.assertTrue(study.is_active)
        for field in ("baseline_start", "baseline_end", "intervention_start", "intervention_end"):
            self.assertIsNone(getattr(study, field), field)  # no dates are assumed
        self.assertEqual(OutcomeDefinition.objects.filter(study=study).count(), 4)

    def test_skip_study_loads_programmes_only(self):
        run("--skip-study")
        self.assertEqual(Programme.objects.count(), len(cmd.PROGRAMMES))
        self.assertFalse(ResearchStudy.objects.exists())

    def test_existing_study_is_never_replaced(self):
        mine = ResearchStudy.objects.create(title="A study already set up", is_active=True)
        run()
        self.assertEqual(list(ResearchStudy.objects.values_list("pk", flat=True)), [mine.pk])

    def test_no_people_calendar_or_collected_data_is_ever_created(self):
        run()
        for model in (User, StudentProfile, LecturerProfile, Enrolment, Course, AcademicYear, Semester, Venue, Participant, Measurement):
            self.assertEqual(model.objects.count(), 0, model.__name__)
        for label in ("attendance.AttendanceRecord", "performance.Assignment", "performance.Submission", "performance.Assessment", "performance.AssessmentResult",
                      "questionnaires.Questionnaire", "questionnaires.Response", "questionnaires.Answer"):
            self.assertEqual(apps.get_model(label).objects.count(), 0, label)

    def test_loading_is_written_to_the_audit_log_once(self):
        run()
        run()
        self.assertEqual(AuditLog.objects.filter(action="institution_data_loaded").count(), 1)

    def test_output_says_what_still_has_to_be_entered(self):
        output = run()
        for item in ("academic years and semesters", "courses", "venues", "students"):
            self.assertIn(item, output)

    def test_setup_script_loads_the_data(self):
        self.assertIn("load_institution_data", (ROOT / "setup_local.py").read_text(encoding="utf-8"))


class FreshInstallPagesTests(TestCase):
    """A newly installed system (study profile loaded, no participants or records yet) must open cleanly."""

    def test_researcher_pages_open_and_say_there_is_not_enough_data(self):
        from django.urls import reverse
        from apps.academics.tests import PW, make_user
        from apps.accounts.models import Role
        run()
        researcher = make_user("res_fresh", Role.RESEARCHER)
        self.client.login(username=researcher.username, password=PW)
        study = ResearchStudy.objects.get()
        for url in (reverse("research:study_detail", args=[study.pk]), reverse("research:outcome_list"),
                    reverse("research:participant_list"), reverse("analytics:dashboard"), reverse("analytics:analysis"),
                    reverse("analytics:exports"), reverse("analytics:dictionary")):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get(reverse("research:study_detail", args=[study.pk])), "Biharwe Division, Mbarara City")

    def test_administrator_can_open_programme_list_with_loaded_programmes(self):
        from django.urls import reverse
        from apps.academics.tests import PW, make_user
        from apps.accounts.models import Role
        run()
        admin = make_user("adm_fresh", Role.ADMIN)
        self.client.login(username=admin.username, password=PW)
        response = self.client.get(reverse("academics:programme_list"))
        self.assertContains(response, "Bachelor of Information Technology")
        self.assertContains(response, "BTHM")


class WordingTests(TestCase):
    """The institution data files must read as real configuration, not as sample content."""

    FILES = ["apps/academics/management/commands/load_institution_data.py", "docs/INSTITUTION_DATA.md"]
    BANNED = re.compile(r"\b(demo|demonstration|synthetic|prototype|dummy|fake|mock|sample data|placeholder)\b", re.I)

    def test_no_banned_wording_in_new_files(self):
        for name in self.FILES:
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIsNone(self.BANNED.search(text), f"{name}: {self.BANNED.search(text) and self.BANNED.search(text).group(0)}")
