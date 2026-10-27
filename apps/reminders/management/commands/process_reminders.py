from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.reminders import services
from apps.reminders.models import ReminderConfig, RunStatus


class Command(BaseCommand):
    help = ("Schedule and deliver due lecture reminders to the in-app notification system. "
            "Safe to run repeatedly (for example every 5 minutes from Windows Task Scheduler): "
            "a reminder is never created or delivered twice.")

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Only report how many reminders are due. Changes nothing and records no run.")
        parser.add_argument("--no-sync", action="store_true",
                            help="Skip re-synchronising reminders with enrolments and intervals; only deliver due ones.")

    def handle(self, *args, **options):
        now = timezone.now()
        if options["dry_run"]:
            enabled = ReminderConfig.get().reminders_enabled
            due = services.due_reminders(now).count()
            self.stdout.write(f"[dry run] reminders enabled: {'yes' if enabled else 'NO'}; due now: {due}. Nothing was changed.")
            return

        run = services.process_due_reminders(now=now, trigger="command", sync=not options["no_sync"])
        if run.status == RunStatus.DISABLED:
            self.stdout.write(self.style.WARNING(run.notes))
            return
        self.stdout.write(
            f"Run {run.pk} at {timezone.localtime(now):%Y-%m-%d %H:%M:%S} (Africa/Kampala)\n"
            f"  Synchronised: {run.sync_created} scheduled, {run.sync_updated} updated, {run.sync_cancelled} cancelled\n"
            f"  Due: {run.due_found} | delivered: {run.delivered} | expired: {run.expired} | "
            f"cancelled: {run.cancelled} | failed: {run.failed} | already handled: {run.skipped}\n"
            "  Delivery is to the in-app notification system only.")
        if run.failed:
            self.stdout.write(run.notes)
            raise CommandError(f"{run.failed} reminder(s) failed to deliver. Failed reminders are retried on the next run.")
