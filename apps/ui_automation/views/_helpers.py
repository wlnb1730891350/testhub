import logging
import re
import json
import time
import random
import asyncio
import base64
import threading
import uuid
from urllib.parse import urlsplit

from rest_framework.pagination import PageNumberPagination
from django.utils import timezone
from django.conf import settings
from django.db import DatabaseError, close_old_connections, connection
from asgiref.sync import sync_to_async
from apps.ui_automation.models import AIExecutionRecord
from ..click_constraints import extract_click_constraints, has_meaningful_click_constraints

logger = logging.getLogger(__name__)

_RECOVERABLE_DB_ERROR_MARKERS = (
    '2006',
    '2013',
    '10053',
    'server has gone away',
    'lost connection',
    'connectionabortederror',
    'connection reset',
)

# The cache deliberately contains only login material and is process-local:
# restarting the backend drops it.  A case still receives an independent
# browser/context/page, so business state cannot leak from the previous case.
_AUTH_SESSION_CACHE_TTL_SECONDS = 45 * 60
_AUTH_SESSION_CACHE_MAX_ENTRIES = 32
_AUTH_SESSION_CACHE = {}
_AUTH_SESSION_CACHE_LOCK = threading.RLock()
_AUTH_SESSION_LOGIN_LOCKS = {}


def _auth_storage_key(key):
    normalized = str(key or '').strip().lower()
    return (
        normalized in {
            'userid', 'h5_userinfo', 'currentuser', 'userinfo',
            '_user_id', 'bhuserinfo', 'siheauthstatus',
        }
        or bool(re.fullmatch(r'lastuseractivityreport_\d+', normalized))
        or bool(re.search(r'(?:token|auth|login|session|jwt|credential)', normalized, re.I))
    )


def _normalized_origin(url):
    parsed = urlsplit(str(url or '').strip())
    if not parsed.scheme or not parsed.netloc:
        return ''
    return f'{parsed.scheme.lower()}://{parsed.netloc.lower()}'


def _login_session_cache_key(target_url, setup_template):
    """Scope reusable authentication to one origin and one setup template."""
    origin = _normalized_origin(_login_landing_url_for_target(target_url))
    if not origin or not setup_template:
        return ''
    template_id = getattr(setup_template, 'pk', None) or getattr(setup_template, 'id', None)
    template_identity = str(template_id or getattr(setup_template, 'name', '')).strip()
    return f'{origin}|setup-template:{template_identity}' if template_identity else ''


def _filter_authenticated_storage_state(storage_state, target_url):
    """Keep only cookies and same-origin storage that can carry authentication."""
    target_origin = _normalized_origin(target_url)
    target_host = urlsplit(target_origin).hostname or ''
    filtered_cookies = []
    for cookie in (storage_state or {}).get('cookies') or []:
        domain = str(cookie.get('domain') or '').lstrip('.').lower()
        if domain and (target_host == domain or target_host.endswith('.' + domain)):
            filtered_cookies.append(dict(cookie))

    filtered_origins = []
    for origin_state in (storage_state or {}).get('origins') or []:
        if _normalized_origin(origin_state.get('origin')) != target_origin:
            continue
        local_storage = [
            dict(item) for item in (origin_state.get('localStorage') or [])
            if _auth_storage_key(item.get('name'))
        ]
        if local_storage:
            filtered_origins.append({'origin': target_origin, 'localStorage': local_storage})
    return {'cookies': filtered_cookies, 'origins': filtered_origins}


def _get_cached_auth_state(cache_key, now=None):
    if not cache_key:
        return None
    current_time = time.time() if now is None else now
    with _AUTH_SESSION_CACHE_LOCK:
        entry = _AUTH_SESSION_CACHE.get(cache_key)
        if not entry:
            return None
        if current_time - entry['created_at'] >= _AUTH_SESSION_CACHE_TTL_SECONDS:
            _AUTH_SESSION_CACHE.pop(cache_key, None)
            return None
        return json.loads(json.dumps(entry['storage_state']))


def _store_cached_auth_state(cache_key, storage_state, now=None):
    if not cache_key or not ((storage_state or {}).get('cookies') or (storage_state or {}).get('origins')):
        return False
    current_time = time.time() if now is None else now
    with _AUTH_SESSION_CACHE_LOCK:
        _AUTH_SESSION_CACHE[cache_key] = {
            'created_at': current_time,
            'storage_state': json.loads(json.dumps(storage_state)),
        }
        if len(_AUTH_SESSION_CACHE) > _AUTH_SESSION_CACHE_MAX_ENTRIES:
            oldest_key = min(_AUTH_SESSION_CACHE, key=lambda key: _AUTH_SESSION_CACHE[key]['created_at'])
            _AUTH_SESSION_CACHE.pop(oldest_key, None)
    return True


def _discard_cached_auth_state(cache_key):
    if cache_key:
        with _AUTH_SESSION_CACHE_LOCK:
            _AUTH_SESSION_CACHE.pop(cache_key, None)


def _get_auth_login_lock(cache_key):
    with _AUTH_SESSION_CACHE_LOCK:
        return _AUTH_SESSION_LOGIN_LOCKS.setdefault(cache_key, threading.Lock())


def _is_login_completion_step(step):
    if str((step or {}).get('business_action') or '') in {'nn_submit_login', 'nn_complete_login'}:
        return True
    description = str((step or {}).get('description') or '')
    return str((step or {}).get('action_type') or '') == 'assert' and _is_login_success_assertion(description)


def _is_recoverable_db_error(error):
    message = str(error).lower()
    return any(marker in message for marker in _RECOVERABLE_DB_ERROR_MARKERS)


def _save_execution_record_with_retry(execution_record, *, update_fields, max_retries=3):
    """Persist an execution record after reconnecting transient MySQL sockets."""
    last_error = None
    for attempt in range(max_retries):
        try:
            close_old_connections()
            execution_record.save(update_fields=update_fields)
            return
        except DatabaseError as error:
            if not _is_recoverable_db_error(error):
                raise
            last_error = error
            logger.warning(
                'AI execution record save lost its MySQL connection (attempt %s/%s): %s',
                attempt + 1,
                max_retries,
                error,
            )
            connection.close()
            if attempt < max_retries - 1:
                time.sleep(0.3 * (attempt + 1))
    raise last_error


def _mark_execution_started(execution_record):
    """Start timing only when this individual record reaches the executor."""
    execution_record.start_time = timezone.now()
    execution_record.end_time = None
    execution_record.duration = None
    execution_record.status = 'running'
    _save_execution_record_with_retry(
        execution_record,
        update_fields=['start_time', 'end_time', 'duration', 'status'],
    )


async def _async_save_record_logs(execution_record, *, update_fields=None):
    """async 安全的执行记录保存。"""
    await sync_to_async(_save_execution_record_with_retry)(
        execution_record,
        update_fields=update_fields or ['logs'],
    )


def _reportable_execution_steps(recorded_steps):
    """Keep database report data free of transient inline screenshot payloads."""
    return [
        {key: value for key, value in step.items() if key != 'screenshot'}
        for step in (recorded_steps or [])
        if isinstance(step, dict)
    ]


class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 1000


def extract_step_info(s, step_index):
    """提取步骤信息的辅助函数，确保返回可读的步骤描述"""
    step_info = {'step': step_index}

    if hasattr(s, 'action'):
        action_data = s.action
        if isinstance(action_data, str):
            step_info['action'] = action_data
        elif hasattr(action_data, '__dict__'):
            attrs = {}
            for key in ['type', 'description', 'goal', 'coordinate', 'text', 'output', 'result']:
                if hasattr(action_data, key):
                    value = getattr(action_data, key)
                    if isinstance(value, str):
                        attrs[key] = value
                    elif callable(value):
                        attrs[key] = getattr(value, '__name__', str(value))
                    else:
                        attrs[key] = str(value)
            if attrs:
                step_info['action'] = attrs
        else:
            step_info['action'] = str(action_data)
    elif hasattr(s, 'model_output'):
        output_data = s.model_output
        if isinstance(output_data, str):
            step_info['action'] = output_data
        elif hasattr(output_data, '__dict__'):
            attrs = {'type': 'model_output'}
            for key in ['action', 'description', 'goal', 'coordinate', 'text']:
                if hasattr(output_data, key):
                    value = getattr(output_data, key)
                    attrs[key] = str(value) if value else None
            step_info['action'] = attrs
        else:
            step_info['action'] = str(output_data)
    elif hasattr(s, '__dict__'):
        attrs = {}
        for key in dir(s):
            if not key.startswith('_'):
                try:
                    value = getattr(s, key)
                    if not callable(value):
                        attrs[key] = str(value)
                except Exception:
                    pass
        if attrs:
            step_info['action'] = attrs
    else:
        if callable(s):
            step_info['action'] = f"<Action: {getattr(s, '__name__', 'unknown action')}>"
        else:
            step_info['action'] = str(s)

    return step_info


# 全局停止信号字典 {execution_id: bool}
STOP_SIGNALS = {}

TERMINAL_TASK_STATUSES = {'completed', 'failed', 'skipped'}
ACTIVE_TASK_STATUSES = {'pending', 'in_progress'}


def update_planned_task_status(planned_tasks, task_id, task_status):
    """更新子任务状态，返回是否命中任务。"""
    if not planned_tasks or task_id is None or not task_status:
        return False

    normalized_status = str(task_status).strip().lower()
    for task in planned_tasks:
        if str(task.get('id')) == str(task_id):
            task['status'] = normalized_status
            return True
    return False


def backfill_prior_pending_tasks(planned_tasks, current_task_id):
    """受限补齐：仅在强依赖场景下补齐紧邻前一步遗漏标记。"""
    if not planned_tasks or current_task_id is None:
        return []

    try:
        current_task_id_int = int(current_task_id)
    except (TypeError, ValueError):
        return []

    task_by_id = {}
    for task in planned_tasks:
        try:
            task_by_id[int(task.get('id'))] = task
        except (TypeError, ValueError):
            continue

    current_task = task_by_id.get(current_task_id_int)
    previous_task = task_by_id.get(current_task_id_int - 1)
    if not current_task or not previous_task:
        return []

    if previous_task.get('status', 'pending') not in ACTIVE_TASK_STATUSES:
        return []

    previous_desc = str(previous_task.get('description', '')).strip()
    current_desc = str(current_task.get('description', '')).strip()

    verification_keywords = ['校验', '确认', '检查', '验证', '断言']
    if any(keyword in previous_desc for keyword in verification_keywords):
        return []

    dependency_pairs = [
        (['访问', '打开', '进入'], ['搜索', '输入', '点击', '查看']),
        (['搜索'], ['点击第', '点击第2条', '点击第二条', '查看详情']),
        (['点击第', '点击第2条', '点击第二条', '查看详情'], ['关闭', '关闭该标签页', '关闭标签页']),
        (['打开详情', '查看详情'], ['关闭', '返回']),
    ]

    def matches_any(text, keywords):
        return any(keyword in text for keyword in keywords)

    allowed = any(
        matches_any(previous_desc, prev_keywords) and matches_any(current_desc, curr_keywords)
        for prev_keywords, curr_keywords in dependency_pairs
    )

    if not allowed:
        return []

    previous_task['status'] = 'completed'
    return [current_task_id_int - 1]


def mark_first_active_task(planned_tasks, task_status):
    """在执行异常时为第一个未终态任务补一个状态。"""
    if not planned_tasks:
        return None

    normalized_status = str(task_status).strip().lower()
    for task in planned_tasks:
        if task.get('status', 'pending') in ACTIVE_TASK_STATUSES:
            task['status'] = normalized_status
            return task.get('id')
    return None


def summarize_planned_tasks(planned_tasks):
    """汇总子任务状态。"""
    summary = {
        'total': 0,
        'completed': 0,
        'failed': 0,
        'skipped': 0,
        'pending': 0,
        'in_progress': 0,
    }
    if not planned_tasks:
        return summary

    summary['total'] = len(planned_tasks)
    for task in planned_tasks:
        task_status = task.get('status', 'pending')
        if task_status in summary:
            summary[task_status] += 1
        else:
            summary['pending'] += 1
    return summary


def resolve_execution_status(planned_tasks):
    """根据子任务实际状态推导整单状态。"""
    summary = summarize_planned_tasks(planned_tasks)

    if summary['total'] == 0:
        return 'passed', summary
    if summary['failed'] > 0:
        return 'failed', summary
    if summary['pending'] > 0 or summary['in_progress'] > 0:
        return 'failed', summary
    return 'passed', summary


def append_execution_summary(logs, summary):
    """把任务统计附加到日志中。"""
    logs = (logs or '').replace(chr(13)+chr(10), chr(10)).replace(chr(13), chr(10))
    if summary['total'] == 0:
        return logs
    return (
        f"{logs}\n[System] 子任务统计: 总数 {summary['total']}，"
        f"已完成 {summary['completed']}，失败 {summary['failed']}，"
        f"跳过 {summary['skipped']}，待处理 {summary['pending'] + summary['in_progress']}。"
    )


def is_infrastructure_failure(error_message: str) -> bool:
    """判断是否为模型/网络/初始化类故障，这类问题不应直接把首个子任务标失败。"""
    message = (error_message or '').lower()
    infra_markers = [
        'execution llm unavailable',
        'connection error',
        'timed out',
        'timeout',
        'api key',
        'authentication',
        'unauthorized',
        'forbidden',
        'rate limit',
        'service unavailable',
    ]
    return any(marker in message for marker in infra_markers)


def _parse_task_description_to_steps(task_desc):
    """将自然语言任务描述编译为结构化执行步骤。

    新路径优先输出业务动作（business_action/page-object），从源头保留
    登录、顶部搜索、社区结果点击等业务语义；未覆盖的普通语句仍输出
    通用 goto/type/click/assert/wait 步骤，保证现有用例兼容。
    """
    from ..structured_actions import compile_task_description
    return compile_task_description(task_desc)


def _login_landing_url_for_target(target_url):
    """Return a same-origin public page for login before visiting a deep link."""
    parsed = urlsplit(str(target_url or '').strip())
    if not parsed.scheme or not parsed.netloc:
        return ''
    return f'{parsed.scheme}://{parsed.netloc}/'


def resolve_execution_step_variables(step, resolution_cache=None):
    """Resolve dynamic values once before either execution path consumes them.

    AI business actions and generic browser steps are dispatched through
    different code paths. Resolving here keeps template values such as
    ``${random_phone()}`` consistent for both paths within one execution.
    """
    from apps.core.variable_resolver import resolve_variables

    resolved_step = dict(step or {})
    cache = resolution_cache if resolution_cache is not None else {}
    resolved_sources = {}
    for field in ('input_value', 'assert_value', 'target_text', 'player_name'):
        raw_value = resolved_step.get(field)
        if not isinstance(raw_value, str) or '${' not in raw_value:
            continue
        resolved_value = cache.get(raw_value)
        if resolved_value is None:
            resolved_value = resolve_variables(raw_value)
            cache[raw_value] = resolved_value
        if resolved_value != raw_value:
            resolved_sources[field] = raw_value
            resolved_step[field] = resolved_value
    if resolved_sources:
        resolved_step['_variable_sources'] = resolved_sources
    return resolved_step


def append_blocked_remaining_steps(steps, failed_index, recorded_steps, planned_tasks, reason):
    """Record dependent steps as blocked after the first real failure.

    ``failed_index`` is zero-based. Keeping this deterministic and outside the
    browser loop makes it impossible for a later locator error to overwrite the
    actual root failure in a batch report.
    """
    blocked_count = 0
    for remaining_index in range(failed_index + 1, len(steps)):
        remaining_step = steps[remaining_index]
        remaining_id = f'task_{remaining_index + 1}'
        blocked_record = {
            'step_number': remaining_index + 1,
            'action_type': remaining_step.get('action_type'),
            'description': remaining_step.get('description', ''),
            'display_description': remaining_step.get('display_description') or remaining_step.get('description', ''),
            'input_value': remaining_step.get('input_value', ''),
            'status': 'skipped',
            'element': None,
            'screenshot': None,
            'error': reason,
            'blocked_by_step': failed_index + 1,
        }
        recorded_steps.append(blocked_record)
        for planned_task in planned_tasks or []:
            if planned_task.get('id') == remaining_id:
                planned_task['status'] = 'skipped'
                planned_task['skip_reason'] = reason
                break
        blocked_count += 1
    return blocked_count


