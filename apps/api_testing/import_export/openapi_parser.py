"""
OpenAPI 3.0 / Swagger 2.0 解析器
将 OpenAPI 规范文件解析为 TestHub 的 Collection + Request 结构
"""
import json
import yaml
import logging

from .header_utils import normalize_import_header

logger = logging.getLogger(__name__)


class OpenAPIParser:
    """解析 OpenAPI 3.0 和 Swagger 2.0 格式"""

    def parse(self, content, filename=''):
        """
        解析 OpenAPI 内容
        Args:
            content: 文件内容（字符串）
            filename: 文件名（用于判断格式）
        Returns:
            dict: {
                'title': str,
                'description': str,
                'base_url': str,
                'collections': [{'name': str, 'description': str, 'requests': [...]}],
                'total_requests': int
            }
        """
        data = self._load_content(content, filename)
        if not data:
            raise ValueError('无法解析文件内容，请确认为有效的 JSON 或 YAML 格式')

        # 判断版本
        if data.get('openapi', '').startswith('3.'):
            return self._parse_openapi3(data)
        elif data.get('swagger', '').startswith('2.'):
            return self._parse_swagger2(data)
        else:
            raise ValueError('不支持的格式，仅支持 OpenAPI 3.x 和 Swagger 2.x')

    def _load_content(self, content, filename):
        """尝试按 JSON 或 YAML 加载"""
        # 先试 JSON
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass
        # 再试 YAML
        try:
            return yaml.safe_load(content)
        except yaml.YAMLError:
            pass
        return None

    def _parse_openapi3(self, data):
        info = data.get('info', {})
        title = info.get('title', 'Imported API')
        description = info.get('description', '')

        # 提取 base_url
        servers = data.get('servers', [])
        base_url = servers[0].get('url', '') if servers else ''

        paths = data.get('paths', {})
        collections_map = {}  # tag -> requests
        total = 0

        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.lower() in ('get', 'post', 'put', 'delete', 'patch', 'head', 'options'):
                    request_data = self._build_request_from_openapi3(path, method, operation, data)
                    tags = operation.get('tags', ['Default'])
                    tag = tags[0] if tags else 'Default'

                    if tag not in collections_map:
                        collections_map[tag] = {
                            'name': tag,
                            'description': '',
                            'requests': []
                        }
                    collections_map[tag]['requests'].append(request_data)
                    total += 1

        # 从 tags 定义获取描述
        for tag_def in data.get('tags', []):
            tag_name = tag_def.get('name', '')
            if tag_name in collections_map:
                collections_map[tag_name]['description'] = tag_def.get('description', '')

        return {
            'title': title,
            'description': description,
            'base_url': base_url,
            'collections': list(collections_map.values()),
            'total_requests': total,
        }

    def _build_request_from_openapi3(self, path, method, operation, spec):
        """从 OpenAPI 3.0 operation 构建请求数据"""
        name = operation.get('summary') or operation.get('operationId') or f'{method.upper()} {path}'
        description = operation.get('description', '')

        # 解析参数
        headers = []
        params = {}
        for param in operation.get('parameters', []):
            param_in = param.get('in', '')
            param_name = param.get('name', '')
            example = self._get_example(param.get('schema', {}))

            if param_in == 'header':
                item = normalize_import_header(
                    param_name,
                    str(example) if example else '',
                    description=param.get('description', ''),
                )
                if item:
                    headers.append(item)
            elif param_in == 'query':
                params[param_name] = str(example) if example else ''

        # 解析请求体
        body = {}
        request_body = operation.get('requestBody', {})
        if request_body:
            content = request_body.get('content', {})
            if 'application/json' in content:
                schema = content['application/json'].get('schema', {})
                example = content['application/json'].get('example')
                if example:
                    body = {'type': 'json', 'data': example}
                else:
                    body = {'type': 'json', 'data': self._generate_example_from_schema(schema, spec)}
            elif 'application/x-www-form-urlencoded' in content:
                schema = content['application/x-www-form-urlencoded'].get('schema', {})
                body = {'type': 'x-www-form-urlencoded', 'data': self._generate_example_from_schema(schema, spec)}
            elif 'multipart/form-data' in content:
                schema = content['multipart/form-data'].get('schema', {})
                body = {'type': 'form-data', 'data': self._generate_example_from_schema(schema, spec)}

        return {
            'name': name,
            'description': description,
            'method': method.upper(),
            'url': path,
            'headers': headers,
            'params': params,
            'body': body,
        }

    def _parse_swagger2(self, data):
        info = data.get('info', {})
        title = info.get('title', 'Imported API')
        description = info.get('description', '')

        host = data.get('host', '')
        base_path = data.get('basePath', '')
        schemes = data.get('schemes', ['https'])
        base_url = f'{schemes[0]}://{host}{base_path}' if host else base_path

        paths = data.get('paths', {})
        collections_map = {}
        total = 0

        for path, methods in paths.items():
            for method, operation in methods.items():
                if method.lower() in ('get', 'post', 'put', 'delete', 'patch', 'head', 'options'):
                    request_data = self._build_request_from_swagger2(path, method, operation, data)
                    tags = operation.get('tags', ['Default'])
                    tag = tags[0] if tags else 'Default'

                    if tag not in collections_map:
                        collections_map[tag] = {
                            'name': tag,
                            'description': '',
                            'requests': []
                        }
                    collections_map[tag]['requests'].append(request_data)
                    total += 1

        for tag_def in data.get('tags', []):
            tag_name = tag_def.get('name', '')
            if tag_name in collections_map:
                collections_map[tag_name]['description'] = tag_def.get('description', '')

        return {
            'title': title,
            'description': description,
            'base_url': base_url,
            'collections': list(collections_map.values()),
            'total_requests': total,
        }

    def _build_request_from_swagger2(self, path, method, operation, spec):
        name = operation.get('summary') or operation.get('operationId') or f'{method.upper()} {path}'
        description = operation.get('description', '')

        headers = []
        params = {}
        body = {}

        for param in operation.get('parameters', []):
            param_in = param.get('in', '')
            param_name = param.get('name', '')

            if param_in == 'header':
                item = normalize_import_header(
                    param_name,
                    '',
                    description=param.get('description', ''),
                )
                if item:
                    headers.append(item)
            elif param_in == 'query':
                params[param_name] = ''
            elif param_in == 'body':
                schema = param.get('schema', {})
                body = {'type': 'json', 'data': self._generate_example_from_schema(schema, spec)}
            elif param_in == 'formData':
                if not body:
                    body = {'type': 'form-data', 'data': {}}
                body['data'][param_name] = ''

        return {
            'name': name,
            'description': description,
            'method': method.upper(),
            'url': path,
            'headers': headers,
            'params': params,
            'body': body,
        }

    def _get_example(self, schema):
        if 'example' in schema:
            return schema['example']
        if 'default' in schema:
            return schema['default']
        type_ = schema.get('type', 'string')
        defaults = {'string': '', 'integer': 0, 'number': 0.0, 'boolean': False, 'array': [], 'object': {}}
        return defaults.get(type_, '')

    def _generate_example_from_schema(self, schema, spec, depth=0):
        """从 schema 生成示例数据，限制递归深度"""
        if depth > 5:
            return {}

        # 处理 $ref
        if '$ref' in schema:
            schema = self._resolve_ref(schema['$ref'], spec)
            if not schema:
                return {}

        if 'example' in schema:
            return schema['example']

        type_ = schema.get('type', 'object')

        if type_ == 'object':
            result = {}
            for prop_name, prop_schema in schema.get('properties', {}).items():
                result[prop_name] = self._generate_example_from_schema(prop_schema, spec, depth + 1)
            return result
        elif type_ == 'array':
            items = schema.get('items', {})
            return [self._generate_example_from_schema(items, spec, depth + 1)]
        else:
            return self._get_example(schema)

    def _resolve_ref(self, ref, spec):
        """解析 $ref 引用"""
        if not ref.startswith('#/'):
            return {}
        parts = ref[2:].split('/')
        current = spec
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return {}
        return current if isinstance(current, dict) else {}
