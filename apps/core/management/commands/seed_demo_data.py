"""Create (or remove) clearly labelled SYNTHETIC demonstration data.

Nothing created here is real: names, marks, numbers and lectures are invented for demonstrating
the application. Run `python manage.py seed_demo_data --password <pw>` and, when finished,
`python manage.py seed_demo_data --remove`.
"""
from datetime import date, datetime, time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import (AcademicYear, Course, CourseOffering, Enrolment, LecturerProfile, Programme,
                                   Semester, StudentProfile)
from apps.accounts.models import Role, User
from apps.timetables import services
from apps.timetables.models import LectureSession, Venue

PREFIX = "demo_"
YEAR_NAME = "DEMO 2026/2027"
PROGRAMME_CODE = "DEMO-IT"
VENUES = ["DEMO Hall A", "DEMO Lab 1"]
COURSES = [("DEMO101", "SYNTHETIC Introduction to Computing"), ("DEMO102", "SYNTHETIC Programming Basics"),
           ("DEMO103", "SYNTHETIC Databases")]
N_STUDENTS = 8


class Command(BaseCommand):
    help = "Create or remove clearly labelled synthetic demonstration data."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password to set on all demo accounts (required when creating).")
        parser.add_argument("--remove", action="store_true", help="Delete all demo data created by this command.")

    def handle(self, *args, **opts):
        if opts["remove"]:
            return self.remove()
        if not opts["password"]:
            raise CommandError("Provide --password. Demo accounts get this password; use it for local demonstrations only.")
        self.create(opts["password"])

    # -- create ------------------------------------------------------------
    @transaction.atomic
    def create(self, password):
        today = timezone.localdate()
        year, _ = AcademicYear.objects.get_or_create(
            name=YEAR_NAME, defaults={"start_date": today - timedelta(days=60), "end_date": today + timedelta(days=300)})
        semester, _ = Semester.objects.get_or_create(
            academic_year=year, number=1, defaults={"start_date": today - timedelta(days=30), "end_date": today + timedelta(days=90)})
        programme, _ = Programme.objects.get_or_create(code=PROGRAMME_CODE, defaults={"name": "SYNTHETIC DEMO Programme"})
        venues = [Venue.objects.get_or_create(name=n, defaults={"capacity": 60})[0] for n in VENUES]

        lecturers = []
        for i in (1, 2):
            user = self._user(f"{PREFIX}lecturer{i}", Role.LECTURER, f"Lecturer{i}", password)
            lecturers.append(LecturerProfile.objects.get_or_create(user=user, defaults={"staff_number": f"DEMO-L{i}"})[0])
        students = []
        for i in range(1, N_STUDENTS + 1):
            user = self._user(f"{PREFIX}student{i:02d}", Role.STUDENT, f"Student{i:02d}", password)
            students.append(StudentProfile.objects.get_or_create(
                user=user, defaults={"registration_number": f"DEMO-S{i:03d}", "programme": programme})[0])
        self._user(f"{PREFIX}researcher", Role.RESEARCHER, "Researcher", password)

        offerings = []
        for idx, (code, title) in enumerate(COURSES):
            course, _ = Course.objects.get_or_create(code=code, defaults={"title": title, "programme": programme})
            offering, _ = CourseOffering.objects.get_or_create(course=course, semester=semester)
            offering.lecturers.add(lecturers[idx % 2])
            offerings.append(offering)
            for st in students:
                Enrolment.objects.get_or_create(student=st, offering=offering)

        created = 0
        start_day = today + timedelta(days=1)
        for day_offset in range(0, 14):
            day = start_day + timedelta(days=day_offset)
            if day.weekday() > 4:
                continue
            for idx, offering in enumerate(offerings):  # one 2-hour slot per course per day, no overlaps
                start = timezone.make_aware(datetime.combine(day, time(8 + idx * 3, 0)))
                end = start + timedelta(hours=2)
                if LectureSession.objects.filter(offering=offering, start_at=start).exists():
                    continue
                session = LectureSession(offering=offering, lecturer=offering.lecturers.first(), venue=venues[idx % 2],
                                         start_at=start, end_at=end, topic="SYNTHETIC demo lecture")
                session.full_clean()
                services.create_session(session, None)
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f"Synthetic demo data ready: {len(students)} students, {len(lecturers)} lecturers, 1 researcher, "
            f"{len(offerings)} offerings, {created} new lectures. Usernames start with '{PREFIX}'. "
            "All of this is invented for demonstration; remove it with --remove."))

    def _user(self, username, role, last_name, password):
        user, created = User.objects.get_or_create(username=username, defaults={
            "role": role, "first_name": "Demo", "last_name": last_name, "email": f"{username}@example.invalid"})
        if created:
            user.set_password(password)
            user.save()
        return user

    # -- remove ------------------------------------------------------------
    @transaction.atomic
    def remove(self):
        offerings = CourseOffering.objects.filter(course__code__in=[c for c, _ in COURSES], semester__academic_year__name=YEAR_NAME)
        LectureSession.objects.filter(offering__in=offerings).delete()
        offerings.delete()
        Course.objects.filter(code__in=[c for c, _ in COURSES]).delete()
        Semester.objects.filter(academic_year__name=YEAR_NAME).delete()
        AcademicYear.objects.filter(name=YEAR_NAME).delete()
        Venue.objects.filter(name__in=VENUES).delete()
        StudentProfile.objects.filter(user__username__startswith=PREFIX).delete()
        LecturerProfile.objects.filter(user__username__startswith=PREFIX).delete()
        Programme.objects.filter(code=PROGRAMME_CODE).delete()
        User.objects.filter(username__startswith=PREFIX).delete()
        self.stdout.write(self.style.SUCCESS("Synthetic demo data removed."))
