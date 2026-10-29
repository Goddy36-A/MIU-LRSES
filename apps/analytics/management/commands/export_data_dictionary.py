from pathlib import Path

from django.core.management.base import BaseCommand

from apps.analytics.exports import dictionary_markdown


class Command(BaseCommand):
    help = "Write the research data dictionary as Markdown (default: docs/DATA_DICTIONARY.md)."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="docs/DATA_DICTIONARY.md")

    def handle(self, *args, **options):
        path = Path(options["output"])
        path.write_text(dictionary_markdown(), encoding="utf-8")
        self.stdout.write(f"Wrote {path}")
