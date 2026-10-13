"""Utilities for preserving user-written click constraints."""

from __future__ import annotations

import re
from typing import Dict, List


_POSITION_KEYWORDS = {
    'top': ['顶部', '上方', '上面'],
    'bottom': ['底部', '下方', '下面'],
    'left': ['左侧', '左边'],
    'right': ['右侧', '右边'],
}

_CONTEXT_KEYWORDS = {
    'result': ['搜索结果', '查询结果', '结果列表', '结果项', '结果卡片', '结果'],
    'list': ['列表', '列表项', '条目', '项目'],
    'card': ['卡片'],
    'dialog': ['弹窗', '弹层', '对话框', '模态框'],
    'menu': ['菜单', '下拉'],
    'sidebar': ['侧边栏', '侧边', '左侧', '右侧'],
}

_SIGNAL_KEYWORDS = {
    'online_count': ['在线人数', '在线成员', '在线数', '人在线'],
    'community_intro': ['社区简介', '简介', '介绍'],
    'official': ['官方'],
    'avatar': ['头像'],
    'price': ['价格', '售价', '金额', '¥', '￥'],
    'stock': ['库存', '余量', '剩余'],
}

_REQUIREMENT_MARKERS = [
    '必须满足',
    '同时满足',
    '需满足',
    '需要满足',
    '要求',
    '带有',
    '包含',
    '显示',
]

_TARGET_NOISE = [
    '点击',
    '点',
    '按',
    '选择',
    '打开',
    '进入',
    '搜索结果',
    '查询结果',
    '结果列表',
    '结果项',
    '结果卡片',
    '结果',
    '列表项',
    '列表',
    '卡片',
    '条目',
    '项目',
    '中的',
    '里的',
    '下的',
    '上方的',
    '下方的',
    '右侧的',
    '左侧的',
]

_REQUIREMENT_NOISE = [
    '必须满足',
    '同时满足',
    '需满足',
    '需要满足',
    '要求',
    '条件',
    '两个条件',
    '一个条件',
    '带有',
    '包含',
    '显示',
    '有',
]


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        item = str(item or '').strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _strip_quotes(text: str) -> str:
    return str(text or '').strip().strip('"').strip("'").strip('“').strip('”').strip('「').strip('」').strip()


def _clean_target_text(text: str) -> str:
    text = _strip_quotes(text)
    for noise in _TARGET_NOISE:
        text = text.replace(noise, '')
    text = re.sub(r'\s*(按钮|链接|图标|入口|控件)$', '', text).strip() or text
    return text.strip(' ，。；;')


def _clean_requirement_text(text: str) -> str:
    text = _strip_quotes(text)
    for noise in _REQUIREMENT_NOISE:
        if text.startswith(noise):
            text = text[len(noise):].strip()
    text = re.sub(r'(标识|标签|文案|文本|信息)$', '', text).strip() or text
    return text.strip(' ，。；;')


def _maps_to_known_signal(text: str) -> bool:
    cleaned = _clean_requirement_text(text)
    return any(token in cleaned for tokens in _SIGNAL_KEYWORDS.values() for token in tokens)


