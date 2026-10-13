"""Rewrite stale Windows battle-plugin cases against the live NN client UI."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.ui_automation.models import AICase


WINDOWS_ROUTE = "/community/7520/plugin/zhanji"


def _case(*operations: str, expected: tuple[str, ...]) -> str:
    lines = [f"目标地址：NN 客户端 {WINDOWS_ROUTE}", "操作步骤："]
    lines.extend(f"{index}. {operation}" for index, operation in enumerate(operations, 1))
    lines.append("预期结果：")
    lines.extend(f"{index}. 断言{item}" for index, item in enumerate(expected, 1))
    return "\n".join(lines)


PAGE_READY = "当前地址保持在 /plugin/zhanji，页面展示“战绩查询”和“查询玩家战绩”输入框"
PAGE_HEALTHY = "页面无白屏、404 或脚本错误"
QUERY_VISIBLE = "“查询玩家战绩”输入框可见且页面地址未跳转"


CASE_BLUEPRINTS = (
    lambda: _case("访问页面", "等待页面就绪", expected=(PAGE_READY, PAGE_HEALTHY)),
    lambda: _case(
        "访问页面", "等待当前账号的战绩数据加载完成",
        expected=("页面展示当前账号昵称、赛季和模式筛选项，以及战绩数据或明确的加载完成状态", PAGE_HEALTHY),
    ),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写test", expected=("“查询玩家战绩”输入框当前值为 test", QUERY_VISIBLE)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写PUBGPLAYER", expected=("“查询玩家战绩”输入框当前值为 PUBGPLAYER", QUERY_VISIBLE)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写test", "清空“查询玩家战绩”输入框", expected=("“查询玩家战绩”输入框当前值为空", QUERY_VISIBLE)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写三个空格", expected=("输入框保留三个空格且页面仍可操作", QUERY_VISIBLE)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写!@#", expected=("“查询玩家战绩”输入框当前值为 !@#", PAGE_HEALTHY)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写PUBGPLAYER12345678901234567890", expected=("“查询玩家战绩”输入框当前值为 PUBGPLAYER12345678901234567890", QUERY_VISIBLE)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写PUBGID123", expected=("“查询玩家战绩”输入框当前值为 PUBGID123", QUERY_VISIBLE)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写PUBGID1234567890", expected=("“查询玩家战绩”输入框当前值为 PUBGID1234567890", QUERY_VISIBLE)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写PUBGID123", "清空“查询玩家战绩”输入框", expected=("“查询玩家战绩”输入框当前值为空", PAGE_HEALTHY)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写PUBGID12345678901234", expected=("“查询玩家战绩”输入框当前值为 PUBGID12345678901234", QUERY_VISIBLE)),
    lambda: _case("访问页面", expected=("已登录账号可直接访问战绩插件，未出现登录弹窗", PAGE_READY)),
    lambda: _case("访问页面", "等待页面就绪", expected=("页面展示已登录账号标识和战绩查询输入框", PAGE_HEALTHY)),
    lambda: _case("访问页面", "在“查询玩家战绩”输入框填写17680942927", expected=("查询输入框可编辑，已登录态未丢失", PAGE_HEALTHY)),
    lambda: _case("访问页面", "等待页面就绪", expected=("已登录账号访问后仍停留在 /plugin/zhanji", PAGE_READY)),
    lambda: _case("访问页面", "点击战绩数据区的“刷新”按钮", expected=("刷新后仍展示战绩查询入口，页面未跳转", PAGE_HEALTHY)),
    lambda: _case("访问页面", "再次访问页面", expected=("当前地址包含 /plugin/zhanji，战绩查询入口可见", PAGE_HEALTHY)),
    lambda: _case("访问页面", expected=("桌面客户端当前窗口内战绩查询输入框完整可见", PAGE_HEALTHY)),
    lambda: _case("访问页面", expected=("桌面客户端当前窗口内战绩筛选项和查询输入框可见", PAGE_HEALTHY)),
    lambda: _case("访问页面", expected=("桌面客户端当前窗口内战绩内容可操作，未出现横向遮挡", PAGE_HEALTHY)),
    lambda: _case("访问页面", expected=("桌面客户端当前窗口内战绩核心输入框可见，内容可滚动访问", PAGE_HEALTHY)),
    lambda: _case("访问页面", "等待页面就绪", expected=("页面展示当前账号的战绩概览或比赛记录内容", PAGE_HEALTHY)),
    lambda: _case("访问页面", "等待页面就绪", expected=("页面展示玩家信息、赛季筛选和至少一个战绩信息区域", PAGE_HEALTHY)),
)


class Command(BaseCommand):
    help = "Rewrite imported ZJ desktop tasks into state-safe NN CDP scenarios."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--backup-dir", default="outputs/ai_case_backups")

    def handle(self, *args, **options):
        cases = list(AICase.objects.filter(project_id=options["project_id"], name__startswith="ZJ-").order_by("id"))
        if not cases:
            raise CommandError("No ZJ cases were found for the requested project.")

        backup_dir = Path(options["backup_dir"])
        if not backup_dir.is_absolute():
            backup_dir = Path.cwd() / backup_dir
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"zhanji_windows_before_rewrite_{datetime.now():%Y%m%d_%H%M%S}.json"
        backup_path.write_text(json.dumps([
            {
                "id": case.id,
                "name": case.name,
                "task_description": case.task_description,
                "desktop_task_description": case.desktop_task_description,
                "description": case.description,
            }
            for case in cases
        ], ensure_ascii=False, indent=2), encoding="utf-8")

        rewritten = 0
        if options["apply"]:
            with transaction.atomic():
                for index, case in enumerate(cases):
                    new_desktop_task = CASE_BLUEPRINTS[index % len(CASE_BLUEPRINTS)]()
                    if case.desktop_task_description == new_desktop_task:
                        continue
                    case.desktop_task_description = new_desktop_task
                    case.description = (
                        "Windows mode uses a self-contained CDP scenario matched to the currently "
                        "available battle-plugin controls. The browser-mode source case is retained."
                    )
                    case.save(update_fields=["desktop_task_description", "description", "updated_at"])
                    rewritten += 1

        self.stdout.write(self.style.SUCCESS(
            f"{'APPLIED' if options['apply'] else 'DRY RUN'}: candidates={len(cases)}, rewritten={rewritten}"
        ))
        self.stdout.write(f"Backup: {backup_path}")
