"""Webhook notifications for completed AI test reports."""

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.parse

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.core.models import UnifiedNotificationConfig

from .models import AIExecutionRecord, UiNotificationLog


logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {'passed', 'failed', 'stopped', 'error'}
SUCCESS_TASK_STATUSES = {'completed', 'passed', 'success'}
FAILED_TASK_STATUSES = {'failed', 'error'}
SKIPPED_TASK_STATUSES = {'skipped', 'cancelled'}


def _frontend_base_url():
    configured_url = (
        getattr(settings, 'FRONTEND_URL', '')
        or getattr(settings, 'SIMPLEUI_INDEX', '')
        or ''
    ).rstrip('/')
    if configured_url:
        return configured_url
    if getattr(settings, 'DEBUG', False):
        return 'http://localhost:3000'
    return ''


def _task_statistics(record):
    tasks = record.planned_tasks or record.steps_completed or []
    statuses = [str(item.get('status') or '').strip().lower() for item in tasks if isinstance(item, dict)]
    passed = sum(status in SUCCESS_TASK_STATUSES for status in statuses)
    failed = sum(status in FAILED_TASK_STATUSES for status in statuses)
    skipped = sum(status in SKIPPED_TASK_STATUSES for status in statuses)
    unfinished = max(len(statuses) - passed - failed - skipped, 0)
    return {
        'total': len(statuses),
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'unfinished': unfinished,
    }


def _format_datetime(value):
    if not value:
        return '未知'
    try:
        return timezone.localtime(value).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return value.strftime('%Y-%m-%d %H:%M:%S')


def _report_url(record):
    base_url = _frontend_base_url()
    if not base_url or not getattr(record, 'id', None):
        return ''
    return f'{base_url}/ai-intelligent-mode/execution-records?record_id={record.id}'


def _batch_report_url(batch_id):
    base_url = _frontend_base_url()
    if not base_url or not batch_id:
        return ''
    return f'{base_url}/ai-intelligent-mode/execution-records?batch_id={batch_id}'


def _last_error(record):
    if record.status not in {'failed', 'error'}:
        return ''
    lines = [line.strip() for line in str(record.logs or '').splitlines() if line.strip()]
    for line in reversed(lines):
        if any(keyword in line for keyword in ('失败', '异常', '错误', '超时', '出错')):
            return line[:300]
    return lines[-1][:300] if lines else ''


def build_ai_report_content(record):
    stats = _task_statistics(record)
    status_text = {
        'passed': '成功',
        'failed': '失败',
        'stopped': '已停止',
        'error': '异常',
    }.get(record.status, record.status)
    project_name = getattr(getattr(record, 'project', None), 'name', '') or '未关联项目'
    executor = getattr(getattr(record, 'executed_by', None), 'username', '') or '系统'
    duration = f'{record.duration:.2f} 秒' if record.duration is not None else '未知'

    lines = [
        f'用例名称: {record.case_name}',
        f'报告 ID: {record.id}',
        f'所属项目: {project_name}',
        f'执行状态: {status_text}',
        f'执行人: {executor}',
        f'开始时间: {_format_datetime(record.start_time)}',
        f'执行耗时: {duration}',
        (
            f"步骤统计: 共 {stats['total']} 步，成功 {stats['passed']} 步，"
            f"失败 {stats['failed']} 步，跳过 {stats['skipped']} 步，未完成 {stats['unfinished']} 步"
        ),
    ]
    error_message = _last_error(record)
    if error_message:
        lines.append(f'失败原因: {error_message}')
    report_url = _report_url(record)
    if report_url:
        lines.append(f'[查看AI测试报告]({report_url})')
    return status_text, '\n\n'.join(lines)


def build_ai_batch_report_content(batch_id, records):
    """Build one authoritative summary after every record in a batch has settled."""
    records = list(records)
    total = len(records)
    passed = sum(record.status == 'passed' for record in records)
    failed = sum(record.status in {'failed', 'error'} for record in records)
    stopped = sum(record.status == 'stopped' for record in records)
    status_text = '成功' if passed == total else ('已停止' if stopped and not failed else '失败')
    starts = [record.start_time for record in records if record.start_time]
    ends = [record.end_time for record in records if record.end_time]
    duration = ''
    if starts and ends:
        duration = f'{(max(ends) - min(starts)).total_seconds():.2f} 秒'
    executor = getattr(getattr(records[0], 'executed_by', None), 'username', '') if records else ''
    project_names = sorted({getattr(getattr(record, 'project', None), 'name', '') for record in records})
    project_names = [name for name in project_names if name]
    lines = [
        f'批次 ID: {batch_id}',
        f'执行状态: {status_text}',
        f'用例统计: 共 {total} 条，通过 {passed} 条，失败 {failed} 条，停止 {stopped} 条',
        f'执行人: {executor or "系统"}',
        f'开始时间: {_format_datetime(min(starts)) if starts else "未知"}',
        f'批次耗时: {duration or "未知"}',
    ]
    if project_names:
        lines.insert(1, f'所属项目: {"、".join(project_names)}')
    failures = []
    for record in records:
        if record.status in {'failed', 'error', 'stopped'}:
            reason = _last_error(record) or '未提供失败原因'
            failures.append(f'- {record.case_name}: {reason}')
    if failures:
        lines.append('失败/停止用例:\n' + '\n'.join(failures[:10]))
        if len(failures) > 10:
            lines.append(f'其余 {len(failures) - 10} 条请在批次报告中查看。')
    report_url = _batch_report_url(batch_id)
    if report_url:
        lines.append(f'[查看批次AI测试报告]({report_url})')
    return status_text, '\n\n'.join(lines)


