"""
cURL 命令解析器
"""
import json
import re
import shlex
import logging

from .header_utils import normalize_import_header

logger = logging.getLogger(__name__)


class CurlParser:
    """解析 cURL 命令为 TestHub 请求格式"""

    def parse(self, content, filename=''):
        """
        解析一个或多个 cURL 命令
        Args:
            content: cURL 命令文本（支持多条，用换行分隔）
        Returns:
            dict: { title, description, base_url, collections, total_requests }
        """
        commands = self._split_commands(content)
        requests = []

        for cmd in commands:
            try:
                req = self._parse_single(cmd)
                if req:
                    requests.append(req)
            except Exception as e:
                logger.warning(f'Failed to parse cURL command: {e}')
                continue

        if not requests:
            raise ValueError('未能解析出有效的 cURL 命令')

        return {
            'title': 'cURL Import',
            'description': f'从 cURL 导入 {len(requests)} 个接口',
            'base_url': '',
            'collections': [{
                'name': 'cURL Import',
                'description': '',
                'requests': requests,
            }],
            'total_requests': len(requests),
        }

    def _split_commands(self, content):
        """分割多条 cURL 命令"""
        content = content.strip()
        # 处理行尾续行符
        content = re.sub(r'\\\s*\n', ' ', content)
        # 按 curl 关键字分割
        parts = re.split(r'(?:^|\n)\s*(?=curl\s)', content)
        return [p.strip() for p in parts if p.strip() and p.strip().lower().startswith('curl')]

    def _parse_single(self, command):
        """解析单条 cURL 命令"""
        # 移除开头的 curl
        command = command.strip()
        if not command.lower().startswith('curl'):
            return None

        try:
            tokens = shlex.split(command)
        except ValueError:
            # 处理未闭合引号等
            command = command.replace("'", '"')
            tokens = shlex.split(command)

        url = ''
        method = 'GET'
        headers = []
        body_raw = ''
        has_data = False
        content_type = ''

        i = 1  # 跳过 'curl'
        while i < len(tokens):
            token = tokens[i]

            if token in ('-X', '--request'):
                i += 1
                if i < len(tokens):
                    method = tokens[i].upper()
            elif token in ('-H', '--header'):
                i += 1
                if i < len(tokens):
                    header_str = tokens[i]
                    if ':' in header_str:
                        key, value = header_str.split(':', 1)
                        item = normalize_import_header(key, value)
                        if item:
                            headers.append(item)
                        if key.strip().lower() == 'content-type':
                            content_type = value.strip().lower()
            elif token in ('-d', '--data', '--data-raw', '--data-binary', '--data-urlencode'):
                i += 1
                if i < len(tokens):
                    body_raw = tokens[i]
                    has_data = True
                    if method == 'GET':
                        method = 'POST'
            elif token in ('-b', '--cookie'):
                # 跳过 cookie 参数
                i += 1
            elif token in ('-u', '--user'):
                i += 1
                # 可以解析为 auth，暂时跳过
            elif token in ('-k', '--insecure', '--compressed', '-s', '--silent',
                           '-v', '--verbose', '-L', '--location', '-i', '--include'):
                pass  # 布尔标记，跳过
            elif not token.startswith('-') and not url:
                url = token
            i += 1

        if not url:
            return None

        # 解析 body
        body = {}
        if body_raw:
            if 'application/json' in content_type:
                try:
                    body = {'type': 'json', 'data': json.loads(body_raw)}
                except json.JSONDecodeError:
                    body = {'type': 'json', 'data': body_raw}
            elif 'application/xml' in content_type or 'text/xml' in content_type:
                body = {'type': 'xml', 'data': body_raw}
            elif 'text/html' in content_type:
                body = {'type': 'html', 'data': body_raw}
            elif 'text/plain' in content_type:
                body = {'type': 'text', 'data': body_raw}
            elif 'application/x-www-form-urlencoded' in content_type:
                data = {}
                for pair in body_raw.split('&'):
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        data[k] = v
                body = {'type': 'x-www-form-urlencoded', 'data': data}
            elif self._is_json(body_raw):
                try:
                    body = {'type': 'json', 'data': json.loads(body_raw)}
                except json.JSONDecodeError:
                    body = {'type': 'raw', 'data': body_raw}
            elif '=' in body_raw and '&' in body_raw:
                # form urlencoded
                data = {}
                for pair in body_raw.split('&'):
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        data[k] = v
                body = {'type': 'x-www-form-urlencoded', 'data': data}
            else:
                body = {'type': 'raw', 'data': body_raw}
        elif content_type:
            if 'application/json' in content_type:
                body = {'type': 'json', 'data': ''}
            elif 'application/xml' in content_type or 'text/xml' in content_type:
                body = {'type': 'xml', 'data': ''}
            elif 'text/html' in content_type:
                body = {'type': 'html', 'data': ''}
            elif 'text/plain' in content_type:
                body = {'type': 'text', 'data': ''}
            elif 'application/x-www-form-urlencoded' in content_type:
                body = {'type': 'x-www-form-urlencoded', 'data': {}}
            else:
                body = {'type': 'raw', 'data': ''}

        # 解析 URL 中的 query params
        params = {}
        if '?' in url:
            url_base, query_string = url.split('?', 1)
            for pair in query_string.split('&'):
                if '=' in pair:
                    k, v = pair.split('=', 1)
                    params[k] = v
        else:
            url_base = url

        # 生成名称
        from urllib.parse import urlparse
        parsed = urlparse(url_base)
        path = parsed.path or '/'
        name = f'{method} {path}'

        return {
            'name': name,
            'description': '',
            'method': method,
            'url': url_base if params else url,
            'headers': headers,
            'params': params,
            'body': body,
        }

    def _is_json(self, text):
        if not text or not isinstance(text, str):
            return False
        text = text.strip()
        return (text.startswith('{') and text.endswith('}')) or \
               (text.startswith('[') and text.endswith(']'))
