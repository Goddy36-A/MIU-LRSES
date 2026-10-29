"""Phase 6 tests: questionnaires, TAM constructs, assignment, student answering, completeness and reports, permissions.

Test fixtures only. Nothing here is a research finding.
"""
from django.contrib.auth.models import Group as AuthGroup
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.academics.models import StudentProfile
from apps.academics.tests import PW, make_user
from apps.accounts.models import AuditLog, Role
from apps.research import services as research_services
from apps.research.models import Group
from apps.research.tests import ResearchFixtureMixin, days

from . import services
from .models import (Answer, Assignment, Option, Question, QuestionType, Questionnaire, QuestionnaireStatus, Response, ResponseStatus)


class QFixtureMixin(ResearchFixtureMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.stu3_user = make_user("stu3", Role.STUDENT)
        cls.student3 = StudentProfile.objects.create(user=cls.stu3_user, registration_number="S003", programme=cls.programme)

    def build(self, *, open_=True, approve=True, extra=True):
        """Draft questionnaire with 2 PU items (one reverse scored), 1 PEOU, 1 choice, 1 optional text."""
        q = Questionnaire.objects.create(study=self.study, title="TAM test questionnaire", created_by=self.researcher)
        specs = [("PU", "PU item one", False), ("PU", "PU item two (negative)", True), ("PEOU", "PEOU item", False)]
        self.items = []
        for i, (c, t, rev) in enumerate(specs, start=1):
            self.items.append(Question.objects.create(questionnaire=q, order=i, text=t, qtype="likert", construct=c, reverse_scored=rev))
        if extra:
            self.choice = Question.objects.create(questionnaire=q, order=4, text="Which device?", qtype="choice", required=True)
            Option.objects.create(question=self.choice, order=1, label="Phone")
            Option.objects.create(question=self.choice, order=2, label="Laptop")
            self.text = Question.objects.create(questionnaire=q, order=5, text="Comments", qtype="text", required=False)
        if approve:
            services.approve_items(q, self.researcher)
        if open_:
            services.open_questionnaire(q, self.researcher)
        return q

    def answers(self, pu1=4, pu2=2, peou=5, choice=True, text="Fine"):
        a = {self.items[0].pk: pu1, self.items[1].pk: pu2, self.items[2].pk: peou}
        if hasattr(self, "choice"):
            a[self.choice.pk] = self.choice.options.first().pk if choice else None
            a[self.text.pk] = text
        return a


# ---- Building and approval --------------------------------------------------------------------------------------------------
class BuildingTests(QFixtureMixin, TestCase):
    def test_a_questionnaire_cannot_be_opened_until_a_researcher_approves_the_items(self):
        q = self.build(open_=False, approve=False)
        self.assertFalse(q.items_approved)
        with self.assertRaises(ValidationError) as ctx:
            services.open_questionnaire(q, self.researcher)
        self.assertIn("approve the items", " ".join(ctx.exception.messages))
        services.approve_items(q, self.researcher)
        q.refresh_from_db()
        self.assertTrue(q.items_approved)
        self.assertEqual(q.approved_by, self.researcher)
        services.open_questionnaire(q, self.researcher)

    def test_no_questionnaire_content_ships_with_the_system(self):
        self.assertEqual(Questionnaire.objects.count(), 0)
        self.assertEqual(Question.objects.count(), 0)

    def test_cannot_open_without_questions_or_with_a_one_option_choice(self):
        q = Questionnaire.objects.create(study=self.study, title="Empty")
        with self.assertRaises(ValidationError):
            services.approve_items(q, self.researcher)
        c = Question.objects.create(questionnaire=q, order=1, text="Pick", qtype="choice")
        Option.objects.create(question=c, order=1, label="Only")
        services.approve_items(q, self.researcher)
        with self.assertRaises(ValidationError):
            services.open_questionnaire(q, self.researcher)

    def test_choice_question_needs_two_distinct_options(self):
        q = Questionnaire.objects.create(study=self.study, title="x")
        for text in ("One", "A\nA"):
            with self.assertRaises(ValidationError):
                services.save_question(Question(questionnaire=q, order=1, text="Pick", qtype="choice"), options_text=text)
        services.save_question(Question(questionnaire=q, order=1, text="Pick", qtype="choice"), options_text="Yes\nNo")
        self.assertEqual(Option.objects.count(), 2)

    def test_only_likert_items_can_have_a_construct_and_text_is_optional(self):
        with self.assertRaises(ValidationError):
            Question(order=1, text="x", qtype="choice", construct="PU").full_clean(exclude=["questionnaire"])
        with self.assertRaises(ValidationError):
            Question(order=1, text="x", qtype="text", required=True).full_clean(exclude=["questionnaire"])

    def test_editing_items_withdraws_approval(self):
        q = self.build(open_=False)
        self.assertTrue(q.items_approved)
        services.save_question(Question(questionnaire=q, order=9, text="New", qtype="likert"))
        q.refresh_from_db()
        self.assertFalse(q.items_approved)
        with self.assertRaises(ValidationError):
            services.open_questionnaire(q, self.researcher)

    def test_items_cannot_change_once_opened_but_can_be_duplicated(self):
        q = self.build()
        with self.assertRaises(ValidationError):
            services.save_question(Question(questionnaire=q, order=9, text="Late", qtype="likert"))
        with self.assertRaises(ValidationError):
            services.delete_question(self.items[0])
        copy = services.duplicate_questionnaire(q, self.researcher)
        self.assertEqual((copy.status, copy.items_approved), ("draft", False))
        self.assertEqual(copy.questions.count(), q.questions.count())
        self.assertEqual(Option.objects.filter(question__questionnaire=copy).count(), 2)
        self.assertEqual(copy.assignments.count(), 0)

    def test_open_close_and_reopen(self):
        q = self.build()
        with self.assertRaises(ValidationError):
            services.open_questionnaire(q, self.researcher)
        services.close_questionnaire(q, self.researcher)
        q.refresh_from_db()
        self.assertEqual(q.status, "closed")
        with self.assertRaises(ValidationError):
            services.close_questionnaire(q, self.researcher)
        services.open_questionnaire(q, self.researcher)

    def test_audit_entries_name_the_questionnaire_not_participants(self):
        q = self.build()
        self.enrol(self.student, Group.INTERVENTION)
        services.assign_questionnaire(q, self.researcher, target="all")
        for entry in AuditLog.objects.filter(action__startswith="questionnaire_"):
            self.assertNotIn(self.student.registration_number, entry.target + entry.details)
            self.assertNotIn("P-", entry.target + entry.details)


# ---- Assignment -----------------------------------------------------------------------------------------------------------------
class AssignmentTests(QFixtureMixin, TestCase):
    def test_nothing_is_assigned_automatically(self):
        self.enrol(self.student, Group.INTERVENTION)
        self.build()
        self.assertEqual(Assignment.objects.count(), 0)

    def test_only_open_questionnaires_can_be_assigned(self):
        self.enrol(self.student)
        q = self.build(open_=False)
        with self.assertRaises(ValidationError):
            services.assign_questionnaire(q, self.researcher, target="all")

    def test_assigns_only_enrolled_consenting_participants_and_is_idempotent(self):
        a = self.enrol(self.student, Group.INTERVENTION)
        self.register(self.student2)                     # registered, not enrolled
        w = self.enrol(self.student3)
        research_services.withdraw_participant(w, self.researcher, withdrawn_on=days(0), data_handling="retain")
        q = self.build()
        self.assertEqual(services.assign_questionnaire(q, self.researcher, target="all"), (1, 0))
        self.assertEqual(list(Assignment.objects.values_list("participant", flat=True)), [a.pk])
        self.assertEqual(services.assign_questionnaire(q, self.researcher, target="all"), (0, 1))
        self.assertEqual(Assignment.objects.count(), 1)

    def test_group_targets(self):
        i = self.enrol(self.student, Group.INTERVENTION)
        c = self.enrol(self.student2, Group.CONTROL)
        q = self.build()
        services.assign_questionnaire(q, self.researcher, target="intervention")
        self.assertEqual(set(Assignment.objects.values_list("participant", flat=True)), {i.pk})
        services.assign_questionnaire(q, self.researcher, target="control")
        self.assertEqual(set(Assignment.objects.values_list("participant", flat=True)), {i.pk, c.pk})
        with self.assertRaises(ValidationError):
            services.assign_questionnaire(q, self.researcher, target="everyone")

    def test_database_blocks_duplicate_assignments(self):
        p = self.enrol(self.student)
        q = self.build()
        Assignment.objects.create(questionnaire=q, participant=p)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Assignment.objects.create(questionnaire=q, participant=p)


# ---- Answering --------------------------------------------------------------------------------------------------------------------
class AnsweringTests(QFixtureMixin, TestCase):
    def setUp(self):
        self.p = self.enrol(self.student, Group.INTERVENTION)
        self.q = self.build()
        services.assign_questionnaire(self.q, self.researcher, target="all")
        self.a = Assignment.objects.get(participant=self.p)

    def save(self, answers, submit=True):
        return services.save_response(self.a, answers, submit=submit)

    def test_full_submission_stores_answers_timestamps_and_locks(self):
        r = self.save(self.answers())
        self.assertEqual((r.status, r.is_submitted), ("submitted", True))
        self.assertIsNotNone(r.submitted_at)
        self.assertLessEqual(r.started_at, r.submitted_at)
        self.assertEqual(r.answers.count(), 5)
        self.assertEqual(r.answers.get(question=self.items[0]).likert_value, 4)
        self.assertEqual(r.answers.get(question=self.choice).option.label, "Phone")
        with self.assertRaises(ValidationError):
            self.save(self.answers(pu1=1))
        self.assertEqual(Answer.objects.get(question=self.items[0]).likert_value, 4)

    def test_draft_can_be_partial_and_resumed(self):
        r = self.save({self.items[0].pk: 3}, submit=False)
        self.assertEqual((r.status, r.submitted_at), ("draft", None))
        self.save({self.items[0].pk: 5, self.items[1].pk: 1}, submit=False)
        self.assertEqual(Response.objects.count(), 1)
        self.assertEqual(Answer.objects.get(question=self.items[0]).likert_value, 5)

    def test_submission_requires_every_required_question_and_saves_nothing_on_failure(self):
        self.save({self.items[0].pk: 3}, submit=False)
        with self.assertRaises(ValidationError) as ctx:
            self.save(self.answers(peou=None, choice=False))
        self.assertIn("question 3, 4", ctx.exception.messages[0])
        self.assertEqual(Response.objects.get().status, "draft")
        self.assertEqual(Answer.objects.count(), 1)           # the earlier draft answer is untouched

    def test_optional_text_may_be_skipped(self):
        r = self.save(self.answers(text=""))
        self.assertTrue(r.is_submitted)
        self.assertFalse(r.answers.filter(question=self.text).exists())

    def test_invalid_answers_are_rejected(self):
        for bad in ({self.items[0].pk: 6}, {self.items[0].pk: 0}, {self.items[0].pk: "abc"},
                    {self.choice.pk: 999999}, {self.text.pk: "x" * 2001}):
            with self.assertRaises(ValidationError, msg=bad):
                self.save(bad, submit=False)
        self.assertEqual(Answer.objects.count(), 0)

    def test_option_from_another_question_is_rejected(self):
        other = Question.objects.create(questionnaire=Questionnaire.objects.create(study=self.study, title="o"), order=1, text="o", qtype="choice")
        stray = Option.objects.create(question=other, order=1, label="Stray")
        with self.assertRaises(ValidationError):
            self.save({self.choice.pk: stray.pk}, submit=False)

    def test_blank_clears_a_draft_answer(self):
        self.save({self.items[0].pk: 3}, submit=False)
        self.save({self.items[0].pk: ""}, submit=False)
        self.assertEqual(Answer.objects.count(), 0)

    def test_closed_questionnaire_rejects_answers(self):
        services.close_questionnaire(self.q, self.researcher)
        with self.assertRaises(ValidationError):
            self.save(self.answers())

    def test_withdrawn_participant_cannot_answer(self):
        research_services.withdraw_participant(self.p, self.researcher, withdrawn_on=days(0), data_handling="retain")
        with self.assertRaises(ValidationError):
            self.save(self.answers())

    def test_database_rules(self):
        r = self.save({self.items[0].pk: 3}, submit=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Answer.objects.create(response=r, question=self.items[0], likert_value=2)    # duplicate answer
        with self.assertRaises(IntegrityError), transaction.atomic():
            Answer.objects.create(response=r, question=self.items[1], likert_value=7)    # outside 1-5
        with self.assertRaises(IntegrityError), transaction.atomic():
            Response.objects.filter(pk=r.pk).update(status="submitted")                  # submitted without a timestamp

    def test_one_response_per_assignment(self):
        self.save({self.items[0].pk: 3}, submit=False)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Response.objects.create(assignment=self.a)


# ---- Scores, completeness and reports ---------------------------------------------------------------------------------------------------
class ReportingTests(QFixtureMixin, TestCase):
    def setUp(self):
        self.pi = self.enrol(self.student, Group.INTERVENTION)
        self.pc = self.enrol(self.student2, Group.CONTROL)
        self.q = self.build()
        services.assign_questionnaire(self.q, self.researcher, target="all")

    def submit(self, p, **kw):
        return services.save_response(Assignment.objects.get(participant=p, questionnaire=self.q), self.answers(**kw), submit=True)

    def test_reverse_scoring_and_complete_case_construct_scores(self):
        r = self.submit(self.pi, pu1=4, pu2=2, peou=5)      # PU = mean(4, 6-2=4) = 4; PEOU = 5
        scores = services.response_construct_scores(list(self.q.questions.all()), r.answers.all())
        self.assertEqual(scores, {"PU": 4, "PEOU": 5})

    def test_a_skipped_optional_likert_item_means_no_construct_score(self):
        self.items[1].required = False
        self.items[1].save()
        r = services.save_response(Assignment.objects.get(participant=self.pi), {**self.answers(), self.items[1].pk: ""}, submit=True)
        scores = services.response_construct_scores(list(self.q.questions.all()), r.answers.all())
        self.assertEqual((scores["PU"], scores["PEOU"]), (None, 5))

    def test_group_summaries_report_n_mean_and_spread(self):
        self.submit(self.pi, pu1=5, pu2=1)                  # PU = mean(5, 5) = 5
        self.submit(self.pc, pu1=3, pu2=3)                  # PU = mean(3, 3) = 3
        pu = next(c for c in services.construct_summaries(self.q) if c["construct"] == "PU")
        groups = dict(pu["groups"])
        self.assertEqual((groups["Intervention"]["n"], groups["Intervention"]["mean"]), (1, 5))
        self.assertEqual((groups["Control"]["n"], groups["Control"]["mean"]), (1, 3))
        self.assertIsNone(groups["Control"]["sd"])           # a spread from one value is not reported
        self.assertEqual((pu["overall"]["n"], pu["overall"]["mean"], pu["overall"]["sd"]), (2, 4, 1.41))

    def test_no_responses_means_no_scores(self):
        for c in services.construct_summaries(self.q):
            self.assertEqual((c["overall"]["n"], c["overall"]["mean"], c["groups"]), (0, None, []))

    def test_drafts_are_not_counted(self):
        services.save_response(Assignment.objects.get(participant=self.pi), self.answers(), submit=False)
        self.assertEqual(services.completeness(self.q)["usable"], 0)
        self.assertEqual(services.completeness(self.q)["in_progress"], 1)

    def test_withdrawn_with_exclude_is_left_out_but_retain_is_kept(self):
        self.submit(self.pi)
        self.submit(self.pc)
        research_services.withdraw_participant(self.pi, self.researcher, withdrawn_on=days(0), data_handling="exclude")
        research_services.withdraw_participant(self.pc, self.researcher, withdrawn_on=days(0), data_handling="retain")
        c = services.completeness(self.q)
        self.assertEqual((c["usable"], c["withdrawn"], c["eligible_to_answer"]), (1, 2, 0))
        self.assertIsNone(c["response_rate"])                # nobody left who could respond

    def test_completeness_counts_and_response_rate(self):
        self.submit(self.pi)
        c = services.completeness(self.q)
        self.assertEqual((c["assigned"], c["submitted"], c["in_progress"], c["not_started"], c["response_rate"]), (2, 1, 0, 1, 50.0))
        by_q = {r["question"].order: r for r in c["questions"]}
        self.assertEqual((by_q[1]["answered"], by_q[5]["answered"], by_q[5]["skipped"]), (1, 1, 0))

    def test_question_summaries_count_each_answer(self):
        self.submit(self.pi, pu1=4)
        self.submit(self.pc, pu1=4)
        s = services.question_summaries(self.q)
        first = next(x for x in s if x["question"].order == 1)
        self.assertEqual((first["n"], first["mean"]), (2, 4))
        self.assertEqual(dict((v, n) for v, _l, n in first["counts"])[4], 2)
        device = next(x for x in s if x["question"].order == 4)
        self.assertEqual(dict((l, n) for _k, l, n in device["counts"]), {"Phone": 2, "Laptop": 0})


# ---- Permissions --------------------------------------------------------------------------------------------------------------------
class PermissionTests(QFixtureMixin, TestCase):
    def setUp(self):
        self.p = self.enrol(self.student, Group.INTERVENTION)
        self.p2 = self.enrol(self.student2, Group.CONTROL)
        self.q = self.build()
        services.assign_questionnaire(self.q, self.researcher, target="all")
        self.a = Assignment.objects.get(participant=self.p)
        self.a2 = Assignment.objects.get(participant=self.p2)
        self.draft = Questionnaire.objects.create(study=self.study, title="A draft")

    def researcher_urls(self):
        q, d = self.q.pk, self.draft.pk
        return [reverse("questionnaires:list"), reverse("questionnaires:add"), reverse("questionnaires:detail", args=[q]),
                reverse("questionnaires:edit", args=[d]), reverse("questionnaires:question_add", args=[d]),
                reverse("questionnaires:responses", args=[q]), reverse("questionnaires:response_detail", args=[self.a.pk]),
                reverse("questionnaires:report", args=[q])]

    def get(self, user, url):
        self.client.logout()
        if user:
            self.client.login(username=user.username, password=PW)
        return self.client.get(url)

    def test_anonymous_goes_to_login(self):
        for url in self.researcher_urls() + [reverse("questionnaires:my_list"), reverse("questionnaires:fill", args=[self.a.pk])]:
            r = self.get(None, url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn(reverse("accounts:login"), r["Location"])

    def test_only_researchers_open_researcher_pages(self):
        for user in (self.admin, self.lec_user, self.stu_user):
            for url in self.researcher_urls():
                self.assertEqual(self.get(user, url).status_code, 403, (user.role, url))
        for url in self.researcher_urls():
            self.assertEqual(self.get(self.researcher, url).status_code, 200, url)

    def test_state_changing_posts_are_researcher_only(self):
        for user in (self.admin, self.lec_user, self.stu_user):
            self.client.login(username=user.username, password=PW)
            for name, args in [("action", [self.q.pk, "close"]), ("question_delete", [self.q.pk, self.items[0].pk])]:
                self.assertEqual(self.client.post(reverse(f"questionnaires:{name}", args=args)).status_code, 403, (user.role, name))
            self.client.logout()
        self.q.refresh_from_db()
        self.assertEqual(self.q.status, "open")

    def test_researcher_pages_are_not_for_students_and_student_pages_not_for_others(self):
        for user in (self.admin, self.lec_user, self.researcher):
            self.assertEqual(self.get(user, reverse("questionnaires:my_list")).status_code, 403)
            self.assertEqual(self.get(user, reverse("questionnaires:fill", args=[self.a.pk])).status_code, 403)

    def test_student_sees_only_their_own_assignment(self):
        r = self.get(self.stu_user, reverse("questionnaires:my_list"))
        self.assertEqual([a.pk for a in r.context["assignments"]], [self.a.pk])
        self.assertEqual(self.get(self.stu_user, reverse("questionnaires:fill", args=[self.a.pk])).status_code, 200)
        self.assertEqual(self.get(self.stu_user, reverse("questionnaires:fill", args=[self.a2.pk])).status_code, 404)

    def test_student_cannot_answer_someone_elses_assignment(self):
        self.client.login(username=self.stu_user.username, password=PW)
        r = self.client.post(reverse("questionnaires:fill", args=[self.a2.pk]), {"submit": "1"})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(Response.objects.exists())

    def test_unassigned_student_sees_nothing(self):
        self.enrol(self.student3)
        r = self.get(self.stu3_user, reverse("questionnaires:my_list"))
        self.assertEqual(list(r.context["assignments"]), [])
        self.assertEqual(self.get(self.stu3_user, reverse("questionnaires:fill", args=[self.a.pk])).status_code, 404)

    def test_withdrawn_student_loses_access(self):
        research_services.withdraw_participant(self.p, self.researcher, withdrawn_on=days(0), data_handling="retain")
        self.assertEqual(self.get(self.stu_user, reverse("questionnaires:fill", args=[self.a.pk])).status_code, 404)

    def test_closed_questionnaire_hidden_from_students_unless_already_submitted(self):
        services.save_response(self.a, self.answers(), submit=True)
        services.close_questionnaire(self.q, self.researcher)
        self.assertEqual(self.get(self.stu_user, reverse("questionnaires:fill", args=[self.a.pk])).status_code, 200)   # own submitted answers
        self.assertEqual(self.get(self.stu2_user, reverse("questionnaires:fill", args=[self.a2.pk])).status_code, 404)  # never answered

    def answers(self):
        return {self.items[0].pk: 4, self.items[1].pk: 2, self.items[2].pk: 5, self.choice.pk: self.choice.options.first().pk}

    def test_researcher_lists_show_codes_not_names(self):
        r = self.get(self.researcher, reverse("questionnaires:responses", args=[self.q.pk]))
        self.assertContains(r, self.p.research_code)
        self.assertNotContains(r, self.student.registration_number)
        self.assertNotContains(r, self.stu_user.display_name())
        r = self.get(self.researcher, reverse("questionnaires:response_detail", args=[self.a.pk]))
        self.assertNotContains(r, self.student.registration_number)

    def test_student_pages_do_not_reveal_group_or_code(self):
        r = self.get(self.stu_user, reverse("questionnaires:fill", args=[self.a.pk]))
        self.assertNotContains(r, self.p.research_code)
        self.assertNotContains(r, "Intervention")

    def test_researcher_cannot_open_another_studys_questionnaire(self):
        from apps.research.models import ResearchStudy
        other = ResearchStudy.objects.create(title="Other", is_active=True)
        self.assertEqual(self.get(self.researcher, reverse("questionnaires:detail", args=[self.q.pk])).status_code, 404)
        self.assertEqual(other.questionnaires.count(), 0)

    def test_administrator_group_has_no_questionnaire_permissions(self):
        self.assertFalse(AuthGroup.objects.filter(permissions__content_type__app_label="questionnaires").exists())
        self.assertFalse(self.admin.has_perm("questionnaires.view_response"))
        self.assertFalse(self.admin.has_perm("questionnaires.view_answer"))


# ---- End-to-end through the pages ---------------------------------------------------------------------------------------------------
class WorkflowTests(QFixtureMixin, TestCase):
    def test_researcher_builds_approves_opens_assigns_student_answers_researcher_reads(self):
        self.enrol(self.student, Group.INTERVENTION)
        self.client.login(username=self.researcher.username, password=PW)
        r = self.client.post(reverse("questionnaires:add"), {"title": "Form made", "instructions": "Please answer", "research_question": "RQ", "period": "post_intervention"})
        q = Questionnaire.objects.get(title="Form made")
        self.assertRedirects(r, reverse("questionnaires:detail", args=[q.pk]))
        self.client.post(reverse("questionnaires:question_add", args=[q.pk]), {"order": 1, "text": "Useful?", "qtype": "likert", "construct": "PU", "required": "on"})
        self.client.post(reverse("questionnaires:question_add", args=[q.pk]), {"order": 2, "text": "Device?", "qtype": "choice", "required": "on", "options_text": "Phone\nLaptop"})
        self.assertEqual(q.questions.count(), 2)
        self.client.post(reverse("questionnaires:action", args=[q.pk, "approve"]))
        self.client.post(reverse("questionnaires:action", args=[q.pk, "open"]))
        self.client.post(reverse("questionnaires:action", args=[q.pk, "assign"]), {"target": "all"})
        q.refresh_from_db()
        self.assertEqual((q.status, q.items_approved, q.assignments.count()), ("open", True, 1))

        self.client.logout()
        self.client.login(username=self.stu_user.username, password=PW)
        self.assertEqual(self.client.get(reverse("accounts:dashboard_student")).context["pending_questionnaires"], 1)
        a = Assignment.objects.get()
        likert, choice = q.questions.get(order=1), q.questions.get(order=2)
        r = self.client.post(reverse("questionnaires:fill", args=[a.pk]), {f"q{likert.pk}": "4", "submit": "1"})
        self.assertEqual(r.status_code, 200)                                  # choice question missing: re-shown with a message
        self.assertContains(r, "Missing: question 2")
        r = self.client.post(reverse("questionnaires:fill", args=[a.pk]), {f"q{likert.pk}": "4", f"q{choice.pk}": str(choice.options.first().pk), "submit": "1"})
        self.assertRedirects(r, reverse("questionnaires:my_list"))
        self.assertEqual(self.client.get(reverse("accounts:dashboard_student")).context["pending_questionnaires"], 0)

        self.client.logout()
        self.client.login(username=self.researcher.username, password=PW)
        report = self.client.get(reverse("questionnaires:report", args=[q.pk]))
        self.assertEqual(report.context["completeness"]["submitted"], 1)
        self.assertContains(report, "Perceived Usefulness")
        detail = self.client.get(reverse("questionnaires:response_detail", args=[a.pk]))
        self.assertContains(detail, "Phone")

    def test_save_for_later_keeps_partial_answers_and_shows_them_again(self):
        p = self.enrol(self.student, Group.INTERVENTION)
        q = self.build()
        services.assign_questionnaire(q, self.researcher, target="all")
        a = Assignment.objects.get(participant=p)
        self.client.login(username=self.stu_user.username, password=PW)
        self.client.post(reverse("questionnaires:fill", args=[a.pk]), {f"q{self.items[0].pk}": "3", "save": "1"})
        self.assertEqual(Response.objects.get().status, ResponseStatus.DRAFT)
        r = self.client.get(reverse("questionnaires:fill", args=[a.pk]))
        self.assertRegex(r.content.decode(), r'name="q%d" value="3" id="[^"]+" checked' % self.items[0].pk)

    def test_editing_an_opened_questionnaire_through_the_page_is_refused(self):
        q = self.build()
        self.client.login(username=self.researcher.username, password=PW)
        r = self.client.get(reverse("questionnaires:edit", args=[q.pk]), follow=True)
        self.assertContains(r, "Only a draft")
        r = self.client.post(reverse("questionnaires:question_edit", args=[q.pk, self.items[0].pk]), {"order": 1, "text": "Changed", "qtype": "likert", "required": "on"})
        self.items[0].refresh_from_db()
        self.assertEqual(self.items[0].text, "PU item one")

    def test_report_page_renders_with_data_and_chart(self):
        p = self.enrol(self.student, Group.INTERVENTION)
        q = self.build()
        services.assign_questionnaire(q, self.researcher, target="all")
        services.save_response(Assignment.objects.get(participant=p), self.answers(), submit=True)
        self.client.login(username=self.researcher.username, password=PW)
        r = self.client.get(reverse("questionnaires:report", args=[q.pk]))
        self.assertContains(r, "constructChart")
        self.assertContains(r, "no conclusion follows")