def _message_payload(bot_type, record):
    status_text, detail = build_ai_report_content(record)
    title = f'AI测试报告执行{status_text}'
    if bot_type == 'wechat':
        status_color = 'info' if record.status == 'passed' else 'warning'
        return {
            'msgtype': 'markdown',
            'markdown': {
                'content': (
                    f'## {title}\n'
                    f'> 执行状态：<font color="{status_color}">{status_text}</font>\n\n'
                    f'{detail}'
                )
            },
        }
    if bot_type == 'feishu':
        return {
            'msg_type': 'interactive',
            'card': {
                'elements': [{
                    'tag': 'div',
                    'text': {'content': f'**{title}**\n\n{detail}', 'tag': 'lark_md'},
                }],
                'header': {
                    'title': {'content': title, 'tag': 'plain_text'},
                    'template': 'green' if record.status == 'passed' else 'red',
                },
            },
        }
    if bot_type == 'dingtalk':
        return {
            'msgtype': 'markdown',
            'markdown': {'title': title, 'text': f'**{title}**\n\n{detail}'},
        }
    return None


def _batch_message_payload(bot_type, batch_id, records):
    status_text, detail = build_ai_batch_report_content(batch_id, records)
    title = f'AI批次测试报告执行{status_text}'
    if bot_type == 'wechat':
        status_color = 'info' if status_text == '成功' else 'warning'
        return {
            'msgtype': 'markdown',
            'markdown': {
                'content': (
                    f'## {title}\n'
                    f'> 执行状态：<font color="{status_color}">{status_text}</font>\n\n'
                    f'{detail}'
                )
            },
        }
    if bot_type == 'feishu':
        return {
            'msg_type': 'interactive',
            'card': {
                'elements': [{'tag': 'div', 'text': {'content': f'**{title}**\n\n{detail}', 'tag': 'lark_md'}}],
                'header': {'title': {'content': title, 'tag': 'plain_text'}, 'template': 'green' if status_text == '成功' else 'red'},
            },
        }
    if bot_type == 'dingtalk':
        return {'msgtype': 'markdown', 'markdown': {'title': title, 'text': f'**{title}**\n\n{detail}'}}
    return None


def _signed_dingtalk_url(webhook_url, secret):
    if not secret:
        return webhook_url
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f'{timestamp}\n{secret}'.encode('utf-8')
    signature = hmac.new(secret.encode('utf-8'), string_to_sign, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(signature))
    separator = '&' if '?' in webhook_url else '?'
    return f'{webhook_url}{separator}timestamp={timestamp}&sign={sign}'


def _webhook_validation_error(bot):
    bot_type = str(bot.get('type') or '')
    webhook_url = str(bot.get('webhook_url') or '').strip()
    if bot_type != 'wechat':
        return ''
    parsed = urllib.parse.urlparse(webhook_url)
    key = (urllib.parse.parse_qs(parsed.query).get('key') or [''])[0].strip()
    if (
        parsed.scheme == 'https'
        and parsed.netloc.lower() == 'qyapi.weixin.qq.com'
        and parsed.path.rstrip('/') == '/cgi-bin/webhook/send'
        and key
    ):
        return ''
    return (
        '企业微信机器人地址无效，请填写群机器人 Webhook：'
        'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...'
    )


def _enabled_ai_bots():
    configs = UnifiedNotificationConfig.objects.filter(
        config_type__in=['webhook_wechat', 'webhook_feishu', 'webhook_dingtalk'],
        is_active=True,
    )
    bots = []
    for config in configs:
        for bot in config.get_webhook_bots():
            if (
                bot.get('enabled', True)
                and bot.get('enable_ai_testing', False)
                and bot.get('webhook_url')
            ):
                bots.append(bot)
    return bots


def _write_notification_log(record, bot, payload, status, response=None, error_message='', task_name=None, task_type='AI_TEST_REPORT'):
    try:
        UiNotificationLog.objects.create(
            task=None,
            task_name=task_name or record.case_name,
            task_type=task_type,
            notification_type='ai_test_report',
            sender_name='系统Webhook通知',
            sender_email='system@notification.com',
            recipient_info=[{'name': bot.get('name', 'Unknown'), 'type': bot.get('type')}],
            webhook_bot_info={key: value for key, value in bot.items() if key != 'webhook_url'},
            notification_content=json.dumps(payload, ensure_ascii=False),
            status=status,
            error_message=error_message or None,
            response_info=response or {},
            sent_at=timezone.now() if status == 'success' else None,
        )
    except Exception as exc:
        logger.warning('保存 AI 报告通知日志失败: %s', exc, exc_info=True)


