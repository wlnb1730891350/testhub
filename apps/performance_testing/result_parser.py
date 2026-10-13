import csv
import statistics
from collections import defaultdict


def parse_jtl(jtl_path):
    rows = []
    try:
        with open(jtl_path, 'r', encoding='utf-8-sig', newline='') as handle:
            sample = handle.read(4096)
            handle.seek(0)
            if not sample.strip():
                return _empty_result()
            reader = csv.DictReader(handle)
            for row in reader:
                parsed = _parse_row(row)
                if parsed:
                    rows.append(parsed)
    except FileNotFoundError:
        return _empty_result(error='JTL结果文件不存在')

    if not rows:
        return _empty_result()

    summary = _aggregate(rows)
    labels = {}
    for label, label_rows in _group_by_label(rows).items():
        labels[label] = _aggregate(label_rows)

    return {
        'summary': summary,
        'labels': labels,
        'timeline': _timeline(rows),
        'errors': _errors(rows),
    }


def _parse_row(row):
    try:
        elapsed = float(row.get('elapsed') or row.get('Elapsed') or 0)
    except (TypeError, ValueError):
        elapsed = 0
    try:
        timestamp = int(row.get('timeStamp') or row.get('timestamp') or 0)
    except (TypeError, ValueError):
        timestamp = 0

    success_raw = str(row.get('success') or row.get('Success') or '').strip().lower()
    success = success_raw in ('true', '1', 'yes', 'y')
    return {
        'timestamp': timestamp,
        'elapsed': elapsed,
        'label': row.get('label') or row.get('Label') or 'Unknown',
        'success': success,
        'response_code': row.get('responseCode') or row.get('ResponseCode') or '',
        'response_message': row.get('responseMessage') or row.get('ResponseMessage') or '',
        'failure_message': row.get('failureMessage') or '',
        'bytes': _safe_int(row.get('bytes')),
        'sent_bytes': _safe_int(row.get('sentBytes')),
        'latency': _safe_float(row.get('Latency')),
        'connect': _safe_float(row.get('Connect')),
    }


def _aggregate(rows):
    total = len(rows)
    success = sum(1 for row in rows if row['success'])
    failed = total - success
    elapsed = [row['elapsed'] for row in rows]
    timestamps = [row['timestamp'] for row in rows if row['timestamp']]
    duration_seconds = 0
    if timestamps:
        duration_seconds = max((max(timestamps) - min(timestamps)) / 1000, 0.001)

    return {
        'total_samples': total,
        'success_samples': success,
        'failed_samples': failed,
        'error_rate': round((failed / total) * 100, 2) if total else 0,
        'avg_response_time': round(statistics.mean(elapsed), 2) if elapsed else 0,
        'min_response_time': round(min(elapsed), 2) if elapsed else 0,
        'max_response_time': round(max(elapsed), 2) if elapsed else 0,
        'median_response_time': round(statistics.median(elapsed), 2) if elapsed else 0,
        'p90_response_time': _percentile(elapsed, 90),
        'p95_response_time': _percentile(elapsed, 95),
        'p99_response_time': _percentile(elapsed, 99),
        'throughput': round(total / duration_seconds, 2) if duration_seconds else 0,
        'duration_seconds': round(duration_seconds, 2),
        'received_bytes': sum(row['bytes'] for row in rows),
        'sent_bytes': sum(row['sent_bytes'] for row in rows),
    }


def _group_by_label(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['label']].append(row)
    return grouped


def _timeline(rows):
    buckets = defaultdict(lambda: {'total': 0, 'failed': 0, 'elapsed': []})
    for row in rows:
        bucket = int(row['timestamp'] / 10000) * 10 if row['timestamp'] else 0
        buckets[bucket]['total'] += 1
        if not row['success']:
            buckets[bucket]['failed'] += 1
        buckets[bucket]['elapsed'].append(row['elapsed'])

    result = []
    for bucket in sorted(buckets):
        item = buckets[bucket]
        result.append({
            'time': bucket,
            'total': item['total'],
            'failed': item['failed'],
            'avg_response_time': round(statistics.mean(item['elapsed']), 2) if item['elapsed'] else 0,
        })
    return result


def _errors(rows):
    grouped = defaultdict(int)
    for row in rows:
        if row['success']:
            continue
        key = f"{row['label']} | {row['response_code']} | {row['failure_message'] or row['response_message']}"
        grouped[key] += 1
    return [{'message': key, 'count': value} for key, value in sorted(grouped.items(), key=lambda item: item[1], reverse=True)[:20]]


def _percentile(values, percentile):
    if not values:
        return 0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return round(ordered[lower], 2)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _empty_result(error=''):
    result = {
        'summary': _aggregate([]),
        'labels': {},
        'timeline': [],
        'errors': [],
    }
    if error:
        result['error'] = error
    return result
