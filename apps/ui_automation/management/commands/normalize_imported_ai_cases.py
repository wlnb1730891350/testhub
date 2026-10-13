"""Normalize imported AI cases and create a reversible JSON audit snapshot."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ui_automation.case_normalizer import normalize_imported_case
from apps.ui_automation.models import AICase
from apps.ui_automation.structured_actions import compile_task_description


def _compile_issues(task_description: str) -> list[str]:
    steps = compile_task_description(task_description)
    issues = []
    if not any(step.get("action_type") == "goto" for step in steps):
        issues.append("missing_goto")
    if not any(step.get("action_type") not in {"goto", "assert"} for step in steps):
        issues.append("missing_executable_action")
    if not any(step.get("action_type") == "assert" for step in steps):
        issues.append("missing_assertion")
    if any((step.get("assertion_contract") or {}).get("kind") == "review_required" for step in steps):
        issues.append("review_required_assertion")
    return issues


class Command(BaseCommand):
    help = "Normalize imported AI cases into the UI runner authoring format."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--name-prefix", default="", help="Only normalize case names with this prefix.")
        parser.add_argument("--apply", action="store_true", help="Persist the normalized descriptions.")
        parser.add_argument("--backup-dir", default="outputs/ai_case_backups")

    def handle(self, *args, **options):
        cases = AICase.objects.filter(project_id=options["project_id"]).order_by("id")
        if options["name_prefix"]:
            cases = cases.filter(name__startswith=options["name_prefix"])
        cases = list(cases)
        if not cases:
            raise CommandError("No matching AI cases found.")

        snapshot = []
        summary = Counter()
        for case in cases:
            result = normalize_imported_case(case.task_description)
            before_issues = _compile_issues(case.task_description)
            after_issues = _compile_issues(result.task_description)
            snapshot.append({
                "id": case.id,
                "name": case.name,
                "setup_template_id": case.setup_template_id,
                "original_task_description": case.task_description,
                "normalized_task_description": result.task_description,
                "changed": result.changed,
                "requires_controlled_environment": result.requires_controlled_environment,
                "compile_issues_before": before_issues,
                "compile_issues_after": after_issues,
            })
            summary["total"] += 1
            summary["changed"] += int(result.changed)
            summary["controlled_environment"] += int(result.requires_controlled_environment)
            summary["remaining_compile_issues"] += int(bool(after_issues))
            for issue in after_issues:
                summary[f"issue_{issue}"] += 1

        backup_dir = Path(options["backup_dir"])
        if not backup_dir.is_absolute():
            backup_dir = Path.cwd() / backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_path = backup_dir / f"ai_case_normalization_project_{options['project_id']}_{suffix}.json"
        # ASCII JSON is intentional: imported office documents may contain
        # lone Unicode surrogate characters.  Escaping avoids producing an
        # invalid audit file while preserving the exact original text.
        snapshot_path.write_text(json.dumps({"summary": dict(summary), "cases": snapshot}, ensure_ascii=True, indent=2), encoding="utf-8")

        if options["apply"]:
            with transaction.atomic():
                for item in snapshot:
                    if item["changed"]:
                        AICase.objects.filter(id=item["id"]).update(task_description=item["normalized_task_description"])

        mode = "APPLIED" if options["apply"] else "DRY RUN"
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: total={summary['total']} changed={summary['changed']} "
            f"controlled_environment={summary['controlled_environment']} "
            f"remaining_compile_issues={summary['remaining_compile_issues']}"
        ))
        self.stdout.write(f"Snapshot: {snapshot_path}")
