"""
Postman Collection v2.1 导出器
"""
import json
import uuid
import logging

logger = logging.getLogger(__name__)


class PostmanExporter:
    """导出为 Postman Collection v2.1 格式"""

    def export(self, project, collections, requests):
        """
        导出项目为 Postman Collection v2.1 JSON
        Args:
            project: ApiProject 实例
            collections: QuerySet of ApiCollection
            requests: QuerySet of ApiRequest
        Returns:
            dict: Postman Collection v2.1
        """
        collection = {
            'info': {
                '_postman_id': str(uuid.uuid4()),
                'name': project.name,
                'description': project.description or '',
                'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
            },
            'item': [],
        }

        # 按集合分组请求
        collection_requests = {}
        no_collection_requests = []

        for req in requests:
            if req.collection_id:
                if req.collection_id not in collection_requests:
                    collection_requests[req.collection_id] = []
                collection_requests[req.collection_id].append(req)
            else:
                no_collection_requests.append(req)

        # 构建集合文件夹
        for col in collections:
            folder = {
                'name': col.name,
                'description': col.description or '',
                'item': [],
            }

            reqs = collection_requests.get(col.id, [])
            for req in reqs:
                folder['item'].append(self._build_request_item(req))

            if folder['item']:
                collection['item'].append(folder)

        # 无集合的请求放在根级别
        for req in no_collection_requests:
            collection['item'].append(self._build_request_item(req))

        return collection

    def _build_request_item(self, req):
        """将 ApiRequest 转换为 Postman request item"""
        # URL 解析
        url = req.url or ''
        url_obj = {'raw': url}

        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(url)

        if parsed.scheme:
            url_obj['protocol'] = parsed.scheme
        if parsed.hostname:
            url_obj['host'] = parsed.hostname.split('.')
        if parsed.port:
            url_obj['port'] = str(parsed.port)
        if parsed.path:
            url_obj['path'] = [p for p in parsed.path.split('/') if p]

        # Query params
        query = []
        if req.params and isinstance(req.params, dict):
            for k, v in req.params.items():
                query.append({'key': k, 'value': str(v) if v else ''})
        if query:
            url_obj['query'] = query

        # Headers
        headers = []
        if req.headers:
            if isinstance(req.headers, list):
                for h in req.headers:
                    if isinstance(h, dict) and h.get('key'):
                        headers.append({
                            'key': h['key'],
                            'value': h.get('value', ''),
                            'description': h.get('description', ''),
                            'disabled': not h.get('enabled', True),
                        })
            elif isinstance(req.headers, dict):
                for k, v in req.headers.items():
                    headers.append({
                        'key': k,
                        'value': str(v) if v else '',
                    })

        # Body
        body = None
        if req.body and isinstance(req.body, dict):
            body_type = req.body.get('type', '')
            body_data = req.body.get('data', {})

            if body_type == 'json' and body_data:
                body = {
                    'mode': 'raw',
                    'raw': json.dumps(body_data, ensure_ascii=False, indent=2),
                    'options': {
                        'raw': {'language': 'json'}
                    },
                }
            elif body_type == 'x-www-form-urlencoded' and isinstance(body_data, dict):
                body = {
                    'mode': 'urlencoded',
                    'urlencoded': [
                        {'key': k, 'value': str(v), 'type': 'text'}
                        for k, v in body_data.items()
                    ],
                }
            elif body_type == 'form-data' and isinstance(body_data, dict):
                body = {
                    'mode': 'formdata',
                    'formdata': [
                        {'key': k, 'value': str(v), 'type': 'text'}
                        for k, v in body_data.items()
                    ],
                }
            elif body_type == 'raw':
                body = {
                    'mode': 'raw',
                    'raw': str(body_data),
                }

        request_obj = {
            'method': req.method,
            'header': headers,
            'url': url_obj,
        }
        if body:
            request_obj['body'] = body
        if req.description:
            request_obj['description'] = req.description

        return {
            'name': req.name,
            'request': request_obj,
        }