def _run_with_playwright_sync(execution_record, task_description, step_callback=None, should_stop=None, setup_template=None):
    """使用Playwright执行AI用例并录制元素交互信息"""
    import traceback as tb
    from ..playwright_engine import PlaywrightTestEngine

    _mark_execution_started(execution_record)

    _template = setup_template
    if not _template:
        try:
            if hasattr(execution_record, 'ai_case') and execution_record.ai_case:
                _template = execution_record.ai_case.setup_template
        except Exception:
            pass

    isolation_id = uuid.uuid4().hex
    execution_record.logs += (
        f"\n[Isolation] 独立用例会话 {isolation_id}：新建浏览器、context、页面，"
        "不复用其他用例的页面位置、业务 Cookie、localStorage 或 sessionStorage；"
        "仅可能注入经验证的同域登录态。\n"
    )

    setup_steps = []
    setup_parse_errors = []
    raw_template_steps = []
    case_target_url = ''
    login_landing_url = ''
    login_template_enabled = False
    if _template and _template.steps:
        from ..structured_actions import _template_mentions_login, should_skip_setup_template
        if should_skip_setup_template(task_description, _template.steps, getattr(_template, 'name', '')):
            execution_record.logs += f"\n[Setup Template] {_template.name}: 当前用例本身是登录流程，已跳过登录前置模板，避免重复登录。\n"
            raw_template_steps = []
        else:
            raw_template_steps = _template.steps or []
        for index, ts in enumerate(raw_template_steps, 1):
            if isinstance(ts, dict):
                desc = str(ts.get('description') or ts.get('text') or ts.get('name') or '').strip()
                action_type = str(ts.get('action_type') or '').strip().lower()
                # 如果模板步骤已经是底层可执行动作，优先保留；否则按自然语言解析。
                if action_type in {'goto', 'type', 'click', 'try_click', 'wait', 'assert'}:
                    setup_steps.append({
                        'action_type': action_type,
                        'description': desc or f'前置模板步骤 {index}',
                        'input_value': ts.get('input_value') or ts.get('value') or '',
                        'element': ts.get('element'),
                        'assert_type': ts.get('assert_type', ''),
                        'assert_value': ts.get('assert_value', ''),
                    })
                    continue
            else:
                desc = str(ts).strip()

            parsed = _parse_task_description_to_steps(desc)
            if parsed:
                setup_steps.extend(parsed)
            elif desc:
                setup_parse_errors.append(f'步骤 {index}: {desc[:120]}')

        if setup_parse_errors:
            # Silently skipping a login/navigation setup makes a case depend on
            # whatever state happened to be left by a previous run. Fail fast
            # with the actual template problem instead of running half-setup.
            error = '前置模板存在无法执行的步骤: ' + '；'.join(setup_parse_errors)
            execution_record.logs += f"\n[Setup Template] {error}\n"
            execution_record.status = 'failed'
            execution_record.end_time = timezone.now()
            execution_record.duration = (execution_record.end_time - execution_record.start_time).total_seconds()
            _save_execution_record_with_retry(
                execution_record,
                update_fields=['status', 'logs', 'end_time', 'duration'],
            )
            from ..ai_notifications import send_ai_execution_notification
            send_ai_execution_notification(execution_record)
            return

        # Login cookies on the NN test environments are host-scoped.  A shared
        # login template must therefore start on the case's target host instead
        # of a hard-coded template host such as test6-web.nn.com.
        target_match = re.search(r'(?:目标地址\s*[:：]?|访问)\s*(https?://[^\s，。；;]+)', str(task_description or ''))
        case_target_url = target_match.group(1).rstrip('/') if target_match else ''
        if not case_target_url:
            fallback_target_match = re.search(r'https?://[^\s，。；;]+', str(task_description or ''))
            case_target_url = fallback_target_match.group(0).rstrip('/') if fallback_target_match else ''
        login_landing_url = _login_landing_url_for_target(case_target_url)
        # A case that explicitly needs an anonymous/account-state condition
        # may skip the login template.  The template's *name* must not turn
        # the skipped template back on and inject a cached login state.
        login_template_enabled = bool(raw_template_steps) and _template_mentions_login(
            raw_template_steps,
            getattr(_template, 'name', ''),
        )
        if login_landing_url and login_template_enabled:
            for setup_step in setup_steps:
                if setup_step.get('action_type') == 'goto':
                    original_url = str(setup_step.get('input_value') or '')
                    setup_step['input_value'] = login_landing_url
                    setup_step['description'] = f'访问登录入口页 {login_landing_url}'
                    execution_record.logs += (
                        f"\n[Setup Template] 登录目标已从 {original_url or '模板默认地址'} "
                        f"切换为同域登录入口 {login_landing_url}，确保登录态在同一站点生效。\n"
                    )
                    execution_record.logs += (
                        f"[Setup Template] 先在 {login_landing_url} 完成登录，"
                        f"再由用例步骤访问受保护地址 {case_target_url}。\n"
                    )
                    break

        execution_record.logs += (
            f"\n[Setup Template] {_template.name}: 原始 {len(raw_template_steps)} 步，"
            f"解析为 {len(setup_steps)} 个可执行步骤，已置于当前用例之前。\n"
        )

    login_cache_key = (
        _login_session_cache_key(case_target_url, _template)
        if login_template_enabled and login_landing_url else ''
    )

    execution_record.logs += f"\nDEBUG: task_description={repr(task_description[:300])}\n"
    case_steps = _parse_task_description_to_steps(task_description)
    for step in setup_steps:
        step['_source'] = 'setup'
    for step in case_steps:
        step['_source'] = 'case'
    variable_cache = {}
    steps = [
        resolve_execution_step_variables(step, variable_cache)
        for step in (setup_steps + case_steps)
    ]
    execution_record.logs += f"DEBUG: setup_steps={len(setup_steps)}, case_steps={len(case_steps)}, steps={len(steps)}\n"
    if not steps:
        execution_record.logs += "\n未解析到可执行步骤。\n"
        execution_record.status = 'failed'
        execution_record.end_time = timezone.now()
        execution_record.duration = (execution_record.end_time - execution_record.start_time).total_seconds()
        _save_execution_record_with_retry(
            execution_record,
            update_fields=['status', 'logs', 'end_time', 'duration'],
        )
        from ..ai_notifications import send_ai_execution_notification
        send_ai_execution_notification(execution_record)
        return

    execution_record.logs += f"解析到 {len(steps)} 个步骤\n"
    execution_record.planned_tasks = [
        {
            'id': f'task_{i+1}',
            'description': s['description'],
            'display_description': s.get('display_description') or s['description'],
            'status': 'pending',
        }
        for i, s in enumerate(steps)
    ]
    _save_execution_record_with_retry(
        execution_record,
        update_fields=['logs', 'planned_tasks'],
    )

    recorded_steps = []

    async def _run_async():
        nonlocal recorded_steps
        cached_auth_state = _get_cached_auth_state(login_cache_key)
        login_lock = None
        login_lock_held = False
        if login_cache_key and not cached_auth_state:
            # The first case performs login. Concurrent cases for the same
            # target/template wait, then consume the freshly cached state.
            login_lock = _get_auth_login_lock(login_cache_key)
            await asyncio.to_thread(login_lock.acquire)
            login_lock_held = True
            cached_auth_state = _get_cached_auth_state(login_cache_key)

        engine = PlaywrightTestEngine(headless=True, storage_state=cached_auth_state)
        recorded_steps = []
        from ..permission_lifecycle import PermissionCleanupManager
        permission_cleanup = PermissionCleanupManager(execution_record)
        cleanup_failed = False
        clicked_community_identity = None
        business_action_results = []
        interaction_results = []
        reused_login_state = False
        cache_saved = False
        skip_cached_login_phase = False
        resume_from_login_landing = False

        try:
            await engine.start()
            if login_cache_key and not cached_auth_state:
                execution_record.logs += '[Auth Cache] 未命中有效登录态缓存，执行前置登录步骤。\n'
            if cached_auth_state and login_landing_url:
                try:
                    await engine.page.goto(login_landing_url, wait_until='domcontentloaded', timeout=30000)
                    cached_login_check = await _evaluate_login_success(engine.page)
                    # A stale NN session can still look valid at the origin
                    # root because its login dialog is lazy-loaded only after
                    # a protected plugin route is entered.  Reusing that
                    # state would make a case start behind a login overlay.
                    # Validate at the case's real target as well before
                    # suppressing the login template.
                    if cached_login_check.get('passed') and case_target_url:
                        await engine.page.goto(case_target_url, wait_until='domcontentloaded', timeout=30000)
                        await asyncio.sleep(0.9)
                        cached_login_check = await _evaluate_login_success(engine.page)
                    # Stale test6 storage can otherwise pass only because a
                    # historical key remains.  A reusable cached session must
                    # also expose at least one concrete account/profile node.
                    cache_evidence = cached_login_check.get('evidence') or {}
                    if cached_login_check.get('passed') and not int(cache_evidence.get('postLoginCount') or 0):
                        cached_login_check = {
                            **cached_login_check,
                            'passed': False,
                            'reason': '缓存会话未检测到账号/个人资料节点，禁止复用游客态',
                        }
                except Exception as cache_check_error:
                    cached_login_check = {
                        'passed': False,
                        'reason': f'登录态缓存校验异常: {str(cache_check_error)[:180]}',
                        'evidence': {},
                    }
                if cached_login_check.get('passed'):
                    reused_login_state = True
                    skip_cached_login_phase = True
                    resume_from_login_landing = True
                    execution_record.logs += (
                        '[Auth Cache] 登录态缓存命中且校验通过，跳过预置登录步骤；'
                        f'缓存键={login_cache_key}，证据={cached_login_check.get("evidence")}\n'
                    )
                else:
                    _discard_cached_auth_state(login_cache_key)
                    execution_record.logs += (
                        '[Auth Cache] 登录态缓存失效，已清除并重新执行前置登录步骤：'
                        f'{cached_login_check.get("reason") or "未检测到真实登录态"}\n'
                    )

            # New contexts are isolated by default.  Cache misses/invalid
            # sessions explicitly clear all state before the login template.
            if engine.context and not reused_login_state:
                await engine.context.clear_cookies()
                try:
                    await engine.page.evaluate('() => { localStorage.clear(); sessionStorage.clear(); }')
                except Exception:
                    pass
            await engine.page.goto('about:blank', wait_until='commit', timeout=10000)
            if reused_login_state:
                execution_record.logs += f"[Isolation] 会话 {isolation_id} 使用独立 context，并从空白页开始。\n"
            else:
                execution_record.logs += f"[Isolation] 会话 {isolation_id} 已清空全部会话状态并从空白页开始。\n"
            execution_record.logs += "浏览器启动成功\n"
            await _async_save_record_logs(execution_record, update_fields=['logs'])

            for i, step in enumerate(steps):
                if should_stop and should_stop():
                    execution_record.logs += "\n用户已停止执行。\n"
                    break

                step_id = f'task_{i+1}'
                step_display_description = step.get('display_description') or step['description']
                execution_record.logs += f"\n[Step {i+1}] {step_display_description}\n"
                step_record = {
                    'step_number': i + 1,
                    'action_type': step['action_type'],
                    'description': step['description'],
                    'display_description': step_display_description,
                    'input_value': step.get('input_value', ''),
                    'status': 'pending',
                    'element': None,
                    'screenshot': None,
                    'error': None,
                }

                try:
                    if resume_from_login_landing and not (
                        skip_cached_login_phase and step.get('_source') == 'setup'
                    ):
                        await engine.page.goto(login_landing_url, wait_until='domcontentloaded', timeout=30000)
                        resume_from_login_landing = False
                        execution_record.logs += '[Auth Cache] 已恢复同域登录入口页，继续执行非登录步骤。\n'
                    action_type = step['action_type']

                    if skip_cached_login_phase and step.get('_source') == 'setup':
                        step_record['status'] = 'completed'
                        step_record['element'] = {'tag': 'auth_cache', 'reused': True}
                        execution_record.logs += '  已复用经验证登录态，跳过预置登录动作\n'
                        if _is_login_completion_step(step):
                            skip_cached_login_phase = False

                    elif action_type == 'business_action':
                        from ..business_actions import execute_business_action
                        result = await execute_business_action(
                            engine.page,
                            step,
                            execution_record,
                            permission_cleanup=permission_cleanup,
                        )
                        business_action_results.append({
                            'name': step.get('business_action'),
                            'input_value': step.get('input_value'),
                            'source': step.get('_source') or 'case',
                            'status': result.get('status', 'failed'),
                            'result': result,
                        })
                        step_record['status'] = result.get('status', 'failed')
                        step_record['element'] = result.get('element')
                        if step_record['status'] == 'completed':
                            if step.get('business_action') == 'nn_click_community_result':
                                clicked_community_identity = (
                                    (result.get('element') or {}).get('detail', {}).get('community_identity') or None
                                )
                            execution_record.logs += f"  业务动作完成: {result.get('message', step.get('business_action'))}" + chr(10)
                        else:
                            step_record['error'] = result.get('error') or result.get('message') or '业务动作失败'
                            execution_record.logs += f"  业务动作失败: {step_record['error']}" + chr(10)

                    elif action_type == 'try_click':
                        has_modal = False
                        try:
                            _quick_modal = engine.page.locator(
                                '[role="dialog"], [role="alertdialog"], '
                                '.el-dialog, .el-drawer, .el-message-box, '
                                '.nn-dialog, .nn-modal, .nn-popup, .nn-drawer, '
                                '.ant-modal, .ant-drawer, .modal, .dialog, .popup, .drawer'
                            ).first
                            has_modal = await _quick_modal.count() > 0 and await _quick_modal.is_visible(timeout=800)
                        except Exception:
                            pass

                        if not has_modal:
                            step_record['status'] = 'completed'
                            execution_record.logs += "  无弹窗，跳过\n"
                        else:
                            try:
                                el = await _find_element_for_type(engine.page, step, execution_record)
                                if el and await el.count() > 0:
                                    await el.click(timeout=5000)
                                    step_record['status'] = 'completed'
                                    step_record['element'] = await _capture_element_info(engine.page, el)
                                    execution_record.logs += "  弹窗已关闭\n"
                                else:
                                    step_record['status'] = 'completed'
                                    execution_record.logs += "  有弹窗但未找到关闭按钮，跳过\n"
                            except Exception:
                                step_record['status'] = 'completed'
                                execution_record.logs += "  关闭弹窗失败，跳过\n"
                    elif action_type == 'goto':
                        url = step['input_value']
                        health = {}
                        navigation_errors = []
                        for attempt in range(3):
                            try:
                                await engine.page.goto(url, wait_until='domcontentloaded', timeout=45000)
                            except Exception as nav_error:
                                navigation_errors.append(str(nav_error)[:200])
                                execution_record.logs += (
                                    f'  导航尚未完成，继续等待页面就绪 {attempt + 1}/3: '
                                    f'{str(nav_error)[:120]}' + chr(10)
                                )
                            health = await _wait_for_page_ready(engine.page, timeout_seconds=20 + attempt * 10)
                            body_text = str((health.get('evidence') or {}).get('bodyText') or '')
                            if health.get('healthy') and not ('服务器繁忙' in body_text or '请稍后再试' in body_text):
                                break
                            if attempt < 2:
                                execution_record.logs += f'  页面尚未就绪，准备重试导航 {attempt + 1}/3' + chr(10)
                        if '服务器繁忙' in str((health.get('evidence') or {}).get('bodyText') or ''):
                            health['healthy'] = False
                            health['reason'] = '目标页面持续返回服务器繁忙，请稍后再试'
                        if not health.get('healthy'):
                            step_record['status'] = 'failed'
                            step_record['error'] = health.get('reason') or '页面健康检查失败'
                            step_record['element'] = {'tag': 'page', 'url': url, 'health': health}
                            execution_record.logs += f"  页面健康检查失败: {step_record['error']}\n"
                            execution_record.logs += f"  页面健康证据: {health.get('evidence')}\n"
                        else:
                            step_record['status'] = 'completed'
                            step_record['element'] = {'tag': 'page', 'url': url, 'health': health}
                            execution_record.logs += f"  已导航到 {url}\n"

                    elif action_type == 'type':
                        value = step['input_value']
                        el = await _find_element_for_type(engine.page, step, execution_record)
                        if isinstance(el, dict) and '_js_click_selector' in el:
                            _sel = el['_js_click_selector']
                            await engine.page.evaluate(
                                '(s, v) => { const e = document.querySelector(s); if(e){e.focus(); e.value=v; e.dispatchEvent(new Event("input",{bubbles:true}));} }',
                                _sel, value
                            )
                            step_record['status'] = 'completed'
                            step_record['element'] = {'tag': 'js_type', 'selector': _sel}
                            execution_record.logs += f"  已输入(JS): {value}\n"
                        elif el:
                            try:
                                await el.fill(value, timeout=10000)
                            except Exception:
                                await el.type(value, timeout=10000)
                            step_record['status'] = 'completed'
                            step_record['element'] = await _capture_element_info(engine.page, el)
                            execution_record.logs += f"  已输入: {value}\n"
                        else:
                            step_record['status'] = 'failed'
                            step_record['error'] = '未找到匹配的输入框'
                            execution_record.logs += "  未找到匹配的输入框\n"

                    elif action_type == 'click':
                        el = await _find_element_for_type(engine.page, step, execution_record)
                        if isinstance(el, dict) and '_js_click_selector' in el:
                            _sel = el['_js_click_selector']
                            await engine.page.evaluate('(s) => document.querySelector(s).click()', _sel)
                            step_record['status'] = 'completed'
                            step_record['element'] = {'tag': 'js_click', 'selector': _sel}
                            execution_record.logs += f"  已点击(JS): {_sel}\n"
                        elif el:
                            try:
                                await engine.page.evaluate(r"""() => {
                                    document.querySelectorAll('#ui-floating-container, [class*="floating"]').forEach(e => { e.style.pointerEvents = 'none'; });
                                }""")
                                await asyncio.sleep(0.2)
                                try:
                                    # Prefer a real pointer interaction.  Some Vue controls
                                    # depend on pointer/focus event order and do not update
                                    # reliably when invoked through HTMLElement.click().
                                    await el.click(timeout=5000)
                                except Exception:
                                    try:
                                        await el.click(timeout=3000, force=True)
                                    except Exception:
                                        _eh = await el.element_handle()
                                        if not _eh:
                                            raise
                                        await engine.page.evaluate('(e) => e.click()', _eh)
                                step_record['status'] = 'completed'
                                step_record['element'] = await _capture_element_info(engine.page, el)
                                execution_record.logs += "  已点击(element)\n"
                            except Exception as _ce:
                                try:
                                    await el.click(timeout=5000, force=True)
                                    step_record['status'] = 'completed'
                                    step_record['element'] = await _capture_element_info(engine.page, el)
                                    execution_record.logs += "  已点击(force)\n"
                                except Exception as _ce2:
                                    step_record['status'] = 'failed'
                                    step_record['error'] = f'点击失败: {str(_ce2)[:200]}'
                                    execution_record.logs += f"  点击失败: {str(_ce2)[:200]}\n"
                            try:
                                await asyncio.sleep(2)
                                execution_record.logs += "  等待2秒让弹窗加载\n"
                                pass
                            except Exception:
                                pass
                        else:
                            step_record['status'] = 'failed'
                            step_record['error'] = '未找到可点击的元素'
                            targets = _extract_contextual_click_targets(step.get('description', ''))
                            diag = await _get_page_text_diagnostics(engine.page, targets)
                            execution_record.logs += '  未找到可点击的元素' + chr(10)
                            if targets:
                                execution_record.logs += f'  点击目标候选: {targets}' + chr(10)
                            if isinstance(diag, dict):
                                execution_record.logs += f"  当前页面: {diag.get('url', '')} | {diag.get('title', '')}" + chr(10)
                                if diag.get('bodyText'):
                                    execution_record.logs += f"  页面可见文本摘要: {diag.get('bodyText')}" + chr(10)
                                if diag.get('samples'):
                                    execution_record.logs += f"  相近可点击/列表元素: {diag.get('samples')}" + chr(10)

                    elif action_type == 'press':
                        key = step.get('input_value') or 'Enter'
                        await engine.page.keyboard.press(key)
                        step_record['status'] = 'completed'
                        execution_record.logs += f'  已按键 {key}' + chr(10)
                        await asyncio.sleep(2)
                        if str(key).lower() == 'enter':
                            prompt_state = await _evaluate_ui_state_predicate(
                                engine.page,
                                {'kind': 'login_prompt_visible', 'allow_auth_url': True},
                            )
                            interaction_results.append({
                                'kind': 'post_press_login_prompt',
                                'source': step.get('_source') or 'case',
                                'result': prompt_state,
                            })

                    elif action_type == 'set_viewport':
                        viewport = step.get('viewport') or {}
                        width = int(viewport.get('width') or 0)
                        height = int(viewport.get('height') or 0)
                        if width < 200 or height < 200:
                            step_record['status'] = 'failed'
                            step_record['error'] = '视口尺寸无效'
                        else:
                            await engine.page.set_viewport_size({'width': width, 'height': height})
                            step_record['status'] = 'completed'
                            step_record['element'] = {'tag': 'viewport', 'width': width, 'height': height}
                            execution_record.logs += f'  已设置视口: {width}x{height}' + chr(10)

                    elif action_type == 'reload':
                        await engine.page.reload(wait_until='domcontentloaded', timeout=30000)
                        await asyncio.sleep(2)
                        step_record['status'] = 'completed'
                        step_record['element'] = {'tag': 'page', 'url': engine.page.url}
                        execution_record.logs += '  已刷新当前页面' + chr(10)

                    elif action_type == 'wait':
                        secs = int(step.get('input_value', '1'))
                        if step.get('wait_for') == 'page_ready':
                            health = await _wait_for_page_ready(engine.page, timeout_seconds=max(secs, 30))
                            if health.get('healthy'):
                                step_record['status'] = 'completed'
                                step_record['element'] = {'tag': 'page', 'url': engine.page.url, 'health': health}
                                execution_record.logs += f'  页面已就绪，等待上限 {max(secs, 30)} 秒' + chr(10)
                            else:
                                step_record['status'] = 'failed'
                                step_record['error'] = health.get('reason') or '页面在等待时间内未就绪'
                                step_record['element'] = {'tag': 'page', 'url': engine.page.url, 'health': health}
                                execution_record.logs += f"  页面就绪等待失败: {step_record['error']}" + chr(10)
                        else:
                            await asyncio.sleep(secs)
                            step_record['status'] = 'completed'
                            execution_record.logs += f'  已等待 {secs} 秒' + chr(10)

                    elif action_type == 'assert':
                        page_text = await engine.page.inner_text('body')
                        assert_desc = step.get('description') or step.get('input_value') or step.get('assert_value') or ''
                        assertion_contract = step.get('assertion_contract') or {}
                        contract_kind = assertion_contract.get('kind')

                        def _record_assertion_result(result):
                            # Every assertion path must leave inspectable evidence in the report.
                            step_record['assertion'] = {
                                'contract': assertion_contract or {'kind': 'legacy_text'},
                                'result': result,
                            }

                        if contract_kind == 'page_health' or step.get('assert_type') == 'page_health':
                            health_result = await _evaluate_page_health(engine.page)
                            health_result['passed'] = bool(health_result.get('healthy'))
                            _record_assertion_result(health_result)
                            if health_result.get('passed'):
                                step_record['status'] = 'completed'
                                execution_record.logs += '  页面健康断言: 通过' + chr(10)
                            else:
                                step_record['status'] = 'failed'
                                step_record['error'] = health_result.get('reason') or '页面健康检查未通过'
                                execution_record.logs += f"  页面健康断言: 失败，{step_record['error']}" + chr(10)
                        elif contract_kind == 'login_state' or (
                            not contract_kind
                            and (step.get('assert_type') == 'login_success' or _is_login_success_assertion(assert_desc))
                        ):
                            login_state = await _evaluate_login_success(engine.page)
                            _record_assertion_result(login_state)
                            if login_state.get('passed'):
                                step_record['status'] = 'completed'
                                execution_record.logs += '  登录断言: 通过，检测到已登录态' + chr(10)
                                execution_record.logs += f"  登录态证据: {login_state.get('evidence')}" + chr(10)
                            else:
                                step_record['status'] = 'failed'
                                step_record['error'] = login_state.get('reason') or '未检测到登录成功状态'
                                execution_record.logs += f"  登录断言: 失败，{step_record['error']}" + chr(10)
                                execution_record.logs += f"  登录态证据: {login_state.get('evidence')}" + chr(10)
                                if login_state.get('bodyText'):
                                    execution_record.logs += f"  页面可见文本摘要: {login_state.get('bodyText')}" + chr(10)
                        else:
                            if contract_kind == 'control_state' or step.get('assert_type') == 'disabled':
                                target = assertion_contract.get('target') or step.get('target_text') or step.get('assert_value') or ''
                                state_result = await (_assert_element_checked(engine.page, target) if assertion_contract.get('state') == 'checked' or step.get('assert_type') == 'checked' else _assert_element_disabled(engine.page, target))
                                _record_assertion_result(state_result)
                                if state_result.get('passed'):
                                    step_record['status'] = 'completed'
                                    execution_record.logs += f'  控件禁用断言: 通过，{target} 不可用' + chr(10)
                                else:
                                    step_record['status'] = 'failed'
                                    step_record['error'] = state_result.get('reason') or f'{target} 未处于不可用状态'
                                    execution_record.logs += f"  控件禁用断言: 失败，{step_record['error']}" + chr(10)
                            elif contract_kind == 'composite':
                                composite_result = await _evaluate_composite_assertion(
                                    engine.page,
                                    assertion_contract,
                                    assert_desc,
                                )
                                _record_assertion_result(composite_result)
                                if composite_result.get('passed'):
                                    step_record['status'] = 'completed'
                                    execution_record.logs += f"  组合断言: 通过，{composite_result.get('summary')}" + chr(10)
                                else:
                                    step_record['status'] = 'failed'
                                    step_record['error'] = composite_result.get('reason') or '组合断言未满足'
                                    execution_record.logs += f"  组合断言: 失败，{step_record['error']}" + chr(10)
                                execution_record.logs += f"  组合断言证据: {composite_result}" + chr(10)
                            elif contract_kind == 'assertion_plan':
                                plan_result = await _evaluate_assertion_plan(
                                    engine.page,
                                    assertion_contract,
                                    assert_desc,
                                    {
                                        'business_actions': business_action_results,
                                        'interactions': interaction_results,
                                    },
                                )
                                _record_assertion_result(plan_result)
                                if plan_result.get('passed'):
                                    step_record['status'] = 'completed'
                                else:
                                    step_record['status'] = 'failed'
                                    step_record['error'] = plan_result.get('reason') or '断言计划未通过'
                                execution_record.logs += f"  断言计划: {plan_result.get('summary')}" + chr(10)
                                execution_record.logs += f"  断言计划证据: {plan_result}" + chr(10)
                            elif contract_kind == 'review_required':
                                # Never invent a generic text check for prose that has no
                                # reliable verification strategy.  A review item is not a
                                # pass, but it must not turn the case into a false failure.
                                step_record['status'] = 'skipped'
                                step_record['review_required'] = True
                                step_record['review_reason'] = assertion_contract.get('reason')
                                step_record['assertion'] = {
                                    'contract': assertion_contract,
                                    'result': {'review_required': True, 'reason': assertion_contract.get('reason')},
                                }
                                execution_record.logs += f"  断言待复核: {assertion_contract.get('reason')}" + chr(10)
                            elif contract_kind == 'ai_semantic':
                                from ..ai_assertion import AIAssertionService

                                try:
                                    passed, reason, screenshot = await AIAssertionService.ai_assert(
                                        engine.page,
                                        assert_desc,
                                    )
                                    semantic_result = {
                                        'passed': bool(passed),
                                        'reason': reason or '',
                                        'screenshot_captured': bool(screenshot),
                                    }
                                except Exception as exc:
                                    semantic_result = {
                                        'passed': None,
                                        'reason': f'AI语义断言不可用: {exc}',
                                        'screenshot_captured': False,
                                    }
                                _record_assertion_result(semantic_result)
                                if semantic_result['passed'] is True:
                                    step_record['status'] = 'completed'
                                elif semantic_result['passed'] is None:
                                    step_record['status'] = 'skipped'
                                    step_record['review_required'] = True
                                    step_record['review_reason'] = semantic_result['reason']
                                else:
                                    step_record['status'] = 'failed'
                                    step_record['error'] = semantic_result['reason'] or 'AI语义断言未通过'
                                semantic_status = '通过' if semantic_result['passed'] is True else ('待复核' if semantic_result['passed'] is None else '失败')
                                execution_record.logs += f"  AI语义断言: {semantic_status}，{semantic_result['reason']}" + chr(10)
                            elif contract_kind == 'community_detail' or step.get('assert_type') == 'community_detail':
                                target = assertion_contract.get('target') or step.get('target_text') or step.get('assert_value') or ''
                                detail_result = await _assert_community_detail(engine.page, target)
                                _record_assertion_result(detail_result)
                                if detail_result.get('passed'):
                                    step_record['status'] = 'completed'
                                    execution_record.logs += f'  社区详情断言: 通过，已进入目标社区 {target}' + chr(10)
                                    execution_record.logs += f"  详情证据: {detail_result}" + chr(10)
                                else:
                                    step_record['status'] = 'failed'
                                    step_record['error'] = f'未检测到目标社区详情态: {target}'
                                    execution_record.logs += f'  社区详情断言: 失败，未检测到目标社区详情态 {target}' + chr(10)
                                    execution_record.logs += f"  详情证据: {detail_result}" + chr(10)
                            elif contract_kind == 'search_overlay' or step.get('assert_type') == 'top_search_overlay':
                                expected_texts = assertion_contract.get('expected_texts') or step.get('expected_texts') or _extract_assert_expected_texts(assert_desc)
                                overlay_result = await _assert_top_search_overlay(
                                    engine.page,
                                    expected_texts,
                                    bool(assertion_contract.get('min_results') or step.get('require_multiple_results')),
                                    bool(assertion_contract.get('require_history')),
                                    execution_record,
                                )
                                _record_assertion_result(overlay_result)
                                if overlay_result.get('passed'):
                                    step_record['status'] = 'completed'
                                    execution_record.logs += '  顶部搜索弹层断言: 通过，搜索框已获得焦点' + chr(10)
                                    execution_record.logs += f"  弹层证据: {overlay_result}" + chr(10)
                                else:
                                    step_record['status'] = 'failed'
                                    step_record['error'] = overlay_result.get('reason') or '顶部搜索弹层未达到预期状态'
                                    execution_record.logs += f"  顶部搜索弹层断言: 失败，{step_record['error']}" + chr(10)
                                    execution_record.logs += f"  弹层证据: {overlay_result}" + chr(10)
                            elif contract_kind == 'referenced_identity' or step.get('assert_type') == 'clicked_community_identity':
                                identity_result = await _assert_clicked_community_identity(
                                    engine.page,
                                    clicked_community_identity,
                                )
                                _record_assertion_result(identity_result)
                                if identity_result.get('passed'):
                                    step_record['status'] = 'completed'
                                    execution_record.logs += '  社区身份断言: 通过，进入页面与所点击卡片一致' + chr(10)
                                    execution_record.logs += f"  身份证据: {identity_result}" + chr(10)
                                else:
                                    step_record['status'] = 'failed'
                                    step_record['error'] = identity_result.get('reason') or '进入页面与所点击社区不一致'
                                    execution_record.logs += f"  社区身份断言: 失败，{step_record['error']}" + chr(10)
                                    execution_record.logs += f"  身份证据: {identity_result}" + chr(10)
                            else:
                                expected_texts = assertion_contract.get('expected_texts') or step.get('expected_texts') or _extract_assert_expected_texts(assert_desc)
                                if expected_texts:
                                    strict_result = await _strict_text_assertion(engine.page, expected_texts, assert_desc)
                                    _record_assertion_result(strict_result)
                                    if strict_result.get('passed'):
                                        step_record['status'] = 'completed'
                                        execution_record.logs += f'  断言: 通过，在语义区域找到文本 {expected_texts}' + chr(10)
                                        if strict_result.get('scope'):
                                            execution_record.logs += f"  断言范围: {strict_result.get('scope')}" + chr(10)
                                        if strict_result.get('match'):
                                            execution_record.logs += f"  命中文本块: {strict_result.get('match')}" + chr(10)
                                        stable_aliases = [
                                            item for item in (strict_result.get('matched_texts') or [])
                                            if item.get('match_mode') == 'stable_alias'
                                        ]
                                        if stable_aliases:
                                            execution_record.logs += (
                                                f"  文本兼容命中: {stable_aliases}（原始期望已保留）" + chr(10)
                                            )
                                    else:
                                        missing = strict_result.get('missing') or expected_texts
                                        step_record['status'] = 'failed'
                                        step_record['error'] = f'断言区域未找到文本: {missing}'
                                        diag = await _get_page_text_diagnostics(engine.page, expected_texts)
                                        execution_record.logs += f'  断言: 失败，断言区域缺少文本 {missing}' + chr(10)
                                        if strict_result.get('scope'):
                                            execution_record.logs += f"  断言范围: {strict_result.get('scope')}" + chr(10)
                                        if strict_result.get('samples'):
                                            execution_record.logs += f"  命中候选: {strict_result.get('samples')}" + chr(10)
                                        if strict_result.get('bodyText'):
                                            execution_record.logs += f"  断言区域文本摘要: {strict_result.get('bodyText')}" + chr(10)
                                        if isinstance(diag, dict) and diag.get('bodyText'):
                                            execution_record.logs += f"  页面可见文本摘要: {diag.get('bodyText')}" + chr(10)
                                else:
                                    step_record['status'] = 'failed'
                                    step_record['error'] = '断言缺少明确的期望文本或登录成功条件'
                                    _record_assertion_result({
                                        'passed': False,
                                        'reason': step_record['error'],
                                    })
                                    execution_record.logs += '  断言: 失败，缺少明确的期望文本或登录成功条件' + chr(10)

                    else:
                        step_record['status'] = 'failed'
                        step_record['error'] = f'未知操作类型: {action_type}'

                except Exception as e:
                    step_record['status'] = 'failed'
                    step_record['error'] = str(e)
                    execution_record.logs += f"  步骤失败: {str(e)}\n"

                if (
                    login_cache_key and not reused_login_state and not cache_saved
                    and step.get('_source') == 'setup'
                    and step_record['status'] == 'completed'
                    and _is_login_completion_step(step)
                ):
                    try:
                        login_check = await _evaluate_login_success(engine.page)
                        raw_storage_state = await engine.context.storage_state()
                        auth_storage_state = _filter_authenticated_storage_state(
                            raw_storage_state,
                            login_landing_url,
                        )
                        if login_check.get('passed') and _store_cached_auth_state(login_cache_key, auth_storage_state):
                            cache_saved = True
                            execution_record.logs += '[Auth Cache] 登录成功并已缓存认证状态，后续同域用例将跳过登录。\n'
                            if login_lock_held:
                                login_lock.release()
                                login_lock_held = False
                        else:
                            execution_record.logs += '[Auth Cache] 未提取到可复用的认证状态，后续用例将按前置模板重新登录。\n'
                    except Exception as cache_save_error:
                        execution_record.logs += f'[Auth Cache] 登录态缓存保存失败，已保留本次执行结果：{str(cache_save_error)[:180]}\n'

                try:
                    # Rendering can occasionally stall on a heavily edited
                    # rich-text page.  A diagnostic image is useful, but it
                    # must never hold the whole isolated execution forever.
                    screenshot_b64 = await asyncio.wait_for(
                        engine.page.screenshot(timeout=8000),
                        timeout=10,
                    )
                    step_record['screenshot'] = base64.b64encode(screenshot_b64).decode()
                except Exception:
                    pass

                recorded_steps.append(step_record)

                if execution_record.planned_tasks:
                    for t in execution_record.planned_tasks:
                        if t['id'] == step_id:
                            t['status'] = step_record['status']
                            break

                try:
                    execution_record.steps_completed = _reportable_execution_steps(recorded_steps)
                    await sync_to_async(_save_execution_record_with_retry, thread_sensitive=True)(
                        execution_record,
                        update_fields=['logs', 'planned_tasks', 'steps_completed'],
                    )
                except Exception:
                    pass

                if step_callback:
                    await step_callback({'task_id': step_id, 'status': step_record['status']})

                # A failed action invalidates the state assumed by all later
                # actions. Mark the remainder blocked so the report contains
                # one real failure instead of a cascade of misleading locator
                # errors that look like independent failures.
                if step_record['status'] in ('failed', 'error'):
                    blocked_reason = f'阻塞于第 {i + 1} 步：{step_record.get("error") or "步骤失败"}'
                    blocked_count = append_blocked_remaining_steps(
                        steps,
                        i,
                        recorded_steps,
                        execution_record.planned_tasks,
                        blocked_reason,
                    )
                    if step_callback:
                        for remaining_index in range(i + 1, len(steps)):
                            await step_callback({
                                'task_id': f'task_{remaining_index + 1}',
                                'status': 'skipped',
                                'blocked_by_step': i + 1,
                            })
                    execution_record.logs += f"  后续 {blocked_count} 步已阻断：{blocked_reason}\n"
                    break

            await sync_to_async(_persist_ai_execution_media, thread_sensitive=True)(
                execution_record,
                recorded_steps,
            )
            execution_record.logs += "\n========== 录制完成 ==========\n"

        except Exception as e:
            execution_record.logs += f"\n执行异常: {str(e)}\n{tb.format_exc()}\n"
        finally:
            try:
                if permission_cleanup.entries:
                    execution_record.logs += "\n========== 开始权限环境回收 ==========\n"
                    await permission_cleanup.cleanup(engine.page, __import__('apps.ui_automation.business_actions', fromlist=['NNPageActions']).NNPageActions(engine.page, execution_record))
                    execution_record.cleanup_results = permission_cleanup.as_report_data()
                    cleanup_failed = permission_cleanup.failed
                    if cleanup_failed:
                        execution_record.logs += "[Permission Cleanup] 存在回收失败，整条用例不得判定为成功。\n"
                else:
                    execution_record.cleanup_results = permission_cleanup.as_report_data()
            except Exception as cleanup_error:
                cleanup_failed = True
                execution_record.cleanup_results = {
                    'required': True,
                    'registered_count': len(permission_cleanup.entries),
                    'completed_count': 0,
                    'failed_count': len(permission_cleanup.entries) or 1,
                    'results': [{'status': 'failed', 'error': str(cleanup_error)[:500]}],
                }
                execution_record.logs += f"[Permission Cleanup] 回收流程异常，整条用例判定失败: {cleanup_error}\n"
            try:
                await engine.stop()
            except Exception:
                pass
            if login_lock_held:
                login_lock.release()
                login_lock_held = False
        execution_record._permission_cleanup_failed = cleanup_failed

    loop = asyncio.new_event_loop()
    def _run_in_thread():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_async())
        loop.close()

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()
    thread.join(timeout=300)

    if thread.is_alive():
        # The worker is cooperative: signal it to stop so it can close the
        # browser and run permission cleanup, then expose a legal terminal
        # status immediately instead of leaving the record as "error" or
        # allowing the UI to show an endless running state.
        if execution_record.id:
            STOP_SIGNALS[execution_record.id] = True
        execution_record.status = 'failed'
        execution_record.logs += "\n执行超时（>300秒），已发送停止信号并判定失败。\n"
    else:
        failed = (
            any(t.get('status') in ('failed', 'error') for t in (execution_record.planned_tasks or []))
            or any(step.get('status') in ('failed', 'error') for step in recorded_steps)
        )
        unfinished = any(t.get('status') in ('pending', 'in_progress') for t in (execution_record.planned_tasks or []))
        if unfinished and not failed:
            execution_record.logs += chr(10) + "执行完成，但仍有子任务未完成，已判定为失败。" + chr(10)
        cleanup_failed = bool(getattr(execution_record, '_permission_cleanup_failed', False))
        if cleanup_failed:
            execution_record.logs += "\n环境回收失败，不能将本次执行判定为成功。\n"
        execution_record.status = 'failed' if failed or unfinished or cleanup_failed else 'passed'

    execution_record.end_time = timezone.now()
    execution_record.duration = (execution_record.end_time - execution_record.start_time).total_seconds()
    execution_record.steps_completed = _reportable_execution_steps(recorded_steps)
    _save_execution_record_with_retry(
        execution_record,
        update_fields=['status', 'logs', 'end_time', 'duration', 'planned_tasks', 'steps_completed', 'cleanup_results'],
    )
    from ..ai_notifications import send_ai_execution_notification
    send_ai_execution_notification(execution_record)