def extract_click_target_texts(description: str, fallback_target: str = '') -> List[str]:
    desc = str(description or '').strip()
    if not desc:
        return _dedupe_keep_order([_clean_target_text(fallback_target)]) if fallback_target else []

    target_desc = re.split(r'[，,]\s*(?:必须满足|同时满足|需满足|需要满足|要求)', desc, maxsplit=1)[0].strip()
    candidates: List[str] = []

    patterns = [
        r'(?:名称|名字|名为)\s*[“"\'「]?([^“”"\'「」，。,；;]{1,60})[”"\'」]?',
        r'(?:点击|点|按|选择|打开|进入)\s*.+?(?:中的|里的|下的|上方的|下方的|右侧的|左侧的)\s*[“"\']?([^“"\'，。,；;]+)[”"\']?',
        r'(?:点击|点|按|选择|打开|进入)\s*[“"\']?([^“"\'，。,；;]+)[”"\']?\s*(?:按钮|链接|图标|卡片|结果|条目|项目|社区)?$',
    ]
    for pattern in patterns:
        match = re.search(pattern, target_desc)
        if match:
            candidates.append(match.group(1))

    candidates.extend(re.findall(r'[“"\'「]([^“”"\'」]{1,60})[”"\'」]', target_desc))
    if fallback_target:
        candidates.append(fallback_target)

    cleaned: List[str] = []
    for raw in candidates:
        text = _clean_target_text(raw)
        if len(text) < 2:
            continue
        cleaned.append(text)
        for suffix in ['社区', '卡片', '条目', '项目', '结果项', '结果', '按钮', '链接']:
            if text.endswith(suffix) and len(text) > len(suffix) + 1:
                cleaned.append(text[:-len(suffix)].strip())
    return _dedupe_keep_order(cleaned)[:6]


def _extract_required_signals(description: str) -> List[str]:
    desc = str(description or '')
    signals = []
    for signal, tokens in _SIGNAL_KEYWORDS.items():
        if any(token in desc for token in tokens):
            signals.append(signal)
    return _dedupe_keep_order(signals)


def _extract_required_texts(description: str, target_texts: List[str]) -> List[str]:
    desc = str(description or '').strip()
    if not desc:
        return []

    chunks: List[str] = []
    tail_patterns = [
        r'(?:必须满足|同时满足|需满足|需要满足)\s*(?:\d+个条件)?\s*[：:，,\s]+\s*(.+)$',
        r'(?:要求)\s*(?:带有|包含|显示)?\s*(.+)$',
    ]
    for pattern in tail_patterns:
        match = re.search(pattern, desc)
        if match:
            chunks.extend(re.split(r'[、,，]|(?:和|且|并且)', match.group(1)))

    inline_patterns = [
        r'(?:带有|包含|显示)\s*[“"\']?([^“"\'，。,；;]{1,30})[”"\']?(?:标识|标签|文案|文本|信息)?',
    ]
    for pattern in inline_patterns:
        chunks.extend(re.findall(pattern, desc))

    required_texts = []
    for raw in chunks:
        text = _clean_requirement_text(raw)
        if len(text) < 2 or len(text) > 24:
            continue
        if _maps_to_known_signal(text):
            continue
        if text in target_texts:
            continue
        required_texts.append(text)
    return _dedupe_keep_order(required_texts)[:6]


def extract_click_constraints(description: str, fallback_target: str = '') -> Dict[str, object]:
    desc = str(description or '').strip()
    if not desc:
        return {}

    target_texts = extract_click_target_texts(desc, fallback_target=fallback_target)
    required_signals = _extract_required_signals(desc)
    required_texts = _extract_required_texts(desc, target_texts)
    position_terms = [
        position
        for position, keywords in _POSITION_KEYWORDS.items()
        if any(keyword in desc for keyword in keywords)
    ]
    context_terms = [
        context
        for context, keywords in _CONTEXT_KEYWORDS.items()
        if any(keyword in desc for keyword in keywords)
    ]

    constraints: Dict[str, object] = {}
    if target_texts:
        constraints['target_texts'] = target_texts
    if required_signals:
        constraints['required_signals'] = required_signals
    if required_texts:
        constraints['required_texts'] = required_texts
    if position_terms:
        constraints['position_terms'] = _dedupe_keep_order(position_terms)
    if context_terms:
        constraints['context_terms'] = _dedupe_keep_order(context_terms)
    if any(marker in desc for marker in _REQUIREMENT_MARKERS):
        constraints['has_explicit_requirements'] = True
    return constraints


def has_meaningful_click_constraints(constraints: Dict[str, object]) -> bool:
    constraints = constraints or {}
    return any(
        constraints.get(key)
        for key in (
            'required_signals',
            'required_texts',
            'position_terms',
            'context_terms',
        )
    )
