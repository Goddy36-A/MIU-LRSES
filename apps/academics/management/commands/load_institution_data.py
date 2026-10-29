"""Load the institution's verifiable reference data.

What is loaded
  * Programmes: Metropolitan International University programmes that have an official abbreviation and a
    stated three-year duration on the university's own website (miu.ac.ug, pages checked 30 October 2026).
  * The research study profile for this project, using the title and planning figures from the research
    proposal, plus the standard outcome definitions (editable afterwards).

What is deliberately NOT loaded (enter these through the application, from the Academic Registrar's records)
  * Academic years and semesters. MIU admits in several intakes (January, May and August/September) and a
    verifiable semester calendar was not found, so no dates are assumed.
  * Course units and course codes, lecture venues, lecturers, students, enrolments.
  * Attendance, marks, research participants, measurements or questionnaire responses. These are collected
    data and must only ever come from real records.

Safe to run repeatedly: existing rows are never changed or duplicated.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.academics.models import Programme
from apps.accounts.audit import log_action

# (code, name, duration in years) - names and abbreviations as published on miu.ac.ug/programmes and the
# faculty pages. The site is not perfectly consistent (for example "Tourism and Hotel Management" on the
# programmes page and "Tourism and Hospitality Management" on a faculty page); the wording on the page that
# carries the official abbreviation is used. Administrators can edit any programme afterwards.
PROGRAMMES = [
    ("BBA", "Bachelor of Business Administration", 3),
    ("BIT", "Bachelor of Information Technology", 3),
    ("BSW", "Bachelor of Social Work and Social Administration", 3),
    ("BCOM", "Bachelor of Commerce", 3),
    ("BPAM", "Bachelor of Public Administration and Management", 3),
    ("BJM", "Bachelor of Journalism and Media Studies", 3),
    ("BTHM", "Bachelor of Tourism and Hotel Management", 3),
]

STUDY_TITLE = ("Evaluating the Impact of Lecture Reminder Systems on Student Engagement and Academic Performance: "
               "A Case Study of Metropolitan International University, Biharwe Division, Mbarara City.")
STUDY_DESCRIPTION = (
    "Evaluates whether lecture reminders affect student lecture attendance, timely assignment submission, "
    "academic performance, engagement with reminders, and students' acceptance and perceived usefulness of the "
    "system. Setting: Metropolitan International University, Mbarara Campus, Biharwe Division. "
    "The participant numbers and the eight-week intervention length are planning figures from the research "
    "proposal; they are not records of recruitment.")


class Command(BaseCommand):
    help = "Load MIU programmes and the research study profile. Safe to run again; changes nothing that already exists."

    def add_arguments(self, parser):
        parser.add_argument("--skip-study", action="store_true", help="Load programmes only.")

    @transaction.atomic
    def handle(self, *args, **options):
        created = []
        for code, name, years in PROGRAMMES:
            _obj, was_created = Programme.objects.get_or_create(code=code, defaults={"name": name, "duration_years": years})
            if was_created:
                created.append(code)
        self.stdout.write(f"Programmes: {len(created)} added, {len(PROGRAMMES) - len(created)} already present.")

        study_note = "skipped (--skip-study)"
        if not options["skip_study"]:
            from apps.research.models import ResearchStudy
            from apps.research.services import ensure_default_outcomes
            if ResearchStudy.objects.exists():
                study_note = "a study already exists - left untouched"
            else:
                study = ResearchStudy.objects.create(title=STUDY_TITLE, description=STUDY_DESCRIPTION, is_active=True)
                outcomes = ensure_default_outcomes(study)
                study_note = f"created (planning status, ethics not recorded) with {outcomes} outcome definitions"
        self.stdout.write(f"Research study: {study_note}.")

        if created or "created" in study_note:
            log_action("institution_data_loaded", target="programmes/study", details=f"programmes added: {', '.join(created) or 'none'}; study: {study_note}")
        self.stdout.write(
            "\nStill to be entered in the application from official records: academic years and semesters, courses, "
            "venues, lecturers, students and enrolments. Nothing about people, marks or attendance is loaded.")
