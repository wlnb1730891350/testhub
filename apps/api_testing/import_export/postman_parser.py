"""
Postman Collection v2.1 解析器
"""
import json
import logging

from .header_utils import normalize_import_headers

logger = logging.getLogger(__name__)


class PostmanParser:
    """解析 Postman Collection v2.1 格式"""

    def parse(self, content, filename=''):
        """
        解析 Postman Collection JSON
        Returns:
            dict: { title, description, base_url, collections, total_requests }
        """
        try:
            data = json.loads(content) if isinstance(content, str) else content
        except json.JSONDecodeError:
            raise ValueError('无效的 JSON 格式')

        # 支持 {"collection": {...}} 包装格式（Postman API 导出）
        if 'collection' in data and isinstance(data['collection'], dict):
            data = data['collection']

        info = data.get('info', {})
        schema_url = info.get('schema', '')

        # 兼容 http/https 以及第三方工具（如 Apifox）的导出格式
        is_postman_v2 = (
            schema_url.startswith('https://schema.getpostman.com/json/collection/v2')
            or schema_url.startswith('http://schema.getpostman.com/json/collection/v2')
        )
        # 即使没有标准 schema URL，只要有 info.name 和 item 数组就尝试解析
        has_collection_structure = info.get('name') and isinstance(data.get('item'), list)

        if not is_postman_v2 and not has_collection_structure:
            raise ValueError('不支持的 Postman Collection 版本，仅支持 v2.x')

        title = info.get('name', 'Imported Collection')
        description = info.get('description', '')

        collections = []
        total = [0]  # 用列表以便在递归中修改

        items = data.get('item', [])
        self._parse_items(items, collections, total)

        return {
            'title': title,
            'description': description if isinstance(description, str) else str(description),
            'base_url': '',
            'collections': collections,
            'total_requests': total[0],
        }

    def _parse_items(self, items, collections, total, parent_name=''):
        """递归解析 Postman items（文件夹和请求）"""
        # 把同级别的请求收集到一个默认集合中
        loose_requests = []

        for item in items:
            if 'item' in item:
                # 文件夹 → Collection
                collection = {
                    'name': item.get('name', 'Unnamed'),
                    'description': self._get_description(item),
                    'requests': [],
                }
                sub_collections = []
                self._parse_folder(item['item'], collection, sub_collections, total)
                collections.append(collection)
                collections.extend(sub_collections)
            elif 'request' in item:
                # 请求
                request_data = self._parse_request(item)
                loose_requests.append(request_data)
                total[0] += 1

        if loose_requests:
            collection_name = parent_name or 'Default'
            collections.append({
                'name': collection_name,
                'description': '',
                'requests': loose_requests,
            })

    def _parse_folder(self, items, collection, sub_collections, total):
        """解析文件夹内容"""
        for item in items:
            if 'item' in item:
                # 子文件夹 → 独立 collection
                sub = {
                    'name': f"{collection['name']} / {item.get('name', 'Unnamed')}",
                    'description': self._get_description(item),
                    'requests': [],
                }
                self._parse_folder(item['item'], sub, sub_collections, total)
                sub_collections.append(sub)
            elif 'request' in item:
                request_data = self._parse_request(item)
                collection['requests'].append(request_data)
                total[0] += 1

    def _parse_request(self, item):
        """解析单个 Postman 请求"""
        req = item.get('request', {})
        if isinstance(req, str):
            return {
                'name': item.get('name', 'Unnamed'),
                'description': '',
                'method': 'GET',
                'url': req,
                'headers': [],
                'params': {},
                'body': {},
            }

        # URL
        url_obj = req.get('url', {})
        if isinstance(url_obj, str):
            url = url_obj
            params = {}
        else:
            raw = url_obj.get('raw', '')
            url = raw
            params = {}
            for q in url_obj.get('query', []):
                if q.get('key'):
                    params[q['key']] = q.get('value', '')

        # Method
        method = req.get('method', 'GET').upper()

        # Headers
        headers = normalize_import_headers(req.get('header', []))

        # Body
        body = {}
        body_obj = req.get('body', {})
        if body_obj:
            mode = body_obj.get('mode', '')
            if mode == 'raw':
                raw_content = body_obj.get('raw', '')
                # 检查是否是 JSON
                options = body_obj.get('options', {})
                lang = options.get('raw', {}).get('language', '')
                if lang == 'json' or self._is_json(raw_content):
                    try:
                        body = {'type': 'json', 'data': json.loads(raw_content)}
                    except json.JSONDecodeError:
                        body = {'type': 'raw', 'data': raw_content}
                else:
                    body = {'type': 'raw', 'data': raw_content}
            elif mode == 'urlencoded':
                data = {}
                for item_data in body_obj.get('urlencoded', []):
                    if item_data.get('key'):
                        data[item_data['key']] = item_data.get('value', '')
                body = {'type': 'x-www-form-urlencoded', 'data': data}
            elif mode == 'formdata':
                data = {}
                for item_data in body_obj.get('formdata', []):
                    if item_data.get('key'):
                        data[item_data['key']] = item_data.get('value', '')
                body = {'type': 'form-data', 'data': data}

        # Description
        desc = self._get_description(item)

        return {
            'name': item.get('name', 'Unnamed'),
            'description': desc,
            'method': method,
            'url': url,
            'headers': headers,
            'params': params,
            'body': body,
        }

    def _get_description(self, item):
        desc = item.get('description', '')
        if isinstance(desc, dict):
            return desc.get('content', '')
        return desc or ''

    def _is_json(self, text):
        if not text or not isinstance(text, str):
            return False
        text = text.strip()
        return (text.startswith('{') and text.endswith('}')) or \
               (text.startswith('[') and text.endswith(']'))