def _response_succeeded(response):
    if response.status_code != 200:
        return False
    try:
        body = response.json()
    except (TypeError, ValueError, AttributeError):
        return True
    if not isinstance(body, dict):
        return True
    for key in ('errcode', 'code', 'StatusCode'):
        if key in body:
            return body[key] in (0, '0', None)
    return True


def send_ai_execution_notification(record):
    """Send one completed AI execution report to each opted-in webhook bot."""
    if not record or record.status not in TERMINAL_STATUSES:
        return []
    batch_id = getattr(record, 'batch_id', None)
    if batch_id:
        return send_ai_batch_execution_notification(batch_id)

    try:
        bots = _enabled_ai_bots()
    except Exception as exc:
        logger.error('读取 AI 报告机器人配置失败: %s', exc, exc_info=True)
        return []

    results = []
    for bot in bots:
        bot_type = bot.get('type')
        payload = _message_payload(bot_type, record)
        if payload is None:
            continue
        validation_error = _webhook_validation_error(bot)
        if validation_error:
            _write_notification_log(record, bot, payload, 'failed', error_message=validation_error)
            results.append({'type': bot_type, 'success': False, 'error': validation_error})
            logger.error('AI 测试报告机器人配置无效: %s', validation_error)
            continue
        webhook_url = bot['webhook_url']
        if bot_type == 'dingtalk':
            webhook_url = _signed_dingtalk_url(webhook_url, bot.get('secret'))

        try:
            response = requests.post(
                webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=10,
            )
            response_info = {'status_code': response.status_code, 'response': response.text}
            if _response_succeeded(response):
                _write_notification_log(record, bot, payload, 'success', response=response_info)
                results.append({'type': bot_type, 'success': True})
                logger.info('AI 测试报告已发送到机器人 %s', bot.get('name', bot_type))
            else:
                response_text = str(response.text or '')[:500]
                error_message = f'HTTP {response.status_code}: {response_text}'
                _write_notification_log(
                    record, bot, payload, 'failed', response=response_info, error_message=error_message
                )
                results.append({'type': bot_type, 'success': False, 'error': error_message})
        except requests.RequestException as exc:
            error_message = str(exc)
            _write_notification_log(record, bot, payload, 'failed', error_message=error_message)
            results.append({'type': bot_type, 'success': False, 'error': error_message})
            logger.error('发送 AI 测试报告失败: %s', exc, exc_info=True)
    return results


def send_ai_batch_execution_notification(batch_id):
    """Send one summary notification once the entire AI batch is complete."""
    if not batch_id:
        return []
    records = list(AIExecutionRecord.objects.filter(batch_id=batch_id).select_related('project', 'executed_by'))
    if not records or any(record.status not in TERMINAL_STATUSES for record in records):
        return []

    lock_key = f'ai-batch-notification:{batch_id}'
    if not cache.add(lock_key, 'sending', timeout=60 * 60):
        return []

    try:
        bots = _enabled_ai_bots()
    except Exception as exc:
        cache.delete(lock_key)
        logger.error('读取 AI 批次报告机器人配置失败: %s', exc, exc_info=True)
        return []

    results = []
    batch_name = f'AI批次测试报告 {batch_id}'
    for bot in bots:
        bot_type = bot.get('type')
        payload = _batch_message_payload(bot_type, batch_id, records)
        if payload is None:
            continue
        validation_error = _webhook_validation_error(bot)
        if validation_error:
            _write_notification_log(
                records[0], bot, payload, 'failed', error_message=validation_error,
                task_name=batch_name, task_type='AI_BATCH_TEST_REPORT',
            )
            results.append({'type': bot_type, 'success': False, 'error': validation_error})
            continue
        webhook_url = bot['webhook_url']
        if bot_type == 'dingtalk':
            webhook_url = _signed_dingtalk_url(webhook_url, bot.get('secret'))
        try:
            response = requests.post(webhook_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=10)
            response_info = {'status_code': response.status_code, 'response': response.text}
            if _response_succeeded(response):
                _write_notification_log(
                    records[0], bot, payload, 'success', response=response_info,
                    task_name=batch_name, task_type='AI_BATCH_TEST_REPORT',
                )
                results.append({'type': bot_type, 'success': True, 'batch_id': str(batch_id)})
                logger.info('AI 批次测试报告已发送到机器人 %s: %s', bot.get('name', bot_type), batch_name)
            else:
                error_message = f'HTTP {response.status_code}: {str(response.text or "")[:500]}'
                _write_notification_log(
                    records[0], bot, payload, 'failed', response=response_info, error_message=error_message,
                    task_name=batch_name, task_type='AI_BATCH_TEST_REPORT',
                )
                results.append({'type': bot_type, 'success': False, 'error': error_message})
        except requests.RequestException as exc:
            error_message = str(exc)
            _write_notification_log(
                records[0], bot, payload, 'failed', error_message=error_message,
                task_name=batch_name, task_type='AI_BATCH_TEST_REPORT',
            )
            results.append({'type': bot_type, 'success': False, 'error': error_message})
    return results