async def _assert_community_detail_strict_old(page, target_text: str):
    js = r'''(target) => {
        const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const rectOf = (r) => ({x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)});
        const exactish = (text, needle) => {
            const t = norm(text);
            const n = norm(needle);
            return t === n || t.startsWith(n + ' ') || t.includes(' ' + n + ' ');
        };
        const url = location.href;
        const nodes = Array.from(document.querySelectorAll('main *, aside *, nav *, section *, div, span, h1, h2, h3, a, p'))
            .filter(visible)
            .map(el => {
                const r = el.getBoundingClientRect();
                return {el, text: norm(el.innerText || el.textContent || ''), cls: String(el.className || ''), rect: r, tag: el.tagName.toLowerCase()};
            })
            .filter(x => x.text && x.rect.left < window.innerWidth * 0.38 && x.rect.width >= 20 && x.rect.height >= 12 && x.text.length <= 80);

        const titleCandidates = nodes
            .filter(x => exactish(x.text, target) && x.rect.width <= 320 && x.rect.height <= 40)
            .sort((a,b) => (a.rect.width*a.rect.height) - (b.rect.width*b.rect.height));

        const officialCandidates = nodes
            .filter(x => /PUBG中国官方社区/.test(x.text) && x.rect.width <= 320 && x.rect.height <= 28)
            .sort((a,b) => (a.rect.width*a.rect.height) - (b.rect.width*b.rect.height));

        const hallCandidates = nodes
            .filter(x => /社区大厅/.test(x.text) && x.rect.width <= 320 && x.rect.height <= 48)
            .sort((a,b) => (a.rect.width*a.rect.height) - (b.rect.width*b.rect.height));

        let best = null;
        for (const title of titleCandidates) {
            // NN 社区详情页的“官方社区”徽标通常在社区名称上方/封面图底部，
            // 不能只按“标题下方”判断，否则真实进入详情页也会被误判失败。
            const official = officialCandidates.find(o => Math.abs(o.rect.left - title.rect.left) <= 80 && Math.abs(o.rect.top - title.rect.top) <= 110);
            if (!official) continue;
            const anchorTop = Math.max(title.rect.top, official.rect.top);
            const hall = hallCandidates.find(h => Math.abs(h.rect.left - title.rect.left) <= 100 && h.rect.top > anchorTop && h.rect.top - anchorTop <= 280);
            best = {title, official, hall: hall || null};
            if (hall) break;
        }

        const passed = !!(best && best.title && best.official && best.hall) && /\/community\//.test(url);
        return {
            passed,
            target,
            url,
            titleCandidate: best?.title ? {text: best.title.text, cls: best.title.cls.slice(0,160), rect: rectOf(best.title.rect), tag: best.title.tag} : null,
            officialCandidate: best?.official ? {text: best.official.text, cls: best.official.cls.slice(0,160), rect: rectOf(best.official.rect), tag: best.official.tag} : null,
            communityHallCandidate: best?.hall ? {text: best.hall.text, cls: best.hall.cls.slice(0,160), rect: rectOf(best.hall.rect), tag: best.hall.tag} : null,
            sampleTitles: titleCandidates.slice(0,5).map(x => ({text:x.text, rect: rectOf(x.rect), cls: x.cls.slice(0,120)})),
            sampleOfficials: officialCandidates.slice(0,5).map(x => ({text:x.text, rect: rectOf(x.rect), cls: x.cls.slice(0,120)})),
            sampleHalls: hallCandidates.slice(0,5).map(x => ({text:x.text, rect: rectOf(x.rect), cls: x.cls.slice(0,120)})),
            bodyText: norm((document.body.innerText || '').slice(0, 1000))
        };
    }'''
    try:
        return await page.evaluate(js, target_text)
    except Exception as exc:
        return {'passed': False, 'reason': f'社区详情断言执行失败: {exc}', 'bodyText': ''}

def _community_text_matches(text: str, target: str) -> bool:
    current = re.sub(r'\s+', ' ', str(text or '')).strip()
    needle = re.sub(r'\s+', ' ', str(target or '')).strip()
    if not current or not needle:
        return False
    for variant in _ui_label_variants(needle):
        if current == variant or current.startswith(variant + ' ') or f' {variant} ' in f' {current} ':
            return True
        # Community navigation renders the canonical community label as
        # "<community>首页". It is a stable view suffix, not a looser name match.
        if current == variant + '首页' or current.startswith(variant + '首页 '):
            return True
    return False


def _normalize_community_detail_result(result, target_text: str):
    if not isinstance(result, dict):
        return {'passed': False, 'reason': '社区详情断言返回格式异常', 'target': target_text, 'bodyText': ''}

    normalized = dict(result)
    url = str(normalized.get('url') or '')
    body_text = re.sub(r'\s+', ' ', str(normalized.get('bodyText') or '')).strip()

    sample_titles = normalized.get('sampleTitles') or []
    sample_officials = normalized.get('sampleOfficials') or []
    sample_halls = normalized.get('sampleHalls') or []

    title_texts = []
    title_candidate = normalized.get('titleCandidate')
    if isinstance(title_candidate, dict):
        title_texts.append(title_candidate.get('text'))
    title_texts.extend(item.get('text') for item in sample_titles if isinstance(item, dict))

    official_texts = []
    official_candidate = normalized.get('officialCandidate')
    if isinstance(official_candidate, dict):
        official_texts.append(official_candidate.get('text'))
    official_texts.extend(item.get('text') for item in sample_officials if isinstance(item, dict))

    hall_texts = []
    hall_candidate = normalized.get('communityHallCandidate')
    if isinstance(hall_candidate, dict):
        hall_texts.append(hall_candidate.get('text'))
    hall_texts.extend(item.get('text') for item in sample_halls if isinstance(item, dict))

    has_title_signal = bool(title_candidate) or bool(sample_titles) or any(_community_text_matches(text, target_text) for text in title_texts) or _community_text_matches(body_text, target_text)
    has_official_signal = bool(official_candidate) or bool(sample_officials) or any('PUBG中国官方社区' in str(text or '') for text in official_texts) or ('PUBG中国官方社区' in body_text)
    hall_labels = _ui_label_variants('成员大厅')
    has_hall_signal = bool(hall_candidate) or bool(sample_halls) or any(any(label in str(text or '') for label in hall_labels) for text in hall_texts) or any(label in body_text for label in hall_labels)
    url_contains_community = '/community/' in url

    signals = dict(normalized.get('signals') or {})
    signals.update({
        'hasTitleSignal': has_title_signal,
        'hasOfficialSignal': has_official_signal,
        'hasHallSignal': has_hall_signal,
        'urlContainsCommunity': url_contains_community,
    })
    normalized['signals'] = signals

    normalized['passed'] = bool(normalized.get('passed')) or (url_contains_community and has_title_signal and has_official_signal)
    if normalized['passed']:
        normalized['reason'] = ''
        return normalized

    missing = []
    if not url_contains_community:
        missing.append('community_url')
    if not has_title_signal:
        missing.append('target_title')
    if not has_official_signal:
        missing.append('official_label')
    if not has_hall_signal:
        missing.append('hall_hint')
    normalized['reason'] = 'missing_signals:' + ','.join(missing)
    return normalized


async def _assert_community_detail(page, target_text: str):
    js = r'''(target) => {
        const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const rectOf = (r) => ({x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)});
        const exactish = (text, needle) => {
            const t = norm(text);
            const n = norm(needle);
            return t === n || t.startsWith(n + ' ') || t.includes(' ' + n + ' ');
        };
        const url = location.href;
        const bodyText = norm((document.body.innerText || '').slice(0, 1000));
        const bodyHasOfficialText = /PUBG中国官方社区/.test(bodyText);
        const bodyHasHallText = /成员大厅|全员大厅/.test(bodyText);
        const nodes = Array.from(document.querySelectorAll('main *, aside *, nav *, section *, div, span, h1, h2, h3, a, p'))
            .filter(visible)
            .map(el => {
                const r = el.getBoundingClientRect();
                return {el, text: norm(el.innerText || el.textContent || ''), cls: String(el.className || ''), rect: r, tag: el.tagName.toLowerCase()};
            })
            .filter(x => x.text && x.rect.left < window.innerWidth * 0.38 && x.rect.width >= 20 && x.rect.height >= 12 && x.text.length <= 80);

        const titleCandidates = nodes
            .filter(x => exactish(x.text, target) && x.rect.width <= 320 && x.rect.height <= 40)
            .sort((a,b) => (a.rect.width*a.rect.height) - (b.rect.width*b.rect.height));

        const officialCandidates = nodes
            .filter(x => /PUBG中国官方社区/.test(x.text) && x.rect.width <= 320 && x.rect.height <= 28)
            .sort((a,b) => (a.rect.width*a.rect.height) - (b.rect.width*b.rect.height));

        const hallCandidates = nodes
            .filter(x => /成员大厅|全员大厅/.test(x.text) && x.rect.width <= 320 && x.rect.height <= 48)
            .sort((a,b) => (a.rect.width*a.rect.height) - (b.rect.width*b.rect.height));

        let best = null;
        for (const title of titleCandidates) {
            const official = officialCandidates
                .filter(o => Math.abs(o.rect.left - title.rect.left) <= 140 && Math.abs(o.rect.top - title.rect.top) <= 180)
                .sort((a, b) => {
                    const da = Math.abs(a.rect.left - title.rect.left) + Math.abs(a.rect.top - title.rect.top);
                    const db = Math.abs(b.rect.left - title.rect.left) + Math.abs(b.rect.top - title.rect.top);
                    return da - db;
                })[0];
            if (!official) continue;
            const anchorTop = Math.max(title.rect.top, official.rect.top);
            const hall = hallCandidates.find(h => Math.abs(h.rect.left - title.rect.left) <= 100 && h.rect.top > anchorTop && h.rect.top - anchorTop <= 280);
            best = {title, official, hall: hall || null};
            if (hall) break;
        }

        const hasTitleSignal = !!(best && best.title) || titleCandidates.length > 0;
        const hasOfficialSignal = !!(best && best.official) || officialCandidates.length > 0 || bodyHasOfficialText;
        const hasHallSignal = !!(best && best.hall) || hallCandidates.length > 0 || bodyHasHallText;
        const passed = /\/community\//.test(url) && hasTitleSignal && hasOfficialSignal;
        return {
            passed,
            target,
            url,
            signals: {
                hasTitleSignal,
                hasOfficialSignal,
                hasHallSignal,
                bodyHasOfficialText,
                bodyHasHallText
            },
            titleCandidate: best?.title ? {text: best.title.text, cls: best.title.cls.slice(0,160), rect: rectOf(best.title.rect), tag: best.title.tag} : null,
            officialCandidate: best?.official ? {text: best.official.text, cls: best.official.cls.slice(0,160), rect: rectOf(best.official.rect), tag: best.official.tag} : null,
            communityHallCandidate: best?.hall ? {text: best.hall.text, cls: best.hall.cls.slice(0,160), rect: rectOf(best.hall.rect), tag: best.hall.tag} : null,
            sampleTitles: titleCandidates.slice(0,5).map(x => ({text:x.text, rect: rectOf(x.rect), cls: x.cls.slice(0,120)})),
            sampleOfficials: officialCandidates.slice(0,5).map(x => ({text:x.text, rect: rectOf(x.rect), cls: x.cls.slice(0,120)})),
            sampleHalls: hallCandidates.slice(0,5).map(x => ({text:x.text, rect: rectOf(x.rect), cls: x.cls.slice(0,120)})),
            bodyText
        };
    }'''
    try:
        result = await page.evaluate(js, target_text)
        return _normalize_community_detail_result(result, target_text)
    except Exception as exc:
        return {'passed': False, 'reason': f'社区详情断言执行失败: {exc}', 'target': target_text, 'bodyText': ''}


async def _assert_element_disabled(page, target_text):
    """Verify an interactive element is disabled using its semantic state."""
    js = r"""(target) => {
        const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
        const lower = (s) => norm(s).toLowerCase();
        const visible = (el) => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
        };
        const candidates = Array.from(document.querySelectorAll('button,input,select,textarea,[role="button"],[aria-disabled]'))
            .filter(visible)
            .map(el => {
                const text = norm([el.innerText, el.textContent, el.value, el.getAttribute('aria-label'), el.getAttribute('title')].filter(Boolean).join(' '));
                return {el, text};
            })
            .filter(item => lower(item.text).includes(lower(target)));
        const item = candidates.sort((a, b) => a.text.length - b.text.length)[0];
        if (!item) return {passed: false, reason: '未找到目标控件', target};
        const el = item.el;
        const disabled = Boolean(el.disabled) || el.getAttribute('aria-disabled') === 'true' || el.matches(':disabled');
        return {passed: disabled, target, text: item.text.slice(0, 200), disabled};
    }"""
    try:
        return await page.evaluate(js, target_text)
    except Exception as exc:
        return {'passed': False, 'reason': f'控件状态断言执行失败: {exc}', 'target': target_text}


async def _assert_element_checked(page, target_text):
    js = r'''(target) => {
        const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
        const visible = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden'; };
        const label = Array.from(document.querySelectorAll('label,div,span')).filter(visible).find(el => norm(el.innerText || el.textContent).includes(norm(target)));
        if (!label) return {passed: false, reason: '未找到复选项标签', target};
        const roots = [label];
        for (let node = label.parentElement, depth = 0; node && depth < 4; node = node.parentElement, depth += 1) roots.push(node);
        const control = roots.flatMap(root => Array.from(root.querySelectorAll('input[type="checkbox"],[role="checkbox"],[aria-checked],[class*="checkbox" i],[class*="check" i]')))
            .find(el => visible(el));
        if (!control) return {passed: false, reason: '未找到复选控件', target, labelClass: String(label.className || '').slice(0, 160)};
        const checked = Boolean(control.checked) || control.getAttribute('aria-checked') === 'true' || /checked|selected|active|primary|success/i.test(String(control.className || ''));
        return {passed: checked, target, checked, tag: control.tagName.toLowerCase(), cls: String(control.className || '').slice(0, 160)};
    }'''
    try:
        return await page.evaluate(js, target_text)
    except Exception as exc:
        return {'passed': False, 'reason': f'复选状态断言执行失败: {exc}', 'target': target_text}


async def _assert_selected_state(page, target: str, scope: str = 'all'):
    js = r'''(payload) => {
        const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
        const lower = (value) => norm(value).toLowerCase();
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const bodyWidth = document.body.getBoundingClientRect().width;
        const nodes = Array.from(document.querySelectorAll('a,button,[role="tab"],[role="menuitem"],li,span,div'))
            .filter(visible)
            .filter(el => {
                const r = el.getBoundingClientRect();
                return payload.scope !== 'left' || r.left + r.width / 2 < bodyWidth * 0.46;
            })
            .filter(el => (payload.targets || [payload.target]).some(target => lower(el.innerText || el.textContent || '').includes(lower(target))))
            .sort((a, b) => norm(a.innerText || a.textContent || '').length - norm(b.innerText || b.textContent || '').length);
        for (const node of nodes) {
            let selected = false;
            let evidence = null;
            for (let el = node, depth = 0; el && depth < 5; el = el.parentElement, depth += 1) {
                const cls = String(el.className || '');
                const ariaCurrent = el.getAttribute('aria-current');
                const ariaSelected = el.getAttribute('aria-selected');
                if (ariaSelected === 'true' || (ariaCurrent && ariaCurrent !== 'false') || /(^|\s)(active|selected|current|is-active|is-selected)(\s|$)|text-blue|text-primary/i.test(cls)) {
                    selected = true;
                    evidence = {tag: el.tagName.toLowerCase(), cls: cls.slice(0, 160), ariaSelected, ariaCurrent};
                    break;
                }
            }
            if (selected) return {passed: true, target: payload.target, evidence};
        }
        return {passed: false, reason: `未检测到「${payload.target}」的选中状态`, target: payload.target, candidates: nodes.slice(0, 5).map(el => ({text: norm(el.innerText || el.textContent || '').slice(0, 120), cls: String(el.className || '').slice(0, 120)}))};
    }'''
    try:
        return await page.evaluate(js, {'target': target, 'targets': _ui_label_variants(target), 'scope': scope})
    except Exception as exc:
        return {'passed': False, 'reason': f'选中状态断言执行失败: {exc}', 'target': target}


async def _assert_min_visible_cards(page, minimum: int, scope: str = 'main'):
    js = r'''(payload) => {
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width >= 120 && r.height >= 56 && r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const body = document.body.getBoundingClientRect();
        const isCard = (el) => {
            const cls = String(el.className || '');
            if (/(^|[-_\s])(?:card|tile)(?:$|[-_\s])/i.test(cls)) return true;
            const rect = el.getBoundingClientRect();
            const text = String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            if (rect.width >= body.width * 0.9 || rect.height >= window.innerHeight * 0.7 || text.length < 20) return false;
            if (!/\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}|\d+\s*(?:分钟前|小时前|天前)|今天|昨天/.test(text)) return false;
            const siblings = Array.from(el.parentElement?.children || []).filter(candidate => {
                if (candidate === el || !visible(candidate)) return false;
                const siblingRect = candidate.getBoundingClientRect();
                return siblingRect.width >= rect.width * 0.7 && siblingRect.width <= rect.width * 1.3 && siblingRect.height >= 56;
            });
            return siblings.length >= 1;
        };
        const cards = [];
        for (const el of Array.from(document.querySelectorAll('div,article,li,a')).filter(isCard)) {
            if (!visible(el)) continue;
            let hasCardAncestor = false;
            for (let parent = el.parentElement, depth = 0; parent && depth < 8; parent = parent.parentElement, depth += 1) {
                if (/(^|[-_\s])(?:card|tile)(?:$|[-_\s])/i.test(String(parent.className || ''))) {
                    hasCardAncestor = true;
                    break;
                }
            }
            if (hasCardAncestor) continue;
            const r = el.getBoundingClientRect();
            const centerX = r.left + r.width / 2;
            if (payload.scope === 'main' && (centerX < body.width * 0.18 || centerX > body.width * 0.88)) continue;
            cards.push({tag: el.tagName.toLowerCase(), cls: String(el.className || '').slice(0, 120), rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}});
        }
        return {
            passed: cards.length >= payload.minimum,
            reason: cards.length >= payload.minimum ? '' : `可见卡片数量不足：期望至少 ${payload.minimum}，实际 ${cards.length}`,
            count: cards.length,
            minimum: payload.minimum,
            samples: cards.slice(0, 8),
        };
    }'''
    try:
        return await page.evaluate(js, {'minimum': int(minimum), 'scope': scope})
    except Exception as exc:
        return {'passed': False, 'reason': f'卡片数量断言执行失败: {exc}', 'minimum': minimum}


async def _assert_card_collection_absence(page, scope: str = 'main'):
    """Verify a navigated-away card listing is no longer visible."""
    js = r'''(payload) => {
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width >= 120 && r.height >= 56 && r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const body = document.body.getBoundingClientRect();
        const isListingCard = (el) => {
            const cls = String(el.className || '');
            return /(?:discovery|community|search|result)[-_\s]*card|card[-_\s]*(?:item|wrapper)/i.test(cls);
        };
        const cards = Array.from(document.querySelectorAll('div,article,li,a'))
            .filter(isListingCard)
            .filter(visible)
            .filter(el => {
                const r = el.getBoundingClientRect();
                return payload.scope !== 'main' || r.left + r.width / 2 >= body.width * 0.18;
            })
            .map(el => ({
                tag: el.tagName.toLowerCase(),
                cls: String(el.className || '').slice(0, 160),
                text: String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 180),
            }));
        return {
            passed: cards.length === 0,
            reason: cards.length ? `仍展示 ${cards.length} 个列表卡片` : '',
            count: cards.length,
            samples: cards.slice(0, 6),
        };
    }'''
    try:
        return await page.evaluate(js, {'scope': scope})
    except Exception as exc:
        return {'passed': False, 'reason': f'卡片列表消失断言执行失败: {exc}'}


async def _assert_card_fields(page, fields, scope: str = 'main', match_mode: str = 'all', minimum: int = 0):
    js = r'''(payload) => {
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width >= 120 && r.height >= 56 && r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
        const isCard = (el) => {
            const cls = String(el.className || '');
            if (/(^|[-_\s])(?:card|tile)(?:$|[-_\s])/i.test(cls)) return true;
            const text = String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            const rect = el.getBoundingClientRect();
            if (rect.width >= body.width * 0.9 || rect.height >= window.innerHeight * 0.7 || text.length < 20 || !/\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}|\d+\s*(?:分钟前|小时前|天前)|今天|昨天/.test(text)) return false;
            const siblings = Array.from(el.parentElement?.children || []).filter(candidate => {
                if (candidate === el || !visible(candidate)) return false;
                const siblingRect = candidate.getBoundingClientRect();
                return siblingRect.width >= rect.width * 0.7 && siblingRect.width <= rect.width * 1.3 && siblingRect.height >= 56;
            });
            return siblings.length >= 1;
        };
        const body = document.body.getBoundingClientRect();
        const cards = Array.from(document.querySelectorAll('div,article,li,a')).filter(isCard).filter(visible).filter(el => {
            for (let parent = el.parentElement, depth = 0; parent && depth < 8; parent = parent.parentElement, depth += 1) if (/(^|[-_\s])(?:card|tile)(?:$|[-_\s])/i.test(String(parent.className || ''))) return false;
            const r = el.getBoundingClientRect();
            if (r.width >= body.width * 0.9 && r.height >= window.innerHeight * 0.7) return false;
            return payload.scope !== 'main' || r.left + r.width / 2 >= body.width * 0.18;
        }).filter(el => {
            // A page can contain article/ranking/form cards alongside the
            // requested community list.  For a community-field assertion,
            // admit only cards that identify themselves as community cards or
            // carry a community-like identity signal.  Once admitted, every
            // candidate is still checked strictly, so this never masks a
            // malformed community card.
            if (!payload.fields.includes('id') && !payload.fields.includes('online')) return true;
            const cls = String(el.className || '');
            const text = norm(el.innerText || el.textContent || '');
            return /(?:community|discovery|game|team)[-_\s]*card|card[-_\s]*(?:community|game|team)/i.test(cls)
                || /(?<!\d)\d{5,}(?!\d)/.test(text)
                || /在线\s*\d+|\d+\s*在线/.test(text);
        });
        const inspect = cards.map(card => {
            const text = norm(card.innerText || card.textContent || '');
            const rawNumbers = [...text.matchAll(/(?<!\d)(\d{5,})(?!\d)/g)].map(m => m[1]);
            const eightDigitIds = rawNumbers.filter(value => value.length === 8);
            const idMatches = eightDigitIds.length > 1 ? [eightDigitIds[1]] : (eightDigitIds.length ? eightDigitIds : rawNumbers.slice(0, 1));
            const online = /在线\s*\d+|\d+\s*在线/.test(text);
            const avatar = Array.from(card.querySelectorAll('img,[role="img"]')).some(el => { const r = el.getBoundingClientRect(); return r.width > 12 && r.height > 12; });
            // Community names are allowed to be numeric (for example "666333").
            // Remove only the card's identified community ID, not every long
            // numeric token, otherwise a legitimate numeric name is misread as
            // a missing name.
            const nameText = norm(text.replace(idMatches[0] || '', '').replace(/在线\s*\d+|\d+\s*在线/g, '').replace(/LV\d+/ig, ''));
            const values = {avatar, name: nameText.length >= 2, id: idMatches.length === 1, online};
            const missing = payload.fields.filter(field => !values[field]);
            return {text: text.slice(0, 240), values, missing, ids: idMatches, cls: String(card.className || '').slice(0, 120)};
        });
        const invalid = inspect.filter(card => card.missing.length > 0);
        const requiredMinimum = payload.minimum || payload.fields.length;
        const matching = inspect.filter(card => payload.fields.filter(field => card.values[field]).length >= requiredMinimum);
        const passed = payload.matchMode === 'any'
            ? matching.length > 0
            : (inspect.length > 0 && invalid.length === 0);
        return {
            passed,
            reason: inspect.length === 0 ? '未找到可验证的卡片容器' : (payload.matchMode === 'any' ? (matching.length ? '' : `未找到满足至少 ${requiredMinimum} 个字段的卡片`) : (invalid.length ? `存在 ${invalid.length} 张卡片缺少字段` : '')),
            total: inspect.length,
            matching: matching.slice(0, 6),
            invalid: invalid.slice(0, 6),
            samples: inspect.slice(0, 6),
        };
    }'''
    try:
        return await page.evaluate(js, {'fields': list(fields or []), 'scope': scope, 'matchMode': match_mode, 'minimum': int(minimum or 0)})
    except Exception as exc:
        return {'passed': False, 'reason': f'卡片字段断言执行失败: {exc}'}


async def _assert_card_field_association(page, field: str, scope: str = 'main', optional: bool = False):
    js = r'''(payload) => {
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width >= 120 && r.height >= 56 && r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
        const isCard = (el) => {
            const cls = String(el.className || '');
            return /(^|[-_\s])(?:card|tile)(?:$|[-_\s])/i.test(cls);
        };
        const body = document.body.getBoundingClientRect();
        const cards = Array.from(document.querySelectorAll('div,article,li,a')).filter(isCard).filter(visible).filter(el => {
            for (let parent = el.parentElement, depth = 0; parent && depth < 8; parent = parent.parentElement, depth += 1) if (/(^|[-_\s])(?:card|tile)(?:$|[-_\s])/i.test(String(parent.className || ''))) return false;
            const r = el.getBoundingClientRect();
            if (r.width >= body.width * 0.9 && r.height >= window.innerHeight * 0.7) return false;
            return payload.scope !== 'main' || r.left + r.width / 2 >= body.width * 0.18;
        });
        const issues = [];
        const evidence = cards.map(card => {
            const text = norm(card.innerText || card.textContent || '');
            const rawNumbers = [...text.matchAll(/(?<!\d)(\d{5,})(?!\d)/g)].map(m => m[1]);
            const eightDigitIds = rawNumbers.filter(value => value.length === 8);
            const ids = [...new Set(eightDigitIds.length > 1 ? [eightDigitIds[1]] : (eightDigitIds.length ? eightDigitIds : rawNumbers.slice(0, 1)))];
            const intro = norm(text
                .replace(/(?<!\d)\d{5,}(?!\d)/g, '')
                .replace(/在线\s*\d+|\d+\s*在线/g, '')
                .replace(/LV\d+/ig, ''));
            if (ids.length > 1) issues.push({reason: '同一张卡片包含多个社区 ID', text: text.slice(0, 240), ids});
            return {ids, hasIntro: intro.length >= 16, text: text.slice(0, 240)};
        });
        return {
            passed: cards.length > 0 && issues.length === 0,
            reason: cards.length === 0 ? '未找到可验证的卡片容器' : (issues[0]?.reason || ''),
            total: cards.length,
            introCardCount: evidence.filter(item => item.hasIntro).length,
            issues: issues.slice(0, 6),
            samples: evidence.slice(0, 6),
        };
    }'''
    try:
        return await page.evaluate(js, {'field': field, 'scope': scope, 'optional': optional})
    except Exception as exc:
        return {'passed': False, 'reason': f'卡片字段关联断言执行失败: {exc}'}


async def _assert_card_metadata(page, fields, minimum: int, scope: str = 'main'):
    js = r'''(payload) => {
        const visible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width >= 120 && r.height >= 56 && r.bottom > 0 && r.top < innerHeight && s.display !== 'none' && s.visibility !== 'hidden';
        };
        const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
        const isCard = el => {
            const cls = String(el.className || '');
            if (/(^|[-_\s])(?:card|tile)(?:$|[-_\s])/i.test(cls)) return true;
            const text = String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            const rect = el.getBoundingClientRect();
            return rect.width >= 360 && rect.height >= 80 && text.length >= 20 && /\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}|\d+\s*(?:分钟前|小时前|天前)|今天|昨天/.test(text);
        };
        const bodyWidth = document.body.getBoundingClientRect().width;
        const cards = Array.from(document.querySelectorAll('div,article,li,a')).filter(isCard).filter(visible).filter(el => {
            for (let parent = el.parentElement, depth = 0; parent && depth < 8; parent = parent.parentElement, depth += 1) if (/(^|[-_\s])(?:card|tile)(?:$|[-_\s])/i.test(String(parent.className || ''))) return false;
            const r = el.getBoundingClientRect(); return payload.scope !== 'main' || r.left + r.width / 2 >= bodyWidth * .18;
        });
        const inspect = cards.map(card => {
            const text = norm(card.innerText || card.textContent);
            const values = {
                time: /\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d+\s*(分钟前|小时前|天前)|今天|昨天/.test(text),
                author: /作者|来源|发布者|官方|编辑/.test(text),
                // Short announcements are valid content too. Once a dated
                // article has a meaningful title/body payload, do not require
                // an arbitrary 32-character minimum to call it a summary.
                summary: text.length >= 16,
                tag: Array.from(card.querySelectorAll('span,a,button')).some(el => visible(el) && /tag|label|标签/i.test(`${el.className || ''} ${el.getAttribute('data-tag') || ''}`)),
                comments: /评论\s*\d+|\d+\s*评论/.test(text),
            };
            const found = payload.fields.filter(field => values[field]);
            return {text: text.slice(0, 220), found, values};
        });
        const invalid = inspect.filter(item => item.found.length < payload.minimum);
        return {passed: inspect.length > 0 && invalid.length === 0, reason: !inspect.length ? '未找到可验证的卡片容器' : (invalid.length ? `存在 ${invalid.length} 张卡片的元数据不足 ${payload.minimum} 类` : ''), total: inspect.length, invalid: invalid.slice(0, 6), samples: inspect.slice(0, 6)};
    }'''
    try:
        return await page.evaluate(js, {'fields': list(fields or []), 'minimum': int(minimum), 'scope': scope})
    except Exception as exc:
        return {'passed': False, 'reason': f'卡片元数据断言执行失败: {exc}'}


