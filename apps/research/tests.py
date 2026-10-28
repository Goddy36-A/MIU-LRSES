"""Phase 5 tests: research study settings, participants, consent, allocation, control-group reminder exclusion,
measurements, calculations from system records, permissions and data integrity.

All data below is synthetic test fixture data. Nothing here is a research finding.
Dates are relative to today so the suite never depends on the calendar.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Group as AuthGroup
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import Enrolment, StudentProfile, StudentStatus
from apps.academics.tests import PW, make_user
from apps.accounts.models import AuditLog, Role
from apps.attendance import services as attendance_services
from apps.attendance.tests import AttendanceFixtureMixin
from apps.performance.models import Assessment, AssessmentResult, Assignment, Submission
from apps.reminders import services as reminder_services
from apps.reminders.models import Notification, NotificationKind, NotificationStatus
from apps.timetables import services as tt
from apps.timetables.tests import at

from . import services
from .forms import ParticipantUpdateForm, ResearchStudyForm
from .models import (Allocation, AllocationMethod, ConsentStatus, Eligibility, Group, Measurement, MeasurementRevision,
                     MeasurementStatus, OutcomeDefinition, Participant, Period, ResearchStudy, StudyStatus)

TODAY = timezone.localdate()


def days(n):
    return TODAY + timedelta(days=n)


class ResearchFixtureMixin(AttendanceFixtureMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.study = ResearchStudy.objects.create(
            title="Synthetic test study", is_active=True, status=StudyStatus.RECRUITING,
            baseline_start=days(-60), baseline_end=days(-31), intervention_start=days(-30), intervention_weeks=2)
        services.ensure_default_outcomes(cls.study)
        cls.attendance_outcome = cls.study.outcomes.get(code="attendance-rate")
        cls.punctuality_outcome = cls.study.outcomes.get(code="punctuality-rate")
        cls.assessment_outcome = cls.study.outcomes.get(code="assessment-score")
        cls.reminder_outcome = cls.study.outcomes.get(code="reminder-read-rate")

    def register(self, student, **kw):
        return services.register_participant(self.study, student, self.researcher, **kw)

    def enrol(self, student, group=""):
        """Register, make eligible, record consent and enrol; optionally allocate (synthetic fixture shortcut)."""
        p = self.register(student, eligibility=Eligibility.ELIGIBLE)
        p.consent_status, p.consent_date, p.enrolled_on = ConsentStatus.GIVEN, days(-65), days(-64)
        p.save()
        if group:
            services.allocate_participant(p, self.researcher, group=group, method=AllocationMethod.MANUAL,
                                          procedure="Synthetic test allocation.")
        return Participant.objects.get(pk=p.pk)


# ---- Study settings -------------------------------------------------------------------------------------------------
class StudySettingsTests(ResearchFixtureMixin, TestCase):
    def test_planning_defaults_match_the_proposal_and_are_just_settings(self):
        s = ResearchStudy.objects.create(title="Defaults")
        self.assertEqual((s.population_size, s.target_sample_size, s.target_intervention, s.target_control, s.intervention_weeks),
                         (350, 156, 78, 78, 8))
        self.assertEqual(s.significance_level, Decimal("0.05"))
        self.assertEqual(Participant.objects.filter(study=s).count(), 0)

    def test_group_targets_must_add_up_to_the_sample(self):
        s = ResearchStudy(title="x", target_sample_size=156, target_intervention=80, target_control=78)
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_sample_cannot_exceed_population(self):
        s = ResearchStudy(title="x", population_size=100, target_sample_size=156, target_intervention=78, target_control=78)
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_protocol_changes_are_allowed(self):
        form = ResearchStudyForm({"title": "x", "status": "planning", "ethics_status": "not_recorded", "population_size": 400,
                                  "target_sample_size": 100, "target_intervention": 50, "target_control": 50, "intervention_weeks": 6,
                                  "eligible_year_min": 1, "eligible_year_max": 2, "significance_level": "0.050"})
        self.assertTrue(form.is_valid(), form.errors)

    def test_only_one_active_study(self):
        other = ResearchStudy.objects.create(title="Other", is_active=True)
        self.study.refresh_from_db()
        self.assertFalse(self.study.is_active)
        self.assertEqual(services.get_active_study(), other)

    def test_baseline_must_end_before_intervention_starts(self):
        s = ResearchStudy(title="x", baseline_start=days(-10), baseline_end=days(5), intervention_start=days(1))
        with self.assertRaises(ValidationError):
            s.full_clean()

    def test_planned_end_is_start_plus_configured_weeks(self):
        s = ResearchStudy(title="x", intervention_start=days(0), intervention_weeks=8)
        self.assertEqual(s.planned_intervention_end, days(0) + timedelta(weeks=8) - timedelta(days=1))
        s.intervention_weeks = 6
        self.assertEqual(s.planned_intervention_end, days(0) + timedelta(weeks=6) - timedelta(days=1))

    def test_actual_end_overrides_planned_end_and_nothing_is_assumed_without_a_start(self):
        s = ResearchStudy(title="x", intervention_start=days(0), intervention_end=days(10))
        self.assertEqual(s.post_window, (days(0), days(10)))
        self.assertIsNone(ResearchStudy(title="y").post_window)
        self.assertIsNone(ResearchStudy(title="y").baseline_window)

    def test_ethics_approval_needs_a_reference_and_defaults_to_not_recorded(self):
        self.assertEqual(ResearchStudy(title="x").ethics_status, "not_recorded")
        with self.assertRaises(ValidationError):
            ResearchStudy(title="x", ethics_status="approved").full_clean()

    def test_creating_a_study_seeds_standard_outcomes_but_no_participants(self):
        self.client.login(username=self.researcher.username, password=PW)
        r = self.client.post(reverse("research:study_add"), {
            "title": "Via form", "status": "planning", "ethics_status": "not_recorded", "population_size": 350, "target_sample_size": 156,
            "target_intervention": 78, "target_control": 78, "intervention_weeks": 8, "eligible_year_min": 1, "eligible_year_max": 2,
            "significance_level": "0.050"})
        self.assertEqual(r.status_code, 302)
        s = ResearchStudy.objects.get(title="Via form")
        self.assertEqual(s.outcomes.count(), 4)
        self.assertEqual(s.participants.count(), 0)
        self.assertEqual(s.created_by, self.researcher)


# ---- Participants, consent, enrolment ----------------------------------------------------------------------------------
class ParticipantTests(ResearchFixtureMixin, TestCase):
    def test_students_are_never_enrolled_automatically(self):
        self.assertEqual(StudentProfile.objects.count(), 2)
        self.assertEqual(Participant.objects.count(), 0)

    def test_registration_creates_unenrolled_participant_with_unique_anonymous_code(self):
        p1, p2 = self.register(self.student), self.register(self.student2)
        for p in (p1, p2):
            self.assertRegex(p.research_code, r"^P-[A-Z2-9]{6}$")
            self.assertFalse(p.is_enrolled)
            self.assertEqual(p.stage, "Registered")
            self.assertEqual(p.group, "")
            self.assertTrue(p.events.filter(event="registered").exists())
        self.assertNotEqual(p1.research_code, p2.research_code)
        self.assertNotIn(self.student.registration_number, p1.research_code)

    def test_same_student_cannot_be_registered_twice_in_a_study(self):
        self.register(self.student)
        with self.assertRaises(ValidationError):
            self.register(self.student)

    def test_database_blocks_duplicate_participants(self):
        self.register(self.student)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Participant.objects.create(study=self.study, student=self.student)

    def test_only_active_students_can_be_registered(self):
        self.student.status = StudentStatus.SUSPENDED
        self.student.save()
        with self.assertRaises(ValidationError):
            self.register(self.student)

    def test_audit_entry_uses_code_not_name_and_no_group(self):
        p = self.register(self.student)
        entry = AuditLog.objects.get(action="participant_registered")
        self.assertEqual(entry.target, p.research_code)
        self.assertNotIn(self.student.registration_number, entry.target + entry.details)

    def test_consent_given_requires_a_date_that_is_not_in_the_future(self):
        p = self.register(self.student)
        p.consent_status = ConsentStatus.GIVEN
        with self.assertRaises(ValidationError):
            p.full_clean()
        p.consent_date = days(1)
        with self.assertRaises(ValidationError):
            p.full_clean()
        p.consent_date = days(-1)
        p.full_clean()

    def test_enrolment_needs_eligibility_and_consent_in_the_right_order(self):
        p = self.register(self.student)
        p.enrolled_on = days(-1)
        with self.assertRaises(ValidationError):
            p.full_clean()                      # not eligible, no consent
        p.eligibility = Eligibility.ELIGIBLE
        with self.assertRaises(ValidationError):
            p.full_clean()                      # no consent yet
        p.consent_status, p.consent_date = ConsentStatus.GIVEN, days(-1)
        p.enrolled_on = days(-2)
        with self.assertRaises(ValidationError):
            p.full_clean()                      # enrolled before consent
        p.enrolled_on = days(-1)
        p.full_clean()
        self.assertTrue(p.is_enrolled)

    def test_stage_labels(self):
        p = self.enrol(self.student)
        self.assertEqual(p.stage, "Enrolled")
        services.allocate_participant(p, self.researcher, group=Group.CONTROL, method=AllocationMethod.MANUAL, procedure="x")
        p.refresh_from_db()
        self.assertEqual(p.stage, "Allocated")

    def test_update_form_records_history_and_audit(self):
        self.client.login(username=self.researcher.username, password=PW)
        p = self.register(self.student)
        r = self.client.post(reverse("research:participant_edit", args=[p.pk]), {
            "eligibility": "eligible", "eligibility_notes": "Year 1", "consent_status": "given", "consent_date": days(-1).isoformat(),
            "consent_reference": "F-001", "enrolled_on": days(-1).isoformat(), "notes": ""})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertTrue(p.is_enrolled)
        events = set(p.events.values_list("event", flat=True))
        self.assertTrue({"eligibility_changed", "consent_changed", "enrolment_changed"} <= events)

    def test_allocated_participant_cannot_lose_eligibility_or_consent_by_editing(self):
        p = self.enrol(self.student, Group.INTERVENTION)
        form = ParticipantUpdateForm({"eligibility": "eligible", "consent_status": "declined", "enrolled_on": "", "eligibility_notes": "",
                                      "consent_date": "", "consent_reference": "", "notes": ""}, instance=p)
        self.assertFalse(form.is_valid())

    def test_year_criterion_flag(self):
        p = self.register(self.student)
        self.assertTrue(p.year_matches_criterion)
        self.student.year_of_study = 3
        self.student.save()
        self.assertFalse(Participant.objects.get(pk=p.pk).year_matches_criterion)


# ---- Allocation ------------------------------------------------------------------------------------------------------------
class AllocationTests(ResearchFixtureMixin, TestCase):
    def allocate(self, p, group, **kw):
        args = dict(group=group, method=AllocationMethod.EXTERNAL, procedure="Random-number list prepared by the principal researcher.")
        args.update(kw)
        return services.allocate_participant(p, self.researcher, **args)

    def test_nothing_allocates_automatically(self):
        p = self.enrol(self.student)
        services.plan_measurements(self.study, self.researcher)
        self.assertEqual(Participant.objects.get(pk=p.pk).group, "")
        self.assertEqual(Allocation.objects.count(), 0)

    def test_allocation_requires_enrolment(self):
        p = self.register(self.student)
        with self.assertRaises(ValidationError):
            self.allocate(p, Group.CONTROL)

    def test_allocation_requires_a_documented_procedure(self):
        p = self.enrol(self.student)
        with self.assertRaises(ValidationError):
            self.allocate(p, Group.CONTROL, procedure="   ")
        self.assertEqual(Allocation.objects.count(), 0)

    def test_allocation_documents_how_the_group_was_decided(self):
        p = self.enrol(self.student)
        a = self.allocate(p, Group.INTERVENTION)
        p.refresh_from_db()
        self.assertEqual(p.group, Group.INTERVENTION)
        self.assertEqual((a.method, a.allocated_by, a.is_reallocation), (AllocationMethod.EXTERNAL, self.researcher, False))
        self.assertIn("Random-number list", a.procedure)

    def test_audit_log_does_not_reveal_the_group(self):
        p = self.enrol(self.student)
        self.allocate(p, Group.CONTROL)
        entry = AuditLog.objects.get(action="participant_allocated")
        self.assertNotIn("control", (entry.target + entry.details).lower())

    def test_reallocation_needs_reason_and_keeps_history(self):
        p = self.enrol(self.student, Group.INTERVENTION)
        with self.assertRaises(ValidationError):
            self.allocate(p, Group.CONTROL)
        with self.assertRaises(ValidationError):
            self.allocate(p, Group.INTERVENTION, reason="same group")
        self.allocate(p, Group.CONTROL, reason="Protocol deviation: moved after timetable clash.")
        p.refresh_from_db()
        self.assertEqual(p.group, Group.CONTROL)
        self.assertEqual(p.allocations.count(), 2)
        self.assertTrue(p.allocations.first().is_reallocation)

    def test_reallocation_blocked_after_post_intervention_data_exist(self):
        p = self.enrol(self.student, Group.INTERVENTION)
        m = Measurement.objects.create(participant=p, outcome=self.attendance_outcome, period=Period.POST)
        services.record_measurement(m, self.researcher, status="collected", value=Decimal("80"), collected_on=days(-1))
        with self.assertRaises(ValidationError):
            self.allocate(p, Group.CONTROL, reason="late change")

    def test_withdrawn_participant_cannot_be_allocated(self):
        p = self.enrol(self.student)
        services.withdraw_participant(p, self.researcher, withdrawn_on=days(0), data_handling="retain")
        with self.assertRaises(ValidationError):
            self.allocate(Participant.objects.get(pk=p.pk), Group.CONTROL)

    def test_withdrawal_records_status_handling_and_history(self):
        p = self.enrol(self.student, Group.CONTROL)
        with self.assertRaises(ValidationError):
            services.withdraw_participant(p, self.researcher, withdrawn_on=days(1), data_handling="retain")
        with self.assertRaises(ValidationError):
            services.withdraw_participant(p, self.researcher, withdrawn_on=days(0), data_handling="")
        services.withdraw_participant(p, self.researcher, withdrawn_on=days(0), data_handling="exclude", reason="")
        p.refresh_from_db()
        self.assertEqual((p.stage, p.withdrawal_data_handling, p.is_enrolled), ("Withdrawn", "exclude", False))
        self.assertTrue(p.events.filter(event="withdrawn").exists())
        with self.assertRaises(ValidationError):
            services.withdraw_participant(p, self.researcher, withdrawn_on=days(0), data_handling="exclude")


# ---- Control group and reminders ------------------------------------------------------------------------------------------
NOW = at(2, 8, 0)


class ControlGroupReminderTests(ResearchFixtureMixin, TestCase):
    """The control group must not receive intervention reminders; everyone else still does."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from apps.accounts.models import Role as R
        cls.stu3_user = make_user("stu3", R.STUDENT)
        cls.student3 = StudentProfile.objects.create(user=cls.stu3_user, registration_number="S003", programme=cls.programme)
        Enrolment.objects.create(student=cls.student3, offering=cls.offering, enrolled_on=days(-60))

    def lecture(self):
        return self.make_session(start=at(3, 9), end=at(3, 11))   # 25 hours after NOW

    def reminders_for(self, user, session):
        return Notification.objects.filter(recipient=user, session=session, kind=NotificationKind.REMINDER)

    def test_control_gets_no_reminders_intervention_and_non_participants_do(self):
        self.enrol(self.student, Group.CONTROL)
        self.enrol(self.student2, Group.INTERVENTION)
        s = self.lecture()
        reminder_services.sync_session_reminders(s, now=NOW)
        self.assertEqual(self.reminders_for(self.stu_user, s).count(), 0)
        self.assertGreater(self.reminders_for(self.stu2_user, s).count(), 0)
        self.assertGreater(self.reminders_for(self.stu3_user, s).count(), 0)      # not a participant: unaffected

    def test_unallocated_or_unenrolled_participants_are_not_restricted(self):
        self.enrol(self.student)                 # enrolled, not yet allocated
        self.register(self.student2)             # registered only
        s = self.lecture()
        reminder_services.sync_session_reminders(s, now=NOW)
        self.assertGreater(self.reminders_for(self.stu_user, s).count(), 0)
        self.assertGreater(self.reminders_for(self.stu2_user, s).count(), 0)

    def test_allocating_to_control_cancels_reminders_already_scheduled(self):
        p = self.enrol(self.student)
        s = self.lecture()
        reminder_services.sync_session_reminders(s, now=NOW)
        pending = self.reminders_for(self.stu_user, s).filter(status=NotificationStatus.PENDING)
        self.assertGreater(pending.count(), 0)
        services.allocate_participant(p, self.researcher, group=Group.CONTROL, method=AllocationMethod.MANUAL, procedure="x")
        self.assertEqual(self.reminders_for(self.stu_user, s).filter(status=NotificationStatus.PENDING).count(), 0)
        self.assertTrue(self.reminders_for(self.stu_user, s).filter(status=NotificationStatus.CANCELLED).exists())

    def test_processing_never_delivers_to_control_even_if_a_reminder_slipped_through(self):
        s = self.lecture()
        reminder_services.sync_session_reminders(s, now=NOW)           # student 1 has pending reminders
        p = Participant.objects.create(study=self.study, student=self.student, eligibility=Eligibility.ELIGIBLE,
                                       consent_status=ConsentStatus.GIVEN, consent_date=days(-2), enrolled_on=days(-1), group=Group.CONTROL)
        run = reminder_services.process_due_reminders(now=s.start_at - timedelta(minutes=30))
        self.assertEqual(self.reminders_for(self.stu_user, s).filter(status=NotificationStatus.DELIVERED).count(), 0)
        self.assertGreater(self.reminders_for(self.stu2_user, s).filter(status=NotificationStatus.DELIVERED).count(), 0)
        self.assertEqual(p.group, Group.CONTROL)
        self.assertGreater(run.delivered, 0)

    def test_schedule_change_notices_still_reach_control_students(self):
        self.enrol(self.student, Group.CONTROL)
        s = self.lecture()
        reminder_services.sync_session_reminders(s, now=NOW)
        tt.cancel_session(s, self.lec_user, reason="Lecturer unwell")
        self.assertTrue(Notification.objects.filter(recipient=self.stu_user, session=s, kind=NotificationKind.SCHEDULE_CHANGE).exists())
        self.assertEqual(self.reminders_for(self.stu_user, s).count(), 0)

    def test_withdrawn_control_participant_receives_reminders_again(self):
        p = self.enrol(self.student, Group.CONTROL)
        s = self.lecture()
        reminder_services.sync_session_reminders(s, now=NOW)
        self.assertEqual(self.reminders_for(self.stu_user, s).count(), 0)
        services.withdraw_participant(p, self.researcher, withdrawn_on=days(0), data_handling="retain")
        reminder_services.sync_session_reminders(s, now=NOW)
        self.assertGreater(self.reminders_for(self.stu_user, s).count(), 0)

    def test_closing_the_study_lifts_the_restriction(self):
        self.enrol(self.student, Group.CONTROL)
        self.study.status = StudyStatus.CLOSED
        self.study.save()
        s = self.lecture()
        reminder_services.sync_session_reminders(s, now=NOW)
        self.assertGreater(self.reminders_for(self.stu_user, s).count(), 0)

    def test_moving_a_participant_to_intervention_restores_reminders(self):
        p = self.enrol(self.student, Group.CONTROL)
        s = self.lecture()
        reminder_services.sync_session_reminders(s, now=NOW)
        services.allocate_participant(p, self.researcher, group=Group.INTERVENTION, method=AllocationMethod.OTHER, procedure="y", reason="Protocol deviation")
        reminder_services.sync_session_reminders(s, now=NOW)
        self.assertGreater(self.reminders_for(self.stu_user, s).count(), 0)

    def test_restriction_holds_even_if_another_study_is_active(self):
        self.enrol(self.student, Group.CONTROL)
        ResearchStudy.objects.create(title="Another", is_active=True)
        s = self.lecture()
        reminder_services.sync_session_reminders(s, now=NOW)
        self.assertEqual(self.reminders_for(self.stu_user, s).count(), 0)


