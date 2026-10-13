"""Shared request header cleanup for API import parsers."""

from __future__ import annotations

from typing import Any


SKIP_IMPORT_HEADER_NAMES = {
    ':method',
    ':authority',
    ':scheme',
    ':path',
    'accept',
    'referer',
    'content-length',
    'priority',
    'accept-encoding',
    'connection',
    'host',
    'proxy-connection',
    'transfer-encoding',
}


def should_skip_import_header(name: Any) -> bool:
    key = str(name or '').strip().lower()
    return not key or key in SKIP_IMPORT_HEADER_NAMES or key.startswith('sec-')


def normalize_import_header(
    name: Any,
    value: Any = '',
    *,
    enabled: bool = True,
    description: Any = '',
) -> dict[str, Any] | None:
    key = str(name or '').strip()
    if should_skip_import_header(key):
        return None
    return {
        'key': key,
        'value': '' if value is None else str(value).strip(),
        'enabled': bool(enabled),
        'description': '' if description is None else str(description),
    }


def normalize_import_headers(headers: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    if isinstance(headers, dict):
        iterable = headers.items()
        for key, value in iterable:
            item = normalize_import_header(key, value)
            if item:
                normalized.append(item)
        return normalized

    if not isinstance(headers, list):
        return normalized

    for header in headers:
        if isinstance(header, dict):
            key = header.get('key', header.get('name', ''))
            value = header.get('value', '')
            item = normalize_import_header(
                key,
                value,
                enabled=not header.get('disabled', False) if 'disabled' in header else header.get('enabled', True),
                description=header.get('description', ''),
            )
        elif isinstance(header, (list, tuple)) and len(header) >= 2:
            item = normalize_import_header(header[0], header[1])
        else:
            item = None

        if item:
            normalized.append(item)

    return normalized
