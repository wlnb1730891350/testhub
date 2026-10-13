"""
OpenAPI 3.0 导出器
将 TestHub 项目数据导出为 OpenAPI 3.0 规范
"""
import json
import logging

logger = logging.getLogger(__name__)


class OpenAPIExporter:
    """导出为 OpenAPI 3.0 格式"""

    def export(self, project, collections, requests):
        """
        导出项目为 OpenAPI 3.0 JSON
        Args:
            project: ApiProject 实例
            collections: QuerySet of ApiCollection
            requests: QuerySet of ApiRequest
        Returns:
            dict: OpenAPI 3.0 规范
        """
        spec = {
            'openapi': '3.0.3',
            'info': {
                'title': project.name,
                'description': project.description or '',
                'version': '1.0.0',
            },
            'paths': {},
            'tags': [],
        }

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
            path = req.url or '/'
            # 如果是 http(s) 开头，则保留完整 URL，否则确保以 / 开头
            if not path.startswith('http') and not path.startswith('/'):
                # 尝试提取路径部分
                from urllib.parse import urlparse
                parsed = urlparse(path)
                path = parsed.path or '/'

            method = req.method.lower()
            tag = collection_map.get(req.collection_id, 'Default')

            operation = {
                'summary': req.name,
                'description': req.description or '',
                'tags': [tag],
                'operationId': f'{method}_{path.replace("/", "_").strip("_")}',
                'responses': {
                    '200': {
                        'description': 'Successful response',
                    }
                },
            }

            # 参数
            parameters = []

            # Query params
            if req.params and isinstance(req.params, dict):
                for key, value in req.params.items():
                    parameters.append({
                        'name': key,
                        'in': 'query',
                        'schema': {'type': 'string'},
                        'example': value if isinstance(value, str) else str(value),
                    })

            # Headers
            if req.headers:
                header_list = req.headers if isinstance(req.headers, list) else []
                for h in header_list:
                    if isinstance(h, dict) and h.get('key'):
                        # 跳过 Content-Type（OpenAPI 在 requestBody 中处理）
                        if h['key'].lower() == 'content-type':
                            continue
                        parameters.append({
                            'name': h['key'],
                            'in': 'header',
                            'schema': {'type': 'string'},
                            'example': h.get('value', ''),
                        })

            if parameters:
                operation['parameters'] = parameters

            # Request Body
            if req.body and isinstance(req.body, dict):
                body_type = req.body.get('type', '')
                body_data = req.body.get('data', {})

                if body_type == 'json' and body_data:
                    operation['requestBody'] = {
                        'content': {
                            'application/json': {
                                'schema': self._infer_schema(body_data),
                                'example': body_data,
                            }
                        }
                    }
                elif body_type == 'x-www-form-urlencoded' and body_data:
                    properties = {k: {'type': 'string'} for k in body_data}
                    operation['requestBody'] = {
                        'content': {
                            'application/x-www-form-urlencoded': {
                                'schema': {
                                    'type': 'object',
                                    'properties': properties,
                                }
                            }
                        }
                    }

            # 添加到 paths
            if path not in spec['paths']:
                spec['paths'][path] = {}

            # 如果同一路径和方法已存在，说明有同名的 URL 和 Method（比如变量不同），可以给 operationId 或者 path 加个后缀
            if method in spec['paths'][path]:
                # 尝试使用 operationId 作为后缀避免覆盖
                unique_path = f"{path}?req_id={req.id}"
                if unique_path not in spec['paths']:
                    spec['paths'][unique_path] = {}
                spec['paths'][unique_path][method] = operation
            else:
                spec['paths'][path][method] = operation

        return spec

    def _infer_schema(self, data):
        """从数据推导 JSON Schema"""
        if isinstance(data, dict):
            properties = {}
            for k, v in data.items():
                properties[k] = self._infer_schema(v)
            return {'type': 'object', 'properties': properties}
        elif isinstance(data, list):
            items = self._infer_schema(data[0]) if data else {'type': 'string'}
            return {'type': 'array', 'items': items}
        elif isinstance(data, bool):
            return {'type': 'boolean'}
        elif isinstance(data, int):
            return {'type': 'integer'}
        elif isinstance(data, float):
            return {'type': 'number'}
        else:
            return {'type': 'string'}
