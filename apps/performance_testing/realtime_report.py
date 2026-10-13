import csv
import io
import json
import re
from collections import defaultdict
from datetime import UTC, timedelta
from urllib.parse import quote, urlencode

from django.conf import settings
from django.utils import timezone
import httpx


REALTIME_FIELDS = [
    'avg', 'min', 'max', 'hit', 'count', 'countError', 'rb', 'sb',
    'pct90', 'pct90.0', 'pct95', 'pct95.0', 'pct99', 'pct99.0',
    'minAT', 'maxAT', 'meanAT', 'startedT', 'endedT',
]
WINDOW_PATTERN = re.compile(r'^\d+[smhd]$')


def get_realtime_report_config(test_title='', execution=None):
    config = getattr(settings, 'PERFORMANCE_REALTIME_REPORT', {}) or {}
    if not config.get('enabled'):
        return None

    custom_tags = {}
    if execution:
        custom_tags = {
            'testhubExecutionId': execution.id,
            'testhubProjectId': execution.project_id,
            'testhubScriptId': execution.script_id,
        }

    write_url = config.get('write_url') or _build_v1_write_url(config)
    return {
        'enabled': True,
        'backend_class': 'org.apache.jmeter.visualizers.backend.influxdb.InfluxdbBackendListenerClient',
        'queue_size': config.get('queue_size') or 5000,
        'influxdb_metrics_sender': 'org.apache.jmeter.visualizers.backend.influxdb.HttpMetricsSender',
        'influxdb_url': write_url,
        'influxdb_token': config.get('token') or '',
        'application': config.get('application') or 'testhub',
        'measurement': config.get('measurement') or 'jmeter',
        'summary_only': bool(config.get('summary_only')),
        'samplers_regex': config.get('samplers_regex') or '.*',
        'percentiles': config.get('percentiles') or '99;95;90',
        'test_title': test_title or config.get('test_title') or 'TestHub Performance Test',
        'event_tags': config.get('event_tags') or '',
        'custom_tags': custom_tags,
    }


def _build_v1_write_url(config):
    base_url = (config.get('url') or 'http://localhost:8086').rstrip('/')
    query = {'db': config.get('database') or 'jmeter'}
    retention_policy = config.get('retention_policy')
    if retention_policy:
        query['rp'] = retention_policy
    return f'{base_url}/write?{urlencode(query)}'


def get_realtime_report_url(execution):
    config = getattr(settings, 'PERFORMANCE_REALTIME_REPORT', {}) or {}
    if not config.get('enabled'):
        return ''

    frontend_url = getattr(settings, 'FRONTEND_URL', '').rstrip('/')
    if frontend_url:
        return f'{frontend_url}/performance-testing/realtime-reports/{execution.id}'
    return f'/performance-testing/realtime-reports/{execution.id}'


def get_realtime_dashboard_url(execution):
    config = getattr(settings, 'PERFORMANCE_REALTIME_REPORT', {}) or {}
    if not config.get('enabled') or not config.get('dashboard_url'):
        return get_realtime_report_url(execution)

    values = {
        'execution_id': execution.id,
        'project': execution.project.name if execution.project_id else '',
        'script': execution.script.name if execution.script_id else '',
        'application': config.get('application') or 'testhub',
        'measurement': config.get('measurement') or 'jmeter',
    }
    url = config['dashboard_url']
    for key, value in values.items():
        url = url.replace('{' + key + '}', quote(str(value), safe=''))
    return url


def query_realtime_report(execution, window=''):
    config = getattr(settings, 'PERFORMANCE_REALTIME_REPORT', {}) or {}
    base_response = {
        'enabled': bool(config.get('enabled')),
        'configured': False,
        'available': False,
        'error': '',
        'execution': {
            'id': execution.id,
            'status': execution.status,
            'script_name': execution.script.name if execution.script_id else '',
            'project_name': execution.project.name if execution.project_id else '',
        },
        'summary': {},
        'series': {
            'response_time': [],
            'throughput': [],
            'errors': [],
            'threads': [],
        },
        'transactions': [],
        'range': {},
        'point_count': 0,
    }
    if not config.get('enabled'):
        base_response['error'] = '实时报告未启用'
        return base_response

    missing = _missing_query_config(config)
    if missing:
        base_response['error'] = f'实时报告查询配置缺失: {", ".join(missing)}'
        return base_response

    window = _normalize_window(window or config.get('query_window') or '5s')
    start, stop = _query_range(execution)
    query = _build_flux_query(config, execution, start, stop, window)
    base_response['configured'] = True
    base_response['range'] = {
        'start': _isoformat(start),
        'stop': _isoformat(stop),
        'window': window,
        'bucket': config.get('bucket') or config.get('database') or 'jmeter',
        'measurement': config.get('measurement') or 'jmeter',
        'application': config.get('application') or 'testhub',
    }

    try:
        response = _post_flux_query(config, query)
    except httpx.TimeoutException:
        base_response['error'] = 'InfluxDB 查询超时'
        return base_response
    except httpx.HTTPError as exc:
        base_response['error'] = f'InfluxDB 查询失败: {exc.__class__.__name__}'
        return base_response

    if response.status_code >= 400:
        detail = _response_error_detail(response)
        base_response['error'] = f'InfluxDB 查询失败: HTTP {response.status_code}'
        if detail:
            base_response['error'] = f'{base_response["error"]}: {detail}'
        return base_response

    rows = _parse_annotated_csv(response.text)
    report = _build_report(rows)
    base_response.update(report)
    base_response['available'] = True
    base_response['point_count'] = len(rows)
    return base_response