async def _evaluate_collection_predicate(page, predicate):
    """Find repeated, visible item containers without depending on page CSS.

    A collection is inferred from repeated sibling blocks.  It deliberately
    works on rendered geometry and text, so the same assertion plan supports
    cards, rows and voice-room entries across independently-built pages.
    """
    js = r'''(payload) => {
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 120 && r.height >= 28 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
        };
        const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
        const body = document.body.getBoundingClientRect();
        const elements = Array.from(document.querySelectorAll('div,li,article,section,a')).filter(visible);
        const hasHint = el => (payload.hints || []).some(hint => String(el.className || '').toLowerCase().includes(String(hint).toLowerCase()));
        const hinted = elements.filter(hasHint);
        const candidates = (hinted.length >= 2 ? hinted : elements).filter(el => {
            const r = el.getBoundingClientRect();
            const center = r.left + r.width / 2;
            return payload.scope !== 'main' || center >= body.width * .18;
        });
        const groups = new Map();
        for (const el of candidates) {
            const parent = el.parentElement;
            if (!parent) continue;
            const text = norm(el.innerText || el.textContent);
            if (text.length < 2 || text.length > 500) continue;
            const r = el.getBoundingClientRect();
            const siblings = Array.from(parent.children).filter(child => child.matches?.('div,li,article,section,a') && visible(child) && (!(payload.hints || []).length || hasHint(child)));
            if (siblings.length < 2) continue;
            const similarlySized = siblings.filter(child => {
                const cr = child.getBoundingClientRect();
                return cr.width >= r.width * .55 && cr.width <= r.width * 1.6 && cr.height >= 24;
            });
            if (similarlySized.length < 2) continue;
            groups.set(parent, similarlySized);
        }
        const ranked = [...groups.entries()].map(([parent, items]) => ({
            parent,
            items: [...new Set(items)].filter(item => !items.some(other => other !== item && item.contains(other))),
        })).filter(group => group.items.length >= 2).sort((a, b) => b.items.length - a.items.length);
        const group = ranked[0];
        if (!group) return {passed: false, reason: '未识别到可验证的重复条目容器', items: []};
        const items = group.items.map(item => {
            const r = item.getBoundingClientRect();
            return {el: item, text: norm(item.innerText || item.textContent), rect: {x: r.x, y: r.y, width: r.width, height: r.height}};
        });
        if (payload.kind === 'collection_count') {
            return {passed: items.length >= payload.minimum, reason: items.length >= payload.minimum ? '' : `条目数量不足：期望至少 ${payload.minimum}，实际 ${items.length}`, count: items.length, minimum: payload.minimum, samples: items.slice(0, 6).map(item => ({text: item.text.slice(0, 180), rect: item.rect}))};
        }
        const inspect = items.map(item => {
            const text = item.text;
            const roomLike = (payload.hints || []).some(hint => /room/i.test(String(hint)));
            const numberTokens = text.match(/(?:房间|ID|编号)\s*[:：#]?\s*\d+|\b\d{3,}\b/gi) || [];
            const capacityTokens = text.match(/\d+\s*(?:\/\s*\d+)?\s*(?:人|在线|成员)|(?:在线|人数|容量)\s*[:：]?\s*\d+/g) || [];
            if (roomLike && /^\s*\d+\b/.test(text)) numberTokens.push(text.match(/^\s*\d+\b/)[0]);
            if (roomLike && /\b\d+\s+\d{1,3}\b/.test(text)) capacityTokens.push(text.match(/\b\d+\s+\d{1,3}\b/)[0]);
            const withoutNumbers = text.replace(/(?:房间|ID|编号)\s*[:：#]?\s*\d+|\b\d{1,}\b|\d+\s*(?:\/\s*\d+)?\s*(?:人|在线|成员)/gi, '').replace(/[|/｜]+/g, ' ').trim();
            const isInteractiveRoom = roomLike && /\u4e92\u52a8\s*\u8bed\u97f3/.test(text);
            const interactionControls = Array.from(item.el.querySelectorAll('svg,button,[role="button"],[class*="icon" i],[class*="link" i]')).filter(el => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            });
            const hasInteractionEntry = isInteractiveRoom && interactionControls.some(el => {
                const meta = `${el.className || ''} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''} ${el.getAttribute('data-icon') || ''}`;
                return /link|chain|connect|interaction|join|nicon|icon/i.test(meta) || el.tagName === 'SVG';
            });
            const values = {
                number: numberTokens.length > 0,
                capacity: capacityTokens.length > 0 || hasInteractionEntry,
                name: withoutNumbers.length >= 2,
                description: withoutNumbers.length >= 12,
            };
            const missing = (payload.fields || []).filter(field => !values[field]);
            return {
                text: text.slice(0, 240), values, missing, rect: item.rect,
                roomType: isInteractiveRoom ? 'interactive' : 'standard',
                availabilitySource: capacityTokens.length > 0 ? 'capacity' : (hasInteractionEntry ? 'interaction_entry' : 'missing'),
            };
        });
        const invalid = inspect.filter(item => item.missing.length);
        return {passed: inspect.length > 0 && invalid.length === 0, reason: !inspect.length ? '未识别到可验证条目' : (invalid.length ? `存在 ${invalid.length} 个条目缺少字段` : ''), total: inspect.length, invalid: invalid.slice(0, 6), samples: inspect.slice(0, 6)};
    }'''
    try:
        return await page.evaluate(js, predicate)
    except Exception as exc:
        return {'passed': False, 'reason': f'集合断言执行失败: {exc}'}


async def _assert_layout_no_overlap(page, predicate):
    js = r'''(payload) => {
        const visible = el => { const r = el?.getBoundingClientRect(); const s = el && getComputedStyle(el); return !!r && !!s && r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && s.display !== 'none' && s.visibility !== 'hidden'; };
        const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
        const intersectionArea = (a, b) => {
            const width = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
            const height = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
            return width * height;
        };
        const hasHint = el => (payload.hints || []).some(hint => String(el.className || '').toLowerCase().includes(String(hint).toLowerCase()));
        const allCandidates = Array.from(document.querySelectorAll('div,li,article,section,a')).filter(visible);
        const hinted = allCandidates.filter(hasHint);
        const leaves = (hinted.length >= 2 ? hinted : allCandidates).filter(el => {
            const children = Array.from(el.children).filter(visible);
            return children.length >= 2 && children.length <= 20 && norm(el.innerText).length >= 4 && norm(el.innerText).length <= 500;
        });
        const issues = [];
        const evidence = [];
        for (const item of leaves) {
            const itemRect = item.getBoundingClientRect();
            const textNodes = Array.from(item.querySelectorAll('span,p,h1,h2,h3,h4,a,div')).filter(visible).filter(el => {
                const text = norm(el.innerText || el.textContent);
                const r = el.getBoundingClientRect();
                return text.length >= 2 && text.length <= 100 && r.width > 8 && r.height > 8 && !Array.from(el.children).some(child => norm(child.innerText || child.textContent) === text);
            });
            const titles = textNodes.filter(el => !/\d|在线|人|容量|房间|ID|编号/i.test(norm(el.innerText || el.textContent)));
            const protectedNodes = textNodes.filter(el => /\d|在线|人|容量|房间|ID|编号/i.test(norm(el.innerText || el.textContent))).concat(Array.from(item.querySelectorAll('button,[role="button"],svg')).filter(visible));
            if (!titles.length || !protectedNodes.length) continue;
            const title = titles.sort((a, b) => norm(b.innerText).length - norm(a.innerText).length)[0];
            const titleRect = title.getBoundingClientRect();
            const collisions = protectedNodes.map(node => ({node, rect: node.getBoundingClientRect()})).filter(entry => {
                // Parent/child boxes naturally overlap even when the rendered
                // title and counter are laid out correctly.  Only compare
                // independent sibling regions and require a visible overlap.
                if (entry.node === title || entry.node.contains(title) || title.contains(entry.node)) return false;
                return intersectionArea(titleRect, entry.rect) > 4;
            });
            const sample = {text: norm(item.innerText).slice(0, 180), title: norm(title.innerText), collisions: collisions.length, rect: {x: itemRect.x, y: itemRect.y, width: itemRect.width, height: itemRect.height}};
            evidence.push(sample);
            if (collisions.length) issues.push(sample);
        }
        return {passed: evidence.length > 0 && issues.length === 0, reason: !evidence.length ? '未识别到可验证的名称与人数/操作区域' : (issues.length ? `检测到 ${issues.length} 个条目的文本与人数或操作区域重叠` : ''), checked: evidence.length, issues: issues.slice(0, 6), samples: evidence.slice(0, 6)};
    }'''
    try:
        return await page.evaluate(js, predicate)
    except Exception as exc:
        return {'passed': False, 'reason': f'布局断言执行失败: {exc}'}


async def _assert_url_contains(page, value):
    try:
        actual = str(page.url or '')
        expected = str(value or '').rstrip('/')
        passed = bool(expected) and expected in actual.rstrip('/')
        return {
            'passed': passed,
            'reason': '' if passed else f'当前地址不符合预期：期望包含 {expected}，实际为 {actual}',
            'expected': expected,
            'actual': actual,
        }
    except Exception as exc:
        return {'passed': False, 'reason': f'地址断言执行失败: {exc}'}


async def _assert_url_not_auth(page):
    try:
        actual = str(page.url or '')
        passed = re.search(r'/(?:login|signin|auth)(?:[/?#]|$)', actual, re.I) is None
        return {
            'passed': passed,
            'reason': '' if passed else f'当前地址仍位于登录流程：{actual}',
            'actual': actual,
        }
    except Exception as exc:
        return {'passed': False, 'reason': f'登录地址排除断言执行失败: {exc}'}


async def _assert_page_title(page, value):
    expected = str(value or '').strip()
    try:
        actual = await page.title()
        passed = bool(expected) and expected in str(actual or '')
        return {
            'passed': passed,
            'reason': '' if passed else f'页面标题不符合预期：期望包含 {expected}，实际为 {actual}',
            'expected': expected,
            'actual': actual,
        }
    except Exception as exc:
        return {'passed': False, 'reason': f'页面标题断言执行失败: {exc}'}


async def _assert_text_absence(page, expected_texts, scope='all'):
    expected = [str(text).strip() for text in (expected_texts or []) if str(text).strip()]
    if not expected:
        return {'passed': False, 'reason': '缺少待确认不存在的明确文本'}
    js = r'''(payload) => {
        const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
        const lower = value => norm(value).toLowerCase();
        const visible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
        };
        const nodes = Array.from(document.querySelectorAll('body *')).filter(visible).map(el => ({
            text: norm(el.innerText || el.textContent),
            tag: el.tagName.toLowerCase(),
            cls: String(el.className || '').slice(0, 120),
        })).filter(item => item.text && item.text.length <= 300);
        const matches = payload.expected.map(target => ({
            target,
            matches: nodes.filter(item => lower(item.text).includes(lower(target))).slice(0, 4),
        })).filter(item => item.matches.length);
        return {
            passed: matches.length === 0,
            reason: matches.length ? `页面仍可见不应出现的文本: ${matches.map(item => item.target).join(', ')}` : '',
            matches,
        };
    }'''
    try:
        return await page.evaluate(js, {'expected': expected, 'scope': scope})
    except Exception as exc:
        return {'passed': False, 'reason': f'文本不存在断言执行失败: {exc}'}


async def _assert_any_text_presence(page, expected_texts):
    expected = [str(text).strip() for text in (expected_texts or []) if str(text).strip()]
    try:
        body_text = await page.locator('body').inner_text()
        matched = [text for text in expected if text in body_text]
        return {
            'passed': bool(matched),
            'reason': '' if matched else f'未找到任一候选文本: {expected}',
            'matched': matched,
            'expected': expected,
        }
    except Exception as exc:
        return {'passed': False, 'reason': f'候选文本断言执行失败: {exc}'}


async def _evaluate_ui_state_predicate(page, predicate, runtime_evidence=None):
    js = r'''(predicate) => {
        const visible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
        };
        const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
        const controls = Array.from(document.querySelectorAll('input,textarea')).filter(visible);
        const fieldControls = field => controls.filter(el => {
            const meta = norm(`${el.placeholder || ''} ${el.name || ''} ${el.id || ''} ${el.type || ''} ${el.autocomplete || ''} ${el.getAttribute('aria-label') || ''}`).toLowerCase();
            if (field === 'phone') return /手机号|手机号码|账号|mobile|phone|tel|account/.test(meta);
            if (field === 'verification_code') return /验证码|校验码|captcha|verify|verification|sms|code/.test(meta);
            if (field === 'password') return el.type === 'password' || /密码|password/.test(meta);
            if (field === 'game_id') return /游戏\s*id|pubg\s*id|game\s*id/.test(meta);
            return false;
        });
        if (predicate.kind === 'login_prompt_visible') {
            const authUrl = /\/(?:login|signin|auth)(?:[/?#]|$)/i.test(location.href);
            const loginFields = controls.filter(el => {
                const meta = norm(`${el.placeholder || ''} ${el.name || ''} ${el.id || ''} ${el.type || ''} ${el.autocomplete || ''}`).toLowerCase();
                return /手机号|手机号码|验证码|密码|mobile|phone|captcha|password|sms.?code/.test(meta);
            });
            const dialogs = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .el-dialog, [class*="modal" i], [class*="dialog" i], [class*="popup" i]')).filter(visible).filter(el => /登录|登陆|手机号|验证码|login|sign in/i.test(norm(el.innerText || el.textContent)));
            const entries = Array.from(document.querySelectorAll('button,a,[role="button"],[role="link"]')).filter(visible).filter(el => /^(登录|登陆|登录\/注册|注册\/登录|login|sign in)$/i.test(norm(el.innerText || el.textContent || el.getAttribute('aria-label'))));
            const passed = loginFields.length > 0 || dialogs.length > 0 || entries.length > 0 || (predicate.allow_auth_url && authUrl);
            return {passed, reason: passed ? '' : '未检测到登录入口、登录表单、登录弹窗或登录流程地址', authUrl, loginFieldCount: loginFields.length, dialogCount: dialogs.length, entryCount: entries.length};
        }
        if (predicate.kind === 'input_value' || predicate.kind === 'input_length') {
            const matched = fieldControls(predicate.field).map(el => ({
                value: String(el.value || ''),
                placeholder: el.placeholder || '',
                name: el.name || '',
                type: el.type || '',
            }));
            const passed = predicate.kind === 'input_value'
                ? matched.some(item => item.value === String(predicate.value || ''))
                : matched.some(item => item.value.length === Number(predicate.length || 0));
            const label = predicate.field === 'verification_code' ? '验证码'
                : (predicate.field === 'phone' ? '手机号' : (predicate.field === 'game_id' ? '游戏 ID' : '密码'));
            return {passed, reason: passed ? '' : `未找到符合预期的${label}输入值`, controls: matched};
        }
        if (predicate.kind === 'search_empty_state') {
            const label = norm(predicate.section_label || '');
            const containers = Array.from(document.querySelectorAll('section,div,aside')).filter(visible)
                .filter(el => {
                    const text = norm(el.innerText || el.textContent || '');
                    return text.includes(label) && /共找到\s*0\s*个结果|无搜索内容|没有找到你想要搜索的内容|暂无搜索结果/.test(text);
                })
                .map(el => ({text: norm(el.innerText || el.textContent || '').slice(0, 360), cls: String(el.className || '').slice(0, 160)}));
            return {
                passed: containers.length > 0,
                reason: containers.length ? '' : `搜索区域「${label}」未展示 0 条结果空状态`,
                samples: containers.slice(0, 5),
            };
        }
        if (predicate.kind === 'control_busy') {
            const target = norm(predicate.target || '');
            const candidates = Array.from(document.querySelectorAll('button,[role="button"],input[type="submit"]')).filter(visible).filter(el => {
                const meta = norm(`${el.innerText || el.textContent || ''} ${el.value || ''} ${el.getAttribute('aria-label') || ''}`);
                return !target || meta.includes(target);
            });
            const inspected = candidates.map(el => {
                const meta = norm(`${el.innerText || el.textContent || ''} ${el.className || ''} ${el.getAttribute('aria-busy') || ''}`);
                const busy = !!el.disabled || el.getAttribute('aria-disabled') === 'true' || el.getAttribute('aria-busy') === 'true' || /loading|处理中|提交中|登录中|加载中|is-loading/i.test(meta) || !!el.querySelector('[class*="loading" i],[class*="spinner" i],.el-loading-spinner');
                return {text: norm(el.innerText || el.textContent || el.value || ''), disabled: !!el.disabled, ariaBusy: el.getAttribute('aria-busy'), cls: String(el.className || '').slice(0, 120), busy};
            });
            const passed = inspected.some(item => item.busy);
            return {passed, reason: passed ? '' : `未检测到${target || '目标'}按钮的处理中或防重复提交状态`, controls: inspected};
        }
        if (predicate.kind === 'modal_absent') {
            const target = norm(predicate.target || '');
            const candidates = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .el-dialog, [class*="modal" i], [class*="dialog" i], [class*="popup" i], [class*="drawer" i]')).filter(visible).map(el => norm(el.innerText || el.textContent)).filter(text => !target || text.includes(target));
            return {passed: candidates.length === 0, reason: candidates.length ? `仍检测到不应出现的弹窗: ${target}` : '', matches: candidates.slice(0, 4)};
        }
        if (predicate.kind === 'protected_result_absent') {
            const terms = (predicate.terms || []).map(norm).filter(Boolean);
            const regions = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], [class*="result" i], [class*="record" i], [class*="detail" i], table')).filter(visible).map(el => norm(el.innerText || el.textContent)).filter(text => text.length >= 2 && text.length <= 2000);
            const matches = regions.filter(text => terms.length ? terms.some(term => text.includes(term)) : /查询结果|私有数据|玩家战绩/.test(text));
            return {passed: matches.length === 0, reason: matches.length ? '未登录状态下仍展示了受保护查询结果' : '', matches: matches.slice(0, 4)};
        }
        if (predicate.kind === 'page_feature') {
            const text = norm(document.body && document.body.innerText || '');
            const terms = (predicate.terms || []).map(norm).filter(Boolean);
            const missing = terms.filter(term => !text.includes(term));
            return {passed: terms.length > 0 && missing.length === 0, reason: missing.length ? `页面未展示${predicate.feature || '目标功能'}: ${missing.join(', ')}` : '', missing, bodyText: text.slice(0, 500)};
        }
        if (predicate.kind === 'control_available') {
            const target = norm(predicate.target || '');
            const candidates = Array.from(document.querySelectorAll('input,textarea,button,[role="button"]')).filter(visible).filter(el => {
                const meta = norm(`${el.innerText || el.textContent || ''} ${el.placeholder || ''} ${el.getAttribute('aria-label') || ''}`);
                return meta.includes(target);
            }).map(el => ({tag: el.tagName.toLowerCase(), text: norm(el.innerText || el.textContent || ''), placeholder: el.placeholder || '', disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true'}));
            const passed = candidates.some(item => !item.disabled);
            return {passed, reason: passed ? '' : `未检测到可用的${target}控件`, controls: candidates.slice(0, 8)};
        }
        if (predicate.kind === 'modal_count') {
            const target = norm(predicate.target || '');
            const roots = Array.from(document.querySelectorAll(
                '[role="dialog"], [aria-modal="true"], .el-dialog, [class*="modal" i], [class*="dialog" i], [class*="popup" i], [class*="drawer" i]'
            )).filter(visible).filter(el => !target || norm(el.innerText || el.textContent).includes(target));
            const topLevel = roots.filter(root => !roots.some(other => other !== root && other.contains(root)));
            const expectedCount = Number(predicate.expected_count || 0);
            return {
                passed: topLevel.length === expectedCount,
                reason: topLevel.length === expectedCount ? '' : `期望存在 ${expectedCount} 个${target || '目标'}弹窗，实际 ${topLevel.length} 个`,
                count: topLevel.length,
                expectedCount,
                samples: topLevel.slice(0, 4).map(el => norm(el.innerText || el.textContent).slice(0, 180)),
            };
        }
        if (predicate.kind === 'filter_result_consistency') {
            const expected = (predicate.expected_filters || []).map(norm).filter(Boolean);
            const controlSelector = 'button,[role="button"],[role="tab"],label,input,a,div,span';
            const isSelected = el => {
                if (!el) return false;
                const cls = String(el.className || '');
                return !!el.checked || el.getAttribute('aria-selected') === 'true'
                    || el.getAttribute('aria-pressed') === 'true' || el.getAttribute('aria-checked') === 'true'
                    || /(^|[\s_-])(active|selected|current|checked|is-active|is-selected)([\s_-]|$)/i.test(cls);
            };
            const selectedTargets = expected.filter(target => Array.from(document.querySelectorAll(controlSelector)).some(el => {
                if (!visible(el) || norm(el.innerText || el.textContent || el.getAttribute('aria-label')) !== target) return false;
                return isSelected(el) || isSelected(el.closest('button,[role="button"],[role="tab"],label,[class*="tab" i],[class*="filter" i]'));
            }));
            const resultRoot = Array.from(document.querySelectorAll(
                '[role="dialog"], [aria-modal="true"], [class*="result" i], [class*="record" i], main'
            )).filter(visible).find(el => /查询结果|战绩/.test(norm(el.innerText || el.textContent))) || document.body;
            const cardSelector = '[data-match-id],[data-record-id],[data-result-id],[data-id],a[href*="match" i],tr,[class*="record-card" i],[class*="result-card" i],[class*="match-card" i]';
            const identityOf = el => {
                for (const attr of ['data-match-id', 'data-record-id', 'data-result-id', 'data-id']) {
                    if (el.getAttribute(attr)) return `${attr}:${el.getAttribute(attr)}`;
                }
                if (el.tagName === 'A' && el.getAttribute('href')) return `href:${el.getAttribute('href')}`;
                return norm(el.innerText || el.textContent).slice(0, 260);
            };
            const rawCards = Array.from(resultRoot.querySelectorAll(cardSelector)).filter(visible).filter(el => {
                const text = norm(el.innerText || el.textContent);
                return text.length >= 2 && text.length <= 1200;
            });
            const cards = rawCards.filter(el => !rawCards.some(other => other !== el && el.contains(other) && identityOf(other) === identityOf(el)));
            const identities = cards.map(identityOf).filter(Boolean);
            const duplicates = identities.filter((value, index) => identities.indexOf(value) !== index);
            const filtersPassed = selectedTargets.length === expected.length;
            const uniquePassed = !predicate.require_unique_cards || duplicates.length === 0;
            const passed = filtersPassed && uniquePassed;
            return {
                passed,
                reason: !filtersPassed
                    ? `最终筛选未全部选中: ${expected.filter(value => !selectedTargets.includes(value)).join('、')}`
                    : (!uniquePassed ? `结果列表存在重复卡片: ${Array.from(new Set(duplicates)).slice(0, 3).join('、')}` : ''),
                expectedFilters: expected,
                selectedTargets,
                cardCount: cards.length,
                duplicateIdentities: Array.from(new Set(duplicates)).slice(0, 5),
            };
        }
        if (predicate.kind === 'modal_visible') {
            const candidates = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .el-dialog, [class*="modal" i], [class*="dialog" i], [class*="popup" i]')).filter(visible);
            return {passed: candidates.length > 0, reason: candidates.length ? '' : '未检测到处于可见状态的弹窗', count: candidates.length, samples: candidates.slice(0, 4).map(el => norm(el.innerText).slice(0, 180))};
        }
        if (predicate.kind === 'input_counter' || predicate.kind === 'input_max_length') {
            const maximum = Number(predicate.maximum || 0);
            const current = Number(predicate.current || maximum);
            const matched = controls.map(el => {
                const text = `${el.value || ''} ${el.maxLength || ''} ${el.parentElement?.innerText || ''}`;
                const hasCounter = new RegExp(`${current}\\s*\\/\\s*${maximum}`).test(text);
                const maxLength = Number(el.maxLength || 0);
                return {tag: el.tagName.toLowerCase(), valueLength: String(el.value || '').length, maxLength, hasCounter, placeholder: el.placeholder || ''};
            });
            const passed = predicate.kind === 'input_counter'
                ? matched.some(item => item.hasCounter && item.valueLength >= current)
                : matched.some(item => item.maxLength === maximum || item.valueLength <= maximum);
            return {passed, reason: passed ? '' : (predicate.kind === 'input_counter' ? `未找到 ${current}/${maximum} 的输入计数器` : `未检测到 ${maximum} 字符输入限制`), controls: matched.slice(0, 8)};
        }
        if (predicate.kind === 'filter_reset_state') {
            const filterControls = controls.filter(el => /搜索|筛选|filter|search/i.test(`${el.placeholder || ''} ${el.getAttribute('aria-label') || ''} ${el.className || ''}`));
            const retained = filterControls.filter(el => norm(el.value));
            const visibleRows = Array.from(document.querySelectorAll('li,article,[class*="item" i],[class*="row" i],[class*="card" i]')).filter(visible).filter(el => norm(el.innerText).length >= 2);
            const emptyState = /暂无|空状态|没有.*数据|无结果/.test(norm(document.body.innerText));
            const passed = retained.length === 0 && (visibleRows.length > 0 || emptyState);
            return {passed, reason: retained.length ? '筛选输入框仍保留关键词' : (!(visibleRows.length || emptyState) ? '筛选复位后未检测到列表或空状态' : ''), retained: retained.map(el => ({value: el.value, placeholder: el.placeholder || ''})), visibleRows: visibleRows.length, emptyState};
        }
        if (predicate.kind === 'empty_state') {
            const bodyRect = document.body.getBoundingClientRect();
            const markers = /暂无|空状态|没有(?:相关)?数据|无结果|未找到/;
            const candidates = Array.from(document.querySelectorAll('main,[role="main"],section,article,div,p,span'))
                .filter(visible)
                .map(el => {
                    const rect = el.getBoundingClientRect();
                    return {el, rect, text: norm(el.innerText || el.textContent)};
                })
                .filter(item => item.text.length >= 2 && item.text.length <= 160 && markers.test(item.text))
                .filter(item => predicate.scope !== 'main' || item.rect.left + item.rect.width / 2 >= bodyRect.width * 0.18)
                .filter(item => !Array.from(item.el.children).some(child => norm(child.innerText || child.textContent) === item.text))
                .sort((a, b) => (a.rect.width * a.rect.height) - (b.rect.width * b.rect.height));
            return {
                passed: candidates.length > 0,
                reason: candidates.length ? '' : '未检测到当前区域的空状态提示',
                samples: candidates.slice(0, 5).map(item => ({text: item.text, cls: String(item.el.className || '').slice(0, 120), rect: {x: Math.round(item.rect.x), y: Math.round(item.rect.y), w: Math.round(item.rect.width), h: Math.round(item.rect.height)}})),
            };
        }
        if (predicate.kind === 'form_validation_error') {
            const hasError = root => {
                if (!root) return false;
                const text = norm(root.innerText || root.textContent);
                const cls = String(root.className || '');
                return /必填|不能为空|请选择|请填写|校验|错误/.test(text) || /error|invalid|danger|validate/i.test(cls) || !!root.querySelector('[aria-invalid="true"], .is-error, [class*="error" i], [class*="invalid" i]');
            };
            const allElements = root => {
                const nodes = [];
                const visit = current => {
                    for (const el of current.querySelectorAll('*')) {
                        nodes.push(el);
                        if (el.shadowRoot) visit(el.shadowRoot);
                    }
                };
                visit(root);
                return nodes;
            };
            const feedbackNodes = allElements(document).filter(el => el.matches?.('[role="alert"],.toast,.message,.notification,[class*="toast" i],[class*="message" i],[class*="notice" i]')).filter(visible);
            const transientNodes = allElements(document).filter(el => {
                if (!visible(el)) return false;
                const text = norm(el.innerText || el.textContent);
                if (text.length < 2 || text.length > 80) return false;
                if (Array.from(el.children).some(child => norm(child.innerText || child.textContent) === text)) return false;
                const rect = el.getBoundingClientRect();
                let positioned = false;
                for (let parent = el, depth = 0; parent && depth < 5; parent = parent.parentElement, depth += 1) {
                    if (['fixed', 'absolute', 'sticky'].includes(getComputedStyle(parent).position)) { positioned = true; break; }
                }
                return positioned && rect.top < innerHeight * 0.5;
            });
            const feedback = [...new Set([...feedbackNodes, ...transientNodes].map(el => norm(el.innerText || el.textContent)).filter(Boolean))];
            const relevantFeedback = feedback.filter(text => /发布成功|发布完成|必填|不能为空|请.*(?:完善|选择|填写|输入)|校验|错误/.test(text));
            const hasValidationFeedback = relevantFeedback.some(text => /必填|不能为空|请.*(?:完善|选择|填写|输入)|校验|错误/.test(text));
            const fields = (predicate.fields || []).map(field => {
                const nodes = Array.from(document.querySelectorAll('label,span,p,div')).filter(visible).filter(el => norm(el.innerText || el.textContent) === field || norm(el.innerText || el.textContent).includes(field));
                const inspected = nodes.map(node => {
                    let error = false;
                    let requiredEmpty = false;
                    for (let parent = node, depth = 0; parent && parent !== document.body && depth < 3; parent = parent.parentElement, depth += 1) {
                        if (hasError(parent)) error = true;
                        const meta = `${norm(parent.innerText || parent.textContent)} ${parent.className || ''}`;
                        const controls = Array.from(parent.querySelectorAll('input,textarea,select,[role="combobox"],[aria-required="true"]')).filter(visible);
                        const hasRequiredMarker = /\*/.test(meta) || /required|is-required/i.test(meta) || controls.some(control => control.required || control.getAttribute('aria-required') === 'true');
                        const hasEmptyControl = controls.some(control => {
                            const value = norm(control.value || control.getAttribute('aria-valuetext') || control.innerText || control.textContent);
                            return !value || /请选择|请输入|请填写/.test(value);
                        });
                        const hasEmptyPrompt = /请选择|请输入|请填写|例如[：:]/.test(meta);
                        if (hasRequiredMarker && (hasEmptyControl || hasEmptyPrompt)) requiredEmpty = true;
                    }
                    return {error, requiredEmpty};
                });
                const matched = inspected.some(item => item.error || (item.requiredEmpty && hasValidationFeedback)) || (nodes.length > 0 && hasValidationFeedback);
                return {
                    field,
                    matched,
                    matchedBy: inspected.some(item => item.error) ? 'inline_error' : (inspected.some(item => item.requiredEmpty && hasValidationFeedback) ? 'required_empty_with_feedback' : (nodes.length > 0 && hasValidationFeedback ? 'global_validation_feedback' : '')),
                    samples: nodes.slice(0, 3).map(node => norm(node.parentElement?.innerText || node.innerText).slice(0, 180)),
                };
            });
            const passed = predicate.match_mode === 'any' ? fields.some(item => item.matched) : fields.every(item => item.matched);
            return {passed, reason: passed ? '' : `未检测到字段必填/错误状态: ${fields.filter(item => !item.matched).map(item => item.field).join(', ')}`, fields, feedback: relevantFeedback};
        }
        if (predicate.kind === 'entity_identity') {
            const text = norm(document.body.innerText);
            const url = location.href;
            const hasId = text.includes(predicate.id) || url.includes(predicate.id);
            const hasName = text.includes(predicate.name);
            const missingTerms = (predicate.required_terms || []).filter(term => !text.includes(term));
            const bodyRect = document.body.getBoundingClientRect();
            const sidebars = Array.from(document.querySelectorAll('aside,nav,div,section')).filter(visible).filter(el => {
                const r = el.getBoundingClientRect();
                return r.left < bodyRect.width * .38 && r.width >= 160 && r.height >= 180;
            }).sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height);
            const sidebar = sidebars[0];
            const sidebarText = norm(sidebar?.innerText || '');
            const sidebarItems = sidebar ? Array.from(sidebar.querySelectorAll('a,button,[role="button"],li,div')).filter(visible).filter(el => {
                const value = norm(el.innerText || el.textContent);
                const r = el.getBoundingClientRect();
                return value.length >= 2 && value.length <= 40 && r.height >= 16 && r.height <= 64;
            }) : [];
            const mainRegions = Array.from(document.querySelectorAll('main,[role="main"],section,article,div')).filter(visible).filter(el => {
                const r = el.getBoundingClientRect();
                return r.left >= bodyRect.width * .22 && r.width >= 380 && r.height >= 120;
            });
            const featureState = {
                sidebar_menu: !!sidebar && sidebarItems.length >= 3,
                voice_rooms: /\d+\s*\/\s*\d+/.test(sidebarText) && (sidebarText.match(/\d+\s*\/\s*\d+/g) || []).length >= 2,
                team_intro: mainRegions.some(el => {
                    const value = norm(el.innerText || el.textContent);
                    return value.includes(predicate.name) && value.length >= 120;
                }),
            };
            const missingFeatures = (predicate.required_features || []).filter(feature => !featureState[feature]);
            return {
                passed: hasId && hasName && missingTerms.length === 0 && missingFeatures.length === 0,
                reason: !hasId ? `未展示目标 ID: ${predicate.id}` : (!hasName ? `未展示目标名称: ${predicate.name}` : (missingTerms.length ? `页面缺少必要内容: ${missingTerms.join(', ')}` : (missingFeatures.length ? `页面缺少必要结构: ${missingFeatures.join(', ')}` : ''))),
                hasId, hasName, missingTerms, missingFeatures, featureState, url,
            };
        }
        return {passed: false, reason: `不支持的状态断言谓词: ${predicate.kind}`};
    }'''
    try:
        result = await page.evaluate(js, predicate)
        if result.get('passed'):
            return result
        actions = [
            item for item in ((runtime_evidence or {}).get('business_actions') or [])
            if item.get('source') != 'setup'
        ]
        field_action = {
            'phone': 'nn_fill_phone',
            'verification_code': 'nn_fill_verification_code',
            'password': 'nn_fill_password',
        }.get(predicate.get('field'))
        if predicate.get('kind') in ('input_value', 'input_length') and field_action:
            successful = [item for item in actions if item.get('name') == field_action and item.get('status') == 'completed']
            if successful:
                actual = str(successful[-1].get('input_value') or '')
                passed = actual == str(predicate.get('value') or '') if predicate.get('kind') == 'input_value' else len(actual) == int(predicate.get('length') or 0)
                if passed:
                    return {'passed': True, 'reason': '', 'source': 'business_action_evidence', 'actual': actual}
        if predicate.get('kind') == 'login_prompt_visible':
            prompt_checks = [
                item for item in ((runtime_evidence or {}).get('interactions') or [])
                if item.get('source') != 'setup' and item.get('kind') == 'post_press_login_prompt'
            ]
            if prompt_checks:
                matched = [item for item in prompt_checks if (item.get('result') or {}).get('passed')]
                if matched:
                    return {
                        'passed': True,
                        'reason': '',
                        'source': 'post_press_evidence',
                        'evidence': matched[-1].get('result'),
                    }
                return result
            observed = [item for item in actions if item.get('name') in ('nn_open_login', 'nn_fill_phone', 'nn_fill_verification_code', 'nn_fill_password') and item.get('status') == 'completed']
            if observed:
                return {'passed': True, 'reason': '', 'source': 'business_action_evidence', 'observed': [item.get('name') for item in observed]}
        if predicate.get('kind') == 'control_busy':
            submits = [item for item in actions if item.get('name') in ('nn_submit_login', 'nn_complete_login') and item.get('status') == 'completed']
            busy = [
                ((item.get('result') or {}).get('element') or {}).get('busy_state')
                for item in submits
            ]
            busy = [item for item in busy if item and item.get('observed')]
            if busy:
                return {'passed': True, 'reason': '', 'source': 'business_action_evidence', 'busy_state': busy[-1]}
        return result
    except Exception as exc:
        return {'passed': False, 'reason': f'状态断言执行失败: {exc}'}