# ---- Planning and recording measurements ---------------------------------------------------------------------------------------
class MeasurementTests(ResearchFixtureMixin, TestCase):
    def setUp(self):
        self.p_int = self.enrol(self.student, Group.INTERVENTION)
        self.p_ctl = self.enrol(self.student2, Group.CONTROL)

    def row(self, p, outcome=None, period=Period.BASELINE):
        return Measurement.objects.get(participant=p, outcome=outcome or self.attendance_outcome, period=period)

    def test_planning_creates_empty_rows_only_for_enrolled_participants(self):
        stu3 = StudentProfile.objects.create(user=make_user("stu3", Role.STUDENT), registration_number="S003", programme=self.programme)
        self.register(stu3)                       # registered but not enrolled
        created = services.plan_measurements(self.study, self.researcher)
        # 3 two-period outcomes x 2 periods x 2 participants + 1 post-only, intervention-only outcome x 1 participant
        self.assertEqual(created, 13)
        self.assertFalse(Measurement.objects.filter(participant__student=stu3).exists())
        self.assertTrue(all(m.status == "planned" and m.value is None for m in Measurement.objects.all()))

    def test_intervention_only_outcome_is_not_planned_for_control(self):
        services.plan_measurements(self.study, self.researcher)
        self.assertFalse(Measurement.objects.filter(participant=self.p_ctl, outcome=self.reminder_outcome).exists())
        self.assertTrue(Measurement.objects.filter(participant=self.p_int, outcome=self.reminder_outcome, period=Period.POST).exists())
        self.assertFalse(Measurement.objects.filter(participant=self.p_int, outcome=self.reminder_outcome, period=Period.BASELINE).exists())

    def test_planning_is_idempotent(self):
        services.plan_measurements(self.study, self.researcher)
        self.assertEqual(services.plan_measurements(self.study, self.researcher), 0)

    def test_withdrawn_participants_get_no_new_planned_rows(self):
        services.withdraw_participant(self.p_ctl, self.researcher, withdrawn_on=days(0), data_handling="retain")
        services.plan_measurements(self.study, self.researcher)
        self.assertFalse(Measurement.objects.filter(participant=self.p_ctl).exists())

    def test_record_collected_value_and_history(self):
        services.plan_measurements(self.study, self.researcher)
        m = self.row(self.p_int)
        self.assertTrue(services.record_measurement(m, self.researcher, status="collected", value=Decimal("72.5"), collected_on=days(-3)))
        m.refresh_from_db()
        self.assertEqual((m.status, m.value, m.source, m.recorded_by), ("collected", Decimal("72.50"), "manual", self.researcher))
        self.assertEqual(m.revisions.count(), 1)

    def test_collected_needs_value_date_in_range_and_not_future(self):
        services.plan_measurements(self.study, self.researcher)
        m = self.row(self.p_int)
        bad = [dict(value=None, collected_on=days(-1)), dict(value=Decimal("50"), collected_on=None),
               dict(value=Decimal("101"), collected_on=days(-1)), dict(value=Decimal("-1"), collected_on=days(-1)),
               dict(value=Decimal("50"), collected_on=days(1))]
        for kw in bad:
            with self.assertRaises(ValidationError, msg=kw):
                services.record_measurement(m, self.researcher, status="collected", **kw)
        m.refresh_from_db()
        self.assertEqual((m.status, m.value), ("planned", None))

    def test_post_intervention_data_need_a_recorded_start_date(self):
        self.study.intervention_start = None
        self.study.save()
        services.plan_measurements(self.study, self.researcher)
        m = self.row(self.p_int, period=Period.POST)
        with self.assertRaises(ValidationError):
            services.record_measurement(m, self.researcher, status="collected", value=Decimal("60"), collected_on=days(-1))
        self.study.intervention_start = days(-10)
        self.study.save()
        m = Measurement.objects.get(pk=m.pk)
        with self.assertRaises(ValidationError):
            services.record_measurement(m, self.researcher, status="collected", value=Decimal("60"), collected_on=days(-11))
        services.record_measurement(Measurement.objects.get(pk=m.pk), self.researcher, status="collected", value=Decimal("60"), collected_on=days(-1))

    def test_missing_needs_a_reason_and_has_no_value(self):
        services.plan_measurements(self.study, self.researcher)
        m = self.row(self.p_int)
        with self.assertRaises(ValidationError):
            services.record_measurement(m, self.researcher, status="missing")
        services.record_measurement(m, self.researcher, status="missing", missing_reason="Participant absent on collection day", value=Decimal("5"))
        m.refresh_from_db()
        self.assertEqual((m.status, m.value), ("missing", None))

    def test_database_rejects_a_collected_row_without_a_value(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Measurement.objects.create(participant=self.p_int, outcome=self.attendance_outcome, period=Period.BASELINE, status="collected")

    def test_database_rejects_a_value_on_a_row_that_is_not_collected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Measurement.objects.create(participant=self.p_int, outcome=self.attendance_outcome, period=Period.BASELINE,
                                       status="planned", value=Decimal("10"))

    def test_one_measurement_per_participant_outcome_period(self):
        Measurement.objects.create(participant=self.p_int, outcome=self.attendance_outcome, period=Period.BASELINE)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Measurement.objects.create(participant=self.p_int, outcome=self.attendance_outcome, period=Period.BASELINE)

    def test_correction_needs_a_reason_and_keeps_the_original_value(self):
        services.plan_measurements(self.study, self.researcher)
        m = self.row(self.p_int)
        services.record_measurement(m, self.researcher, status="collected", value=Decimal("70"), collected_on=days(-3))
        with self.assertRaises(ValidationError):
            services.record_measurement(m, self.researcher, status="collected", value=Decimal("75"), collected_on=days(-3))
        m.refresh_from_db()
        self.assertEqual(m.value, Decimal("70.00"))
        services.record_measurement(m, self.researcher, status="collected", value=Decimal("75"), collected_on=days(-3), reason="Transcription error")
        m.refresh_from_db()
        self.assertEqual(m.value, Decimal("75.00"))
        rev = m.revisions.first()
        self.assertEqual((rev.old_value, rev.new_value, rev.reason), (Decimal("70.00"), Decimal("75.00"), "Transcription error"))
        self.assertEqual(m.revisions.count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="measurement_corrected").exists())

    def test_saving_identical_values_changes_nothing(self):
        services.plan_measurements(self.study, self.researcher)
        m = self.row(self.p_int)
        services.record_measurement(m, self.researcher, status="collected", value=Decimal("70"), collected_on=days(-3))
        self.assertFalse(services.record_measurement(m, self.researcher, status="collected", value=Decimal("70"), collected_on=days(-3)))
        self.assertEqual(m.revisions.count(), 1)

    def test_a_collected_measurement_cannot_be_turned_back_into_planned(self):
        services.plan_measurements(self.study, self.researcher)
        m = self.row(self.p_int)
        services.record_measurement(m, self.researcher, status="collected", value=Decimal("70"), collected_on=days(-3))
        with self.assertRaises(ValidationError):
            services.record_measurement(m, self.researcher, status="planned", reason="oops")

    def test_cannot_record_for_withdrawn_or_unenrolled_participants(self):
        services.plan_measurements(self.study, self.researcher)
        m = self.row(self.p_ctl)
        services.withdraw_participant(self.p_ctl, self.researcher, withdrawn_on=days(0), data_handling="retain")
        with self.assertRaises(ValidationError):
            services.record_measurement(m, self.researcher, status="collected", value=Decimal("70"), collected_on=days(-3))

    def test_intervention_only_outcome_rejects_control_values(self):
        m = Measurement.objects.create(participant=self.p_ctl, outcome=self.reminder_outcome, period=Period.POST)
        with self.assertRaises(ValidationError):
            services.record_measurement(m, self.researcher, status="collected", value=Decimal("50"), collected_on=days(-1))

    def test_display_states_distinguish_planned_not_yet_collected_collected_missing_and_withdrawn(self):
        services.plan_measurements(self.study, self.researcher)
        baseline = self.row(self.p_int)                  # baseline window ended 31 days ago, nothing collected
        self.assertEqual(services.display_state(baseline), "not_yet_collected")
        post = self.row(self.p_int, period=Period.POST)  # intervention window runs until days(-17): also ended
        self.study.intervention_weeks = 8
        self.study.save()
        post = Measurement.objects.get(pk=post.pk)
        self.assertEqual(services.display_state(post), "planned")
        services.record_measurement(baseline, self.researcher, status="collected", value=Decimal("70"), collected_on=days(-3))
        self.assertEqual(services.display_state(Measurement.objects.get(pk=baseline.pk)), "collected")
        other = self.row(self.p_int, self.punctuality_outcome)
        services.record_measurement(other, self.researcher, status="missing", missing_reason="No records")
        self.assertEqual(services.display_state(Measurement.objects.get(pk=other.pk)), "missing")
        services.withdraw_participant(self.p_ctl, self.researcher, withdrawn_on=days(0), data_handling="retain")
        withdrawn = self.row(self.p_ctl)                  # planned row of a participant who has since withdrawn
        self.assertEqual((withdrawn.status, services.display_state(withdrawn)), ("planned", "withdrawn"))


