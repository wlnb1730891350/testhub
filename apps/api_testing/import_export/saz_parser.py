"""
Fiddler SAZ 文件解析器
"""
from __future__ import annotations

import json
import logging
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse, urlunparse

from .header_utils import normalize_import_header

logger = logging.getLogger(__name__)


class SAZParser:
    """解析 Fiddler SAZ 抓包文件为 TestHub 请求格式"""

    def parse(self, content, filename: str = ''):
        if not content:
            raise ValueError('SAZ 文件不能为空')

        collection_name = Path(filename).stem or 'SAZ Import'

        with tempfile.TemporaryDirectory(prefix='saz_extract_') as temp_dir:
            extracted = self._extract_saz(content, Path(temp_dir), filename=filename)
            requests = self._parse_requests(extracted)

        if not requests:
            raise ValueError('SAZ 文件中没有可导入的接口')

        collections = self._build_collections(requests, collection_name)
        return {
            'title': collection_name,
            'description': f'从 SAZ 文件导入 {len(requests)} 个接口',
            'base_url': '',
            'collections': collections,
            'total_requests': len(requests),
        }

    def _extract_saz(self, content, temp_dir: Path, filename: str = '') -> Path:
        if isinstance(content, (bytes, bytearray)):
            saz_bytes = bytes(content)
        elif isinstance(content, str):
            saz_bytes = content.encode('utf-8', errors='ignore')
        elif hasattr(content, 'read'):
            saz_bytes = content.read()
        else:
            raise ValueError('不支持的 SAZ 文件内容类型')

        saz_path = temp_dir / (Path(filename).name if filename else 'import.saz')
        saz_path.write_bytes(saz_bytes)

        try:
            with zipfile.ZipFile(saz_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
        except zipfile.BadZipFile as exc:
            raise ValueError('无效的 SAZ 文件，无法解压') from exc

        raw_dir = temp_dir / 'raw'
        if not raw_dir.exists():
            raise ValueError('SAZ 文件中未找到 raw 目录')
        return raw_dir

    def _parse_requests(self, raw_dir: Path) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []
        entries = sorted(raw_dir.glob('*_c.txt'), key=self._sort_key)
        for c_file in entries:
            try:
                c_content = self._read_text_with_fallback(c_file)
                request_data = self._parse_single_entry(c_content)
                if request_data:
                    requests.append(request_data)
            except Exception as exc:
                logger.warning('Failed to parse SAZ entry %s: %s', c_file.name, exc)
                continue
        return requests

    def _read_text_with_fallback(self, path: Path) -> str:
        encodings = ('utf-8', 'utf-8-sig', 'utf-16-le', 'latin-1')
        raw = path.read_bytes()
        for encoding in encodings:
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode('latin-1', errors='ignore')

    def _parse_single_entry(self, content: str) -> dict[str, Any] | None:
        normalized = content.replace('\r\n', '\n').replace('\r', '\n').strip()
        if not normalized:
            return None

        header_block, body_block = self._split_header_body(normalized)
        header_lines = [line for line in header_block.split('\n') if line.strip()]
        if not header_lines:
            return None

        request_line = header_lines[0].strip()
        request_meta = self._parse_request_line(request_line)
        header_dict = self._parse_headers(header_lines[1:])

        if not request_meta.get('url'):
            request_meta = self._rebuild_request_meta(request_meta, header_dict)

        url = request_meta.get('url', '')
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        url_without_query = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))

        body = self._parse_body(body_block, header_dict)
        name = f"{request_meta.get('method', 'GET')} {parsed.path or '/'}"

        return {
            'name': name,
            'description': '',
            'method': request_meta.get('method', 'GET'),
            'url': url_without_query or url,
            'headers': header_dict,
            'params': params,
            'body': body,
        }

    def _split_header_body(self, content: str) -> tuple[str, str]:
        if '\n\n' in content:
            return content.split('\n\n', 1)
        return content, ''

    def _parse_request_line(self, line: str) -> dict[str, str]:
        match = re.match(r'^(?P<method>[A-Z]+)\s+(?P<url>\S+)(?:\s+HTTP/\d(?:\.\d)?)?$', line.strip())
        if not match:
            return {'method': 'GET', 'url': ''}
        return {'method': match.group('method').upper(), 'url': match.group('url')}

    def _parse_headers(self, lines: list[str]) -> list[dict[str, Any]]:
        headers: list[dict[str, Any]] = []
        for line in lines:
            if ': ' not in line:
                continue
            key, value = line.split(': ', 1)
            item = normalize_import_header(key, value)
            if item:
                headers.append(item)
        return headers

    def _rebuild_request_meta(self, request_meta: dict[str, str], headers: list[dict[str, Any]]) -> dict[str, str]:
        header_map = {item.get('key', '').lower(): item.get('value', '') for item in headers}
        scheme = header_map.get(':scheme', 'https')
        authority = header_map.get(':authority', '')
        path = header_map.get(':path', '/')
        if authority:
            request_meta['url'] = f'{scheme}://{authority}{path}'
        return request_meta

    def _parse_body(self, body: str, headers: list[dict[str, Any]]) -> dict[str, Any]:
        if not body.strip():
            return {}

        content_type = ''
        for item in headers:
            if item.get('key', '').lower() == 'content-type':
                content_type = str(item.get('value', '')).lower()
                break

        body_text = body.strip()
        if 'application/json' in content_type:
            try:
                return {'type': 'json', 'data': json.loads(body_text)}
            except json.JSONDecodeError:
                return {'type': 'raw', 'data': body_text}
        if 'application/x-www-form-urlencoded' in content_type:
            return {'type': 'x-www-form-urlencoded', 'data': dict(parse_qsl(body_text, keep_blank_values=True))}
        if 'multipart/form-data' in content_type:
            return {'type': 'raw', 'data': body_text}
        if self._looks_like_json(body_text):
            try:
                return {'type': 'json', 'data': json.loads(body_text)}
            except json.JSONDecodeError:
                return {'type': 'raw', 'data': body_text}
        return {'type': 'raw', 'data': body_text}

    def _build_collections(self, requests: list[dict[str, Any]], collection_name: str) -> list[dict[str, Any]]:
        return [{
            'name': collection_name,
            'description': f'从 {collection_name} 导入的接口',
            'requests': requests,
        }]

    def _looks_like_json(self, text: str) -> bool:
        text = text.strip()
        return (text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']'))

    def _sort_key(self, path: Path):
        match = re.search(r'(\d+)_c\.txt$', path.name)
        return int(match.group(1)) if match else path.name
