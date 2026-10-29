"""Phase 7 tests: which data may be analysed, group comparisons, TAM summaries, reminders summary, data-quality checks,
CSV exports, the data dictionary and permissions.

All data below is synthetic test fixture data. Nothing here is a research finding.
"""
import csv
import io
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import StudentProfile
from apps.academics.tests import PW, make_user
from apps.accounts.models import AuditLog, Role
from apps.questionnaires import services as q_services
from apps.questionnaires.models import Questionnaire
from apps.questionnaires.tests import QFixtureMixin
from apps.reminders.models import Notification, NotificationKind, NotificationStatus
from apps.research import services as research_services
from apps.research.forms import ResearchStudyForm
from apps.research.models import (Allocation, ConsentStatus, Group, Measurement, MeasurementStatus, OutcomeDefinition, Participant, Period)
from apps.research.tests import days

from . import exports, quality, services, stats

D = Decimal


class AnalyticsFixtureMixin(QFixtureMixin):
    """Synthetic participants with synthetic values (invented numbers, no designed effect)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.study.min_analysis_n = 4
        cls.study.save()
        cls.counter = 0

    def people(self, n_int, n_ctl):
        out = {Group.INTERVENTION: [], Group.CONTROL: []}
        for group, n in ((Group.INTERVENTION, n_int), (Group.CONTROL, n_ctl)):
            for _ in range(n):
                type(self).counter += 1
                i = type(self).counter
                user = make_user(f"an{i}", Role.STUDENT)
                student = StudentProfile.objects.create(user=user, registration_number=f"AN{i:03d}", programme=self.programme)
                out[group].append(self.enrol(student, group))
        return out

    def collect(self, participant, outcome, period, value, on=None):
        on = on or (days(-40) if period == Period.BASELINE else days(-10))
        return Measurement.objects.create(participant=participant, outcome=outcome, period=period, status=MeasurementStatus.COLLECTED,
                                          value=D(str(value)), collected_on=on, source="manual")

    def fill(self, outcome, ivg, ctl, ivg_pairs, ctl_pairs):
        for p, (b, a) in zip(ivg, ivg_pairs):
            self.collect(p, outcome, Period.BASELINE, b)
            self.collect(p, outcome, Period.POST, a)
        for p, (b, a) in zip(ctl, ctl_pairs):
            self.collect(p, outcome, Period.BASELINE, b)
            self.collect(p, outcome, Period.POST, a)

    def login(self, user):
        self.client.login(username=user.username, password=PW)


IVG_PAIRS = [(50, 58), (62, 65), (48, 47), (71, 80), (55, 61), (60, 63)]
CTL_PAIRS = [(52, 53), (60, 59), (49, 52), (70, 72), (56, 55), (61, 64)]


# ---- Which data may be used ----------------------------------------------------------------------------------------------
class DataRuleTests(AnalyticsFixtureMixin, TestCase):
    def test_only_eligible_consenting_enrolled_participants_are_analysed(self):
        ok = self.people(2, 1)
        declined = self.register(self.student, eligibility="eligible")
        declined.consent_status = ConsentStatus.DECLINED
        declined.save()
        self.register(self.student2)  # registered only
        codes = set(services.analysis_participants(self.study).values_list("research_code", flat=True))
        self.assertEqual(codes, {p.research_code for g in ok.values() for p in g})

    def test_withdrawal_with_exclude_removes_everything_and_retain_keeps_earlier_data(self):
        groups = self.people(3, 0)
        keep, drop, stay = groups[Group.INTERVENTION]
        for p in (keep, drop, stay):
            self.collect(p, self.attendance_outcome, Period.BASELINE, 60, on=days(-40))
        research_services.withdraw_participant(keep, self.researcher, withdrawn_on=days(-35), data_handling="retain")
        research_services.withdraw_participant(drop, self.researcher, withdrawn_on=days(-35), data_handling="exclude")
        self.collect(keep, self.attendance_outcome, Period.POST, 70, on=days(-5))  # after withdrawal: not usable
        used = {(m.participant.research_code, m.period) for m in services.usable_measurements(self.study)}
        self.assertEqual(used, {(keep.research_code, "baseline"), (stay.research_code, "baseline")})

    def test_withdrawal_without_a_recorded_choice_is_treated_as_exclude(self):
        p = self.people(1, 0)[Group.INTERVENTION][0]
        Participant.objects.filter(pk=p.pk).update(withdrawn_on=days(-5), withdrawal_data_handling="")
        self.assertEqual(services.analysis_participants(self.study).count(), 0)

    def test_only_collected_values_are_used(self):
        a, b = self.people(2, 0)[Group.INTERVENTION]
        self.collect(a, self.attendance_outcome, Period.POST, 80)
        Measurement.objects.create(participant=b, outcome=self.attendance_outcome, period=Period.POST, status="missing", missing_reason="x")
        Measurement.objects.create(participant=b, outcome=self.punctuality_outcome, period=Period.POST, status="planned")
        self.assertEqual(services.usable_measurements(self.study).count(), 1)


# ---- Group comparisons ----------------------------------------------------------------------------------------------------
class ComparisonTests(AnalyticsFixtureMixin, TestCase):
    def setUp(self):
        groups = self.people(6, 6)
        self.ivg, self.ctl = groups[Group.INTERVENTION], groups[Group.CONTROL]
        self.fill(self.attendance_outcome, self.ivg, self.ctl, IVG_PAIRS, CTL_PAIRS)

    def blocks(self):
        return {b["title"].split(":")[0] + ":" + b["title"].split(":")[1][:12]: b for b in services.analyse_outcome(self.study, self.attendance_outcome)["blocks"]}

    def test_all_five_comparisons_are_produced_for_an_outcome_measured_twice(self):
        blocks = services.analyse_outcome(self.study, self.attendance_outcome)["blocks"]
        self.assertEqual([b["kind"] for b in blocks], ["two_sample", "two_sample", "two_sample", "paired", "paired"])
        self.assertTrue(all(b["available"] for b in blocks))

    def test_post_comparison_numbers_match_direct_calculation(self):
        post = services.analyse_outcome(self.study, self.attendance_outcome)["blocks"][1]
        x, y = [float(a) for _, a in IVG_PAIRS], [float(a) for _, a in CTL_PAIRS]
        self.assertEqual([g["n"] for g in post["groups"]], [6, 6])
        self.assertAlmostEqual(post["groups"][0]["summary"]["mean"], round(stats.mean(x), 2))
        self.assertEqual(post["primary_is"], "Mann-Whitney U test")          # 6 per group: too few for a normality check
        self.assertIn("fewer than 20", post["selection"])
        self.assertAlmostEqual(post["primary"]["p"], stats.mann_whitney(x, y)["p"], places=12)
        self.assertAlmostEqual(post["secondary"]["p"], stats.welch_t(x, y)["p"], places=12)
        self.assertEqual(post["secondary"]["test"], "Welch's t-test")
        self.assertAlmostEqual(post["secondary"]["diff"], round(stats.mean(x) - stats.mean(y), 2))

    def test_change_comparison_uses_each_participants_change(self):
        change = services.analyse_outcome(self.study, self.attendance_outcome)["blocks"][2]
        ci, cc = [a - b for b, a in IVG_PAIRS], [a - b for b, a in CTL_PAIRS]
        self.assertAlmostEqual(change["groups"][0]["summary"]["mean"], round(stats.mean(ci), 2))
        self.assertAlmostEqual(change["groups"][1]["summary"]["mean"], round(stats.mean(cc), 2))

    def test_paired_blocks_report_baseline_post_and_change(self):
        paired = services.analyse_outcome(self.study, self.attendance_outcome)["blocks"][3]
        diffs = [float(a - b) for b, a in IVG_PAIRS]
        self.assertEqual(paired["primary_is"], "Wilcoxon signed-rank test")
        self.assertAlmostEqual(paired["secondary"]["p"], stats.paired_t(diffs)["p"], places=12)
        g = paired["groups"][0]
        self.assertEqual((g["n"], g["baseline"]["n"]), (6, 6))

    def test_missing_values_are_counted_not_filled_in(self):
        extra = self.people(1, 0)[Group.INTERVENTION][0]
        self.collect(extra, self.attendance_outcome, Period.BASELINE, 55)  # baseline only: no pair, no post value
        blocks = services.analyse_outcome(self.study, self.attendance_outcome)["blocks"]
        post = blocks[1]
        self.assertEqual((post["groups"][0]["enrolled"], post["groups"][0]["n"], post["groups"][0]["missing"]), (7, 6, 1))
        self.assertEqual(blocks[3]["groups"][0]["n"], 6)  # complete pairs only
        self.assertEqual(blocks[0]["groups"][0]["n"], 7)

    def test_not_available_below_the_minimum_with_a_clear_message(self):
        self.study.min_analysis_n = 7
        self.study.save()
        blocks = services.analyse_outcome(self.study, self.attendance_outcome)["blocks"]
        for b in blocks:
            self.assertFalse(b["available"], b["title"])
            self.assertIn("Analysis not yet available", b["message"])
            self.assertIn("at least 7", b["message"])
            self.assertIsNone(b["primary"])
        self.assertEqual(blocks[1]["groups"][0]["n"], 6)  # descriptives still shown

    def test_no_data_at_all_gives_empty_but_safe_blocks(self):
        result = services.analyse_outcome(self.study, self.punctuality_outcome)
        self.assertEqual(result["collected"], 0)
        self.assertTrue(all(not b["available"] for b in result["blocks"]))

    def test_identical_values_are_reported_as_not_estimable_not_as_an_error(self):
        groups = self.people(4, 4)
        for p in groups[Group.INTERVENTION] + groups[Group.CONTROL]:
            self.collect(p, self.assessment_outcome, Period.POST, 50)
        post = services.analyse_outcome(self.study, self.assessment_outcome)["blocks"][1]
        self.assertTrue(post["available"])
        self.assertFalse(post["primary"]["estimable"])
        self.assertFalse(post["secondary"]["estimable"])

    def test_unallocated_participants_are_in_no_comparison(self):
        type(self).counter += 1
        user = make_user(f"an{self.counter}", Role.STUDENT)
        s = StudentProfile.objects.create(user=user, registration_number=f"AN{self.counter:03d}", programme=self.programme)
        unallocated = self.enrol(s)
        self.collect(unallocated, self.attendance_outcome, Period.POST, 99)
        post = services.analyse_outcome(self.study, self.attendance_outcome)["blocks"][1]
        self.assertEqual([g["n"] for g in post["groups"]], [6, 6])
        self.assertEqual(services.group_counts(self.study)[""], 1)

    def test_intervention_only_outcome_has_no_control_comparison(self):
        for p, v in zip(self.ivg, (80, 60, 70, 90, 50, 75)):
            self.collect(p, self.reminder_outcome, Period.POST, v)
        result = services.analyse_outcome(self.study, self.reminder_outcome)
        self.assertEqual([b["kind"] for b in result["blocks"]], ["descriptive"])
        self.assertEqual(result["blocks"][0]["groups"][0]["n"], 6)

    def test_confidence_level_follows_the_studys_significance_level(self):
        self.study.significance_level = D("0.010")
        self.study.save()
        post = services.analyse_outcome(self.study, self.attendance_outcome)["blocks"][1]
        self.assertEqual(post["ci_level"], "99%")
        self.assertEqual(post["alpha"], 0.01)

    def test_large_clearly_normal_samples_choose_the_t_test(self):
        extra_groups = self.people(18, 18)  # 24 per group in total
        for i, p in enumerate(extra_groups[Group.INTERVENTION]):
            self.collect(p, self.assessment_outcome, Period.POST, 50 + ((i * 7) % 13) - 6)
        for i, p in enumerate(extra_groups[Group.CONTROL]):
            self.collect(p, self.assessment_outcome, Period.POST, 52 + ((i * 5) % 11) - 5)
        for p in self.ivg + self.ctl:
            self.collect(p, self.assessment_outcome, Period.POST, 51 + (p.pk % 5))
        post = services.analyse_outcome(self.study, self.assessment_outcome)["blocks"][1]
        self.assertEqual(post["groups"][0]["n"], 24)
        self.assertIn(post["primary_is"], ("Welch's t-test", "Mann-Whitney U test"))
        self.assertTrue(post["selection"])


# ---- TAM ------------------------------------------------------------------------------------------------------------------------
class TamAnalysisTests(AnalyticsFixtureMixin, TestCase):
    def setUp(self):
        groups = self.people(5, 5)
        self.ivg, self.ctl = groups[Group.INTERVENTION], groups[Group.CONTROL]
        self.q = self.build()
        q_services.assign_questionnaire(self.q, self.researcher, target="all")

    def submit(self, participant, **kw):
        assignment = participant.questionnaire_assignments.get(questionnaire=self.q)
        return q_services.save_response(assignment, self.answers(**kw), submit=True)

    def test_construct_scores_reliability_and_comparison(self):
        for p, (pu1, pu2) in zip(self.ivg, [(5, 1), (4, 2), (5, 2), (4, 1), (3, 3)]):
            self.submit(p, pu1=pu1, pu2=pu2, peou=4)
        for p, (pu1, pu2) in zip(self.ctl, [(3, 3), (2, 4), (3, 2), (4, 3), (2, 3)]):
            self.submit(p, pu1=pu1, pu2=pu2, peou=3)
        result = services.analyse_tam(self.study)
        self.assertEqual(len(result), 1)
        pu = next(c for c in result[0]["constructs"] if c["construct"] == "PU")
        # PU score = mean(pu1, 6 - pu2) because the second item is reverse scored
        ivg_scores = [(5 + 5) / 2, (4 + 4) / 2, (5 + 4) / 2, (4 + 5) / 2, (3 + 3) / 2]
        self.assertAlmostEqual(pu["groups"][0][1]["mean"], round(stats.mean(ivg_scores), 2))
        self.assertEqual((pu["overall"]["n"], pu["incomplete"], pu["items"]), (10, 0, 2))
        self.assertIsNotNone(pu["alpha"])
        self.assertEqual(pu["alpha_n"], 10)
        self.assertTrue(pu["comparison"]["available"])
        self.assertEqual(pu["comparison"]["groups"][0]["n"], 5)
        peou = next(c for c in result[0]["constructs"] if c["construct"] == "PEOU")
        self.assertIsNone(peou["alpha"])                 # a single item has no reliability
        self.assertIn("2 items", peou["alpha_note"])

    def test_only_submitted_responses_of_usable_participants_count(self):
        self.submit(self.ivg[0])
        assignment = self.ivg[1].questionnaire_assignments.get(questionnaire=self.q)
        q_services.save_response(assignment, self.answers(), submit=False)           # draft: never used
        self.submit(self.ivg[2])
        research_services.withdraw_participant(self.ivg[2], self.researcher, withdrawn_on=days(-1), data_handling="exclude")
        pu = next(c for c in services.analyse_tam(self.study)[0]["constructs"] if c["construct"] == "PU")
        self.assertEqual(pu["overall"]["n"], 1)

    def test_comparison_needs_both_groups_and_the_minimum(self):
        for p in self.ivg[:3]:
            self.submit(p)
        pu = next(c for c in services.analyse_tam(self.study)[0]["constructs"] if c["construct"] == "PU")
        self.assertIsNone(pu["comparison"])               # nobody in the control group answered
        for p in self.ctl[:3]:
            self.submit(p)
        pu = next(c for c in services.analyse_tam(self.study)[0]["constructs"] if c["construct"] == "PU")
        self.assertFalse(pu["comparison"]["available"])   # 3 per group < the minimum of 4
        self.assertIn("not yet available", pu["comparison"]["message"])


# ---- Reminder interaction ---------------------------------------------------------------------------------------------------
class ReminderSummaryTests(AnalyticsFixtureMixin, TestCase):
    def make_reminder(self, participant, *, read, hours_ago=24 * 20):  # default: inside the fixture's post window (30 to 17 days ago)
        session = self.past_session()
        when = timezone.now() - timedelta(hours=hours_ago)
        return Notification.objects.create(recipient=participant.student.user, session=session, kind=NotificationKind.REMINDER,
                                           minutes_before=60, title="Reminder", message="m", scheduled_for=when,
                                           status=NotificationStatus.DELIVERED, delivered_at=when,
                                           read_at=when + timedelta(minutes=30) if read else None)

    def test_summary_by_group_and_control_group_has_none(self):
        groups = self.people(3, 2)
        a, b, c = groups[Group.INTERVENTION]
        self.make_reminder(a, read=True)
        self.make_reminder(a, read=False)
        self.make_reminder(b, read=True)
        result = services.reminder_summary(self.study)["rows"]
        iv = next(r for r in result if r["label"] == "Intervention")
        ct = next(r for r in result if r["label"] == "Control")
        self.assertEqual((iv["participants"], iv["with_reminders"], iv["delivered"], iv["read"], iv["read_rate"]), (3, 2, 3, 2, 66.7))
        self.assertEqual((ct["participants"], ct["delivered"], ct["read_rate"]), (2, 0, None))

    def test_pending_cancelled_and_schedule_change_notices_are_not_counted(self):
        a = self.people(1, 0)[Group.INTERVENTION][0]
        n = self.make_reminder(a, read=False)
        Notification.objects.filter(pk=n.pk).update(status=NotificationStatus.CANCELLED)
        m = self.make_reminder(a, read=False)
        Notification.objects.filter(pk=m.pk).update(kind=NotificationKind.SCHEDULE_CHANGE)
        self.assertEqual(services.reminder_summary(self.study)["rows"][0]["delivered"], 0)

    def test_window_is_the_post_intervention_window_when_set(self):
        a = self.people(1, 0)[Group.INTERVENTION][0]
        self.make_reminder(a, read=True, hours_ago=24 * 100)   # before the intervention start (30 days ago)
        self.make_reminder(a, read=True, hours_ago=24 * 20)    # inside the window (30 to 17 days ago)
        self.make_reminder(a, read=True, hours_ago=24 * 5)     # after the window ended
        self.assertEqual(services.reminder_summary(self.study)["rows"][0]["delivered"], 1)
        self.study.intervention_start = None
        self.study.baseline_end = None
        self.study.save()
        self.assertEqual(services.reminder_summary(self.study)["rows"][0]["delivered"], 3)  # window unset: all time


# ---- Data quality --------------------------------------------------------------------------------------------------------------
class QualityTests(AnalyticsFixtureMixin, TestCase):
    def codes(self):
        return {i["code"]: i for i in quality.data_quality_issues(self.study)}

    def test_clean_data_has_no_errors(self):
        groups = self.people(2, 2)
        self.fill(self.attendance_outcome, groups[Group.INTERVENTION], groups[Group.CONTROL], IVG_PAIRS[:2], CTL_PAIRS[:2])
        self.assertEqual([i for i in quality.data_quality_issues(self.study) if i["severity"] == "error"], [])

    def test_group_without_allocation_record_and_mismatch(self):
        a, b = self.people(2, 0)[Group.INTERVENTION]
        Allocation.objects.filter(participant=a).delete()
        Participant.objects.filter(pk=b.pk).update(group=Group.CONTROL)
        found = self.codes()
        self.assertEqual(found["group_without_allocation_record"]["examples"], [a.research_code])
        self.assertEqual(found["group_differs_from_latest_allocation"]["examples"], [b.research_code])
        self.assertEqual(found["group_without_allocation_record"]["severity"], "error")

    def test_enrolled_not_allocated_is_a_warning(self):
        type(self).counter += 1
        s = StudentProfile.objects.create(user=make_user(f"an{self.counter}", Role.STUDENT), registration_number=f"AN{self.counter:03d}", programme=self.programme)
        p = self.enrol(s)
        issue = self.codes()["enrolled_not_allocated"]
        self.assertEqual((issue["severity"], issue["examples"]), ("warning", [p.research_code]))

    def test_control_participant_who_received_reminders_is_flagged(self):
        c = self.people(0, 1)[Group.CONTROL][0]
        now = timezone.now()
        Notification.objects.create(recipient=c.student.user, session=self.past_session(), kind=NotificationKind.REMINDER, minutes_before=60,
                                    title="r", message="m", scheduled_for=now, status=NotificationStatus.DELIVERED, delivered_at=now)
        self.assertEqual(self.codes()["control_received_reminders"]["examples"], [c.research_code])

    def test_intervention_only_outcome_collected_for_control_is_flagged(self):
        c = self.people(0, 1)[Group.CONTROL][0]
        self.collect(c, self.reminder_outcome, Period.POST, 50)
        self.assertEqual(self.codes()["intervention_only_outcome_for_control"]["examples"], [c.research_code])

    def test_invalid_dates_are_flagged(self):
        a, b, c = self.people(3, 0)[Group.INTERVENTION]
        self.collect(a, self.attendance_outcome, Period.POST, 50, on=days(-45))       # before the intervention started (30 days ago)
        self.collect(b, self.attendance_outcome, Period.BASELINE, 50, on=days(-20))   # baseline after the intervention started
        Measurement.objects.filter(participant=b).update(collected_on=days(3))
        self.collect(c, self.punctuality_outcome, Period.BASELINE, 50, on=days(-40))
        Participant.objects.filter(pk=c.pk).update(withdrawn_on=days(-70), withdrawal_data_handling="retain")  # before enrolment (64 days ago)
        found = self.codes()
        self.assertEqual(found["post_before_intervention_start"]["examples"], [a.research_code])
        self.assertEqual(found["collection_date_in_future"]["examples"], [b.research_code])
        self.assertEqual(found["collected_after_withdrawal"]["examples"], [c.research_code])
        self.assertEqual(found["invalid_participant_dates"]["examples"], [c.research_code])  # withdrawn before enrolment

    def test_missing_data_warnings(self):
        a, b = self.people(2, 0)[Group.INTERVENTION]
        Measurement.objects.create(participant=a, outcome=self.attendance_outcome, period=Period.BASELINE, status="planned")
        Participant.objects.filter(pk=b.pk).update(withdrawn_on=days(-2), withdrawal_data_handling="")
        found = self.codes()
        self.assertIn(a.research_code, found["enrolled_without_collected_data"]["examples"])
        self.assertEqual(found["overdue_planned_measurements"]["examples"], [a.research_code])
        self.assertEqual(found["withdrawal_choice_missing"]["examples"], [b.research_code])

    def test_unanswered_past_due_questionnaire(self):
        a = self.people(1, 0)[Group.INTERVENTION][0]
        q = self.build()
        q_services.assign_questionnaire(q, self.researcher, target="all", due_date=days(-1))
        self.assertEqual(self.codes()["questionnaire_past_due_unanswered"]["examples"], [a.research_code])

    def test_checks_report_only_and_use_research_codes_only(self):
        self.people(1, 0)
        before = Measurement.objects.count(), Participant.objects.count()
        issues = quality.data_quality_issues(self.study)
        self.assertEqual(before, (Measurement.objects.count(), Participant.objects.count()))
        for issue in issues:
            for example in issue["examples"]:
                self.assertTrue(example.startswith("P-") or example.startswith("Response"), example)

    def test_examples_are_capped_at_ten(self):
        self.people(12, 0)
        self.assertEqual(len(self.codes()["enrolled_without_collected_data"]["examples"]), 10)
        self.assertEqual(self.codes()["enrolled_without_collected_data"]["count"], 12)


# ---- Exports -------------------------------------------------------------------------------------------------------------------------
def parse(text):
    return list(csv.DictReader(io.StringIO(text)))


class ExportTests(AnalyticsFixtureMixin, TestCase):
    def setUp(self):
        groups = self.people(3, 3)
        self.ivg, self.ctl = groups[Group.INTERVENTION], groups[Group.CONTROL]
        self.fill(self.attendance_outcome, self.ivg, self.ctl, IVG_PAIRS[:3], CTL_PAIRS[:3])

    def export(self, key):
        return parse(exports.dataset_csv(exports.DATASET_BY_KEY[key], self.study)[0])

    def test_every_dataset_header_matches_the_dictionary_and_rows_have_exactly_those_fields(self):
        q = self.build()
        q_services.assign_questionnaire(q, self.researcher, target="all")
        q_services.save_response(self.ivg[0].questionnaire_assignments.get(questionnaire=q), self.answers(), submit=True)
        now = timezone.now() - timedelta(days=20)   # inside the fixture's post-intervention window
        Notification.objects.create(recipient=self.ivg[0].student.user, session=self.past_session(), kind=NotificationKind.REMINDER,
                                    minutes_before=60, title="r", message="m", scheduled_for=now, status=NotificationStatus.DELIVERED,
                                    delivered_at=now, read_at=now)
        self.collect(self.ivg[0], self.punctuality_outcome, Period.POST, 80)
        self.collect(self.ivg[0], self.assessment_outcome, Period.POST, 65)
        self.assertEqual(len(exports.DATASETS), 9)
        for d in exports.DATASETS:
            text, count = exports.dataset_csv(d, self.study)   # raises if any row's fields differ from the dictionary
            self.assertEqual(text.splitlines()[0].split(","), d.header, d.key)
            self.assertGreaterEqual(count, 1, d.key)           # every dataset has at least one row in this fixture
            self.assertEqual(len(parse(text)), count)

    def test_dictionary_describes_every_field_with_all_four_columns(self):
        for row in exports.dictionary_rows():
            dataset, field, meaning, values, calc = row
            self.assertTrue(all(str(c).strip() for c in row), row)
        keys = {r[0] for r in exports.dictionary_rows()}
        self.assertEqual(keys, {d.key for d in exports.DATASETS} | {"data_quality_report"})
        self.assertEqual(len({(r[0], r[1]) for r in exports.dictionary_rows()}), len(exports.dictionary_rows()))  # no duplicate fields
        self.assertEqual(len(parse(exports.dictionary_csv())), len(exports.dictionary_rows()))

    def test_committed_data_dictionary_is_up_to_date(self):
        path = Path(__file__).resolve().parents[2] / "docs" / "DATA_DICTIONARY.md"
        self.assertEqual(path.read_text(encoding="utf-8"), exports.dictionary_markdown(),
                         "Run: python manage.py export_data_dictionary")

    def test_participants_export_uses_codes_and_no_identifiers(self):
        text = exports.dataset_csv(exports.DATASET_BY_KEY["participants"], self.study)[0]
        rows = parse(text)
        self.assertEqual(len(rows), 6)
        self.assertEqual({r["group"] for r in rows}, {"intervention", "control"})
        everything = text + "".join(exports.dataset_csv(d, self.study)[0] for d in exports.DATASETS)
        for forbidden in ("AN0", "@example.test", "an1", "Test", "pbkdf2", "password", self.researcher.email):
            self.assertNotIn(forbidden, everything, forbidden)
        for person in self.ivg + self.ctl:
            self.assertIn(person.research_code, text)
        self.assertEqual(set(rows[0]), set(exports.DATASET_BY_KEY["participants"].header))

    def test_declined_ineligible_unenrolled_and_excluded_participants_are_not_exported(self):
        declined = self.register(self.student, eligibility="eligible")
        declined.consent_status = ConsentStatus.DECLINED
        declined.save()
        self.register(self.student2, eligibility="ineligible")
        gone = self.ivg[0]
        research_services.withdraw_participant(gone, self.researcher, withdrawn_on=days(-1), data_handling="exclude")
        kept = self.ivg[1]
        research_services.withdraw_participant(kept, self.researcher, withdrawn_on=days(-1), data_handling="retain")
        for d in exports.DATASETS:
            text = exports.dataset_csv(d, self.study)[0]
            self.assertNotIn(declined.research_code, text, d.key)
            self.assertNotIn(gone.research_code, text, d.key)
        rows = {r["research_code"]: r for r in self.export("participants")}
        self.assertEqual(rows[kept.research_code]["withdrawn"], "yes")
        self.assertEqual(rows[kept.research_code]["withdrawal_data_handling"], "retain")
        self.assertEqual(len(rows), 5)

    def test_measurement_exports_split_by_kind_and_period(self):
        self.collect(self.ivg[0], self.punctuality_outcome, Period.BASELINE, 70)
        self.assertEqual({r["outcome_kind"] for r in self.export("attendance")}, {"attendance_rate"})
        self.assertEqual({r["outcome_kind"] for r in self.export("punctuality")}, {"punctuality_rate"})
        self.assertEqual(self.export("performance"), [])
        self.assertEqual({r["period"] for r in self.export("baseline")}, {"baseline"})
        self.assertEqual({r["period"] for r in self.export("post_intervention")}, {"post_intervention"})
        self.assertEqual(len(self.export("attendance")), 12)   # 6 participants x 2 periods

    def test_values_are_exported_exactly_and_non_collected_rows_have_no_value(self):
        Measurement.objects.create(participant=self.ivg[0], outcome=self.assessment_outcome, period=Period.POST, status="missing",
                                   missing_reason="secret reason with identifying words")
        Measurement.objects.create(participant=self.ivg[1], outcome=self.assessment_outcome, period=Period.POST, status="planned")
        self.collect(self.ctl[0], self.assessment_outcome, Period.POST, "-3.75")
        rows = {r["research_code"]: r for r in self.export("performance")}
        self.assertEqual((rows[self.ivg[0].research_code]["status"], rows[self.ivg[0].research_code]["value"], rows[self.ivg[0].research_code]["state"]), ("missing", "", "missing"))
        # the fixture's post-intervention window ended 2+ weeks ago, so a still-planned row is shown as overdue
        self.assertEqual((rows[self.ivg[1].research_code]["value"], rows[self.ivg[1].research_code]["state"]), ("", "not_yet_collected"))
        self.assertEqual(rows[self.ctl[0].research_code]["value"], "-3.75")          # negative numbers are not mangled
        self.assertNotIn("secret reason", exports.dataset_csv(exports.DATASET_BY_KEY["performance"], self.study)[0])

    def test_nothing_is_modified_or_rounded_by_exporting(self):
        self.collect(self.ctl[1], self.assessment_outcome, Period.BASELINE, "61.07")
        before = list(Measurement.objects.order_by("pk").values_list("pk", "value", "status", "updated_at"))
        rows = {r["research_code"]: r for r in self.export("baseline")}
        self.assertEqual([r for r in self.export("baseline") if r["outcome_code"] == "assessment-score"][0]["value"], "61.07")
        self.assertEqual(before, list(Measurement.objects.order_by("pk").values_list("pk", "value", "status", "updated_at")))
        self.assertTrue(rows)

    def test_spreadsheet_formula_injection_is_neutralised(self):
        OutcomeDefinition.objects.filter(pk=self.attendance_outcome.pk).update(name='=HYPERLINK("http://evil.example","x")')
        OutcomeDefinition.objects.filter(pk=self.punctuality_outcome.pk).update(name="@SUM(1+1)")
        self.collect(self.ivg[0], self.punctuality_outcome, Period.BASELINE, 70)
        text = exports.dataset_csv(exports.DATASET_BY_KEY["attendance"], self.study)[0]
        self.assertIn("\"'=HYPERLINK", text)
        self.assertNotIn(",=HYPERLINK", text)
        self.assertIn("'@SUM", exports.dataset_csv(exports.DATASET_BY_KEY["punctuality"], self.study)[0])
        self.assertEqual(exports.safe_cell("+1"), "'+1")
        self.assertEqual(exports.safe_cell("-1+2"), "'-1+2")
        self.assertEqual(exports.safe_cell("plain"), "plain")
        self.assertEqual(exports.format_value(D("-5.50")), "-5.50")
        self.assertEqual(exports.format_value(-2.5), "-2.5")

    def test_questionnaire_exports_include_unanswered_questions_but_no_free_text(self):
        q = self.build()
        q_services.assign_questionnaire(q, self.researcher, target="all")
        q_services.save_response(self.ivg[0].questionnaire_assignments.get(questionnaire=q), self.answers(pu1=5, pu2=2, peou=4, text="Call me on 0700 000000"), submit=True)
        q_services.save_response(self.ctl[0].questionnaire_assignments.get(questionnaire=q), self.answers(pu1=3, pu2=3, peou=2, text="x"), submit=True)
        draft = self.ctl[1].questionnaire_assignments.get(questionnaire=q)
        q_services.save_response(draft, self.answers(), submit=False)
        text = exports.dataset_csv(exports.DATASET_BY_KEY["questionnaire_responses"], self.study)[0]
        self.assertNotIn("0700", text)
        rows = parse(text)
        self.assertEqual(len(rows), 2 * 5)                                     # 5 questions x 2 submitted responses; the draft is excluded
        mine = [r for r in rows if r["research_code"] == self.ivg[0].research_code]
        pu2 = next(r for r in mine if r["question_text"].startswith("PU item two"))
        self.assertEqual((pu2["likert_value"], pu2["scored_value"], pu2["reverse_scored"], pu2["construct"]), ("2", "4", "yes", "PU"))
        self.assertEqual(next(r for r in mine if r["question_type"] == "text")["text_provided"], "yes")
        scores = parse(exports.dataset_csv(exports.DATASET_BY_KEY["construct_scores"], self.study)[0])
        pu = next(r for r in scores if r["research_code"] == self.ivg[0].research_code and r["construct"] == "PU")
        self.assertEqual((pu["score"], pu["complete"], pu["items_in_construct"]), ("4.5", "yes", "2"))

    def test_reminder_events_export(self):
        now = timezone.now() - timedelta(days=20)   # inside the fixture's post-intervention window
        Notification.objects.create(recipient=self.ivg[0].student.user, session=self.past_session(), kind=NotificationKind.REMINDER, minutes_before=60,
                                    title="r", message="m", scheduled_for=now, status=NotificationStatus.DELIVERED, delivered_at=now,
                                    read_at=now + timedelta(minutes=12))
        rows = self.export("reminder_events")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["group"], rows[0]["minutes_before"], rows[0]["is_read"], rows[0]["minutes_to_read"]), ("intervention", "60", "yes", "12"))
        self.assertTrue(rows[0]["delivered_at"].endswith("+03:00"))

    def test_quality_report_export(self):
        rows = parse(exports.quality_csv(self.study)[0])
        self.assertEqual(set(rows[0]) if rows else {f.name for f in exports.QUALITY_FIELDS}, {f.name for f in exports.QUALITY_FIELDS})


# ---- Pages and permissions -----------------------------------------------------------------------------------------------------
class PermissionAndPageTests(AnalyticsFixtureMixin, TestCase):
    def urls(self):
        return [reverse("analytics:dashboard"), reverse("analytics:analysis"), reverse("analytics:exports"),
                reverse("analytics:dictionary"), reverse("analytics:dictionary_csv")]

    def test_anonymous_users_are_sent_to_login(self):
        for url in self.urls() + [reverse("analytics:export_download", args=["participants"])]:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/login", resp["Location"])

    def test_only_researchers_can_open_analytics_or_download(self):
        for user in (self.admin, self.lec_user, self.stu_user):
            self.login(user)
            for url in self.urls():
                self.assertEqual(self.client.get(url).status_code, 403, (user.username, url))
            self.assertEqual(self.client.post(reverse("analytics:export_download", args=["participants"])).status_code, 403, user.username)
            self.client.logout()
        self.assertFalse(AuditLog.objects.filter(action="research_export").exists())

    def test_pages_render_for_a_researcher_with_and_without_data(self):
        self.login(self.researcher)
        for url in self.urls():
            self.assertEqual(self.client.get(url).status_code, 200, url)
        groups = self.people(6, 6)
        self.fill(self.attendance_outcome, groups[Group.INTERVENTION], groups[Group.CONTROL], IVG_PAIRS, CTL_PAIRS)
        q = self.build()
        q_services.assign_questionnaire(q, self.researcher, target="all")
        for p in groups[Group.INTERVENTION] + groups[Group.CONTROL]:
            q_services.save_response(p.questionnaire_assignments.get(questionnaire=q), self.answers(pu1=3 + p.pk % 3), submit=True)
        for url in self.urls():
            self.assertEqual(self.client.get(url).status_code, 200, url)
        resp = self.client.get(reverse("analytics:analysis"))
        self.assertContains(resp, "does not prove that the reminders caused")
        self.assertContains(resp, "Mann-Whitney U test")
        self.assertContains(resp, "Cronbach")
        dash = self.client.get(reverse("analytics:dashboard"))
        self.assertContains(dash, "groupChart")
        self.assertEqual(dash.context["groups"][Group.INTERVENTION], 6)

    def test_insufficient_data_message_is_shown(self):
        self.login(self.researcher)
        self.assertContains(self.client.get(reverse("analytics:analysis")), "Analysis not yet available")

    def test_without_an_active_study_researchers_are_sent_to_the_study_list(self):
        from apps.research.models import ResearchStudy
        ResearchStudy.objects.update(is_active=False)
        self.login(self.researcher)
        for url in self.urls():
            resp = self.client.get(url)
            self.assertRedirects(resp, reverse("research:study_list"))

    def test_downloads_are_post_only_audited_and_not_cached(self):
        self.people(1, 1)
        self.login(self.researcher)
        url = reverse("analytics:export_download", args=["participants"])
        self.assertEqual(self.client.get(url).status_code, 405)
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment; filename=\"miu-lrses-participants-", resp["Content-Disposition"])
        self.assertEqual(resp["Cache-Control"], "no-store")
        self.assertEqual(len(parse(resp.content.decode())), 2)
        entry = AuditLog.objects.filter(action="research_export").latest("timestamp")
        self.assertEqual((entry.target, entry.actor), ("participants", self.researcher))
        self.assertNotIn("P-", entry.details)
        self.assertEqual(self.client.post(reverse("analytics:export_download", args=["data_quality_report"])).status_code, 200)
        self.assertEqual(self.client.post(reverse("analytics:export_download", args=["nope"])).status_code, 404)

    def test_downloads_require_csrf_token(self):
        from django.test import Client
        strict = Client(enforce_csrf_checks=True)
        strict.login(username=self.researcher.username, password=PW)
        self.assertEqual(strict.post(reverse("analytics:export_download", args=["participants"])).status_code, 403)

    def test_dictionary_csv_download(self):
        self.login(self.researcher)
        resp = self.client.get(reverse("analytics:dictionary_csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(parse(resp.content.decode())[0]), ["dataset", "field", "meaning", "permitted_values", "how_calculated"])

    def test_minimum_n_setting_is_editable_and_validated(self):
        base = {"title": "x", "status": "planning", "ethics_status": "not_recorded", "population_size": 350, "target_sample_size": 156,
                "target_intervention": 78, "target_control": 78, "intervention_weeks": 8, "eligible_year_min": 1, "eligible_year_max": 2,
                "significance_level": "0.050"}
        self.assertTrue(ResearchStudyForm(dict(base, min_analysis_n=10)).is_valid())
        self.assertFalse(ResearchStudyForm(dict(base, min_analysis_n=2)).is_valid())
        self.assertEqual(self.study.__class__(title="d").min_analysis_n, 10)
