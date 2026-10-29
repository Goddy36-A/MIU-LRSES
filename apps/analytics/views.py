from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.audit import log_action
from apps.research.views import ActiveStudyMixin

from . import exports, services


def _download(text, filename):
    response = HttpResponse(text, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


class DashboardView(ActiveStudyMixin, TemplateView):
    """Research dashboard. Researchers only: it contains participant-level aggregates and group results."""

    template_name = "analytics/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(services.dashboard(self.study))
        return ctx


class AnalysisView(ActiveStudyMixin, TemplateView):
    template_name = "analytics/analysis.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.research.models import OutcomeDefinition
        ctx.update(study=self.study, design_note=services.DESIGN_NOTE, alpha=services.alpha_of(self.study), ci_level=services.ci_level(services.alpha_of(self.study)),
                   outcomes=[services.analyse_outcome(self.study, o) for o in OutcomeDefinition.objects.filter(study=self.study, is_active=True)],
                   tam=services.analyse_tam(self.study))
        return ctx


class ExportsView(ActiveStudyMixin, TemplateView):
    template_name = "analytics/exports.html"

    def get_context_data(self, **kwargs):
        from . import quality
        ctx = super().get_context_data(**kwargs)
        ctx.update(study=self.study, datasets=[{"dataset": d, "rows": sum(1 for _ in d.rows(self.study))} for d in exports.DATASETS],
                   issues=quality.data_quality_issues(self.study))
        return ctx


class ExportDownloadView(ActiveStudyMixin, View):
    """POST only (with CSRF protection): every export is written to the audit log with its row count and no participant data."""

    http_method_names = ["post"]

    def post(self, request, key):
        stamp = timezone.localdate().strftime("%Y%m%d")
        if key == "data_quality_report":
            text, count = exports.quality_csv(self.study)
        else:
            dataset = exports.DATASET_BY_KEY.get(key)
            if dataset is None:
                from django.http import Http404
                raise Http404("Unknown dataset.")
            text, count = exports.dataset_csv(dataset, self.study)
        log_action("research_export", actor=request.user, target=key, details=f"{count} row(s); study id {self.study.pk}", request=request)
        return _download(text, f"miu-lrses-{key.replace('_', '-')}-{stamp}.csv")


class DictionaryView(ActiveStudyMixin, TemplateView):
    template_name = "analytics/dictionary.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(datasets=exports.DATASETS, quality_fields=exports.QUALITY_FIELDS)
        return ctx


class DictionaryCsvView(ActiveStudyMixin, View):
    def get(self, request):
        return _download(exports.dictionary_csv(), "miu-lrses-data-dictionary.csv")