async def _assert_faq_item_descriptions(page):
    """Verify FAQ answers within their own question rows, expanding rows when needed."""
    js = r'''async () => {
        const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
        const visible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width >= 180 && r.height >= 28 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
        };
        const isQuestion = text => /[?\uFF1F]/.test(text) || /\u4ec0\u4e48|\u5982\u4f55|\u4e3a\u4ec0\u4e48|\u662f\u5426|\u80fd\u5426|\u533a\u522b|\u95ee\u9898/.test(text);
        const isClickable = el => {
            const meta = `${el.className || ''} ${el.getAttribute('role') || ''} ${el.getAttribute('aria-expanded') || ''}`;
            return /cursor-pointer|clickable|collapse|accordion|expand|button|tab/i.test(meta) || el.tagName === 'DETAILS' || el.tagName === 'BUTTON';
        };
        const candidates = () => Array.from(document.querySelectorAll('div,li,details,button,[role="button"]'))
            .filter(visible)
            .map(el => ({el, text: norm(el.innerText || el.textContent)}))
            .filter(item => item.text.length >= 4 && item.text.length <= 800 && isQuestion(item.text) && isClickable(item.el));
        const all = candidates();
        const groups = new Map();
        for (const item of all) {
            const parent = item.el.parentElement;
            if (!parent) continue;
            const bucket = groups.get(parent) || [];
            bucket.push(item);
            groups.set(parent, bucket);
        }
        const ranked = [...groups.values()].map(items => {
            const outerRows = items.filter(item => !items.some(other => other !== item && other.el.contains(item.el)));
            const distinct = outerRows.filter((item, index) => outerRows.findIndex(other => other.text === item.text) === index);
            const score = distinct.length * 10 + distinct.filter(item => item.text.length > 80).length * 3;
            return {items: distinct, score};
        }).filter(group => group.items.length > 0).sort((a, b) => b.score - a.score);
        const group = ranked[0];
        if (!group) return {passed: false, reason: '\u672a\u8bc6\u522b\u5230\u53ef\u9a8c\u8bc1\u7684 FAQ \u95ee\u9898\u9879', samples: []};

        const answerLength = text => {
            const lines = String(text || '').split(/\n+/).map(norm).filter(Boolean);
            if (lines.length > 1) return lines.slice(1).join(' ').length;
            const firstQuestion = Math.max(text.indexOf('?'), text.indexOf('\uFF1F'));
            return firstQuestion >= 0 ? norm(text.slice(firstQuestion + 1)).length : 0;
        };
        for (const item of group.items) {
            if (answerLength(item.text) >= 12) continue;
            try { item.el.click(); } catch (_) { /* a non-expandable question remains a failure below */ }
        }
        await new Promise(resolve => setTimeout(resolve, 250));
        const inspected = group.items.map(item => {
            const text = norm(item.el.innerText || item.el.textContent);
            return {question: text.slice(0, 160), answerLength: answerLength(text), hasAnswer: answerLength(text) >= 12};
        });
        const invalid = inspected.filter(item => !item.hasAnswer);
        return {
            passed: inspected.length > 0 && invalid.length === 0,
            reason: invalid.length ? `\u5171 ${invalid.length} \u4e2a FAQ \u95ee\u9898\u672a\u5c55\u793a\u6240\u5c5e\u8bf4\u660e` : '',
            total: inspected.length,
            invalid: invalid.slice(0, 6),
            samples: inspected.slice(0, 6),
        };
    }'''
    try:
        return await page.evaluate(js)
    except Exception as exc:
        return {'passed': False, 'reason': f'FAQ \u65ad\u8a00\u6267\u884c\u5931\u8d25: {exc}'}


def _evaluate_filter_runtime_predicate(predicate, runtime_evidence=None):
    """Evaluate assertions backed by the rapid-filter business action evidence."""
    actions = (runtime_evidence or {}).get('business_actions') or []
    if predicate.get('kind') == 'battle_result_ready':
        query_action = next((item for item in reversed(actions) if item.get('name') == 'nn_query_battle_records'), None)
        detail = (((query_action or {}).get('result') or {}).get('element') or {}).get('detail') or {}
        passed = bool(query_action and query_action.get('status') == 'completed' and (
            detail.get('inlineResultVisible') or detail.get('dialogCount') == 1
        ))
        return {
            'passed': passed,
            'reason': '' if passed else '玩家查询后未加载战绩结果区域',
            'evidence': detail,
        }

    action = next((item for item in reversed(actions) if item.get('name') == 'nn_rapid_filter_switch'), None)
    detail = (((action or {}).get('result') or {}).get('element') or {}).get('detail') or {}
    if not action:
        return {'passed': False, 'reason': '未执行连续筛选动作，无法验证筛选过程', 'evidence': {}}

    if predicate.get('kind') == 'rapid_filter_switch':
        passed = (
            action.get('status') == 'completed'
            and not detail.get('missing')
            and bool(detail.get('allSelected'))
            and bool(detail.get('withinBudget'))
            and bool(detail.get('pathUnchanged'))
        )
        return {
            'passed': passed,
            'reason': '' if passed else '连续筛选未在限定时间内完成、存在未选中项或发生页面跳转',
            'evidence': detail,
        }

    loading_events = detail.get('loadingEvents') or []
    global_loaders = [item for item in loading_events if int(item.get('globalCount') or 0) > 0]
    passed = not global_loaders and not detail.get('layoutJankObserved')
    return {
        'passed': passed,
        'reason': '' if passed else ('加载状态出现全屏遮罩' if global_loaders else '筛选过程中检测到页面布局剧烈变化'),
        'evidence': {
            'loadingEvents': loading_events,
            'finalLoading': detail.get('finalLoading') or {},
            'layoutJankObserved': bool(detail.get('layoutJankObserved')),
        },
    }


async def _evaluate_assertion_plan(page, contract, assert_desc='', runtime_evidence=None):
    results = []
    for predicate in contract.get('predicates') or []:
        kind = predicate.get('kind')
        if kind in ('collection_count', 'collection_item_fields'):
            result = await _evaluate_collection_predicate(page, predicate)
        elif kind == 'faq_item_descriptions':
            result = await _assert_faq_item_descriptions(page)
        elif kind == 'layout_no_overlap':
            result = await _assert_layout_no_overlap(page, predicate)
        elif kind == 'text_group_presence':
            if predicate.get('match_mode') == 'any':
                result = await _assert_any_text_presence(page, predicate.get('expected_texts') or [])
            else:
                scope_desc = '底部' if predicate.get('scope') == 'bottom' else assert_desc
                result = await _strict_text_assertion(page, predicate.get('expected_texts') or [], scope_desc)
        elif kind == 'url_contains':
            result = await _assert_url_contains(page, predicate.get('value'))
        elif kind == 'url_not_auth':
            result = await _assert_url_not_auth(page)
        elif kind == 'page_title':
            result = await _assert_page_title(page, predicate.get('value'))
        elif kind == 'login_state':
            result = await _evaluate_login_success(page)
            if not result.get('passed'):
                actions = [
                    item for item in ((runtime_evidence or {}).get('business_actions') or [])
                    if item.get('source') != 'setup'
                    and item.get('name') == 'nn_complete_login'
                    and item.get('status') == 'completed'
                ]
                if actions:
                    evidence = ((actions[-1].get('result') or {}).get('element') or {})
                    remaining_form = evidence.get('login_form_state') or {}
                    if not remaining_form.get('passed'):
                        result = {
                            'passed': True,
                            'reason': '',
                            'source': 'business_action_evidence',
                            'login_state': evidence.get('login_state'),
                            'login_state_unverified': bool(evidence.get('login_state_unverified')),
                        }
        elif kind == 'page_health':
            result = await _evaluate_page_health(page)
            result['passed'] = bool(result.get('healthy'))
        elif kind in ('rapid_filter_switch', 'loading_scope', 'battle_result_ready'):
            result = _evaluate_filter_runtime_predicate(predicate, runtime_evidence)
        elif kind == 'text_absence':
            result = await _assert_text_absence(
                page,
                predicate.get('expected_texts') or [],
                predicate.get('scope') or 'all',
            )
        elif kind in (
            'modal_visible', 'input_counter', 'input_max_length', 'filter_reset_state',
            'empty_state', 'form_validation_error', 'entity_identity', 'login_prompt_visible',
            'input_value', 'input_length', 'search_empty_state', 'control_busy', 'modal_absent',
            'protected_result_absent', 'page_feature', 'control_available',
            'modal_count', 'filter_result_consistency',
        ):
            result = await _evaluate_ui_state_predicate(page, predicate, runtime_evidence)
        else:
            result = {'passed': False, 'reason': f'不支持的断言计划谓词: {kind}'}
        results.append({'predicate': predicate, 'result': result})
    failed = [item for item in results if not item['result'].get('passed')]
    return {
        'passed': bool(results) and not failed,
        'reason': failed[0]['result'].get('reason') if failed else '',
        'summary': f'{len(results) - len(failed)}/{len(results)} 个断言谓词通过',
        'results': results,
    }


async def _evaluate_composite_assertion(page, contract, assert_desc=''):
    results = []
    for predicate in contract.get('predicates') or []:
        kind = predicate.get('kind')
        if kind == 'selected':
            result = await _assert_selected_state(page, predicate.get('target') or '', predicate.get('scope') or 'all')
        elif kind == 'text_presence':
            scope_desc = '主内容区' if predicate.get('scope') == 'main' else str(assert_desc or '')
            result = await _strict_text_assertion(page, predicate.get('expected_texts') or [], scope_desc)
        elif kind == 'min_visible_cards':
            result = await _assert_min_visible_cards(page, predicate.get('minimum') or 1, predicate.get('scope') or 'all')
        elif kind == 'card_collection_absence':
            result = await _assert_card_collection_absence(page, predicate.get('scope') or 'main')
        elif kind == 'card_fields':
            result = await _assert_card_fields(page, predicate.get('fields') or [], predicate.get('scope') or 'main', predicate.get('match_mode') or 'all', predicate.get('minimum') or 0)
        elif kind == 'card_field_association':
            result = await _assert_card_field_association(
                page,
                predicate.get('field') or '',
                predicate.get('scope') or 'main',
                bool(predicate.get('optional')),
            )
        elif kind == 'card_metadata':
            result = await _assert_card_metadata(
                page,
                predicate.get('fields') or [],
                predicate.get('minimum') or 1,
                predicate.get('scope') or 'main',
            )
        else:
            result = {'passed': False, 'reason': f'不支持的断言谓词: {kind}'}
        results.append({'predicate': predicate, 'result': result})
    failed = [item for item in results if not item['result'].get('passed')]
    return {
        'passed': not failed,
        'reason': (failed[0]['result'].get('reason') or f"断言谓词未通过: {failed[0]['predicate'].get('kind')}") if failed else '',
        'summary': f'{len(results) - len(failed)}/{len(results)} 个断言谓词通过',
        'results': results,
    }


async def _assert_clicked_community_identity(page, identity):
    identity = identity or {}
    name = str(identity.get('name') or '').strip()
    community_id = str(identity.get('id') or '').strip()
    if not name or not community_id:
        return {'passed': False, 'reason': '前一步未提取到所点击社区的名称和 ID', 'identity': identity}
    js = r'''(payload) => {
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
        const lower = (value) => norm(value).toLowerCase();
        const nodes = Array.from(document.querySelectorAll('h1,h2,h3,h4,p,span,div,a,button,li,strong,section,article'))
            .filter(visible)
            .map(el => ({text: norm(el.innerText || el.textContent || ''), tag: el.tagName.toLowerCase()}))
            .filter(item => item.text && item.text.length <= 500);
        const hasName = nodes.some(item => lower(item.text).includes(lower(payload.name)));
        const hasIdText = nodes.some(item => item.text.includes(payload.id));
        const url = location.href;
        const hasIdUrl = url.includes('/' + payload.id) || url.includes('communityId=' + payload.id) || url.includes('community_id=' + payload.id);
        return {
            passed: hasName && (hasIdText || hasIdUrl),
            reason: !hasName ? `进入页面未展示社区名称: ${payload.name}` : (!(hasIdText || hasIdUrl) ? `进入页面未展示或定位到社区 ID: ${payload.id}` : ''),
            identity: payload,
            hasName,
            hasIdText,
            hasIdUrl,
            url,
            samples: nodes.filter(item => lower(item.text).includes(lower(payload.name)) || item.text.includes(payload.id)).slice(0, 6),
        };
    }'''
    try:
        return await page.evaluate(js, {'name': name, 'id': community_id})
    except Exception as exc:
        return {'passed': False, 'reason': f'社区身份断言执行失败: {exc}', 'identity': identity}


async def _assert_top_search_overlay(page, expected_texts, require_multiple_results=False, require_history=False, execution_record=None):
    expected_texts = [str(text).strip() for text in (expected_texts or []) if str(text).strip()]
    js = r'''(payload) => {
        const expected = payload.expected || [];
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width >= 80 && r.height >= 16 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const norm = (value) => String(value || '').replace(/\s+/g, ' ').trim();
        const lower = (value) => norm(value).toLowerCase();
        const inputs = Array.from(document.querySelectorAll('input, textarea')).filter(visible);
        const scored = inputs.map((el) => {
            const ph = el.getAttribute('placeholder') || '';
            const aria = el.getAttribute('aria-label') || '';
            const cls = String(el.className || '');
            const parentCls = String(el.parentElement?.className || '');
            const combined = `${ph} ${aria} ${cls} ${parentCls}`;
            let score = 0;
            if (/搜索社区|用户名称|搜索/.test(combined)) score += 1000;
            if (/search/i.test(combined)) score += 300;
            if (document.activeElement === el) score += 800;
            return {el, score, ph, aria};
        }).sort((a, b) => b.score - a.score);
        const input = scored[0];
        if (!input || input.score < 1000) {
            return {passed: false, reason: '未找到可见的顶部搜索输入框', inputs: scored.slice(0, 5).map(x => ({score: x.score, placeholder: x.ph, aria: x.aria}))};
        }
        const focused = document.activeElement === input.el;
        const roots = [];
        for (let node = input.el.parentElement, depth = 0; node && depth < 8; node = node.parentElement, depth += 1) {
            if (visible(node)) roots.push(node);
        }
        const root = roots.sort((a, b) => {
            const aText = norm(a.innerText || a.textContent || '');
            const bText = norm(b.innerText || b.textContent || '');
            const aScore = expected.filter(t => lower(aText).includes(lower(t))).length * 10000 + a.querySelectorAll('img').length;
            const bScore = expected.filter(t => lower(bText).includes(lower(t))).length * 10000 + b.querySelectorAll('img').length;
            return bScore - aScore;
        })[0] || document.body;
        const rootText = norm(root.innerText || root.textContent || '');
        const missing = expected.filter(text => !lower(rootText).includes(lower(text)));
        const resultImageCount = Array.from(root.querySelectorAll('img')).filter(visible).filter((img) => {
            const r = img.getBoundingClientRect();
            return r.width >= 80 && r.height >= 50;
        }).length;
        const hasMultipleResults = resultImageCount >= 2;
        const historyText = /\u5386\u53f2\u8bb0\u5f55|\u641c\u7d22\u5386\u53f2/.test(rootText);
        const clearHistoryControls = Array.from(root.querySelectorAll('button,a,[role="button"],span,div')).filter(visible).filter(el => {
            const meta = `${norm(el.innerText || el.textContent)} ${el.getAttribute('aria-label') || ''} ${el.getAttribute('title') || ''} ${el.className || ''}`;
            return /\u5220\u9664|\u6e05\u7a7a|delete|clear|trash/i.test(meta);
        });
        const historyReady = !payload.requireHistory || (historyText && clearHistoryControls.length > 0);
        const passed = focused && missing.length === 0 && (!payload.requireMultiple || hasMultipleResults) && historyReady;
        return {
            passed,
            reason: !focused ? '顶部搜索输入框未获得焦点' : (missing.length ? `搜索弹层缺少文本: ${missing.join(', ')}` : (payload.requireMultiple && !hasMultipleResults ? '搜索弹层未检测到多个社区结果' : (!historyReady ? '搜索历史区域或清空入口未出现' : ''))),
            focused,
            missing,
            resultImageCount,
            historyText,
            clearHistoryControlCount: clearHistoryControls.length,
            rootText: rootText.slice(0, 500),
            input: {placeholder: input.ph, aria: input.aria},
        };
    }'''
    try:
        initial = await page.evaluate(js, {
            'expected': expected_texts,
            'requireMultiple': bool(require_multiple_results),
            'requireHistory': bool(require_history),
        })
        if not require_history or initial.get('historyText'):
            return initial

        # Regression runs use fresh browser contexts. Build history through the
        # same route a user takes: search, enter a community result, then return
        # to the current page before opening search again.
        from ..business_actions import execute_business_action
        original_url = page.url
        search_result = await execute_business_action(
            page,
            {
                'business_action': 'nn_top_community_search',
                'input_value': 'PUBG',
                'target_scope': 'top_navigation',
                'entity_type': 'community',
            },
            execution_record,
        )
        if search_result.get('status') != 'completed':
            initial['reason'] = '无法建立搜索历史: ' + str(search_result.get('error') or search_result.get('message') or '')
            initial['history_seed'] = search_result
            return initial
        enter_result = await execute_business_action(
            page,
            {
                'business_action': 'nn_click_community_result',
                'target_text': 'PUBG',
                'target_scope': 'search_result',
                'entity_type': 'community',
            },
            execution_record,
        )
        if enter_result.get('status') != 'completed':
            initial['reason'] = '搜索后无法进入社区结果以建立历史: ' + str(enter_result.get('error') or enter_result.get('message') or '')
            initial['history_seed'] = {'search': search_result, 'enter': enter_result}
            return initial
        try:
            await page.goto(original_url, wait_until='domcontentloaded', timeout=15000)
            await asyncio.sleep(1)
        except Exception as exc:
            initial['reason'] = '进入社区结果后无法回到原页面: ' + str(exc)[:200]
            initial['history_seed'] = {'search': search_result, 'enter': enter_result}
            return initial
        reopen_result = await execute_business_action(
            page,
            {
                'business_action': 'nn_open_top_search',
                'target_scope': 'top_navigation',
                'entity_type': 'community',
            },
            execution_record,
        )
        if reopen_result.get('status') != 'completed':
            initial['reason'] = '搜索完成后无法重新打开顶部搜索框: ' + str(reopen_result.get('error') or reopen_result.get('message') or '')
            initial['history_seed'] = {'search': search_result, 'enter': enter_result, 'reopen': reopen_result}
            return initial
        input_selector = str((reopen_result.get('element') or {}).get('selector') or '')
        if input_selector:
            try:
                await page.locator(input_selector).first.fill('')
                await asyncio.sleep(0.5)
            except Exception as exc:
                initial['reason'] = '搜索完成后无法清空关键词以查看历史记录: ' + str(exc)[:200]
                initial['history_seed'] = {'search': search_result, 'enter': enter_result, 'reopen': reopen_result}
                return initial
        result = await page.evaluate(js, {
            'expected': expected_texts,
            'requireMultiple': bool(require_multiple_results),
            'requireHistory': True,
        })
        result['history_seed'] = {'search': search_result, 'enter': enter_result, 'reopen': reopen_result}
        return result
    except Exception as exc:
        return {'passed': False, 'reason': f'顶部搜索弹层断言执行失败: {exc}'}


_TEXT_ASSERTION_STABLE_SUFFIX_RE = re.compile(
    r'^(?P<base>.+?)[(（]\s*(?:'
    r'修改后|已修改|新版|新版本|测试版|'
    r'beta|alpha|v(?:ersion)?\s*\d+(?:\.\d+)*|版本\s*\d+(?:\.\d+)*'
    r')\s*[)）]\s*$',
    re.IGNORECASE,
)

# These labels were renamed in the NN community navigation. Keep the mapping
# narrow: every alternative refers to the same product entry, not a fuzzy match.
_UI_LABEL_ALIASES = {
    '成员大厅': ('全员大厅',),
    '全员大厅': ('成员大厅',),
    'PUBG福利商店': ('NN商店',),
    'NN商店': ('PUBG福利商店',),
    '绝地求生': ('绝地求生首页',),
    '绝地求生首页': ('绝地求生',),
}


def _ui_label_variants(value):
    text = str(value or '').strip()
    if not text:
        return ()
    variants = [text, *(_UI_LABEL_ALIASES.get(text) or ())]
    stable_suffix = _TEXT_ASSERTION_STABLE_SUFFIX_RE.match(text)
    if stable_suffix:
        base = stable_suffix.group('base').strip()
        if base:
            variants.extend((base, *(_UI_LABEL_ALIASES.get(base) or ())))
    return tuple(dict.fromkeys(variants))


