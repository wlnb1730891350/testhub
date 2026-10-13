"""
Swagger 2.0 导出器
将 TestHub 项目数据导出为 Swagger 2.0 规范
"""
import logging
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


class SwaggerExporter:
    """导出为 Swagger 2.0 格式"""

    def export(self, project, collections, requests):
        """
        导出项目为 Swagger 2.0 JSON
        Args:
            project: ApiProject 实例
            collections: QuerySet of ApiCollection
            requests: QuerySet of ApiRequest
        Returns:
            dict: Swagger 2.0 规范
        """
        host, base_path, schemes = self._infer_server_info(requests)

        spec = {
            'swagger': '2.0',
            'info': {
                'title': project.name,
                'description': project.description or '',
                'version': '1.0.0',
            },
            'paths': {},
            'definitions': {},
            'tags': [],
        }

        if host:
            spec['host'] = host
        if base_path:
            spec['basePath'] = base_path
        if schemes:
            spec['schemes'] = schemes

        # 构建 tags
        collection_map = {}
        for col in collections:
            tag_name = col.name
            spec['tags'].append({
                'name': tag_name,
                'description': col.description or '',
            })
            collection_map[col.id] = tag_name

        # 构建 paths
        for req in requests:
            path = self._normalize_path(req.url or '/')
            method = req.method.lower()
            tag = collection_map.get(req.collection_id, 'Default')

            operation = {
                'summary': req.name,
                'description': req.description or '',
                'tags': [tag],
                'operationId': f'{method}_{path.replace("/", "_").strip("_")}',
                'consumes': [],
                'produces': ['application/json'],
                'parameters': [],
                'responses': {
                    '200': {
                        'description': 'Successful response',
                    }
                },
            }

            # Query 参数
            if req.params and isinstance(req.params, dict):
                for key, value in req.params.items():
                    operation['parameters'].append({
                        'name': key,
                        'in': 'query',
                        'type': 'string',
                        'required': False,
                        'example': value if isinstance(value, str) else str(value),
                    })

            # Header 参数
            header_items = req.headers if isinstance(req.headers, list) else []
            for header in header_items:
                if not isinstance(header, dict) or not header.get('key'):
                    continue
                if header['key'].lower() == 'content-type':
                    continue
                operation['parameters'].append({
                    'name': header['key'],
                    'in': 'header',
                    'type': 'string',
                    'required': False,
                    'example': header.get('value', ''),
                })

            # Request Body
            if req.body and isinstance(req.body, dict):
                body_type = req.body.get('type', '')
                body_data = req.body.get('data', {})

                if body_type in ('json', 'raw') and body_data is not None:
                    operation['consumes'] = ['application/json']
                    operation['parameters'].append({
                        'name': 'body',
                        'in': 'body',
                        'required': True,
                        'schema': self._infer_schema(body_data),
                    })
                elif body_type == 'xml':
                    operation['consumes'] = ['application/xml']
                    operation['parameters'].append({
                        'name': 'body',
                        'in': 'body',
                        'required': True,
                        'schema': {
                            'type': 'string',
                            'example': body_data,
                        },
                    })
                elif body_type == 'x-www-form-urlencoded' and isinstance(body_data, dict):
                    operation['consumes'] = ['application/x-www-form-urlencoded']
                    for key, value in body_data.items():
                        operation['parameters'].append({
                            'name': key,
                            'in': 'formData',
                            'type': 'string',
                            'required': False,
                            'example': value if isinstance(value, str) else str(value),
                        })
                elif body_type == 'form-data' and isinstance(body_data, dict):
                    operation['consumes'] = ['multipart/form-data']
                    for key, value in body_data.items():
                        operation['parameters'].append({
                            'name': key,
                            'in': 'formData',
                            'type': 'string',
                            'required': False,
                            'example': value if isinstance(value, str) else str(value),
                        })

            # Swagger 2.0 中 path 参数需要显式声明
            for path_param in self._extract_path_params(path):
                operation['parameters'].append({
                    'name': path_param,
                    'in': 'path',
                    'type': 'string',
                    'required': True,
                })

            # 清理空数组，避免生成过多无效字段
            if not operation['consumes']:
                operation.pop('consumes', None)

            if path not in spec['paths']:
                spec['paths'][path] = {}
            spec['paths'][path][method] = operation

        return spec

    def _infer_server_info(self, requests):
        """从请求 URL 推断 Swagger 的 host/basePath/schemes"""
        for req in requests:
            url = getattr(req, 'url', '') or ''
            if not url:
                continue
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                path = parsed.path or '/'
                base_path = path.rsplit('/', 1)[0] if '/' in path.rstrip('/') else '/'
                if not base_path.startswith('/'):
                    base_path = f'/{base_path}'
                if base_path == '':
                    base_path = '/'
                return parsed.netloc, base_path, [parsed.scheme]
        return '', '', ['https']

    def _normalize_path(self, path):
        """将请求 URL 归一化为 Swagger path"""
        if not path:
            return '/'

        parsed = urlparse(path)
        if parsed.scheme and parsed.netloc:
            path = parsed.path or '/'
        elif '?' in path:
            path = path.split('?', 1)[0]

        if not path.startswith('/'):
            path = f'/{path}'

        # 保留花括号路径参数，兼容 /api/{id} 形式
        return path or '/'

    def _extract_path_params(self, path):
        """提取 Swagger 路径参数名"""
        params = []
        current = ''
        in_brace = False
        for char in path:
            if char == '{':
                current = ''
                in_brace = True
            elif char == '}' and in_brace:
                if current:
                    params.append(current)
                current = ''
                in_brace = False
            elif in_brace:
                current += char
        return params

    def _infer_schema(self, data):
        """从数据推断 JSON Schema"""
        if isinstance(data, dict):
            properties = {k: self._infer_schema(v) for k, v in data.items()}
            return {'type': 'object', 'properties': properties}
        if isinstance(data, list):
            items = self._infer_schema(data[0]) if data else {'type': 'string'}
            return {'type': 'array', 'items': items}
        if isinstance(data, bool):
            return {'type': 'boolean'}
        if isinstance(data, int):
            return {'type': 'integer'}
        if isinstance(data, float):
            return {'type': 'number'}
        return {'type': 'string'}
