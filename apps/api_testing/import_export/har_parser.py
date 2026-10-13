"""
HAR (HTTP Archive) 文件解析器
"""
import json
import logging
from urllib.parse import urlparse

from .header_utils import normalize_import_header

logger = logging.getLogger(__name__)


class HARParser:
    """解析 HAR 文件格式"""

    # 过滤掉的静态资源扩展名
    SKIP_EXTENSIONS = {
        '.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico',
        '.woff', '.woff2', '.ttf', '.eot', '.map', '.webp', '.avif',
    }

    def parse(self, content, filename=''):
        """
        解析 HAR 文件
        Returns:
            dict: { title, description, base_url, collections, total_requests }
        """
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            raise ValueError('无效的 JSON 格式')

        log = data.get('log', {})
        entries = log.get('entries', [])

        if not entries:
            raise ValueError('HAR 文件中没有请求记录')

        # 按域名分组
        collections_map = {}
        total = 0

        for entry in entries:
            request = entry.get('request', {})
            url = request.get('url', '')
            method = request.get('method', 'GET').upper()

            # 过滤静态资源
            parsed = urlparse(url)
            path = parsed.path.lower()
            if any(path.endswith(ext) for ext in self.SKIP_EXTENSIONS):
                continue

            # 过滤非 API 请求（可选：只保留 XHR 类型）
            # 这里我们保留所有非静态资源请求

            domain = f'{parsed.scheme}://{parsed.netloc}'
            if domain not in collections_map:
                collections_map[domain] = {
                    'name': parsed.netloc or 'Unknown',
                    'description': f'从 {parsed.netloc} 导入的接口',
                    'requests': [],
                }

            req_data = self._parse_entry(entry)
            if req_data:
                collections_map[domain]['requests'].append(req_data)
                total += 1

        if total == 0:
            raise ValueError('HAR 文件中没有可导入的 API 请求')

        return {
            'title': 'HAR Import',
            'description': f'从 HAR 文件导入 {total} 个接口',
            'base_url': '',
            'collections': list(collections_map.values()),
            'total_requests': total,
        }

    def _parse_entry(self, entry):
        """解析单个 HAR entry"""
        request = entry.get('request', {})
        url = request.get('url', '')
        method = request.get('method', 'GET').upper()

        if not url:
            return None

        parsed = urlparse(url)

        # Headers
        headers = []
        for h in request.get('headers', []):
            item = normalize_import_header(h.get('name', ''), h.get('value', ''))
            if item:
                headers.append(item)

        # Query params
        params = {}
        for q in request.get('queryString', []):
            if q.get('name'):
                params[q['name']] = q.get('value', '')

        # Body
        body = {}
        post_data = request.get('postData', {})
        if post_data:
            mime_type = post_data.get('mimeType', '')
            text = post_data.get('text', '')

            if 'application/json' in mime_type and text:
                try:
                    body = {'type': 'json', 'data': json.loads(text)}
                except json.JSONDecodeError:
                    body = {'type': 'raw', 'data': text}
            elif 'x-www-form-urlencoded' in mime_type:
                data = {}
                for p in post_data.get('params', []):
                    if p.get('name'):
                        data[p['name']] = p.get('value', '')
                body = {'type': 'x-www-form-urlencoded', 'data': data}
            elif 'multipart/form-data' in mime_type:
                data = {}
                for p in post_data.get('params', []):
                    if p.get('name'):
                        data[p['name']] = p.get('value', '')
                body = {'type': 'form-data', 'data': data}
            elif text:
                body = {'type': 'raw', 'data': text}

        # URL 只保留 path 部分（base_url 在集合级别）
        url_without_query = f'{parsed.scheme}://{parsed.netloc}{parsed.path}'
        name = f'{method} {parsed.path}' if parsed.path else f'{method} /'

        return {
            'name': name,
            'description': '',
            'method': method,
            'url': url_without_query,
            'headers': headers,
            'params': params,
            'body': body,
        }