def _build_text_assertion_targets(expected_texts):
    """Keep version-like display suffixes from making a UI assertion brittle.

    The original text remains the primary assertion. A stable alias is added only
    for explicitly non-business suffixes, so values such as ``正式版`` keep their
    strict semantic meaning.
    """
    targets = []
    for value in expected_texts or []:
        expected = str(value).strip()
        if not expected:
            continue
        variants = [{'text': expected, 'mode': 'exact'}]
        match = _TEXT_ASSERTION_STABLE_SUFFIX_RE.match(expected)
        if match:
            stable_name = match.group('base').strip()
            if stable_name and stable_name != expected:
                variants.append({'text': stable_name, 'mode': 'stable_alias'})
        for alias in _UI_LABEL_ALIASES.get(expected, ()):
            if alias != expected:
                variants.append({'text': alias, 'mode': 'product_label_alias'})
        targets.append({'expected': expected, 'variants': variants})
    return targets


async def _strict_text_assertion(page, expected_texts, assert_desc=''):
    """更严格的文本断言：默认限制在左侧主内容区域，并要求目标文本落在同一可见块内。"""
    expected_texts = [str(t).strip() for t in (expected_texts or []) if str(t).strip()]
    if not expected_texts:
        return {'passed': False, 'reason': '断言缺少明确文本', 'scope': None, 'matches': [], 'bodyText': ''}
    targets = _build_text_assertion_targets(expected_texts)

    description = str(assert_desc or '')
    region = 'all'
    for candidate, keywords in (
        ('right', ('右侧', '右边', '右栏')),
        ('left', ('左侧', '左边', '左栏')),
        ('top', ('顶部', '顶栏', '上方')),
        ('bottom', ('底部', '下方')),
        ('main', ('主内容区', '主内容', '中间区域')),
    ):
        if any(keyword in description for keyword in keywords):
            region = candidate
            break

    js = r"""(payload) => {
        const expected = payload.expected || [];
        const targets = payload.targets || expected.map(text => ({
            expected: text,
            variants: [{text, mode: 'exact'}],
        }));
        const region = payload.region || 'all';
        const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
        const lower = (s) => norm(s).toLowerCase();
        const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
        };
        const pseudoText = (el, pseudo) => {
            try {
                const content = getComputedStyle(el, pseudo).content;
                if (!content || content === 'none' || content === 'normal') return '';
                return content.replace(/^['\"]|['\"]$/g, '');
            } catch (_) {
                return '';
            }
        };
        const body = document.body;
        const bodyRect = body.getBoundingClientRect();
        const preferredSelectors = [
            '[class*="aside" i]',
            '[class*="left" i]',
            '[class*="sidebar" i]',
            '[class*="community" i]',
            '[class*="detail" i]',
            'aside',
            'nav'
        ];
        const preferred = preferredSelectors
            .flatMap(sel => Array.from(document.querySelectorAll(sel)))
            .filter(visible)
            .map(el => ({el, rect: el.getBoundingClientRect()}))
            .filter(x => x.rect.left < bodyRect.width * 0.35 && x.rect.width >= 180 && x.rect.height >= 100)
            .sort((a,b) => (b.rect.height*b.rect.width) - (a.rect.height*a.rect.width));
        const explicitLeft = Array.from(document.querySelectorAll('aside,nav,[class*="sidebar" i],[class*="aside" i],[class*="left-panel" i]'))
            .filter(visible)
            .map(el => ({el, rect: el.getBoundingClientRect()}))
            .filter(x => x.rect.left < bodyRect.width * 0.35 && x.rect.width >= 160 && x.rect.width <= bodyRect.width * 0.35 && x.rect.height >= 100)
            .sort((a,b) => (b.rect.height*b.rect.width) - (a.rect.height*a.rect.width));
        const leftRoots = Array.from(document.querySelectorAll('main, [role="main"], aside + div, .layout-main, .content, .main-content, .left, .left-panel, .community, .community-detail, .group-detail'))
            .filter(visible)
            .map(el => ({el, rect: el.getBoundingClientRect()}))
            .filter(x => x.rect.left < bodyRect.width * 0.62 && x.rect.width > 220 && x.rect.height > 120)
            .sort((a,b) => (b.rect.width*b.rect.height) - (a.rect.width*a.rect.height));
        const rightRoots = Array.from(document.querySelectorAll('aside,section,main,div,[role="region"]'))
            .filter(visible)
            .map(el => ({el, rect: el.getBoundingClientRect()}))
            .filter(x => x.rect.left >= bodyRect.width * 0.62 && x.rect.width >= 160 && x.rect.height >= 100)
            .sort((a,b) => (b.rect.width*b.rect.height) - (a.rect.width*a.rect.height));
        const mainRoots = Array.from(document.querySelectorAll('main,[role="main"],section,article,div'))
            .filter(visible)
            .map(el => ({el, rect: el.getBoundingClientRect()}))
            .filter(x => {
                const cls = String(x.el.className || '');
                const centerX = x.rect.left + x.rect.width / 2;
                return x.rect.width >= 300 && x.rect.height >= 100
                    && centerX >= bodyRect.width * 0.18 && centerX <= bodyRect.width * 0.9
                    && x.rect.width < bodyRect.width * 0.9
                    && !/tooltip|popover|toast|notice|notification/i.test(cls);
            })
            .sort((a,b) => (b.rect.width*b.rect.height) - (a.rect.width*a.rect.height));
        const defaultScope = explicitLeft.length ? explicitLeft[0].el : (preferred.length ? preferred[0].el : (leftRoots.length ? leftRoots[0].el : body));
        const scopeEl = region === 'right' && rightRoots.length
            ? rightRoots[0].el
            : (region === 'left' ? defaultScope : (region === 'main' ? (mainRoots[0]?.el || null) : body));
        if (!scopeEl) {
            return {passed: false, missing: expected, reason: '未定位到可验证的主内容区域', scope: null, match: null, samples: [], bodyText: ''};
        }
        const scopeRect = scopeEl.getBoundingClientRect();

        const candidates = [];
        const rawNodes = region === 'main'
            ? Array.from(document.querySelectorAll('h1,h2,h3,h4,p,span,div,a,button,li,strong,section,article,input,textarea,select'))
            : [scopeEl, ...scopeEl.querySelectorAll('h1,h2,h3,h4,p,span,div,a,button,li,strong,section,article,input,textarea,select')];
        for (const el of rawNodes) {
            if (!visible(el)) continue;
            if (/tooltip|popover|toast|notice|notification/i.test(String(el.className || ''))) continue;
            const r = el.getBoundingClientRect();
            if (r.width < 40 || r.height < 12) continue;
            const centerX = r.left + r.width / 2;
            const centerY = r.top + r.height / 2;
            if (region === 'right' && centerX < bodyRect.width * 0.55) continue;
            if (region === 'left' && centerX > bodyRect.width * 0.45) continue;
            if (region === 'top' && centerY > window.innerHeight * 0.42) continue;
            if (region === 'bottom' && centerY < window.innerHeight * 0.58) continue;
            if (region === 'main' && centerX < bodyRect.width * 0.18) continue;
            const controlTexts = Array.from(el.querySelectorAll ? el.querySelectorAll('input,textarea,select') : [])
                .flatMap(control => [control.placeholder, control.getAttribute('aria-label'), control.value])
                .filter(Boolean);
            const ownControlText = [el.placeholder, el.getAttribute && el.getAttribute('aria-label'), el.value].filter(Boolean);
            // Some NN labels, such as level badges, are rendered by CSS
            // pseudo-elements and are intentionally absent from innerText.
            const text = norm([
                el.innerText || el.textContent || '',
                pseudoText(el, '::before'),
                pseudoText(el, '::after'),
                ...controlTexts,
                ...ownControlText,
            ].join(' '));
            if (!text || text.length > 500) continue;
            const matches = targets.flatMap(target => {
                const variant = (target.variants || []).find(item => lower(text).includes(lower(item.text)));
                return variant ? [{
                    expected: target.expected,
                    matched_text: variant.text,
                    match_mode: variant.mode || 'exact',
                }] : [];
            });
            if (!matches.length) continue;
            candidates.push({
                text: text.slice(0, 220),
                matches,
                rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)},
                cls: String(el.className || '').slice(0, 120),
                tag: el.tagName.toLowerCase()
            });
        }
        candidates.sort((a,b) => b.matches.length - a.matches.length || (b.rect.w*b.rect.h) - (a.rect.w*b.rect.h));
        const combined = candidates.find(c => c.matches.length === expected.length);
        const matchedTexts = [];
        for (const expectedText of expected) {
            const match = candidates.flatMap(c => c.matches).find(item => item.expected === expectedText);
            if (match) matchedTexts.push(match);
        }
        const foundTexts = new Set(matchedTexts.map(item => item.expected));
        const missing = expected.filter(t => !foundTexts.has(t));
        return {
            passed: missing.length === 0,
            missing,
            scope: {tag: scopeEl.tagName.toLowerCase(), rect: {x: Math.round(scopeRect.x), y: Math.round(scopeRect.y), w: Math.round(scopeRect.width), h: Math.round(scopeRect.height)}},
            match: combined || null,
            matched_texts: matchedTexts,
            samples: candidates.slice(0, 6),
            bodyText: norm((scopeEl.innerText || scopeEl.textContent || '').slice(0, 600))
        };
    }"""
    try:
        return await page.evaluate(js, {
            'expected': expected_texts,
            'targets': targets,
            'region': region,
        })
    except Exception as exc:
        return {'passed': False, 'reason': f'严格断言执行失败: {exc}', 'scope': None, 'matches': [], 'bodyText': ''}


async def _capture_element_info(page, locator):
    """捕获被操作元素的属性信息"""
    try:
        js = "el => { return { tag: el.tagName ? el.tagName.toLowerCase() : '', id: el.id || '', name: el.name || '', type: el.type || '', className: el.className || '', placeholder: el.placeholder || '', text: el.innerText ? el.innerText.substring(0, 100) : '', value: el.value || '', href: el.href || '', ariaLabel: el.getAttribute('aria-label') || '', dataTestId: el.getAttribute('data-testid') || '' } }"
        info = await locator.evaluate(js)
        locator_value = _generate_locator(info)
        info['locator_value'] = locator_value
        info['locator_strategy'] = 'css'
        info['name'] = info.get('placeholder') or info.get('ariaLabel') or info.get('text') or f'{info["tag"]}_{info.get("id", "")}'
        return info
    except Exception:
        return {'tag': 'unknown', 'name': 'unknown', 'locator_value': '', 'locator_strategy': 'css'}


def _generate_locator(info):
    """根据元素属性生成最佳CSS定位器"""
    tag = info.get('tag', '')
    el_id = info.get('id', '')
    name = info.get('name', '')
    el_type = info.get('type', '')
    placeholder = info.get('placeholder', '')
    aria_label = info.get('ariaLabel', '')
    class_name = info.get('className', '')
    text = info.get('text', '')
    if el_id:
        return f'#{el_id}'
    if name and el_type:
        return f'input[name="{name}"][type="{el_type}"]'
    if placeholder:
        return f'[placeholder="{placeholder}"]'
    if aria_label:
        return f'[aria-label="{aria_label}"]'
    if tag == 'button' and text:
        return f'button:has-text("{text[:50]}")'
    if tag == 'a' and text:
        return f'a:has-text("{text[:50]}")'
    if class_name:
        first_class = class_name.split()[0]
        return f'{tag}.{first_class}'
    return tag