def _missing_query_config(config):
    missing = []
    if not config.get('url'):
        missing.append('url')
    if not (config.get('org') or config.get('org_id')):
        missing.append('org')
    if not (config.get('bucket') or config.get('database')):
        missing.append('bucket')
    if not config.get('token'):
        missing.append('token')
    return missing


def _normalize_window(value):
    text = str(value or '5s').strip()
    if WINDOW_PATTERN.match(text):
        return text
    return '5s'


def _query_range(execution):
    start = execution.started_at or execution.created_at or timezone.now()
    start = start - timedelta(seconds=30)
    stop = execution.finished_at or timezone.now()
    stop = stop + timedelta(seconds=30)
    if stop <= start:
        stop = start + timedelta(minutes=5)
    return start, stop


def _build_flux_query(config, execution, start, stop, window):
    field_filter = ' or '.join(f'r._field == {_flux_string(field)}' for field in REALTIME_FIELDS)
    filters = [
        f'r._measurement == {_flux_string(config.get("measurement") or "jmeter")}',
        f'r.application == {_flux_string(config.get("application") or "testhub")}',
        f'r.testhubExecutionId == {_flux_string(str(execution.id))}',
        f'({field_filter})',
    ]
    filter_text = ' and '.join(filters)
    return '\n'.join([
        f'from(bucket: {_flux_string(config.get("bucket") or config.get("database") or "jmeter")})',
        f'  |> range(start: time(v: {_flux_string(_isoformat(start))}), stop: time(v: {_flux_string(_isoformat(stop))}))',
        f'  |> filter(fn: (r) => {filter_text})',
        f'  |> aggregateWindow(every: {window}, fn: mean, createEmpty: false)',
        '  |> yield(name: "testhub_realtime")',
    ])


def _post_flux_query(config, query):
    base_url = (config.get('url') or 'http://localhost:8086').rstrip('/')
    return httpx.post(
        f'{base_url}/api/v2/query',
        params=_query_org_params(config),
        headers={
            'Authorization': f'Token {config.get("token")}',
            'Accept': 'application/csv',
            'Content-Type': 'application/vnd.flux',
        },
        content=query.encode('utf-8'),
        timeout=float(config.get('query_timeout') or 10),
    )


def _query_org_params(config):
    org = str(config.get('org') or '').strip()
    org_id = str(config.get('org_id') or '').strip()
    if org_id and _looks_like_org_id(org_id):
        return {'orgID': org_id}
    if org:
        return {'org': org}
    return {'org': org_id} if org_id else {}


def _looks_like_org_id(value):
    text = str(value or '').strip()
    return bool(re.fullmatch(r'[0-9a-fA-F]{16}|[0-9a-fA-F]{32}|[0-9a-fA-F-]{36}', text))


def _response_error_detail(response):
    text = (response.text or '').strip()
    if not text:
        return ''
    try:
        payload = response.json()
    except ValueError:
        return text[:500]

    if isinstance(payload, dict):
        for key in ('message', 'error', 'code'):
            if payload.get(key):
                return str(payload[key])[:500]
    return text[:500]


def _parse_annotated_csv(content):
    rows = []
    header = None
    for row in csv.reader(io.StringIO(content or '')):
        if not row or row[0].startswith('#'):
            continue
        if '_time' in row and '_value' in row:
            header = row
            continue
        if not header:
            continue
        if len(row) < len(header):
            row = row + [''] * (len(header) - len(row))
        data = dict(zip(header, row))
        data['_value'] = _float_value(data.get('_value'))
        rows.append(data)
    return rows


