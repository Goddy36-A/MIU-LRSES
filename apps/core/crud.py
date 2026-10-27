"""Small generic list/create/update views for administrator-managed records.

Keeps the many simple management pages consistent and avoids duplicated code.
Permissions are enforced server-side through RoleRequiredMixin.
"""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.views.generic import CreateView, ListView, UpdateView

from apps.accounts.audit import log_action
from apps.accounts.models import Role
from apps.accounts.permissions import RoleRequiredMixin


def resolve(obj, accessor):
    """Read a dotted attribute path (or call a function) and format it for display."""
    if callable(accessor):
        value = accessor(obj)
    else:
        value = obj
        for part in accessor.split("."):
            value = getattr(value, part, None)
            if callable(value):
                value = value()
            if value is None:
                break
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    if value is None or value == "":
        return "-"
    return value


class CrudListView(RoleRequiredMixin, ListView):
    allowed_roles = (Role.ADMIN,)
    template_name = "crud/list.html"
    paginate_by = 15
    title = ""
    subtitle = ""
    columns = ()          # [(header, accessor)]
    search_fields = ()    # ORM lookups, matched with icontains
    search_help = ""
    filters = ()          # [(param, lookup, label, choices | None)] ; None = date input
    add_url = None        # url name, or None to hide the Add button
    edit_url = None       # url name taking pk
    detail_url = None     # url name taking pk; first column links to it
    select_related = ()
    empty_text = "Nothing here yet."

    def can_add(self):
        return bool(self.add_url)

    def get_queryset(self):
        qs = super().get_queryset()
        if self.select_related:
            qs = qs.select_related(*self.select_related)
        q = self.request.GET.get("q", "").strip()
        if q and self.search_fields:
            cond = Q()
            for field in self.search_fields:
                cond |= Q(**{f"{field}__icontains": q})
            qs = qs.filter(cond)
        for param, lookup, _label, _choices in self.filters:
            value = self.request.GET.get(param, "").strip()
            if value:
                try:
                    qs = qs.filter(**{lookup: value})
                except (ValueError, ValidationError):
                    continue  # ignore malformed filter input
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        get = self.request.GET
        filters = []
        for param, _lookup, label, choices in self.filters:
            options = choices() if callable(choices) else choices
            filters.append({"param": param, "label": label, "options": options, "selected": get.get(param, "")})
        params = get.copy()
        params.pop("page", None)
        rows = []
        for obj in ctx["object_list"]:
            cells = [resolve(obj, acc) for _h, acc in self.columns]
            rows.append({"obj": obj, "cells": cells})
        ctx.update(
            title=self.title, subtitle=self.subtitle, headers=[h for h, _a in self.columns], rows=rows,
            q=get.get("q", ""), has_search=bool(self.search_fields), search_help=self.search_help,
            filters=filters, querystring=params.urlencode(), add_url=self.add_url if self.can_add() else None,
            edit_url=self.edit_url, detail_url=self.detail_url, empty_text=self.empty_text,
        )
        return ctx


class _AuditedFormMixin:
    allowed_roles = (Role.ADMIN,)
    template_name = "crud/form.html"
    title = ""
    entity = "record"       # label used in messages and audit entries
    submit_label = "Save"
    cancel_url = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(title=self.title, submit_label=self.submit_label, cancel_url=self.cancel_url or self.success_url)
        return ctx

    def _after_save(self, verb):
        log_action(f"{self.entity}_{verb}", actor=self.request.user, target=str(self.object), request=self.request)
        messages.success(self.request, f"{self.entity.replace('_', ' ').capitalize()} {verb}: {self.object}.")


class CrudCreateView(_AuditedFormMixin, RoleRequiredMixin, CreateView):
    submit_label = "Create"

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
        self._after_save("created")
        return response


class CrudUpdateView(_AuditedFormMixin, RoleRequiredMixin, UpdateView):
    submit_label = "Save changes"

    def form_valid(self, form):
        with transaction.atomic():
            response = super().form_valid(form)
        self._after_save("updated")
        return response