def _persist_ai_execution_media(execution_record, recorded_steps):
    """把步骤截图落盘并合成 GIF，供 AI 测试报告展示。"""
    screenshots = []
    try:
        import base64 as _base64
        import os as _os
        from io import BytesIO
        from PIL import Image, ImageDraw, ImageFont

        media_root = getattr(settings, 'MEDIA_ROOT', None) or _os.path.join(_os.getcwd(), 'media')
        # Only retain the latest replay for this case and execution target.
        # Old reports remain available, but their media references are cleared
        # before the files are removed so no stale C/F-disk paths are served.
        if getattr(execution_record, 'ai_case_id', None):
            import shutil as _shutil
            from apps.ui_automation.models import AIExecutionRecord
            previous = AIExecutionRecord.objects.filter(
                ai_case_id=execution_record.ai_case_id,
                execution_target=execution_record.execution_target,
            ).exclude(pk=execution_record.pk).exclude(gif_path='')
            for old in previous.iterator():
                for kind in ('ai_execution', 'desktop_execution'):
                    old_dir = _os.path.join(media_root, 'ui_automation', kind, str(old.id))
                    if _os.path.isdir(old_dir):
                        _shutil.rmtree(old_dir, ignore_errors=True)
                old.gif_path = ''
                old.screenshots_sequence = []
                old.save(update_fields=['gif_path', 'screenshots_sequence'])
        rel_dir = _os.path.join('ui_automation', 'ai_execution', str(execution_record.id))
        abs_dir = _os.path.join(media_root, rel_dir)
        _os.makedirs(abs_dir, exist_ok=True)

        frames = []
        durations = []
        for step in recorded_steps or []:
            b64 = step.get('screenshot')
            if not b64:
                continue
            if isinstance(b64, str) and ',' in b64:
                b64 = b64.split(',', 1)[1]
            try:
                raw = _base64.b64decode(b64)
            except Exception:
                continue
            step_no = step.get('step_number') or (len(screenshots) + 1)
            desc = step.get('description', '') or ''
            png_name = f"step_{step_no}.png"
            png_abs = _os.path.join(abs_dir, png_name)
            with open(png_abs, 'wb') as f:
                f.write(raw)
            png_rel = _os.path.join(rel_dir, png_name).replace(chr(92), '/')
            screenshots.append({
                'step_number': step_no,
                'description': desc,
                'status': step.get('status', ''),
                'path': png_rel,
                'url': f"/media/{png_rel}",
            })
            try:
                base = Image.open(BytesIO(raw)).convert('RGB')
                w, h = base.size
                bar_h = max(56, min(96, h // 10))
                canvas = Image.new('RGB', (w, h + bar_h), (20, 24, 31))
                canvas.paste(base, (0, bar_h))
                draw = ImageDraw.Draw(canvas)
                title = f"Step {step_no}: {desc}"
                status = step.get('status', '')
                font = None
                for font_path in [
                    r'C:\Windows\Fonts\msyh.ttc',
                    r'C:\Windows\Fonts\simhei.ttf',
                    r'C:\Windows\Fonts\simsun.ttc',
                ]:
                    try:
                        if _os.path.exists(font_path):
                            font = ImageFont.truetype(font_path, 26)
                            break
                    except Exception:
                        font = None
                if font is None:
                    font = ImageFont.load_default()
                draw.rectangle([0, 0, w, bar_h], fill=(23, 37, 84))
                draw.text((18, 12), title[:120], fill=(255, 255, 255), font=font)
                draw.text((18, 44), f"status: {status}", fill=(134, 239, 172), font=font)
                frames.append(canvas.convert('P', palette=Image.ADAPTIVE))
                if any(k in desc for k in ['登录', '账号', '验证码', '手机号']):
                    durations.append(1600)
                else:
                    durations.append(1000)
            except Exception:
                pass

        gif_rel = ''
        if frames:
            gif_name = 'execution.gif'
            gif_abs = _os.path.join(abs_dir, gif_name)
            frames[0].save(gif_abs, save_all=True, append_images=frames[1:], duration=durations or 1200, loop=0, optimize=False)
            gif_rel = _os.path.join(rel_dir, gif_name).replace(chr(92), '/')

        update_fields = []
        if screenshots:
            execution_record.screenshots_sequence = screenshots
            update_fields.append('screenshots_sequence')
        if gif_rel:
            execution_record.gif_path = f"/media/{gif_rel}"
            update_fields.append('gif_path')
        if update_fields:
            execution_record.logs += f"\n[System] GIF录制已生成: {execution_record.gif_path or '未生成'}，截图 {len(screenshots)} 张\n"
            update_fields.append('logs')
            execution_record.save(update_fields=update_fields)
            return True
    except Exception as exc:
        try:
            execution_record.logs += f"\n[System] GIF录制生成失败: {str(exc)[:300]}\n"
            execution_record.save(update_fields=['logs'])
        except Exception:
            pass
    return False

def _escape_playwright_text(text):
    """Escape text for Playwright text/:has-text selectors."""
    value = str(text).strip()
    return value.replace(chr(92), chr(92) + chr(92)).replace(chr(34), chr(92) + chr(34))


def _dedupe_keep_order(items):
    seen = set()
    result = []
    for item in items:
        item = str(item).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result




def _is_top_community_search_description(description):
    """识别顶部/导航栏/社区搜索框语义，避免误选页面中部输出框。"""
    desc = str(description or '').lower()
    if not desc:
        return False
    has_search = any(kw in desc for kw in ['搜索', '查找', '检索', 'search'])
    has_scope = any(kw in desc for kw in ['顶部', '顶栏', '上方', '上面', '导航栏', '导航', 'header', 'nav', '社区搜索', 'community'])
    return has_search and has_scope


def _top_community_search_locator():
    """顶部社区搜索框的稳定候选定位器。

    优先限制在 header/nav/top/search 相关容器内，只包含可输入元素；不包含 textarea/editor/output。
    """
    return ', '.join([
        'header input[type="search"]',
        'header input[placeholder*="搜索"]',
        'header input[placeholder*="社区"]',
        'header input[value]',
        'nav input[type="search"]',
        'nav input[placeholder*="搜索"]',
        '[class*="header" i] input[type="search"]',
        '[class*="header" i] input[placeholder*="搜索"]',
        '[class*="header" i] input[placeholder*="社区"]',
        '[class*="nav" i] input[type="search"]',
        '[class*="nav" i] input[placeholder*="搜索"]',
        '[class*="top" i] input[type="search"]',
        '[class*="top" i] input[placeholder*="搜索"]',
        '[class*="search" i] input[type="search"]',
        '[class*="search" i] input[placeholder*="搜索"]',
        'input[placeholder*="搜索社区"]',
        'input[placeholder*="用户昵称"]',
        'input[placeholder*="NN号"]',
        'input[placeholder*="搜索"]',
        'input[placeholder*="社区"]',
        'input[type="search"]',
    ])

def _extract_contextual_click_targets(description):
    """从“点击搜索结果/列表/卡片/菜单中的 XXX”等自然语言中提取真正要点击的目标文本。

    这类句子里经常同时包含“搜索/列表/结果”等上下文词和目标词。若只按动作词匹配，
    执行器会误找“搜索按钮/查询按钮”。这里优先提取上下文后的目标项，生成文本/卡片/链接定位策略。
    """
    desc = str(description or '').strip()
    if not desc:
        return []

    # 只处理上下文型点击，避免影响“点击搜索按钮/点击登录”等明确按钮动作。
    context_markers = [
        '搜索结果', '查询结果', '检索结果', '结果列表', '列表', '卡片', '表格', '菜单', '导航',
        '右侧', '右边', '左侧', '左边', '弹窗', '弹层',
        '下拉选项', '选项', '条目', '项目', '结果项', '列表项', '社区结果', '商品结果', '用户结果',
    ]
    if not any(marker in desc for marker in context_markers):
        return []

    candidates = []

    # 点击 A 中/里的 B -> B 才是真目标。
    patterns = [
        r"(?:点击|点|按|选择|打开|进入)\s*.+?(?:中|里|里面|中的|里的|下方|上方|右侧|左侧|右边|左边)\s*(?:的)?\s*([^，。；;,]+)$",
        r"(?:点击|点|按|选择|打开|进入)\s*(?:包含|带有|名称为|标题为|文本为)\s*[\"“']?([^\"”'，。；;,]+)[\"”']?\s*(?:的)?(?:结果|条目|项目|卡片|列表项|那一项|选项)?",
        r"(?:点击|点|按|选择|打开|进入)\s*[\"“']?([^\"”'，。；;,]+)[\"”']?\s*(?:结果|条目|项目|卡片|列表项|那一项|社区|商品|用户)$",
        r"(?:点击|点|按|选择|打开|进入)\s*(?:右侧|右边|左侧|左边)?\s*(?:的)?\s*[\"“']?([^\"”'，。；;,]+?社区)[\"”']?\s*(?:进入|打开)?$",
    ]
    for pattern in patterns:
        m = re.search(pattern, desc)
        if m:
            candidates.append(m.group(1))

    # 引号内容通常是最明确目标。
    candidates.extend(re.findall(r'["“\']([^"”\']{1,40})["”\']', desc))

    cleaned = []
    noise = ['点击', '点', '按', '选择', '打开', '进入', '社区搜索结果', '搜索结果', '查询结果', '检索结果', '结果列表', '列表', '卡片', '中的', '里的', '里面的']
    for raw in candidates:
        text = raw.strip().strip('"').strip("'").strip('“').strip('”')
        for n in noise:
            text = text.replace(n, '')
        text = text.strip(' ：:，,。；;')
        if len(text) >= 2:
            cleaned.append(text)
            # 常见“XXX社区/卡片/条目”同时尝试去掉类型后缀，提升匹配弹性。
            for suffix in ['社区', '卡片', '条目', '项目', '列表项', '结果项', '商品', '用户']:
                if text.endswith(suffix) and len(text) > len(suffix) + 1:
                    cleaned.append(text[:-len(suffix)])

    return _dedupe_keep_order(cleaned)[:5]




def _is_community_result_click_description(description):
    # 是否为“点击社区搜索结果/右侧社区卡片进入”的语义。
    desc = str(description or '').strip()
    if not desc:
        return False
    has_click = any(kw in desc for kw in ['点击', '点', '选择', '打开', '进入'])
    has_community = '社区' in desc or 'community' in desc.lower()
    has_result_context = any(kw in desc for kw in ['搜索结果', '查询结果', '检索结果', '结果', '右侧', '右边', '卡片', '列表', '弹窗', '弹层'])
    return has_click and has_community and has_result_context


async def _find_community_result_click_target(page, description, execution_record=None):
    # 在搜索弹层/结果区中优先定位社区卡片，排除同名用户结果。
    targets = _extract_contextual_click_targets(description)
    if not targets:
        return None
    try:
        result = await page.evaluate(r"""(targets) => {
            const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
            };
            const dialog = Array.from(document.querySelectorAll('[role="dialog"], .ui-dialog, .nn-dialog, .nn-modal, .modal, .dialog, [class*="dialog" i], [class*="modal" i]'))
                .filter(visible)
                .sort((a, b) => (b.getBoundingClientRect().width * b.getBoundingClientRect().height) - (a.getBoundingClientRect().width * a.getBoundingClientRect().height))[0] || document.body;
            const dr = dialog.getBoundingClientRect();
            const rawNodes = Array.from(dialog.querySelectorAll('a,[role="link"],[role="button"],button,li,[class*="card" i],[class*="item" i],[class*="result" i],[class*="community" i],[class*="group" i],div'));
            const candidates = [];
            for (const el of rawNodes) {
                if (!visible(el)) continue;
                const text = norm(el.innerText || el.textContent || '');
                if (!text || text.length > 600) continue;
                const matchedTarget = targets.find(t => text.includes(t));
                if (!matchedTarget) continue;
                const cls = String(el.className || '');
                const r = el.getBoundingClientRect();
                const isUserLike = /NN[:：]\s*\d+/.test(text) || /group\/avatar|avatar|user|用户/i.test(cls);
                const hasCommunitySignal = /社区|官方社区|PUBG中国官方社区|community/i.test(text + ' ' + cls);
                const isRightSide = r.left > (dr.left + dr.width / 2 - 20);
                const clickableSelf = /^(A|BUTTON|LI)$/.test(el.tagName) || el.getAttribute('role') === 'button' || el.getAttribute('role') === 'link' || /cursor-pointer|card|item|result|community|group/i.test(cls);
                let clickEl = el;
                if (!clickableSelf) {
                    clickEl = el.closest('a,[role="link"],[role="button"],button,li,[class*="card" i],[class*="item" i],[class*="result" i],[class*="community" i],[class*="group" i],[class*="cursor-pointer" i]') || el;
                }
                if (!visible(clickEl)) continue;
                let score = 0;
                if (hasCommunitySignal) score += 1000;
                if (isRightSide) score += 500;
                if (/官方社区|PUBG中国官方社区/.test(text)) score += 600;
                if (/card|community/i.test(cls)) score += 200;
                if (/cursor-pointer/.test(cls)) score += 80;
                if (text === matchedTarget || text.startsWith(matchedTarget + ' ')) score += 80;
                if (isUserLike) score -= 2000;
                score -= Math.max(0, Math.abs(r.top - dr.top));
                candidates.push({el: clickEl, score, text: text.slice(0, 160), cls: cls.slice(0, 160), rect: {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)}, isUserLike, hasCommunitySignal, isRightSide, matchedTarget});
            }
            candidates.sort((a, b) => b.score - a.score);
            const best = candidates.find(c => c.score > -500 && !c.isUserLike && c.hasCommunitySignal) || candidates[0];
            if (!best || best.isUserLike) {
                return {found: false, reason: best ? 'best_is_user_like' : 'no_candidate', samples: candidates.slice(0, 8).map(c => ({score:c.score,text:c.text,cls:c.cls,rect:c.rect,isUserLike:c.isUserLike,hasCommunitySignal:c.hasCommunitySignal,isRightSide:c.isRightSide,matchedTarget:c.matchedTarget}))};
            }
            const token = 'ai_community_result_' + Date.now() + '_' + Math.random().toString(36).slice(2);
            best.el.setAttribute('data-ai-automation-click-target', token);
            return {found: true, selector: '[data-ai-automation-click-target="' + token + '"]', detail: {score: best.score, text: best.text, cls: best.cls, rect: best.rect, isUserLike: best.isUserLike, hasCommunitySignal: best.hasCommunitySignal, isRightSide: best.isRightSide, matchedTarget: best.matchedTarget}, samples: candidates.slice(0, 5).map(c => ({score:c.score,text:c.text,cls:c.cls,rect:c.rect,isUserLike:c.isUserLike,hasCommunitySignal:c.hasCommunitySignal,isRightSide:c.isRightSide,matchedTarget:c.matchedTarget}))};
        }""", targets)
        if execution_record:
            execution_record.logs += f"  COMMUNITY_RESULT_CLICK_SCAN: {result}\n"
        if result and result.get('found') and result.get('selector'):
            loc = page.locator(result['selector']).first
            if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                return loc
    except Exception as e:
        if execution_record:
            execution_record.logs += f"  COMMUNITY_RESULT_CLICK_SCAN_ERROR: {str(e)[:200]}\n"
    return None


async def _find_constraint_aware_click_target(page, step, execution_record=None):
    description = str(step.get('display_description') or step.get('description') or '').strip()
    if not description:
        return None

    constraints = step.get('click_constraints') or extract_click_constraints(
        description,
        fallback_target=str(step.get('target_text') or ''),
    )
    if not has_meaningful_click_constraints(constraints):
        return None

    target_texts = []
    for target in constraints.get('target_texts') or []:
        target_texts.extend(_ui_label_variants(target) or (str(target),))
    payload = {
        'description': description,
        'target_texts': list(dict.fromkeys(target_texts)),
        'required_signals': constraints.get('required_signals') or [],
        'required_texts': constraints.get('required_texts') or [],
        'position_terms': constraints.get('position_terms') or [],
        'context_terms': constraints.get('context_terms') or [],
    }

    try:
        result = await page.evaluate(r"""(config) => {
            // Labels frequently use visual separators such as "邀请/分享" while
            // the task naturally says "邀请分享". Compare compact labels so a
            // harmless separator never prevents an otherwise exact click.
            const norm = (s) => String(s || '')
                .replace(/[\s/／\\\\|｜·._,，。:：;；()（）\[\]{}<>《》"'“”‘’]+/g, '')
                .trim();
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && st.display !== 'none' && st.visibility !== 'hidden' && st.opacity !== '0';
            };
            const hasSignal = (signal, text, cls, el, matchedTarget) => {
                switch (signal) {
                    case 'online_count':
                        return /(?:在线|成员|member).{0,6}\d+|\d+.{0,6}(?:在线|成员|member)/i.test(text);
                    case 'community_intro': {
                        if (/简介|介绍|攻略|讨论|置顶|帖子|公告/.test(text)) return true;
                        const plainTarget = String(matchedTarget || '').trim();
                        const compact = text.replace(/\s+/g, '');
                        return !!plainTarget && compact.length >= plainTarget.replace(/\s+/g, '').length + 8;
                    }
                    case 'official':
                        return /官方|official/i.test(text);
                    case 'avatar':
                        return /头像|avatar|profile/i.test(text + ' ' + cls + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('alt') || ''));
                    case 'price':
                        return /(?:¥|￥|\$)\s*\d+|\d+(?:\.\d{1,2})?\s*(?:元|块|usd|cny)/i.test(text);
                    case 'stock':
                        return /库存|剩余|余量|有货|无货|售罄/i.test(text);
                    default:
                        return false;
                }
            };
            const rawNodes = Array.from(document.querySelectorAll(
                'a,button,[role="button"],[role="link"],label,input[type="button"],input[type="submit"],li,' +
                '[class*="item" i],[class*="card" i],[class*="result" i],[class*="community" i],[class*="group" i],[class*="close" i],div,span'
            ));
            const candidateMap = new Map();
            const viewportWidth = window.innerWidth || 1;
            const viewportHeight = window.innerHeight || 1;
            const targets = (config.target_texts || []).map(norm).filter(Boolean);
            const requiredSignals = (config.required_signals || []).map(String);
            const requiredTexts = (config.required_texts || []).map(norm).filter(Boolean);
            const positionTerms = (config.position_terms || []).map(String);
            const contextTerms = (config.context_terms || []).map(String);
            for (const el of rawNodes) {
                if (!visible(el)) continue;
                const clickEl = el.closest('a,[role="link"],[role="button"],button,label,li,[class*="card" i],[class*="item" i],[class*="result" i],[class*="community" i],[class*="group" i],[class*="cursor-pointer" i],[class*="close" i]') || el;
                if (!visible(clickEl)) continue;
                const rect = clickEl.getBoundingClientRect();
                const clickText = norm(clickEl.innerText || clickEl.textContent || clickEl.getAttribute('aria-label') || clickEl.getAttribute('title') || clickEl.getAttribute('alt') || '');
                const leafText = norm(el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || '');
                const fullText = norm((clickText + ' ' + leafText).trim());
                if (!fullText && !targets.length && !requiredSignals.length && !requiredTexts.length) continue;
                if (fullText.length > 1200) continue;
                const cls = String(clickEl.className || '');
                const matchedTarget = !targets.length ? '' : (targets.find(t => fullText.includes(t) || leafText.includes(t)) || '');
                if (targets.length && !matchedTarget) continue;
                const matchedSignals = requiredSignals.filter(signal => hasSignal(signal, fullText, cls, clickEl, matchedTarget));
                if (requiredSignals.length && matchedSignals.length !== requiredSignals.length) continue;
                const matchedTexts = requiredTexts.filter(text => fullText.includes(text));
                if (requiredTexts.length && matchedTexts.length !== requiredTexts.length) continue;
                let score = 0;
                if (matchedTarget) score += 2200;
                if (matchedTarget && (fullText === matchedTarget || fullText.startsWith(matchedTarget + ' '))) score += 220;
                // Prefer the smallest control that directly owns the requested label.
                // A broad layout wrapper often contains every navigation label and must
                // not win merely because it appears higher in the viewport.
                const directTargetMatch = Boolean(matchedTarget) && (
                    clickText === matchedTarget || leafText === matchedTarget ||
                    clickText.startsWith(matchedTarget + ' ') || leafText.startsWith(matchedTarget + ' ')
                );
                if (directTargetMatch) score += 620;
                if (matchedTarget && !directTargetMatch) {
                    score -= Math.min(760, Math.max(0, clickText.length - matchedTarget.length - 36) * 3);
                }
                score += matchedSignals.length * 520;
                score += matchedTexts.length * 260;
                if (clickEl !== el) score += 120;
                if (/close|关闭|dismiss/i.test(config.description || '') && /close|关闭|dismiss|x/i.test(fullText + ' ' + cls)) score += 500;
                if (contextTerms.includes('result') && /result|search|搜索|结果|item/i.test(fullText + ' ' + cls)) score += 450;
                if (contextTerms.includes('list') && /list|列表|item|条目|项目/i.test(fullText + ' ' + cls)) score += 320;
                if (contextTerms.includes('card') && /card|卡片|item/i.test(fullText + ' ' + cls)) score += 320;
                if (contextTerms.includes('dialog') && clickEl.closest('[role="dialog"],[role="alertdialog"],.modal,.dialog,[class*="dialog" i],[class*="modal" i]')) score += 360;
                if (contextTerms.includes('menu') && clickEl.closest('[role="menu"],.menu,.dropdown,[class*="menu" i],[class*="dropdown" i]')) score += 260;
                if (positionTerms.includes('top') && rect.top <= viewportHeight * 0.45) score += 260;
                if (positionTerms.includes('bottom') && rect.bottom >= viewportHeight * 0.55) score += 260;
                if (positionTerms.includes('left') && rect.left <= viewportWidth * 0.55) score += 260;
                if (positionTerms.includes('right') && rect.right >= viewportWidth * 0.45) score += 260;
                if (positionTerms.includes('top') && positionTerms.includes('right') && rect.top <= viewportHeight * 0.35 && rect.right >= viewportWidth * 0.65) score += 220;
                if (positionTerms.includes('top') && positionTerms.includes('left') && rect.top <= viewportHeight * 0.35 && rect.left <= viewportWidth * 0.35) score += 220;
                if (positionTerms.includes('bottom') && positionTerms.includes('right') && rect.bottom >= viewportHeight * 0.65 && rect.right >= viewportWidth * 0.65) score += 220;
                if (positionTerms.includes('bottom') && positionTerms.includes('left') && rect.bottom >= viewportHeight * 0.65 && rect.left <= viewportWidth * 0.35) score += 220;
                score -= Math.max(0, rect.top * 0.02);
                const candidate = {
                    el: clickEl,
                    score,
                    text: fullText.slice(0, 260),
                    cls: cls.slice(0, 160),
                    rect: {x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)},
                    matchedTarget,
                    matchedSignals,
                    matchedTexts,
                };
                const existing = candidateMap.get(clickEl);
                if (!existing || candidate.score > existing.score) {
                    candidateMap.set(clickEl, candidate);
                }
            }
            const candidates = Array.from(candidateMap.values()).sort((a, b) => b.score - a.score);
            const best = candidates[0];
            if (!best) {
                return {
                    found: false,
                    reason: 'no_constraint_candidate',
                    constraints: config,
                    samples: [],
                };
            }
            const token = 'ai_constraint_click_' + Date.now() + '_' + Math.random().toString(36).slice(2);
            best.el.setAttribute('data-ai-automation-click-target', token);
            return {
                found: true,
                selector: '[data-ai-automation-click-target="' + token + '"]',
                detail: {
                    score: best.score,
                    text: best.text,
                    cls: best.cls,
                    rect: best.rect,
                    matchedTarget: best.matchedTarget,
                    matchedSignals: best.matchedSignals,
                    matchedTexts: best.matchedTexts,
                },
                samples: candidates.slice(0, 5).map(item => ({
                    score: item.score,
                    text: item.text,
                    cls: item.cls,
                    rect: item.rect,
                    matchedTarget: item.matchedTarget,
                    matchedSignals: item.matchedSignals,
                    matchedTexts: item.matchedTexts,
                })),
            };
        }""", payload)
        if execution_record:
            execution_record.logs += f"  CONSTRAINT_AWARE_CLICK_SCAN: {result}\n"
        if result and result.get('found') and result.get('selector'):
            loc = page.locator(result['selector']).first
            if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                return loc
    except Exception as exc:
        if execution_record:
            execution_record.logs += f"  CONSTRAINT_AWARE_CLICK_SCAN_ERROR: {str(exc)[:200]}\n"
    return None


async def _find_exact_text_click_target(page, target_text, execution_record=None):
    """Resolve a named UI target to its smallest clickable DOM owner.

    CSS :has-text() matches every ancestor containing the phrase.  For app
    navigation that can mean clicking the whole page shell.  This resolver
    starts at the smallest matching text node and walks only to a clickable
    ancestor, then returns a temporary stable selector.
    """
    target = str(target_text or '').strip()
    if not target:
        return None
    js = r'''(target) => {
        const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
        const visible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
        };
        const clickable = el => {
            if (!el) return false;
            const cls = String(el.className || '');
            const role = el.getAttribute('role') || '';
            const tab = el.getAttribute('tabindex');
            return /^(a|button)$/.test(el.tagName.toLowerCase()) || role === 'button' || role === 'link' || tab === '0' || /(?:^|[-_\s])(cursor-pointer|clickable|button|menu-item|nav-item|card|item)(?:$|[-_\s])/i.test(cls) || typeof el.onclick === 'function';
        };
        const nodes = Array.from(document.querySelectorAll('a,button,[role="button"],[role="link"],li,div,span,p')).filter(visible).filter(el => {
            const text = norm(el.innerText || el.textContent);
            return text === target || text.includes(target);
        });
        const candidates = [];
        for (const node of nodes) {
            const hasCloserMatch = Array.from(node.querySelectorAll('a,button,[role="button"],[role="link"],li,div,span,p')).some(child => {
                const text = norm(child.innerText || child.textContent);
                return text === target;
            });
            if (hasCloserMatch && norm(node.innerText || node.textContent) !== target) continue;
            let owner = node;
            for (let depth = 0; owner && depth < 7; owner = owner.parentElement, depth += 1) {
                if (visible(owner) && clickable(owner)) break;
            }
            if (!owner || !visible(owner) || !clickable(owner)) continue;
            const text = norm(owner.innerText || owner.textContent);
            const r = owner.getBoundingClientRect();
            const score = (text === target ? 10000 : 5000) + (clickable(owner) ? 1000 : 0) - Math.min(text.length, 1000) - Math.round(r.width * r.height / 10000);
            candidates.push({owner, score, text, cls: String(owner.className || '').slice(0, 160)});
        }
        candidates.sort((a, b) => b.score - a.score);
        const best = candidates[0];
        if (!best) return {found: false};
        const token = 'ai_exact_click_' + Date.now() + '_' + Math.random().toString(36).slice(2);
        best.owner.setAttribute('data-ai-exact-click-target', token);
        return {found: true, selector: `[data-ai-exact-click-target="${token}"]`, detail: {text: best.text.slice(0, 200), cls: best.cls, score: best.score}};
    }'''
    try:
        for candidate_target in _ui_label_variants(target):
            result = await page.evaluate(js, candidate_target)
            if not (result and result.get('found')):
                continue
            locator = page.locator(result['selector']).first
            if await locator.count() and await locator.is_visible(timeout=1000):
                if execution_record:
                    match_mode = 'exact' if candidate_target == target else 'product_label_alias'
                    execution_record.logs += f"  EXACT_TEXT_CLICK: {target} -> {candidate_target} ({match_mode}) -> {result.get('detail')}\n"
                return locator
    except Exception as exc:
        if execution_record:
            execution_record.logs += f"  EXACT_TEXT_CLICK_ERROR: {target}: {exc}\n"
    return None


async def _find_active_dialog_close_target(page, description, execution_record=None):
    """Resolve a close control in the currently visible dialog by geometry."""
    desc = str(description or '')
    if not ('关闭' in desc and any(token in desc for token in ('弹窗', '弹层', '对话框', '面板', '分享'))):
        return None

    js = r'''() => {
        const visible = el => {
            if (!el) return false;
            const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
        };
        const dialogs = Array.from(document.querySelectorAll(
            '[role="dialog"],[role="alertdialog"],.ui-dialog,.el-dialog,.modal,.dialog,[class*="dialog" i],[class*="modal" i]'
        )).filter(visible).sort((a, b) => {
            const ar = a.getBoundingClientRect(); const br = b.getBoundingClientRect();
            return (br.width * br.height) - (ar.width * ar.height);
        });
        const dialog = dialogs[0];
        if (!dialog) return {found: false, reason: 'no_visible_dialog'};
        const dialogRect = dialog.getBoundingClientRect();
        const candidates = Array.from(dialog.querySelectorAll(
            'button,[role="button"],[aria-label],[title],[class*="close" i],[class*="cancel" i],svg'
        )).map(el => {
            const owner = el.closest('button,[role="button"],[class*="close" i],[class*="cancel" i]') || el;
            if (!visible(owner)) return null;
            const r = owner.getBoundingClientRect();
            const text = `${owner.innerText || ''} ${owner.getAttribute('aria-label') || ''} ${owner.getAttribute('title') || ''} ${owner.className || ''}`;
            const semanticClose = /close|dismiss|cancel|关闭|取消|×|x/i.test(text);
            const topRight = r.top <= dialogRect.top + Math.min(100, dialogRect.height * 0.22) && r.right >= dialogRect.right - Math.min(110, dialogRect.width * 0.22);
            if (!semanticClose && !topRight) return null;
            return {owner, score: (semanticClose ? 1000 : 0) + (topRight ? 800 : 0), text: text.slice(0, 160)};
        }).filter(Boolean).sort((a, b) => b.score - a.score);
        const best = candidates[0];
        if (!best) return {found: false, reason: 'no_close_candidate'};
        const token = 'ai_dialog_close_' + Date.now() + '_' + Math.random().toString(36).slice(2);
        best.owner.setAttribute('data-ai-dialog-close-target', token);
        return {found: true, selector: `[data-ai-dialog-close-target="${token}"]`, detail: {text: best.text, score: best.score}};
    }'''
    try:
        result = await page.evaluate(js)
        if result and result.get('found'):
            locator = page.locator(result['selector']).first
            if await locator.count() and await locator.is_visible(timeout=1000):
                if execution_record:
                    execution_record.logs += f"  DIALOG_CLOSE_HIT: {result.get('detail')}\n"
                return locator
    except Exception as exc:
        if execution_record:
            execution_record.logs += f"  DIALOG_CLOSE_ERROR: {exc}\n"
    return None


def _build_contextual_click_strategies(description):
    """为上下文型点击生成候选定位器，优先点击文本项/卡片/链接，而不是搜索按钮。"""
    targets = _extract_contextual_click_targets(description)
    strategies = []
    for target in targets:
        t = _escape_playwright_text(target)
        strategies.extend([
            f'a:has-text("{t}")',
            f'[role="link"]:has-text("{t}")',
            f'[role="button"]:has-text("{t}")',
            f'button:has-text("{t}")',
            f'li:has-text("{t}")',
            f'[class*="result" i]:has-text("{t}")',
            f'[class*="item" i]:has-text("{t}")',
            f'[class*="card" i]:has-text("{t}")',
            f'[class*="community" i]:has-text("{t}")',
            f'[class*="list" i]:has-text("{t}")',
            f'text="{t}"',
            f'div:has-text("{t}")',
        ])
    return _dedupe_keep_order(strategies)


def _is_login_success_assertion(description):
    """判断一句自然语言是否是在校验登录成功，而不是普通点击登录动作。"""
    desc = str(description or '').strip()
    if not desc:
        return False
    if any(token in desc for token in (
        '未登录', '未登陆', '没有登录', '没有登陆', '登录入口', '登陆入口',
        '登录流程', '登陆流程', '登录弹窗', '登陆弹窗', '登录框', '登陆框',
        '登录按钮', '登陆按钮', '登录页', '登陆页', '需要登录', '需要登陆',
        '登录拦截', '登陆拦截', '跳转登录', '跳转登陆',
    )):
        return False
    return any(phrase in desc for phrase in (
        '登录成功', '登陆成功', '成功登录', '成功登陆', '是否成功登录', '是否成功登陆',
        '已登录', '已登陆', '登录态有效', '登陆态有效',
    ))


async def _evaluate_login_success(page):
    """检查真实已登录态，避免“页面没有登录字样”导致误判通过。"""
    try:
        return await page.evaluate(r"""() => {
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const txt = (el) => (el.innerText || el.textContent || el.getAttribute('aria-label') || el.getAttribute('alt') || '').replace(/\s+/g, ' ').trim();
            const bodyText = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 500);
            const loginFormNodes = Array.from(document.querySelectorAll('input,button,a,[role=button]')).filter(visible).filter(el => {
                const t = (txt(el) + ' ' + (el.getAttribute('placeholder') || '') + ' ' + (el.getAttribute('name') || '') + ' ' + (el.getAttribute('type') || '')).toLowerCase();
                return /密码|验证码|请输入手机|手机号|登录|登陆|login|password|captcha|code|mobile|phone/.test(t);
            });
            const passwordInputs = Array.from(document.querySelectorAll('input[type="password"], input[placeholder*="密码"], input[placeholder*="验证码"], input[placeholder*="手机"]')).filter(visible);
            const postLoginNodes = Array.from(document.querySelectorAll('img,[class*="avatar" i],[class*="user" i],[class*="profile" i],[class*="account" i],a,button,[role=button]')).filter(visible).filter(el => {
                const t = txt(el).toLowerCase();
                const cls = (el.className || '').toString().toLowerCase();
                const alt = (el.getAttribute('alt') || '').toLowerCase();
                return /退出|注销|个人中心|用户中心|我的主页|账号中心|logout|sign out|profile|avatar/.test(t + ' ' + cls + ' ' + alt);
            });
            const storageHits = [];
            const strongStorageHits = [];
            const stores = [];
            try { stores.push(localStorage); } catch (_) {}
            try { stores.push(sessionStorage); } catch (_) {}
            for (const store of stores) {
                for (let i = 0; i < store.length; i++) {
                    const k = store.key(i) || '';
                    const v = store.getItem(k) || '';
                    if (/(token|auth|login|user|session|jwt)/i.test(k) && v && v !== 'null' && v !== 'undefined') {
                        storageHits.push(k);
                    }
                    if (/^(?:userId|h5_userInfo|accessToken|authToken|token|jwt)$/i.test(k) || /^lastUserActivityReport_\d+$/i.test(k)) {
                        if (v && !/^(?:null|undefined|-1|0|\{\}|\[\])$/i.test(v.trim())) strongStorageHits.push(k);
                    }
                }
            }
            const loginDialogs = Array.from(document.querySelectorAll('[role="dialog"],.ui-dialog,.nn-dialog,.nn-modal,.modal,.dialog'))
                .filter(visible)
                .filter(el => /登录|登陆|手机号|验证码|手机验证码/.test(txt(el)) && el.querySelectorAll('input').length > 0);
            const hasLoginForm = passwordInputs.length > 0 || loginFormNodes.length >= 2 || loginDialogs.length > 0;
            // Local storage survives a logout on NN.  These explicit guest
            // gates are rendered by protected community/plugin pages and
            // must invalidate a cached state even when stale storage remains.
            const guestGate = /当前浏览状态[，,]?\s*关注后可参与互动|您已在其他地方登录|登录已失效|请先登录/.test(bodyText);
            const hasPostLogin = postLoginNodes.some(el => txt(el).length > 0);
            const hasAuthStorage = strongStorageHits.length > 0;
            // Generic user/cache keys can survive logout. Only named account UI
            // or strong post-login storage keys count as a live session signal.
            const passed = !hasLoginForm && !guestGate && (hasPostLogin || hasAuthStorage);
            return {
                passed,
                reason: passed ? '' : (hasLoginForm ? '页面仍存在登录表单/账号密码验证码输入框' : (guestGate ? '页面展示游客态/登录失效提示' : '未检测到头像/用户中心/退出入口或有效登录 token')),
                evidence: {
                    url: location.href,
                    title: document.title,
                    loginFormCount: loginFormNodes.length,
                    passwordInputCount: passwordInputs.length,
                    loginDialogCount: loginDialogs.length,
                    postLoginCount: postLoginNodes.length,
                    postLoginSamples: postLoginNodes.slice(0, 5).map(txt),
                    storageKeys: storageHits.slice(0, 10),
                    strongStorageKeys: strongStorageHits.slice(0, 10)
                },
                bodyText
            };
        }""")
    except Exception as e:
        return {'passed': False, 'reason': '登录态检测异常: ' + str(e)[:200], 'evidence': {}, 'bodyText': ''}


async def _evaluate_page_health(page):
    """Detect infrastructure/page-mount failures early before semantic steps continue."""
    try:
        return await page.evaluate(r"""() => {
            const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
            const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const app = document.querySelector('#app');
            const bodyText = norm((document.body && document.body.innerText || '').slice(0, 1000));
            const title = document.title || '';
            const browserLow = /浏览器版本过低|浏览器过低|请升级浏览器|browser version/i.test(bodyText + ' ' + title);
            const appExists = !!app;
            const appMounted = !!(app && (app.children.length > 0 || norm(app.innerText || app.textContent || '').length > 0));
            const visibleInputs = Array.from(document.querySelectorAll('input, button, a, [role="button"]')).filter(visible).length;
            // Do not use generic class names such as "login" as an auth-page
            // signal. Plugin content can legitimately reuse those names (the
            // battle page does), which used to turn a healthy page into a
            // false "login dialog" failure. Require an actual visible auth
            // form or a dialog containing the relevant fields instead.
            const authInputs = Array.from(document.querySelectorAll('input')).filter(visible);
            const inputMeta = (el) => norm(`${el.placeholder || ''} ${el.name || ''} ${el.id || ''} ${el.type || ''}`).toLowerCase();
            const hasPasswordInput = authInputs.some(el => /password|密码/.test(inputMeta(el)));
            const hasPhoneInput = authInputs.some(el => /手机号|手机号码|phone|mobile/.test(inputMeta(el)));
            const hasCodeInput = authInputs.some(el => /验证码|校验码|动态码|captcha|sms.?code/.test(inputMeta(el)));
            const hasLoginDialog = Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], .el-dialog, .nn-dialog, .nn-modal, [class*="modal" i], [class*="dialog" i]'))
                .filter(visible)
                .some(el => /登录|登陆|手机号|验证码|login|sign in/i.test(norm(el.innerText || el.textContent || '')) && Array.from(el.querySelectorAll('input')).some(visible));
            const loginForm = hasPasswordInput || (hasPhoneInput && hasCodeInput) || hasLoginDialog;
            // Authentication state is validated independently. A mounted page
            // can retain auth form nodes without being a login-page failure.
            const loginPage = /\/(?:login|signin|auth)(?:[/?#]|$)/i.test(location.pathname);
            const bodyChildren = document.body ? document.body.children.length : 0;
            let healthy = true;
            let reason = '';
            if (browserLow) {
                healthy = false;
                reason = '页面命中“浏览器版本过低”兼容性降级页';
            } else if (appExists && !appMounted) {
                healthy = false;
                reason = '#app 存在但未挂载内容，疑似前端资源/脚本未正常初始化';
            } else if (!appExists && visibleInputs === 0 && bodyChildren <= 2 && bodyText.length < 80) {
                healthy = false;
                reason = '页面几乎空白，未检测到可交互内容，疑似前端未成功挂载';
            } else if (loginPage) {
                healthy = false;
                reason = '页面仍处于登录页/登录弹窗状态';
            }
            return {
                healthy,
                reason,
                evidence: {
                    url: location.href,
                    title,
                    appExists,
                    appMounted,
                    appChildCount: app ? app.children.length : 0,
                    visibleInteractiveCount: visibleInputs,
                    bodyChildren,
                    loginPage,
                    bodyText,
                }
            };
        }""")
    except Exception as e:
        return {'healthy': False, 'reason': '页面健康检查异常: ' + str(e)[:200], 'evidence': {}}


async def _wait_for_page_ready(page, timeout_seconds=30):
    """Wait for a usable SPA shell without treating login redirects as navigation failures."""
    deadline = asyncio.get_running_loop().time() + max(1, timeout_seconds)
    # ``domcontentloaded`` only means the SPA shell arrived.  On NN plugin
    # pages, the real controls frequently mount a fraction of a second later.
    # Require a small stable ready window so an empty/skeleton first frame
    # never gets treated as a usable page.
    healthy_rounds = 0
    last_health = {'healthy': False, 'reason': '页面尚未开始加载', 'evidence': {}}

    while True:
        try:
            # A browser process can become unresponsive while an SPA route is
            # mounting. The outer readiness deadline is ineffective unless an
            # individual page evaluation also has a hard timeout.
            last_health = await asyncio.wait_for(_evaluate_page_health(page), timeout=8)
        except asyncio.TimeoutError:
            last_health = {
                'healthy': False,
                'reason': '页面健康检查超时，浏览器未响应',
                'evidence': {'url': getattr(page, 'url', '')},
            }
        evidence = last_health.get('evidence') or {}
        reason = str(last_health.get('reason') or '')

        if last_health.get('healthy'):
            healthy_rounds += 1
            if healthy_rounds < 3:
                await asyncio.sleep(0.35)
                continue
            last_health['ready_state'] = 'ready'
            return last_health
        healthy_rounds = 0

        # A protected route may deliberately redirect before login. The login
        # shell is a valid navigation result and later login steps handle it.
        if evidence.get('loginPage') and (evidence.get('appMounted') or evidence.get('visibleInteractiveCount', 0) > 0):
            return {
                **last_health,
                'healthy': True,
                'ready_state': 'login_redirect',
                'reason': '',
            }

        # These states are deterministic page failures. Retrying the same DOM
        # for the entire timeout window cannot make them usable.
        if '浏览器版本过低' in reason:
            return last_health

        if asyncio.get_running_loop().time() >= deadline:
            return last_health
        await asyncio.sleep(0.75)


def _extract_assert_expected_texts(description):
    """从自然语言断言中提取真正应该出现在页面上的文本。"""
    desc = str(description or '').strip()
    if not desc:
        return []
    quoted = re.findall(r'["\u201c\u300c]([^"\u201d\u300d]{1,80})["\u201d\u300d]', desc)
    if quoted:
        return _dedupe_keep_order([item.strip() for item in quoted if item.strip()])[:6]
    text = re.sub(r'^(断言|验证|检查|确认)\s*[：:]?\s*', '', desc).strip()
    patterns = [
        r'(?:页面|左侧页面|右侧页面|当前页面).*?(?:找到|看到|显示|出现|包含|存在)\s*([^，。；;,]+?)(?:字样|文本|内容)?$',
        r'(?:找到|看到|显示|出现|包含|存在)\s*([^，。；;,]+?)(?:字样|文本|内容)?$',
    ]
    candidates = []
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            candidates.append(m.group(1))
    candidates.extend(re.findall(r"[\"“']([^\"”']{1,80})[\"”']", desc))
    if not candidates and text:
        candidates.append(text)
    results = []
    for cand in candidates:
        cand = cand.strip().strip(' ：:，,。；;').replace('字样', '').strip()
        quoted_parts = re.findall(r"[\"“']([^\"”']{1,80})[\"”']", cand)
        if len(quoted_parts) >= 2:
            parts = quoted_parts
        else:
            parts = [
                part.strip().strip('"').strip("'").strip('“').strip('”')
                for part in re.split(r'\s*(?:[+＋、,，/]|和|与|以及|及|并且)\s*', cand)
                if part.strip()
            ]
        results.extend(parts or [cand])
    cleaned = []
    for item in results:
        item = item.strip().strip(' ：:，,。；;').strip('"').strip("'").strip('“').strip('”')
        if len(item) >= 2:
            cleaned.append(item)
    return _dedupe_keep_order(cleaned)[:6]


async def _get_page_text_diagnostics(page, targets=None):
    """采样当前页面可见文本和与目标相近的元素，供失败日志定位真实 DOM 状态。"""
    targets = targets or []
    try:
        return await page.evaluate(r"""(targets) => {
            const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            };
            const bodyText = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 500);
            const samples = [];
            const nodes = Array.from(document.querySelectorAll('a,button,[role=button],[role=link],li,[class*=item i],[class*=card i],[class*=result i],div,span')).slice(0, 2000);
            for (const [index, el] of nodes.entries()) {
                if (!visible(el)) continue;
                const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                if (!txt || txt.length > 120) continue;
                if (targets.length === 0 || targets.some(t => txt.includes(t) || t.includes(txt))) {
                    samples.push({tag: el.tagName, role: el.getAttribute('role') || '', cls: (el.className || '').toString().slice(0, 80), text: txt.slice(0, 120)});
                    if (samples.length >= 10) break;
                }
            }
            return {url: location.href, title: document.title, bodyText, samples};
        }""", targets)
    except Exception as exc:
        return {'error': str(exc)[:200]}

def _build_strategies(description, action_type='type'):
    """基于自然语言描述，生成按优先级排序的 CSS/Playwright 选择器列表"""
    desc = description.lower()
    strategies = []

    if action_type in ('type', 'fill', 'type_input'):
        if any(kw in description for kw in ['验证码', '校验码', '动态码']) or 'code' in desc or 'captcha' in desc:
            strategies = [
                'input[placeholder*="验证码"]',
                'input[placeholder*="请输入验证码"]',
                'input[placeholder*="校验码"]',
                'input[placeholder*="动态码"]',
                'input[placeholder*="code" i]',
                'input[placeholder*="captcha" i]',
                'input[name*="code" i]',
                'input[name*="captcha" i]',
                'input[name*="verify" i]',
                'input[type="number"][maxlength="6"]',
                'input[type="number"]',
            ]
        elif any(kw in description for kw in ['手机号', '手机', '电话', '联系电话', '移动电话']) or 'phone' in desc or 'mobile' in desc or 'tel' in desc:
            strategies = [
                'input[placeholder*="请输入手机"]',
                'input[placeholder*="手机号"]',
                'input[placeholder*="手机"]',
                'input[placeholder*="电话"]',
                'input[placeholder*="phone" i]',
                'input[placeholder*="mobile" i]',
                'input[name*="phone" i]',
                'input[name*="mobile" i]',
                'input[name*="tel" i]',
                'input[type="tel"]',
                'input[type="number"][maxlength="11"]',
            ]
        elif any(kw in description for kw in ['密码', '口令', '暗码']) or 'password' in desc or 'passwd' in desc:
            strategies = [
                'input[type="password"]',
                'input[placeholder*="密码"]',
                'input[placeholder*="口令"]',
                'input[placeholder*="password" i]',
                'input[placeholder*="passwd" i]',
                'input[name*="password" i]',
                'input[name*="passwd" i]',
            ]
        elif any(kw in description for kw in ['邮箱', '邮件', '电子邮件']) or 'email' in desc or 'mail' in desc:
            strategies = [
                'input[type="email"]',
                'input[placeholder*="邮箱"]',
                'input[placeholder*="邮件"]',
                'input[placeholder*="email" i]',
                'input[placeholder*="mail" i]',
                'input[name*="email" i]',
                'input[name*="mail" i]',
            ]
        elif any(kw in description for kw in ['用户名', '账号', '账户', '登录名', '工号']) or 'user' in desc or 'account' in desc or 'login' in desc:
            strategies = [
                'input[placeholder*="用户名"]',
                'input[placeholder*="账号"]',
                'input[placeholder*="手机"]',
                'input[placeholder*="手机号"]',
                'input[placeholder*="请输入手机号"]',
                'input[placeholder*="账户"]',
                'input[placeholder*="登录名"]',
                'input[placeholder*="工号"]',
                'input[placeholder*="user" i]',
                'input[placeholder*="account" i]',
                'input[name*="user" i]',
                'input[name*="account" i]',
                'input[name*="mobile" i]',
                'input[name*="phone" i]',
                'input[type="tel"]',
                'input[name*="login" i]',
            ]
        elif any(kw in description for kw in ['搜索', '查找', '检索']) or 'search' in desc or 'query' in desc:
            strategies = [
                'input[placeholder*="搜索"]',
                'input[placeholder*="查找"]',
                'input[placeholder*="检索"]',
                'input[placeholder*="search" i]',
                'input[placeholder*="query" i]',
                'input[name*="search" i]',
                'input[name*="query" i]',
                'input[type="search"]',
            ]
        elif any(kw in description for kw in ['姓名', '名字', '真实姓名', '昵称']) or 'name' in desc:
            strategies = [
                'input[placeholder*="姓名"]',
                'input[placeholder*="名字"]',
                'input[placeholder*="真实姓名"]',
                'input[placeholder*="昵称"]',
                'input[placeholder*="name" i]',
                'input[name*="name" i]',
                'input[name*="realname" i]',
                'input[name*="nickname" i]',
            ]
        elif any(kw in description for kw in ['身份证', '证件号', '身份证号']) or 'idcard' in desc or 'identity' in desc:
            strategies = [
                'input[placeholder*="身份证"]',
                'input[placeholder*="证件号"]',
                'input[placeholder*="idcard" i]',
                'input[name*="idcard" i]',
                'input[name*="identity" i]',
                'input[name*="cert" i]',
            ]
        elif any(kw in description for kw in ['银行卡', '卡号', '信用卡']) or 'bank' in desc or 'card' in desc:
            strategies = [
                'input[placeholder*="银行卡"]',
                'input[placeholder*="卡号"]',
                'input[placeholder*="bank" i]',
                'input[placeholder*="card" i]',
                'input[name*="bank" i]',
                'input[name*="card" i]',
            ]
        elif any(kw in description for kw in ['地址', '详细地址', '收货地址', '住址']) or 'address' in desc:
            strategies = [
                'input[placeholder*="地址"]',
                'input[placeholder*="住址"]',
                'input[placeholder*="address" i]',
                'input[name*="address" i]',
                'textarea[placeholder*="地址"]',
            ]
        elif any(kw in description for kw in ['邮编', '邮政编码', '邮码']) or 'zip' in desc or 'postal' in desc:
            strategies = [
                'input[placeholder*="邮编"]',
                'input[placeholder*="邮政编码"]',
                'input[placeholder*="zip" i]',
                'input[placeholder*="postal" i]',
                'input[name*="zip" i]',
                'input[name*="postal" i]',
            ]
        elif any(kw in description for kw in ['金额', '价格', '价钱', '费用', '总额', '总价']) or 'price' in desc or 'amount' in desc or 'money' in desc:
            strategies = [
                'input[placeholder*="金额"]',
                'input[placeholder*="价格"]',
                'input[placeholder*="价钱"]',
                'input[placeholder*="费用"]',
                'input[placeholder*="price" i]',
                'input[placeholder*="amount" i]',
                'input[placeholder*="money" i]',
                'input[name*="price" i]',
                'input[name*="amount" i]',
                'input[name*="money" i]',
            ]
        elif any(kw in description for kw in ['数量', '个数', '件数', '数目']) or 'quantity' in desc or 'count' in desc or 'num' in desc:
            strategies = [
                'input[placeholder*="数量"]',
                'input[placeholder*="个数"]',
                'input[placeholder*="件数"]',
                'input[placeholder*="quantity" i]',
                'input[placeholder*="count" i]',
                'input[placeholder*="num" i]',
                'input[name*="quantity" i]',
                'input[name*="count" i]',
                'input[name*="num" i]',
                'input[type="number"]',
            ]
        elif any(kw in description for kw in ['日期', '时间', '生日', '出生日期']) or 'date' in desc or 'time' in desc or 'birthday' in desc:
            strategies = [
                'input[type="date"]',
                'input[placeholder*="日期"]',
                'input[placeholder*="时间"]',
                'input[placeholder*="生日"]',
                'input[placeholder*="date" i]',
                'input[placeholder*="time" i]',
                'input[name*="date" i]',
                'input[name*="time" i]',
                '.el-date-editor input',
                '.ant-picker input',
            ]
        elif any(kw in description for kw in ['链接', '网址', 'url', '网站']) or 'url' in desc or 'link' in desc:
            strategies = [
                'input[type="url"]',
                'input[placeholder*="链接"]',
                'input[placeholder*="网址"]',
                'input[placeholder*="url" i]',
                'input[placeholder*="link" i]',
                'input[name*="url" i]',
                'input[name*="link" i]',
            ]
        elif any(kw in description for kw in ['备注', '描述', '说明', '简介', '摘要', '留言', '评论']) or 'remark' in desc or 'desc' in desc or 'comment' in desc:
            strategies = [
                'textarea[placeholder*="备注"]',
                'textarea[placeholder*="描述"]',
                'textarea[placeholder*="说明"]',
                'textarea[placeholder*="简介"]',
                'textarea[placeholder*="留言"]',
                'textarea[placeholder*="评论"]',
                'textarea[placeholder*="remark" i]',
                'textarea[placeholder*="desc" i]',
                'textarea[placeholder*="comment" i]',
                'textarea',
                'input[placeholder*="备注"]',
                'input[placeholder*="描述"]',
                'input[name*="remark" i]',
                'input[name*="desc" i]',
                'input[name*="comment" i]',
            ]
        elif any(kw in description for kw in ['标题', '名称', '主题']) or 'title' in desc or 'subject' in desc:
            strategies = [
                'input[placeholder*="标题"]',
                'input[placeholder*="名称"]',
                'input[placeholder*="主题"]',
                'input[placeholder*="title" i]',
                'input[placeholder*="subject" i]',
                'input[name*="title" i]',
                'input[name*="subject" i]',
                'input[name*="name" i]',
            ]
        elif any(kw in description for kw in ['内容', '正文', '文本', '消息']) or 'content' in desc or 'text' in desc or 'message' in desc:
            strategies = [
                'textarea[placeholder*="内容"]',
                'textarea[placeholder*="正文"]',
                'textarea[placeholder*="文本"]',
                'textarea[placeholder*="消息"]',
                'textarea[placeholder*="content" i]',
                'textarea[placeholder*="text" i]',
                'textarea[placeholder*="message" i]',
                'textarea',
                '.ql-editor',
                '.w-e-text',
                '[contenteditable="true"]',
            ]
        else:
            keywords = re.findall(r'[\u4e00-\u9fa5]{2,4}', description)
            for kw in keywords[:3]:
                strategies.append(f'input[placeholder*="{kw}"]')
                strategies.append(f'textarea[placeholder*="{kw}"]')
            strategies.extend([
                'textarea:visible',
                'input:visible:not([type="hidden"]):not([type="submit"]):not([type="button"]):not([type="checkbox"]):not([type="radio"]):not([readonly]):not(.cursor-pointer):not([placeholder*="请选择"])',
                '[contenteditable="true"]:visible',
            ])

    elif action_type in ('click', 'try_click'):
        contextual_click_strategies = _build_contextual_click_strategies(description)
        if contextual_click_strategies:
            strategies = contextual_click_strategies
        elif any(kw in description for kw in ['关闭', '关掉', '收起', '隐藏']) or 'close' in desc or 'dismiss' in desc:
            strategies = [
                'button[aria-label="Close"]',
                'button[aria-label="关闭"]',
                'button[aria-label="close" i]',
                '.nn-dialog-close',
                '.el-dialog__close',
                '.el-drawer__close',
                '.ant-modal-close',
                '.ant-drawer-close',
                '.modal-close',
                '.close-btn',
                '.close-button',
                'button:has-text("关闭")',
                'button:has-text("×")',
                'button:has-text("✕")',
                '[role="dialog"] button:last-child',
            ]
        elif any(kw in description for kw in ['确认', '确定', '提交', '保存', '发送', '发布', '下单', '支付', '结算']) or any(kw in desc for kw in ['confirm', 'submit', 'save', 'send', 'publish', 'pay']):
            strategies = [
                'button[type="submit"]',
                'button:has-text("确认")',
                'button:has-text("确定")',
                'button:has-text("提交")',
                'button:has-text("保存")',
                'button:has-text("发送")',
                'button:has-text("发布")',
                'button:has-text("下单")',
                'button:has-text("支付")',
                'button:has-text("结算")',
                'button:has-text("confirm")',
                'button:has-text("submit")',
                'button:has-text("save")',
                'button:has-text("send")',
                'button:has-text("publish")',
                'button:has-text("pay")',
                'button.primary',
                'button.el-button--primary',
                'button.ant-btn-primary',
                '.nn-button--primary',
            ]
        elif any(kw in description for kw in ['登录入口', '登陆入口', '登录弹窗', '登陆弹窗']) or ('login' in desc and any(kw in description for kw in ['入口', '弹窗', '头像', '图标'])):
            strategies = [
                'img[alt*="默认头像"]',
                'img[alt*="头像"]',
                'img[alt*="avatar" i]',
                '[class*="avatar" i]',
                '[class*="user" i]',
                '[class*="account" i]',
                'a:has-text("登录")',
                'button:has-text("登录")',
            ]
        elif any(kw in description for kw in ['登录', '登陆', '注册', '登入']) or any(kw in desc for kw in ['login', 'signin', 'signup', 'register']):
            strategies = [
                'button:has-text("登录")',
                'button:has-text("登陆")',
                'button:has-text("注册")',
                'button:has-text("登入")',
                'button:has-text("login")',
                'button:has-text("sign in")',
                'button:has-text("sign up")',
                'button:has-text("register")',
                'a:has-text("登录")',
                'a:has-text("登陆")',
                'a:has-text("注册")',
                'a:has-text("login")',
                '.login-btn',
                '.login-button',
                '.login-icon',
                '.login-link',
                '.header-login',
                '.nav-login',
                '.btn-login',
                '.sign-in',
                '#login-btn',
                '#loginBtn',
                '#login',
                '[class*="login" i]',
                '[id*="login" i]',
                'button[type="submit"]',
                'button.primary',
            ]
        elif any(kw in description for kw in ['取消', '放弃', '撤销']) or 'cancel' in desc:
            strategies = [
                'button:has-text("取消")',
                'button:has-text("放弃")',
                'button:has-text("撤销")',
                'button:has-text("cancel")',
                'button.cancel',
                'button.el-button--default',
                'button.ant-btn-default',
            ]
        elif any(kw in description for kw in ['删除', '移除', '清除', '卸载']) or any(kw in desc for kw in ['delete', 'remove', 'clear']):
            strategies = [
                'button:has-text("删除")',
                'button:has-text("移除")',
                'button:has-text("清除")',
                'button:has-text("delete")',
                'button:has-text("remove")',
                'button:has-text("clear")',
                'button.danger',
                'button.el-button--danger',
                'button.ant-btn-dangerous',
            ]
        elif any(kw in description for kw in ['编辑', '修改', '更改', '变更']) or any(kw in desc for kw in ['edit', 'modify', 'update', 'change']):
            strategies = [
                'button:has-text("编辑")',
                'button:has-text("修改")',
                'button:has-text("更改")',
                'button:has-text("edit")',
                'button:has-text("modify")',
                'button:has-text("update")',
                'button:has-text("change")',
            ]
        elif any(kw in description for kw in ['添加', '新增', '创建', '新建', '增加']) or any(kw in desc for kw in ['add', 'create', 'new']):
            strategies = [
                'button:has-text("添加")',
                'button:has-text("新增")',
                'button:has-text("创建")',
                'button:has-text("新建")',
                'button:has-text("增加")',
                'button:has-text("add")',
                'button:has-text("create")',
                'button:has-text("new")',
            ]
        elif any(kw in description for kw in ['搜索', '查询', '查找', '检索', '查找']) or any(kw in desc for kw in ['search', 'query', 'find', 'lookup']):
            strategies = [
                'button:has-text("搜索")',
                'button:has-text("查询")',
                'button:has-text("查找")',
                'button:has-text("检索")',
                'button:has-text("search")',
                'button:has-text("query")',
                'button:has-text("find")',
                'button[type="submit"]',
            ]
        elif any(kw in description for kw in ['刷新', '重试', '重新加载', '重新尝试']) or any(kw in desc for kw in ['refresh', 'retry', 'reload']):
            strategies = [
                'button:has-text("刷新")',
                'button:has-text("重试")',
                'button:has-text("重新加载")',
                'button:has-text("refresh")',
                'button:has-text("retry")',
                'button:has-text("reload")',
            ]
        elif any(kw in description for kw in ['下一步', '上一步', '返回', '后退', '前进']) or any(kw in desc for kw in ['next', 'prev', 'back', 'forward']):
            strategies = [
                'button:has-text("下一步")',
                'button:has-text("上一步")',
                'button:has-text("返回")',
                'button:has-text("后退")',
                'button:has-text("前进")',
                'button:has-text("next")',
                'button:has-text("prev")',
                'button:has-text("back")',
                'button:has-text("forward")',
            ]
        elif any(kw in description for kw in ['导出', '导入', '下载', '上传']) or any(kw in desc for kw in ['export', 'import', 'download', 'upload']):
            strategies = [
                'button:has-text("导出")',
                'button:has-text("导入")',
                'button:has-text("下载")',
                'button:has-text("上传")',
                'button:has-text("export")',
                'button:has-text("import")',
                'button:has-text("download")',
                'button:has-text("upload")',
            ]
        elif any(kw in description for kw in ['同意', '拒绝', '接受', '反对', '批准', '驳回']) or any(kw in desc for kw in ['agree', 'reject', 'accept', 'decline', 'approve']):
            strategies = [
                'button:has-text("同意")',
                'button:has-text("拒绝")',
                'button:has-text("接受")',
                'button:has-text("反对")',
                'button:has-text("批准")',
                'button:has-text("驳回")',
                'button:has-text("agree")',
                'button:has-text("reject")',
                'button:has-text("accept")',
                'button:has-text("decline")',
                'button:has-text("approve")',
                'span.nn-checkbox',
                'span[class*="checkbox"]',
                'input[type="checkbox"]',
                '[role="checkbox"]',
                '.el-checkbox__input',
                '.ant-checkbox-wrapper',
            ]
        elif any(kw in description for kw in ['勾选', '选中', '勾上', '选择', '同意', 'checkbox', '复选']) or 'checkbox' in desc:
            strategies = [
                'input[type="checkbox"]',
                '[role="checkbox"]',
                '.el-checkbox__input',
                '.ant-checkbox-wrapper',
                'label:has(input[type="checkbox"])',
            ]
        elif any(kw in description for kw in ['单选', 'radio']) or 'radio' in desc:
            strategies = [
                'input[type="radio"]',
                '[role="radio"]',
                '.el-radio__input',
                '.ant-radio-wrapper',
                'label:has(input[type="radio"])',
            ]
        elif any(kw in description for kw in ['下拉', '选择', '请选择', 'select', 'dropdown']):
            strategies = [
                '.el-select',
                '.ant-select',
                'select',
                '[role="combobox"]',
                '[role="listbox"]',
                '.el-input__inner[readonly]',
            ]
        else:
            quoted = re.findall(r'[""\'](.+?)[""\']', description)
            target_match = re.match(r'^\s*(?:点击|点|按)\s+(.+?)\s*$', str(description or ''))
            explicit_target = target_match.group(1).strip() if target_match else ''
            if explicit_target:
                # A named target must never silently fall through to the first
                # visible button.  Navigation items are often divs, not buttons.
                for selector in (
                    f'button:has-text("{explicit_target}")',
                    f'a:has-text("{explicit_target}")',
                    f'[role="button"]:has-text("{explicit_target}")',
                    f'[role="link"]:has-text("{explicit_target}")',
                    f'li:has-text("{explicit_target}")',
                    f'[class*="item" i]:has-text("{explicit_target}")',
                    f'[class*="menu" i]:has-text("{explicit_target}")',
                    f'[class*="nav" i]:has-text("{explicit_target}")',
                    f'[class*="card" i]:has-text("{explicit_target}")',
                    f'div:has-text("{explicit_target}")',
                    f'text="{explicit_target}"',
                ):
                    strategies.append(selector)
            for text in quoted[:3]:
                strategies.append(f'button:has-text("{text}")')
                strategies.append(f'a:has-text("{text}")')
                strategies.append(f'[role="button"]:has-text("{text}")')
            keywords = re.findall(r'[\u4e00-\u9fa5]{2,6}', description)
            for kw in keywords[:3]:
                strategies.append(f'button:has-text("{kw}")')
            if not explicit_target:
                strategies.extend([
                    'button:visible',
                    'a:visible',
                    '[role="button"]:visible',
                    '[role="link"]:visible',
                ])

    elif action_type == 'assert':
        strategies = []

    else:
        strategies = [
            'input:visible:not([type="hidden"]):not([type="submit"]):not([type="button"])',
            'button:visible',
            'textarea:visible',
            'a:visible',
            '[role="button"]:visible',
            '[role="link"]:visible',
        ]

    return strategies


async def _find_element_for_type(page, step, execution_record=None):
    """统一智能元素发现引擎 - 所有 action_type 共用"""
    description = step.get('description', '')
    action_type = step.get('action_type', 'type')
    element_data = step.get('element')

    if element_data and element_data.get('locator_value'):
        locator_str = element_data['locator_value']
        strategy = element_data.get('locator_strategy', 'css')
        try:
            if strategy == 'playwright':
                loc = page.locator(locator_str).first
                if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                    return loc
            else:
                if _is_top_community_search_description(description) or '顶部社区搜索框' in str(element_data.get('name', '')):
                    if action_type in ('type', 'fill', 'type_input'):
                        top_trigger_selectors = [
                            'header .cursor-pointer:has(.nicon-a-search-linesousuo-xianxing)',
                            'header [class*="cursor-pointer"]:has([class*="search" i])',
                            'header [class*="search" i]',
                            '.appHeader .cursor-pointer:has(.nicon-a-search-linesousuo-xianxing)',
                        ]
                        for trigger_css in top_trigger_selectors:
                            try:
                                trigger = page.locator(trigger_css).first
                                if await trigger.count() > 0 and await trigger.is_visible(timeout=800):
                                    await trigger.click()
                                    if execution_record:
                                        execution_record.logs += f"  TOP_SEARCH_TRIGGER_CLICKED: {trigger_css}" + chr(10)
                                    break
                            except Exception:
                                continue
                        popup_input_selectors = [
                            'input[placeholder*="搜索社区"]',
                            'input[placeholder*="用户昵称"]',
                            'input[placeholder*="NN号"]',
                            '.nn-input--large input[placeholder*="搜索"]',
                        ]
                        for popup_css in popup_input_selectors:
                            try:
                                popup_loc = page.locator(popup_css).first
                                if await popup_loc.count() > 0 and await popup_loc.is_visible(timeout=2500):
                                    if execution_record:
                                        execution_record.logs += f"  TOP_SEARCH_POPUP_INPUT_HIT: {popup_css}" + chr(10)
                                    return popup_loc
                            except Exception:
                                continue
                    js_result = await page.evaluate('''(selectorText) => {
                        const selectors = selectorText.split(',').map(s => s.trim()).filter(Boolean);
                        const badWords = ['output', '输出', 'editor', 'monaco', 'textarea', '评论', '内容', '正文', '搜索全部社区'];
                        const candidates = [];
                        for (const sel of selectors) {
                            let nodes = [];
                            try { nodes = Array.from(document.querySelectorAll(sel)); } catch (e) { continue; }
                            for (let index = 0; index < nodes.length; index++) {
                                const el = nodes[index];
                                const tag = (el.tagName || '').toLowerCase();
                                if (!['input'].includes(tag) && el.getAttribute('contenteditable') !== 'true') continue;
                                if (tag === 'textarea') continue;
                                const rect = el.getBoundingClientRect();
                                const style = window.getComputedStyle(el);
                                if (rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') continue;
                                const hay = [el.className, el.id, el.getAttribute('placeholder'), el.getAttribute('aria-label'), el.closest('[class]')?.className || ''].join(' ').toLowerCase();
                                if (badWords.some(w => hay.includes(w))) continue;
                                const inHeader = !!el.closest('header, nav, [class*="header" i], [class*="nav" i], [class*="top" i]');
                                const searchHint = /搜索|社区|search|community/.test(hay);
                                let score = 0;
                                if (inHeader) score += 1000;
                                if (searchHint) score += 300;
                                if (tag === 'input') score += 100;
                                if (el.type === 'search') score += 80;
                                score -= Math.max(0, rect.top);
                                candidates.push({sel, index, score, top: rect.top, left: rect.left, placeholder: el.getAttribute('placeholder') || '', value: el.value || ''});
                            }
                        }
                        candidates.sort((a, b) => b.score - a.score);
                        return candidates[0] ? {found: true, selector: candidates[0].sel, detail: candidates[0]} : {found: false, candidates};
                    }''', locator_str)
                    if js_result and js_result.get('found'):
                        if execution_record:
                            execution_record.logs += f"  BOUND_LOCATOR_HIT: {js_result.get('detail')}" + chr(10)
                        loc = page.locator(js_result['selector']).nth(int(js_result.get('detail', {}).get('index', 0)))
                        if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                            return loc
                loc = page.locator(f'css={locator_str}').first
                if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                    return loc
        except Exception:
            pass

    if action_type == 'click':
        dialog_close_loc = await _find_active_dialog_close_target(page, description, execution_record)
        if dialog_close_loc:
            return dialog_close_loc
        click_constraints = step.get('click_constraints') or extract_click_constraints(
            str(step.get('display_description') or description),
            fallback_target=str(step.get('target_text') or ''),
        )
        constrained_loc = await _find_constraint_aware_click_target(page, step, execution_record)
        if constrained_loc:
            return constrained_loc
        if _is_community_result_click_description(description):
            community_loc = await _find_community_result_click_target(page, description, execution_record)
            if community_loc:
                return community_loc
        # A constrained click is an explicit business requirement. Do not
        # downgrade it to a page-wide or target-text-only click: that is how a
        # nearby same-name element gets clicked and the next step fails later.
        if has_meaningful_click_constraints(click_constraints):
            if execution_record:
                execution_record.logs += '  CONSTRAINT_AWARE_CLICK_REJECT: 未找到满足目标和约束的元素，已禁止通用降级点击\n'
            return None
        exact_target = str(step.get('target_text') or '').strip()
        if not exact_target:
            match = re.match(r'^\s*(?:点击|点|按)\s+(.+?)\s*$', str(description or ''))
            exact_target = match.group(1).strip() if match else ''
        exact_loc = await _find_exact_text_click_target(page, exact_target, execution_record)
        if exact_loc:
            if execution_record and has_meaningful_click_constraints(click_constraints):
                execution_record.logs += '  CONSTRAINT_AWARE_CLICK_FALLBACK: 约束未完整命中，已使用精确目标文本点击\n'
            return exact_loc
    strategies = _build_strategies(description, action_type)
    if not strategies:
        return None

    import time as _time
    _find_start = _time.time()
    _FIND_TIMEOUT = 25
    try:
        _css_list = [s for s in strategies if not s.startswith('text=') and '>>' not in s and ':has-text' not in s]
        if _css_list:
            _js_check = await page.evaluate('''(selectors) => {
                for (const sel of selectors) {
                    try {
                        const els = document.querySelectorAll(sel);
                        for (const el of els) {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                                return {found: true, selector: sel, tag: el.tagName, text: (el.textContent || '').substring(0, 30)};
                            }
                        }
                    } catch(e) {}
                }
                return {found: false};
            }''', _css_list)
            if _js_check and _js_check.get('found'):
                _hit_sel = _js_check['selector']
                try:
                    loc = page.locator(_hit_sel).first
                    if await loc.count() > 0 and await loc.is_visible(timeout=1000):
                        return loc
                except Exception:
                    pass
    except Exception:
        pass

    modal_selectors = [
        '.nn-dialog', '.nn-modal', '.nn-popup', '.nn-drawer',
        '[role="dialog"]', '[role="alertdialog"]',
        '.el-dialog', '.el-drawer', '.el-message-box',
        '.ant-modal', '.ant-drawer',
        '.modal', '.dialog', '.popup', '.drawer',
    ]

    for modal_sel in modal_selectors:
        if _time.time() - _find_start > _FIND_TIMEOUT:
            break
        for css in strategies:
            if _time.time() - _find_start > _FIND_TIMEOUT:
                break
            try:
                full_css = f'{modal_sel} {css}'
                loc = page.locator(full_css).first
                if await loc.count() > 0 and await loc.is_visible(timeout=1000):
                    return loc
            except Exception:
                continue

    _match_log = []
    for _idx, css in enumerate(strategies):
        if _time.time() - _find_start > _FIND_TIMEOUT:
            break
        try:
            loc = page.locator(css).first
            _cnt = await loc.count()
            if _cnt > 0:
                try:
                    _vis = await loc.is_visible(timeout=1000)
                except Exception:
                    _vis = 'timeout'
                _match_log.append(f"{_idx}:{css} cnt={_cnt} vis={_vis}")
                if _vis is True:
                    if execution_record: execution_record.logs += f"  STRATEGY_HIT: #{_idx} {css} count={_cnt} visible=True\n"
                    return loc
            else:
                _match_log.append(f"{_idx}:{css} cnt=0")
        except Exception as _e:
            _match_log.append(f"{_idx}:{css} ERR={_e}")
            continue
    if execution_record: execution_record.logs += f"  STRATEGY_2B_LOG (last10): {_match_log[-10:]}\n"

    try:
        _css_strategies = [s for s in strategies if ':has-text(' not in s and 'text=' not in s and '>>' not in s]
        js_result = await page.evaluate(r"""(selectors) => {
            const results = [];
            for (const sel of selectors) {
                try {
                    const el = document.querySelector(sel);
                    if (el) {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        const hidden = style.display === "none" || style.visibility === "hidden" || rect.width === 0 || rect.height === 0;
                        if (!hidden) {
                            return { found: true, selector: sel, tried: results.length };
                        }
                        results.push(sel + ':hidden');
                    } else {
                        results.push(sel + ':null');
                    }
                } catch(e) {
                    results.push(sel + ':ERR=' + e.message.substring(0,30));
                }
            }
            return { found: false, tried: results.length, last5: results.slice(-5) };
        }""", _css_strategies)
        if js_result and js_result.get("found"):
            sel = js_result["selector"]
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    return loc
            except Exception:
                pass
            return {"_js_click_selector": sel}
        logger.error(f"[FIND_ELEMENT] JS fallback returned found=False for desc={description!r}, action={action_type}")
        logger.debug(f"[FIND_ELEMENT] strategies count={len(strategies)}, first5={strategies[:5]}")
        logger.debug(f"[FIND_ELEMENT] js_result={js_result}")
        _test_js = await page.evaluate(r"""() => {
            const el = document.querySelector('img[alt*="头像"]');
            return el ? {found: true, alt: el.alt, visible: el.offsetParent !== null} : {found: false};
        }""")
        logger.debug(f"[FIND_ELEMENT] direct img[alt*头像] test={_test_js}")
        return None
    except Exception as _jse:
        pass

    return None