# ---- Calculations from system records ------------------------------------------------------------------------------------------
class CalculationTests(ResearchFixtureMixin, TestCase):
    """Values come only from existing attendance, submission, marks and reminder records. No data => no value."""

    def setUp(self):
        self.p = self.enrol(self.student, Group.INTERVENTION)
        services.plan_measurements(self.study, self.researcher)

    def m(self, outcome, period=Period.BASELINE):
        return Measurement.objects.get(participant=self.p, outcome=outcome, period=period)

    def calc(self, outcome, period=Period.BASELINE):
        return services.calculate_measurement(self.m(outcome, period), self.researcher)

    def test_attendance_baseline_uses_only_lectures_in_the_window(self):
        for ago, status in [(50, "present"), (45, "absent"), (40, "late"), (5, "absent")]:   # the last is outside the baseline window
            attendance_services.save_attendance(self.past_session(days_ago=ago), self.lec_user, {self.student.pk: status})
        self.assertTrue(self.calc(self.attendance_outcome))
        m = self.m(self.attendance_outcome)
        self.assertEqual((m.status, m.source, m.value), ("collected", "system", Decimal("66.70")))   # (present + late) / 3
        self.assertEqual(m.collected_on, TODAY)
        self.assertIn("Lectures held: 3", m.calculation_detail)

    def test_missing_attendance_records_are_not_treated_as_absences(self):
        attendance_services.save_attendance(self.past_session(days_ago=50), self.lec_user, {self.student.pk: "present"})
        self.past_session(days_ago=45)       # held, never recorded
        self.past_session(days_ago=40)       # held, never recorded
        self.calc(self.attendance_outcome)
        self.assertEqual(self.m(self.attendance_outcome).value, Decimal("100.00"))

    def test_no_data_means_no_value(self):
        self.past_session(days_ago=45)       # a lecture but no attendance record
        with self.assertRaises(ValidationError) as ctx:
            self.calc(self.attendance_outcome)
        self.assertIn("No attendance records", ctx.exception.messages[0])
        m = self.m(self.attendance_outcome)
        self.assertEqual((m.status, m.value), ("planned", None))
        self.assertEqual(m.revisions.count(), 0)

    def test_window_must_be_set_and_finished(self):
        self.study.baseline_end = days(0)
        self.study.save()
        with self.assertRaises(ValidationError) as ctx:
            self.calc(self.attendance_outcome)
        self.assertIn("has not finished", ctx.exception.messages[0])
        self.study.baseline_start = self.study.baseline_end = None
        self.study.save()
        with self.assertRaises(ValidationError) as ctx:
            self.calc(self.attendance_outcome)
        self.assertIn("baseline window", ctx.exception.messages[0])

    def test_records_of_non_consenting_or_withdrawn_participants_are_not_used(self):
        attendance_services.save_attendance(self.past_session(days_ago=50), self.lec_user, {self.student.pk: "present"})
        row = self.m(self.attendance_outcome)
        services.withdraw_participant(self.p, self.researcher, withdrawn_on=days(0), data_handling="exclude")
        with self.assertRaises(ValidationError):
            services.calculate_measurement(row, self.researcher)
        other = self.register(self.student2)           # registered, no consent, not enrolled
        with self.assertRaises(ValidationError):
            services.calculate_outcome(other, self.attendance_outcome, Period.BASELINE)

    def test_punctuality_counts_on_time_and_late_for_complete_records(self):
        a1 = Assignment.objects.create(offering=self.offering, title="A1", deadline=timezone.now() - timedelta(days=40), records_complete=True)
        a2 = Assignment.objects.create(offering=self.offering, title="A2", deadline=timezone.now() - timedelta(days=38), records_complete=True)
        a3 = Assignment.objects.create(offering=self.offering, title="A3", deadline=timezone.now() - timedelta(days=36), records_complete=False)
        Submission.objects.create(assignment=a1, student=self.student, status="submitted", submitted_at=a1.deadline - timedelta(hours=2))
        Submission.objects.create(assignment=a2, student=self.student, status="submitted", submitted_at=a2.deadline + timedelta(hours=2))
        self.calc(self.punctuality_outcome)
        m = self.m(self.punctuality_outcome)
        self.assertEqual(m.value, Decimal("50.00"))      # 1 on time of 2 counted; A3 awaits complete records and is not counted
        self.assertIn("awaiting complete records 1", m.calculation_detail)

    def test_assessment_score_is_mean_of_course_percentages_in_window(self):
        for title, when, marks in [("T1", days(-40), "60"), ("T2", days(-35), "80"), ("Outside", days(-5), "10")]:
            a = Assessment.objects.create(offering=self.offering, title=title, assessment_date=when, max_marks=100)
            AssessmentResult.objects.create(assessment=a, student=self.student, status="marked", marks=Decimal(marks))
        self.calc(self.assessment_outcome)
        self.assertEqual(self.m(self.assessment_outcome).value, Decimal("70.00"))

    def test_unmarked_work_is_never_counted_as_zero(self):
        a = Assessment.objects.create(offering=self.offering, title="T1", assessment_date=days(-40), max_marks=100)
        AssessmentResult.objects.create(assessment=a, student=self.student, status="absent")
        with self.assertRaises(ValidationError):
            self.calc(self.assessment_outcome)

    def test_reminder_read_rate_uses_delivered_reminders_in_the_post_window(self):
        s = self.past_session(days_ago=20)
        for read in (True, False):
            Notification.objects.create(recipient=self.stu_user, session=s, kind=NotificationKind.REMINDER, title="r", message="r",
                                        scheduled_for=timezone.now() - timedelta(days=21), status=NotificationStatus.DELIVERED,
                                        delivered_at=timezone.now() - timedelta(days=20), read_at=timezone.now() if read else None)
        self.study.intervention_weeks = 2          # post window: days(-30) .. days(-17)
        self.study.save()
        self.calc(self.reminder_outcome, Period.POST)
        self.assertEqual(self.m(self.reminder_outcome, Period.POST).value, Decimal("50.00"))

    def test_reminder_rate_not_calculable_without_delivered_reminders(self):
        with self.assertRaises(ValidationError):
            self.calc(self.reminder_outcome, Period.POST)

    def test_recalculation_adds_a_revision_and_keeps_the_old_value(self):
        attendance_services.save_attendance(self.past_session(days_ago=50), self.lec_user, {self.student.pk: "present"})
        self.calc(self.attendance_outcome)
        attendance_services.save_attendance(self.past_session(days_ago=45), self.lec_user, {self.student.pk: "absent"})
        self.assertTrue(self.calc(self.attendance_outcome))
        m = self.m(self.attendance_outcome)
        self.assertEqual(m.value, Decimal("50.00"))
        rev = m.revisions.first()
        self.assertEqual((rev.old_value, rev.new_value), (Decimal("100.00"), Decimal("50.00")))
        self.assertIn("Recalculated", rev.reason)
        self.assertFalse(self.calc(self.attendance_outcome))      # nothing changed the second time

    def test_calculate_all_fills_what_it_can_reports_the_rest_and_never_touches_collected_values(self):
        attendance_services.save_attendance(self.past_session(days_ago=50), self.lec_user, {self.student.pk: "present"})
        done = self.m(self.punctuality_outcome)
        services.record_measurement(done, self.researcher, status="collected", value=Decimal("90"), collected_on=days(-2))
        calculated, skipped = services.calculate_all(self.study, self.researcher)
        self.assertEqual(calculated, 1)                              # only the baseline attendance rate had data
        self.assertEqual(self.m(self.punctuality_outcome).value, Decimal("90.00"))
        self.assertTrue(skipped)
        self.assertEqual(self.m(self.assessment_outcome).status, "planned")

    def test_manual_outcomes_cannot_be_calculated(self):
        manual = OutcomeDefinition.objects.create(study=self.study, code="gpa", name="GPA", kind="other", source="manual", max_value=Decimal("5"))
        m = Measurement.objects.create(participant=self.p, outcome=manual, period=Period.BASELINE)
        with self.assertRaises(ValidationError):
            services.calculate_measurement(m, self.researcher)


