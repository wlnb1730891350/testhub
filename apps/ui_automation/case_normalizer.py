"""Normalize imported AI cases into the executable authoring format.

The importer intentionally keeps source documents verbatim.  This module is
used after import when a document contains test-design wording ("observe",
"count", or API-only checks) that the UI runner must not mistake for a DOM
action.  It keeps the original test intent, but makes the executable path and
runtime assertion intent explicit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


SECTION_HEADERS = ("目标地址", "前置条件", "操作步骤", "预期结果")
NETWORK_DEPENDENCY_PATTERN = re.compile(
    r"(?:测试代理|网络拦截|离线模式|断网|HTTP\s*(?:4|5)\d\d|接口.*(?:超时|延迟)|响应.*(?:超时|延迟))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NormalizationResult:
    task_description: str
    changed: bool
    requires_controlled_environment: bool


def _clean_line(line: str) -> str:
    text = re.sub(r"^\s*(?:[-*+]|\d+[.、．)]?)\s*", "", str(line or "")).strip()
    return re.sub(r"\s+", " ", text)


def _sectioned_lines(task_description: str) -> dict[str, list[str]]:
    sections = {header: [] for header in SECTION_HEADERS}
    current = ""
    for raw_line in str(task_description or "").replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        matched = next((header for header in SECTION_HEADERS if re.match(rf"^{header}\s*[:：]", line)), None)
        if matched:
            current = matched
            value = re.sub(rf"^{matched}\s*[:：]\s*", "", line).strip()
            if value:
                sections[current].append(value)
            continue
        if current:
            cleaned = _clean_line(line)
            if cleaned:
                sections[current].append(cleaned)
    return sections


def _first_url(lines: Iterable[str]) -> str:
    for line in lines:
        matched = re.search(r"https?://[^\s，。；;]+", line)
        if matched:
            return matched.group(0).rstrip("。；;，,")
    return ""


def _is_observation_only(line: str) -> bool:
    return bool(re.match(r"^(?:查看|观察|统计|读取|记录|对比|比较|检查请求|查看请求队列)", line))


def _normalize_operation(line: str) -> str:
    line = _clean_line(line).rstrip("。；;")
    if not line:
        return ""
    # The runner performs result-area stability checks after a player query.
    if re.match(r"^(?:查询|搜索)\s*(?:玩家(?:战绩)?\s*)?[A-Za-z][A-Za-z0-9_-]{2,}$", line):
        player = re.search(r"([A-Za-z][A-Za-z0-9_-]{2,})$", line).group(1)
        return f"查询玩家{player}并等待战绩结果区域加载"
    if _is_observation_only(line):
        return ""
    return line


def _normalize_expected(line: str) -> str:
    line = _clean_line(line).rstrip("。；;")
    if not line:
        return ""
    return line if re.match(r"^(?:断言|验证|检查|确认)", line) else f"断言{line}"


def normalize_imported_case(task_description: str) -> NormalizationResult:
    """Return a stable AI-runner description without inventing test data.

    Source cases frequently contain network assertions.  Those are retained in
    the expected result and flagged for a controlled environment instead of
    being rewritten into a misleading DOM assertion.
    """
    original = str(task_description or "").strip()
    sections = _sectioned_lines(original)
    url = _first_url(sections["目标地址"]) or _first_url(sections["操作步骤"]) or _first_url([original])
    operations = [_normalize_operation(line) for line in sections["操作步骤"]]
    operations = [line for line in operations if line]
    expected = [_normalize_expected(line) for line in sections["预期结果"]]
    expected = [line for line in expected if line]

    # Keep documents that did not use headings usable as a one-step case.
    if not operations and original and not sections["操作步骤"]:
        operations = [_normalize_operation(original)]
        operations = [line for line in operations if line]

    # A page-state, viewport, or injected-network scenario may legitimately
    # contain no click/type instruction.  Keep it runnable by making page
    # readiness an explicit first action instead of leaving the runner with a
    # target URL and nothing to execute.
    if url and not any(re.search(r"(?:访问|进入|打开)\s*(?:https?://|页面|战绩|插件)", line) for line in operations):
        operations[0:0] = [f"访问 {url}", "等待页面就绪"]

    parts = []
    if url:
        parts.append(f"目标地址：{url}")
    if sections["前置条件"]:
        parts.append("前置条件：" + "；".join(_clean_line(line) for line in sections["前置条件"] if _clean_line(line)))
    if operations:
        parts.append("操作步骤：")
        parts.extend(f"{index}. {line}" for index, line in enumerate(operations, 1))
    if expected:
        parts.append("预期结果：")
        parts.extend(f"{index}. {line}" for index, line in enumerate(expected, 1))

    normalized = "\n".join(parts).strip() or original
    return NormalizationResult(
        task_description=normalized,
        changed=normalized != original,
        requires_controlled_environment=bool(NETWORK_DEPENDENCY_PATTERN.search(original)),
    )