def _build_report(rows):
    response_rows = [row for row in rows if row.get('transaction') == 'all']
    thread_rows = [row for row in rows if row.get('transaction') == 'internal']
    return {
        'summary': _summary(response_rows, thread_rows),
        'series': {
            'response_time': _response_time_series(response_rows),
            'throughput': _single_field_series(response_rows, 'hit', 'throughput'),
            'errors': _error_series(response_rows),
            'threads': _single_field_series(thread_rows, 'maxAT', 'active_threads'),
        },
        'transactions': _transaction_rows(rows),
    }


def _response_time_series(rows):
    by_time = defaultdict(dict)
    for row in rows:
        alias = _field_alias(row.get('_field'))
        if alias in ('avg', 'p90', 'p95', 'p99', 'min', 'max'):
            by_time[row.get('_time')][alias] = row.get('_value')
    return _sorted_points(by_time)


def _single_field_series(rows, field, alias):
    by_time = defaultdict(dict)
    for row in rows:
        if row.get('_field') == field:
            by_time[row.get('_time')][alias] = row.get('_value')
    return _sorted_points(by_time)


def _error_series(rows):
    by_time = defaultdict(dict)
    for row in rows:
        alias = _field_alias(row.get('_field'))
        if alias == 'samples':
            by_time[row.get('_time')]['samples'] = row.get('_value')
        elif alias == 'errors':
            by_time[row.get('_time')]['errors'] = row.get('_value')
    points = _sorted_points(by_time)
    for point in points:
        samples = point.get('samples') or 0
        errors = point.get('errors') or 0
        point['error_rate'] = round(errors / samples * 100, 2) if samples else 0
    return points


def _transaction_rows(rows):
    grouped = {}
    for row in rows:
        transaction = row.get('transaction') or ''
        if transaction in ('', 'all', 'internal'):
            continue
        item = grouped.setdefault(transaction, {
            'name': transaction,
            'samples': 0,
            'errors': 0,
            'avg': None,
            'p95': None,
            'p99': None,
            'throughput': None,
            '_latest': '',
        })
        alias = _field_alias(row.get('_field'))
        value = row.get('_value')
        if alias == 'samples':
            item['samples'] += value or 0
        elif alias == 'errors':
            item['errors'] += value or 0
        elif alias in ('avg', 'p95', 'p99', 'throughput') and row.get('_time', '') >= item['_latest']:
            item[alias] = value
            item['_latest'] = row.get('_time', '')

    transactions = []
    for item in grouped.values():
        item.pop('_latest', None)
        item['samples'] = int(round(item['samples'] or 0))
        item['errors'] = int(round(item['errors'] or 0))
        item['error_rate'] = round(item['errors'] / item['samples'] * 100, 2) if item['samples'] else 0
        transactions.append(item)
    return sorted(transactions, key=lambda item: item['samples'], reverse=True)


def _summary(response_rows, thread_rows):
    error_points = _error_series(response_rows)
    response_points = _response_time_series(response_rows)
    throughput_points = _single_field_series(response_rows, 'hit', 'throughput')
    thread_points = _single_field_series(thread_rows, 'maxAT', 'active_threads')
    samples = sum(point.get('samples') or 0 for point in error_points)
    errors = sum(point.get('errors') or 0 for point in error_points)
    latest_response = response_points[-1] if response_points else {}
    latest_throughput = throughput_points[-1] if throughput_points else {}
    latest_threads = thread_points[-1] if thread_points else {}
    return {
        'samples': int(round(samples)),
        'errors': int(round(errors)),
        'error_rate': round(errors / samples * 100, 2) if samples else 0,
        'avg_response_time': _round(latest_response.get('avg')),
        'p95_response_time': _round(latest_response.get('p95')),
        'p99_response_time': _round(latest_response.get('p99')),
        'throughput': _round(latest_throughput.get('throughput')),
        'active_threads': _round(latest_threads.get('active_threads')),
    }


def _sorted_points(by_time):
    return [
        {'time': key, **_round_dict(value)}
        for key, value in sorted(by_time.items())
        if key
    ]


def _field_alias(field):
    aliases = {
        'pct90': 'p90',
        'pct90.0': 'p90',
        'pct95': 'p95',
        'pct95.0': 'p95',
        'pct99': 'p99',
        'pct99.0': 'p99',
        'count': 'samples',
        'countError': 'errors',
        'hit': 'throughput',
    }
    return aliases.get(field, field)


def _round_dict(value):
    return {key: _round(item) for key, item in value.items()}


def _round(value):
    if value is None:
        return None
    return round(float(value), 2)


def _float_value(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flux_string(value):
    return json.dumps(str(value))


def _isoformat(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')