# ---- Outcome definitions ---------------------------------------------------------------------------------------------------------
class OutcomeDefinitionTests(ResearchFixtureMixin, TestCase):
    def test_standard_outcomes_exist_once_and_are_idempotent(self):
        self.assertEqual(self.study.outcomes.count(), 4)
        self.assertEqual(services.ensure_default_outcomes(self.study), 0)

    def test_system_calculation_only_for_calculable_kinds(self):
        o = OutcomeDefinition(study=self.study, code="x", name="x", kind="other", source="calculated")
        with self.assertRaises(ValidationError):
            o.full_clean()

    def test_range_must_be_sensible_and_codes_unique_per_study(self):
        with self.assertRaises(ValidationError):
            OutcomeDefinition(study=self.study, code="y", name="y", kind="other", min_value=5, max_value=5).full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OutcomeDefinition.objects.create(study=self.study, code="attendance-rate", name="dup", kind="other")


# ---- Permissions -------------------------------------------------------------------------------------------------------------------
class PermissionTests(ResearchFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        p = Participant.objects.create(study=cls.study, student=cls.student, eligibility=Eligibility.ELIGIBLE, consent_status=ConsentStatus.GIVEN,
                                       consent_date=days(-2), enrolled_on=days(-1), group=Group.CONTROL)
        cls.p = p
        cls.m = Measurement.objects.create(participant=p, outcome=cls.attendance_outcome, period=Period.BASELINE)

    def urls(self):
        p, m, s = self.p.pk, self.m.pk, self.study.pk
        return {
            "study_list": reverse("research:study_list"), "study_add": reverse("research:study_add"),
            "study_detail": reverse("research:study_detail", args=[s]), "study_edit": reverse("research:study_edit", args=[s]),
            "outcome_list": reverse("research:outcome_list"), "participant_list": reverse("research:participant_list"),
            "participant_register": reverse("research:participant_register"), "participant_detail": reverse("research:participant_detail", args=[p]),
            "participant_edit": reverse("research:participant_edit", args=[p]), "participant_allocate": reverse("research:participant_allocate", args=[p]),
            "participant_withdraw": reverse("research:participant_withdraw", args=[p]), "measurement_list": reverse("research:measurement_list"),
            "measurement_edit": reverse("research:measurement_edit", args=[m]), "completeness": reverse("research:completeness"),
        }

    def get(self, user, name):
        self.client.logout()
        if user:
            self.client.login(username=user.username, password=PW)
        return self.client.get(self.urls()[name])

    def test_anonymous_users_are_sent_to_login(self):
        for name in self.urls():
            r = self.get(None, name)
            self.assertEqual(r.status_code, 302, name)
            self.assertIn(reverse("accounts:login"), r["Location"])

    def test_students_and_lecturers_cannot_open_any_research_page(self):
        for user in (self.stu_user, self.lec_user):
            for name in self.urls():
                self.assertEqual(self.get(user, name).status_code, 403, (user.role, name))

    def test_students_and_lecturers_cannot_post_actions(self):
        for user in (self.stu_user, self.lec_user, self.admin):
            self.client.login(username=user.username, password=PW)
            for name, args in [("study_plan", [self.study.pk]), ("study_calculate", [self.study.pk]), ("measurement_calculate", [self.m.pk])]:
                self.assertEqual(self.client.post(reverse(f"research:{name}", args=args)).status_code, 403, (user.role, name))
            self.client.logout()
        self.assertEqual(Measurement.objects.filter(status="collected").count(), 0)

    def test_administrators_can_configure_the_study_but_not_open_participant_data(self):
        for name in ("study_list", "study_add", "study_detail", "study_edit"):
            self.assertEqual(self.get(self.admin, name).status_code, 200, name)
        for name in ("outcome_list", "participant_list", "participant_register", "participant_detail", "participant_edit",
                     "participant_allocate", "participant_withdraw", "measurement_list", "measurement_edit", "completeness"):
            self.assertEqual(self.get(self.admin, name).status_code, 403, name)

    def test_admin_study_page_shows_counts_but_no_participant_codes_or_groups_of_individuals(self):
        r = self.get(self.admin, "study_detail")
        self.assertNotContains(r, self.p.research_code)
        self.assertNotContains(r, self.student.registration_number)

    def test_researcher_can_open_everything(self):
        for name in self.urls():
            self.assertEqual(self.get(self.researcher, name).status_code, 200, name)

    def test_participant_list_shows_codes_not_names(self):
        r = self.get(self.researcher, "participant_list")
        self.assertContains(r, self.p.research_code)
        self.assertNotContains(r, self.student.registration_number)
        self.assertNotContains(r, self.stu_user.display_name())

    def test_researcher_cannot_open_other_studies_participants_or_measurements(self):
        other = ResearchStudy.objects.create(title="Other", is_active=True)
        self.client.login(username=self.researcher.username, password=PW)
        self.assertEqual(self.client.get(reverse("research:participant_detail", args=[self.p.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("research:measurement_edit", args=[self.m.pk])).status_code, 404)
        self.assertEqual(other.participants.count(), 0)

    def test_researcher_gets_no_attendance_or_marks_pages(self):
        self.client.login(username=self.researcher.username, password=PW)
        self.assertEqual(self.client.get(reverse("attendance:student_report", args=[self.student.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("performance:assignment_list")).status_code, 403)

    def test_no_active_study_redirects_researchers_to_the_study_list(self):
        ResearchStudy.objects.update(is_active=False)
        self.client.login(username=self.researcher.username, password=PW)
        r = self.client.get(reverse("research:participant_list"))
        self.assertRedirects(r, reverse("research:study_list"))

    def test_administrator_group_has_study_permissions_only(self):
        perms = {p for p in AuthGroup.objects.get(name="System Administrator").permissions.values_list("content_type__app_label", "codename")
                 if p[0] == "research"}
        self.assertEqual(perms, {("research", "add_researchstudy"), ("research", "change_researchstudy"), ("research", "view_researchstudy")})
        for role in ("Researcher", "Lecturer", "Student"):
            self.assertFalse(AuthGroup.objects.get(name=role).permissions.filter(content_type__app_label="research").exists())

    def test_django_admin_hides_participant_data_from_administrators(self):
        self.assertFalse(self.admin.has_perm("research.view_participant"))
        self.assertFalse(self.admin.has_perm("research.view_measurement"))
        self.assertTrue(self.admin.has_perm("research.change_researchstudy"))
        self.assertFalse(self.researcher.has_perm("research.view_participant"))


# ---- End to end through the web pages ---------------------------------------------------------------------------------------------------
class ResearcherWorkflowTests(ResearchFixtureMixin, TestCase):
    def setUp(self):
        self.client.login(username=self.researcher.username, password=PW)

    def test_full_flow_register_consent_allocate_plan_record(self):
        r = self.client.post(reverse("research:participant_register"), {"student": self.student.pk, "eligibility": "eligible",
                                                                        "eligibility_notes": "", "notes": ""})
        p = Participant.objects.get(student=self.student)
        self.assertRedirects(r, reverse("research:participant_detail", args=[p.pk]))
        self.client.post(reverse("research:participant_edit", args=[p.pk]), {
            "eligibility": "eligible", "eligibility_notes": "", "consent_status": "given", "consent_date": days(-1).isoformat(),
            "consent_reference": "F-12", "enrolled_on": days(-1).isoformat(), "notes": ""})
        r = self.client.post(reverse("research:participant_allocate", args=[p.pk]), {
            "group": "control", "method": "external_randomisation", "procedure": "Sealed-envelope list prepared by the supervisor.",
            "allocation_date": days(0).isoformat(), "reason": ""})
        self.assertRedirects(r, reverse("research:participant_detail", args=[p.pk]))
        p.refresh_from_db()
        self.assertEqual(p.group, "control")
        self.client.post(reverse("research:study_plan", args=[self.study.pk]))
        m = Measurement.objects.get(participant=p, outcome=self.attendance_outcome, period="baseline")
        r = self.client.post(reverse("research:measurement_edit", args=[m.pk]), {
            "status": "collected", "value": "64.5", "collected_on": days(-2).isoformat(), "missing_reason": "", "notes": "", "reason": ""})
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertEqual((m.status, m.value), ("collected", Decimal("64.50")))
        self.assertContains(self.client.get(reverse("research:participant_detail", args=[p.pk])), "Sealed-envelope list")

    def test_register_form_only_offers_students_not_yet_registered(self):
        self.register(self.student)
        r = self.client.get(reverse("research:participant_register"))
        self.assertNotContains(r, self.student.registration_number)
        self.assertContains(r, self.student2.registration_number)

    def test_invalid_measurement_is_rejected_with_a_message(self):
        p = self.enrol(self.student)
        m = Measurement.objects.create(participant=p, outcome=self.attendance_outcome, period="baseline")
        r = self.client.post(reverse("research:measurement_edit", args=[m.pk]), {
            "status": "collected", "value": "250", "collected_on": days(-2).isoformat(), "missing_reason": "", "notes": "", "reason": ""})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "between")
        m.refresh_from_db()
        self.assertEqual(m.status, "planned")

    def test_dashboard_shows_real_counts_and_no_findings(self):
        self.enrol(self.student, Group.INTERVENTION)
        self.enrol(self.student2, Group.CONTROL)
        r = self.client.get(reverse("accounts:dashboard_researcher"))
        self.assertEqual(r.context["overview"]["enrolled"], 2)
        self.assertEqual((r.context["overview"]["intervention"], r.context["overview"]["control"]), (1, 1))

    def test_dashboard_without_a_study_says_so(self):
        ResearchStudy.objects.update(is_active=False)
        r = self.client.get(reverse("accounts:dashboard_researcher"))
        self.assertContains(r, "no active study")

    def test_overview_counts(self):
        self.enrol(self.student, Group.INTERVENTION)
        self.register(self.student2)
        o = services.study_overview(self.study)
        self.assertEqual((o["registered"], o["enrolled"], o["intervention"], o["control"], o["unallocated"], o["consent_given"], o["consent_pending"]),
                         (2, 1, 1, 0, 0, 1, 1))

    def test_completeness_counts_each_state_and_excludes_withdrawn_from_the_percentage(self):
        a = self.enrol(self.student, Group.CONTROL)
        b = self.enrol(self.student2, Group.CONTROL)
        services.plan_measurements(self.study, self.researcher)
        row = Measurement.objects.get(participant=a, outcome=self.attendance_outcome, period="baseline")
        services.record_measurement(row, self.researcher, status="collected", value=Decimal("80"), collected_on=days(-2))
        services.withdraw_participant(b, self.researcher, withdrawn_on=days(0), data_handling="retain")
        rows = services.completeness(self.study)
        r = next(x for x in rows if x["outcome"] == self.attendance_outcome and x["period"] == "Baseline" and x["group"] == "Control")
        self.assertEqual((r["total"], r["counts"]["collected"], r["counts"]["withdrawn"], r["completeness"]), (2, 1, 1, 100.0))
        self.assertEqual(self.client.get(reverse("research:completeness")).status_code, 200)

    def test_calculate_button_reports_what_could_not_be_calculated(self):
        self.enrol(self.student, Group.INTERVENTION)
        services.plan_measurements(self.study, self.researcher)
        r = self.client.post(reverse("research:study_calculate", args=[self.study.pk]), follow=True)
        text = " ".join(str(m) for m in r.context["messages"])
        self.assertIn("0 measurement(s) calculated", text)
        self.assertIn("not calculated", text)
