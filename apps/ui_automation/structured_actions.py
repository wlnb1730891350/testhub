"""Structured action compiler for AI UI automation.

This module keeps the user's natural-language authoring style, but compiles
high-risk business flows into explicit structured actions before execution.
Fallback generic actions are still emitted for unsupported cases so existing
cases remain compatible.
"""
import re
from typing import Dict, List, Optional

from .click_constraints import extract_click_constraints


Action = Dict[str, object]


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


def _strip_quotes(text: str) -> str:
    return str(text or '').strip().strip('"').strip("'").strip('“').strip('”').strip()


def is_top_community_search_description(description: str) -> bool:
    desc = str(description or '').lower()
    if not desc:
        return False
    has_search = any(kw in desc for kw in ['搜索', '查找', '检索', 'search'])
    has_scope = any(kw in desc for kw in ['顶部', '顶栏', '上方', '上面', '导航栏', '导航', 'header', 'nav', '社区搜索', 'community'])
    return has_search and has_scope


def extract_assert_expected_texts(description: str) -> List[str]:
    desc = str(description or '').strip()
    if not desc:
        return []
    quoted = re.findall(r'["\u201c\u300c]([^"\u201d\u300d]{1,80})["\u201d\u300d]', desc)
    if quoted:
        targets = [_strip_quotes(item.strip()) for item in quoted if item.strip()]
        # Some UIs render a ranking name and its active period as adjacent
        # controls (for example, "吃鸡榜" + "日榜"), not as one literal label.
        # Keep authoring natural while compiling that stable composed meaning
        # into the two DOM facts the page can actually expose.
        expanded = []
        for target in targets:
            rank_match = re.fullmatch(r'(.+?)(日榜|周榜|月榜|总榜|地区榜)', target)
            if rank_match:
                rank_name, period = rank_match.groups()
                expanded.extend([f'{rank_name}榜', period])
            else:
                expanded.append(target)
        return _dedupe_keep_order(expanded)[:6]
    text = re.sub(r'^(断言|验证|检查|确认)\s*[：:]?\s*', '', desc).strip()
    patterns = [
        r'(?:页面|左侧页面|右侧页面|当前页面).*?(?:找到|看到|显示|出现|包含|存在)\s*(.+?)(?:字样|文本|内容)?$',
        r'(?:找到|看到|显示|出现|包含|存在)\s*(.+?)(?:字样|文本|内容)?$',
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
                _strip_quotes(part.strip())
                for part in re.split(r'\s*(?:[+＋、,，/]|和|与|以及|及|并且)\s*', cand)
                if part.strip()
            ]
        results.extend(parts or [cand])

    cleaned = []
    for item in results:
        item = _strip_quotes(str(item).strip().strip(' ：:，,。；;'))
        if len(item) >= 2:
            cleaned.append(item)
    return _dedupe_keep_order(cleaned)[:6]


def _extract_first_quoted_text(description: str) -> str:
    quoted = re.findall(r"[\"\u201c\u300c']([^\"\u201d\u300d']{1,80})[\"\u201d\u300d']", str(description or ''))
    return _strip_quotes(quoted[0]) if quoted else ''


def is_community_detail_assertion(description: str) -> bool:
    desc = str(description or '').strip()
    if not desc:
        return False
    if any(kw in desc for kw in ['搜索框', '搜索弹层', '搜索结果', '获得焦点', '输入框获得焦点']):
        return False
    has_assert = any(kw in desc for kw in ['断言', '验证', '检查', '确认'])
    has_detail = any(kw in desc for kw in ['社区详情', '目标社区', '进入社区', '当前社区'])
    has_sidebar = any(kw in desc for kw in ['左侧社区面板', '左侧面板', '社区面板', '官方社区'])
    return has_assert and (has_detail or has_sidebar)


def is_top_search_overlay_assertion(description: str) -> bool:
    desc = str(description or '').strip()
    return (
        any(kw in desc for kw in ['断言', '验证', '检查', '确认'])
        and any(kw in desc for kw in ['搜索框', '搜索弹层', '搜索面板'])
        and any(kw in desc for kw in ['焦点', '展示', '显示', '出现'])
    )


def is_clicked_community_identity_assertion(description: str) -> bool:
    desc = str(description or '').strip()
    return (
        any(kw in desc for kw in ['断言', '验证', '检查', '确认'])
        and any(kw in desc for kw in ['被点击卡片', '被点击的卡片', '点击的卡片'])
        and '社区名称' in desc
        and any(kw in desc for kw in ['社区 ID', '社区ID'])
    )


def is_login_success_assertion(description: str) -> bool:
    desc = str(description or '').strip()
    if not desc:
        return False
    negative_or_flow_terms = (
        '未登录', '未登陆', '没有登录', '没有登陆', '登录入口', '登陆入口',
        '登录流程', '登陆流程', '登录弹窗', '登陆弹窗', '登录框', '登陆框',
        '登录按钮', '登陆按钮', '登录页', '登陆页', '需要登录', '需要登陆',
        '登录拦截', '登陆拦截', '跳转登录', '跳转登陆',
    )
    if any(token in desc for token in negative_or_flow_terms):
        return False
    return any(phrase in desc for phrase in (
        '登录成功', '登陆成功', '成功登录', '成功登陆', '是否成功登录', '是否成功登陆',
        '已登录', '已登陆', '登录态有效', '登陆态有效',
    ))


def _extract_form_fill(line: str) -> Optional[Action]:
    field_pattern = r'手机号|手机号码|账号|用户名|验证码|密码|姓名|邮箱|地址|身份证号|公司名称|唯一标识|时间戳'
    reverse_match = re.search(
        rf'(?:输入|填写|填入)\s*({field_pattern})(?:输入框|框)?(?:中|内)?\s*[：:]?\s*(.+?)\s*[。.]?$',
        str(line or ''),
    )
    if reverse_match:
        label = reverse_match.group(1)
        value = _strip_quotes(reverse_match.group(2)).strip()
        if value:
            business = {
                '手机号': 'nn_fill_phone',
                '手机号码': 'nn_fill_phone',
                '账号': 'nn_fill_phone',
                '用户名': 'nn_fill_phone',
                '验证码': 'nn_fill_verification_code',
                '密码': 'nn_fill_password',
            }.get(label)
            if business:
                return _business_action(
                    business,
                    f'输入{label}',
                    input_value=value,
                    field=label,
                    display_description=str(line or '').strip(),
                )
            return {
                'action_type': 'type',
                'description': f'输入{label}',
                'input_value': value,
                'target_text': label,
                'element': None,
                'display_description': str(line or '').strip(),
            }

    match = re.search(
        rf'({field_pattern})(?:输入框|框)?(?:中|内)?\s*'
        r'(?:输入(?!框)|填写|填入)\s*[：:]?\s*(.+?)\s*[。.]?$',
        str(line or ''),
    )
    if not match:
        return None
    label = match.group(1)
    value = _strip_quotes(match.group(2)).strip()
    business = {
        '手机号': 'nn_fill_phone',
        '手机号码': 'nn_fill_phone',
        '账号': 'nn_fill_phone',
        '用户名': 'nn_fill_phone',
        '验证码': 'nn_fill_verification_code',
        '密码': 'nn_fill_password',
    }.get(label)
    if not business or not value:
        return None
    return _business_action(
        business,
        f'输入{label}',
        input_value=value,
        field=label,
        display_description=str(line or '').strip(),
    )


def _extract_named_input(line: str) -> Optional[Action]:
    match = re.search(
        r'在\s*[「“"\']?([^「」“”"\']{1,50})[」”"\']?\s*(?:输入框|框)'
        r'(?:中|内)?\s*(?:输入|填写|填入)\s*[：:]?\s*'
        r'(.+?)(?:\s*并?按(?:下)?\s*(Enter|回车)|\s*后按(?:下)?\s*(Enter|回车))?\s*[。.]?$',
        str(line or ''),
        re.I,
    )
    if not match:
        return None
    target = _strip_quotes(match.group(1)).strip()
    value = _strip_quotes(match.group(2)).strip()
    if not target or not value:
        return None
    step = {
        'action_type': 'type',
        'description': f'在{target}输入框输入: {value}',
        'display_description': str(line or '').strip(),
        'input_value': value,
        'target_text': target,
        'element': None,
    }
    if match.group(3) or match.group(4):
        step['press_after'] = 'Enter'
    return step


def _extract_article_editor_input_steps(line: str) -> List[Action]:
    """Compile article title/body writes separately instead of treating prose as one input.

    Imported article cases commonly write both fields in one sentence.  The
    generic input path cannot infer which editor field should receive each
    value, especially when the body is a contenteditable editor.
    """
    desc = str(line or '').strip()
    fields = (
        ('title', '标题', r'(?:文章)?标题\s*(?:输入|填写|填入)\s*(?:为|是|[:：])?\s*'),
        ('body', '正文', r'(?:文章)?(?:正文|内容)\s*(?:输入|填写|填入)\s*(?:为|是|[:：])?\s*'),
    )
    steps = []
    for field, label, pattern in fields:
        match = re.search(
            pattern + r'(?:["“「]([^"”」]{1,200})["”」]|([^，。；;、]+))',
            desc,
        )
        value = _strip_quotes((match.group(1) or match.group(2) or '').strip()) if match else ''
        if value:
            steps.append(_business_action(
                f'nn_fill_article_{field}',
                f'输入文章{label}',
                input_value=value,
                field=label,
                display_description=desc,
            ))
    return steps


def _clean_click_target(text: str) -> str:
    text = _strip_quotes(text)
    text = re.sub(r'\s*(按钮|入口|链接|图标|控件)$', '', text).strip() or text
    return text


def _extract_search_value(line: str) -> Optional[str]:
    patterns = [
        r'^(?:搜索|查找|检索)\s*[：:]?\s*(.+?)(?:确定|确认|回车)?$',
        r'(?:在.*?(?:输入框|搜索框|搜索栏|搜索输入).*?(?:搜索|查找|检索|输入))\s*[：:]?\s*(.+?)(?:确定|确认|回车)?$',
    ]
    for pattern in patterns:
        m = re.search(pattern, line)
        if m:
            value = _strip_quotes(m.group(1))
            if value:
                return value
    return None


def _extract_top_search_input_value(line: str) -> Optional[str]:
    """Extract the keyword from a combined top-search instruction.

    Authors commonly write one natural sentence such as "click the top search
    box, input `keyword`, and press Enter".  It must remain one structured
    action, otherwise the keyword portion is silently lost after the click.
    """
    if not is_top_community_search_description(line):
        return None
    match = re.search(
        r'(?:输入|填写)\s*(?:搜索关键词|关键词|搜索词|内容)?\s*(?:为|是|[:：])?\s*(?:["“「]([^"”」]{1,120})["”」]|([^，。；;、\s]+))',
        str(line or ''),
    )
    if not match:
        return None
    value = _strip_quotes(match.group(1) or match.group(2) or '')
    return value or None


def _community_target_from_description(line: str) -> str:
    desc = str(line or '').strip()
    candidates = []
    patterns = [
        r'(?:点击|点|按|选择|打开|进入)\s*.+?(?:中|里|里面|中的|里的|右侧|右边|左侧|左边)\s*(?:的)?\s*([^，。；;,]+)$',
        r"(?:点击|点|按|选择|打开|进入)\s*(?:右侧|右边|左侧|左边)?\s*(?:的)?\s*[\"“']?([^\"”'，。；;,]+?社区)[\"”']?\s*(?:进入|打开)?$",
    ]
    for pattern in patterns:
        m = re.search(pattern, desc)
        if m:
            candidates.append(m.group(1))
    candidates.extend(re.findall(r"[\"“']([^\"”']{1,40})[\"”']", desc))
    for raw in candidates:
        text = _strip_quotes(raw)
        for n in ['点击', '点', '按', '选择', '打开', '进入', '社区搜索结果', '搜索结果', '查询结果', '检索结果', '结果列表', '列表', '卡片', '中的', '里的', '里面的']:
            text = text.replace(n, '')
        text = _strip_quotes(text.strip(' ：:，,。；;'))
        if text.endswith('社区') and len(text) > 3:
            text = text[:-2]
        text = _strip_quotes(text.strip(' ：:，,。；;'))
        if len(text) >= 2:
            return text
    return ''


def _is_community_result_click(line: str) -> bool:
    desc = str(line or '').strip()
    has_click = any(kw in desc for kw in ['点击', '点', '选择', '打开'])
    has_community = '社区' in desc or 'community' in desc.lower()
    has_context = any(kw in desc for kw in ['搜索结果', '查询结果', '检索结果', '结果', '右侧', '右边', '卡片', '列表', '弹窗', '弹层'])
    return has_click and has_community and has_context


def _is_page_state_assertion(line: str) -> bool:
    desc = re.sub(r'^\s*\d+\s*[.、]\s*', '', str(line or '').strip())
    state_prefixes = ('已进入', '已经进入', '当前已在', '页面已进入', '已打开')
    state_signals = ('处于选中', '已选中', '展示', '显示', '包含', '存在')
    return desc.startswith(state_prefixes) and any(signal in desc for signal in state_signals)


def _extract_community_result_requirements(line: str) -> List[str]:
    desc = str(line or '').strip()
    requirements = []
    if any(token in desc for token in ['在线人数', '在线人数数', '人在线', '在线数', '在线成员']):
        requirements.append('online_count')
    if any(token in desc for token in ['社区简介', '简介', '介绍']):
        requirements.append('community_intro')
    return _dedupe_keep_order(requirements)


def _business_action(name: str, description: str, **kwargs) -> Action:
    step = {
        'action_type': 'business_action',
        'business_action': name,
        'description': description,
        'input_value': kwargs.pop('input_value', ''),
        'element': None,
    }
    step.update(kwargs)
    return step


_COMMUNITY_PLUGIN_TARGETS = frozenset({
    '成员大厅', '全员大厅', '战绩查询', '战绩查询(修改后)', 'PUBG福利商店', 'NN商店',
})


def _community_plugin_click(target: str, display_description: str = '') -> Action:
    """Compile known left-navigation plugins to a state-convergent action."""
    return _business_action(
        'nn_click_community_plugin',
        f'切换左侧社区插件：{target}',
        target_text=target,
        display_description=display_description,
    )


def _click_action(description: str, original_line: str, *, target_text: str = '') -> Action:
    normalized_description = description
    step = {
        'action_type': 'click',
        'description': normalized_description,
        'display_description': original_line or description,
        'input_value': '',
        'element': None,
    }
    constraints = extract_click_constraints(original_line or description, fallback_target=target_text)
    if constraints:
        step['click_constraints'] = constraints
        targets = constraints.get('target_texts') or []
        if targets:
            primary_target = targets[0]
            if normalized_description.startswith('点击 '):
                step['description'] = f'点击 {primary_target}'
            elif normalized_description.startswith('勾选 '):
                step['description'] = f'勾选 {primary_target}'
            step['target_text'] = targets[0]
    elif target_text:
        step['target_text'] = target_text
    return step


def _extract_rapid_filter_switch(line: str) -> Optional[Action]:
    """Compile bounded multi-filter switching into one deterministic action.

    Treating this as several generic clicks is both slower than the stated
    budget and loses the relationship between the intermediate clicks and the
    final filter state.
    """
    normalized = re.sub(r'^\s*\d+\s*[、.．:：]\s*', '', str(line or '')).strip()
    match = re.search(
        r'(?:在\s*)?(?P<budget>\d+)\s*秒(?:内)?\s*依次(?:切换|选择|点击)\s*(?P<values>.+)$',
        normalized,
    )
    if not match:
        return None

    raw_values = match.group('values').strip().strip('。；;')
    values = _dedupe_keep_order(
        re.sub(r'^(?:筛选项?|选项)\s*', '', part).strip().strip('“”"\'')
        for part in re.split(r'[、，,]+', raw_values)
    )
    if len(values) < 2:
        return None
    return _business_action(
        'nn_rapid_filter_switch',
        f'在 {int(match.group("budget"))} 秒内依次切换筛选：{"、".join(values)}',
        filter_values=values,
        time_budget_seconds=int(match.group('budget')),
        display_description=str(line or '').strip(),
    )


def _extract_battle_record_query(line: str) -> Optional[Action]:
    """Compile a player-record query into one action that opens the result dialog."""
    normalized = re.sub(r'^\s*\d+\s*[、.．:：]\s*', '', str(line or '')).strip()
    patterns = (
        r'(?:查询|搜索)\s*(?:玩家(?:战绩)?\s*)?[“”"\']?([A-Za-z][A-Za-z0-9_-]{2,})',
        r'(?:在)?[“”"\']?查询玩家战绩[“”"\']?输入框(?:填写|输入)\s*[“”"\']?([A-Za-z][A-Za-z0-9_-]{2,})',
    )
    player = ''
    for pattern in patterns:
        match = re.search(pattern, normalized, re.I)
        if match:
            player = match.group(1).strip()
            break
    if not player:
        return None
    return _business_action(
        'nn_query_battle_records',
        f'查询玩家战绩：{player}',
        input_value=player,
        player_name=player,
        display_description=str(line or '').strip(),
    )


def _extract_permission_grant(line: str) -> Optional[Action]:
    """Compile permission mutations with an explicit subject and permission.

    The executor owns rollback.  Do not turn an underspecified sentence into
    a fuzzy click: it must fail with a useful contract error at runtime.
    """
    normalized = str(line or '').strip()
    if not re.search(r'(?:添加|授予|赋予|授权|分配|开启).{0,30}权限', normalized):
        return None
    quoted = [item.strip() for item in re.findall(r'[「“"\']([^」”"\']{1,100})[」”"\']', normalized) if item.strip()]
    subject = ''
    permission = ''
    if len(quoted) >= 2:
        subject, permission = quoted[0], quoted[1]
    else:
        match = re.search(
            r'(?:给|为|向)\s*(?:用户|成员|角色)?\s*([^，。；;\s]+)\s*'
            r'(?:添加|授予|赋予|授权|分配)\s*(?:权限)?\s*[：:]?\s*([^，。；;]+)',
            normalized,
        )
        if match:
            subject, permission = match.group(1).strip(), match.group(2).strip()
    return _business_action(
        'nn_grant_permission',
        f'为对象「{subject}」添加权限「{permission}」' if subject and permission else '执行权限添加并在结束时回收',
        subject_text=subject,
        target_text=subject,
        permission_text=permission,
        display_description=normalized,
    )


def compile_natural_language_line(line: str) -> Optional[Action]:
    original_line = str(line or '').strip()
    line = re.sub(r'^\s*\d+\s*[、.．]\s*', '', original_line).strip()
    if not line or re.match(r'^[。；;，,\.]+$', line):
        return None
    if re.match(r'^(?:目标地址|前置条件|操作步骤|预期结果)\s*[：:]?', line):
        return None

    m = re.search(r'访问\s*(https?://[^\s，。；;]+)', line)
    if m:
        return {'action_type': 'goto', 'description': f'访问页面 {m.group(1)}', 'input_value': m.group(1), 'element': None}

    if re.search(r'等待(?:页面|主内容|插件).*(?:就绪|加载完成|稳定)', line):
        return {
            'action_type': 'wait',
            'description': '等待页面就绪',
            'input_value': '2',
            'wait_for': 'page_ready',
            'element': None,
        }

    if re.search(r'^(?:按下?|使用|点击)?\s*(?:Enter|回车)(?:键)?(?:执行|发起|提交|搜索|查询)?', line, re.I):
        return {
            'action_type': 'press',
            'description': '按 Enter 键',
            'input_value': 'Enter',
            'element': None,
        }

    if re.search(r'等待.*(?:请求|接口|响应|加载).*(?:完成|结束|失败|超时)', line):
        return {
            'action_type': 'wait',
            'description': '等待请求状态稳定',
            'input_value': '3',
            'wait_for': 'request_state',
            'element': None,
        }

    permission_grant = _extract_permission_grant(line)
    if permission_grant:
        return permission_grant

    viewport_match = re.search(r'(?:在|切换到|设置为)?\s*(\d{3,4})\s*[x×X]\s*(\d{3,4})(?:\s*(?:视口|访问|页面))?', line)
    if viewport_match and any(token in line for token in ('视口', '访问', '切换', '设置')):
        return {
            'action_type': 'set_viewport',
            'description': f'设置视口为 {viewport_match.group(1)}x{viewport_match.group(2)}',
            'input_value': f'{viewport_match.group(1)}x{viewport_match.group(2)}',
            'viewport': {'width': int(viewport_match.group(1)), 'height': int(viewport_match.group(2))},
            'element': None,
        }

    if re.search(r'(?:刷新|重新加载).*(?:页面|插件)', line):
        return {
            'action_type': 'reload',
            'description': '刷新当前页面',
            'input_value': '',
            'element': None,
        }

    if re.match(r'^(?:访问|进入|打开).*(?:页面|插件)$', line):
        return {
            'action_type': 'wait',
            'description': '等待目标页面就绪',
            'input_value': '2',
            'wait_for': 'page_ready',
            'element': None,
        }

    if any(token in line for token in ('白屏', '404', '脚本异常')) and any(token in line for token in ('登录页', '登陆页')) and any(
        token in line for token in ('断言', '验证', '检查', '确认', '无', '未', '不')
    ):
        return {
            'action_type': 'assert',
            'description': line,
            'input_value': line,
            'assert_type': 'page_health',
            'element': None,
        }

    if re.search(r'(点击|点|按(?!钮)).*?(登录|登陆).*?(入口|头像|图标|弹窗)', line):
        return _business_action('nn_open_login', '打开 NN 登录弹窗', display_description=line)

    if re.search(r'(点击|点|按(?!钮)).*(登录\s*/\s*注册|登录|登陆|注册).*?(按钮)?\s*$', line) and not any(kw in line for kw in ['入口', '头像', '图标', '弹窗']):
        return _business_action('nn_complete_login', '提交 NN 登录并校验登录态', display_description=line)

    if re.search(r'点击.*热门引用.*(?:任一|任意).*标签', line):
        return _business_action('nn_click_popular_tag', '点击热门引用中的一个标签', display_description=line)

    if ('Banner' in line or 'banner' in line) and any(token in line for token in ('另一项', '下一个', '切换')) and any(token in line for token in ('点击', '点')):
        return _business_action('nn_switch_home_banner', '切换至另一项可见社区首页 Banner 活动', display_description=line)

    if re.search(r'(?:点击|点|按).*?招募队友(?:入口|按钮)?', line) and not re.search(r'招募队友信息|发布招募信息', line):
        return _business_action(
            'nn_open_recruitment',
            '打开招募队友信息弹窗并确认状态',
            display_description=line,
        )

    if re.search(r'(点击|点|按).*?(确定发布|发布招募)', line):
        return _business_action(
            'nn_submit_recruitment',
            '在发布招募信息弹窗内点击确定发布并验证反馈',
            display_description=line,
        )

    article_type_match = re.search(
        r'(?:选择发布类型|发布类型).{0,40}?(?:点击|选择)\s*[「“"]?(活动|公告|攻略)[」”"]?',
        line,
    )
    if article_type_match:
        article_type = article_type_match.group(1)
        return _business_action(
            'nn_select_article_type',
            f'选择文章发布类型：{article_type}',
            target_text=article_type,
            article_type=article_type,
            display_description=line,
        )

    if re.search(r'(点击|点|按).*?(?:文章详情|详情页).*(?:关闭|关掉)', line):
        return _business_action('nn_close_article_detail', '关闭文章详情', display_description=line)

    if re.search(r'(?:从|在)?(?:首页|文章列表).{0,32}(?:打开|进入|点击).{0,32}(?:文章详情|详情)', line):
        return _business_action('nn_open_article_detail', '打开一篇可见文章详情', display_description=line)

    if re.search(r'(点击|点|按).*?内容管理', line):
        return _business_action('nn_open_article_management', '打开文章内容管理', display_description=line)

    if re.search(r'(点击|点|按).*?(?:文章内容区.*上方|发布按钮|新建文章).*(?:发布|新建)', line):
        return _business_action('nn_open_article_editor', '打开文章发布编辑器', display_description=line)

    if re.search(r'(点击|点|按).*?(?:编辑器|文章).*(?:存草稿|保存草稿)', line):
        return _business_action('nn_save_article_draft', '保存文章草稿', display_description=line)

    if re.search(r'(点击|点|按).*?(?:编辑器|文章).*(?:发布|重新发布)', line):
        return _business_action('nn_submit_article', '发布文章', display_description=line)

    clear_input = re.search(r'清空(?:右侧|左侧|顶部|底部)?[“"\']?(.+?)[”"\']?(?:输入框|搜索框)', line)
    if clear_input:
        field_name = _strip_quotes(clear_input.group(1)).strip()
        return {
            'action_type': 'type',
            'description': f'清空 {field_name} 输入框',
            'input_value': '',
            'target_text': field_name,
            'element': None,
        }

    form_fill = _extract_form_fill(line)
    if form_fill:
        form_fill['display_description'] = original_line
        return form_fill

    named_input = _extract_named_input(line)
    if named_input:
        named_input['display_description'] = original_line
        return named_input

    m = re.search(r'输入(验证码|密码|手机号|账号|用户名|搜索词|文本)[：:]?\s*(.+)', line)
    if m:
        label, value = m.group(1), _strip_quotes(m.group(2))
        business = {
            '手机号': 'nn_fill_phone',
            '账号': 'nn_fill_phone',
            '用户名': 'nn_fill_phone',
            '验证码': 'nn_fill_verification_code',
            '密码': 'nn_fill_password',
        }.get(label)
        if business:
            return _business_action(business, f'输入{label}', input_value=value, field=label, display_description=line)
        return {'action_type': 'type', 'description': f'输入{label}: {value}', 'input_value': value, 'element': None}

    # Preserve a click + input + Enter instruction as a complete top-search
    # action instead of compiling only its initial click.
    search_value = _extract_top_search_input_value(line) or _extract_search_value(line)
    if search_value:
        if is_top_community_search_description(line):
            return _business_action(
                'nn_top_community_search',
                f'顶部社区搜索框搜索: {search_value}',
                input_value=search_value,
                target_scope='top_navigation',
                entity_type='community',
                display_description=line,
            )
        return {'action_type': 'type', 'description': f'搜索: {search_value}', 'input_value': search_value, 'element': None}

    if re.search(r'(点击|点|按(?!钮)).*?(输入框|搜索框|搜索栏|搜索输入)', line):
        if is_top_community_search_description(line):
            return _business_action('nn_open_top_search', '打开顶部社区搜索框', target_scope='top_navigation', entity_type='community', display_description=line)
        return _click_action(line, line)

    if _is_page_state_assertion(line):
        if any(keyword in line for keyword in ['不可用', '禁用', 'disabled']) and any(keyword in line for keyword in ['按钮', 'button']):
            target = _extract_first_quoted_text(line)
            if target:
                return {
                    'action_type': 'assert',
                    'description': line,
                    'input_value': line,
                    'assert_type': 'disabled',
                    'assert_value': target,
                    'target_text': target,
                    'element': None,
                }
        expected_texts = extract_assert_expected_texts(line)
        return {
            'action_type': 'assert',
            'description': line,
            'input_value': line,
            'assert_type': 'text_contains',
            'assert_value': '+'.join(expected_texts),
            'expected_texts': expected_texts,
            'element': None,
        }

    if _is_community_result_click(line):
        target = _community_target_from_description(line)
        if target:
            requirements = _extract_community_result_requirements(line)
            return _business_action(
                'nn_click_community_result',
                f'点击社区搜索结果: {target}',
                target_text=target,
                entity_type='community',
                required_signals=requirements,
                display_description=line,
            )

    identity_card = re.search(
        r'(?:点击|点)\s*(?:名称为)?[「“"]?([^「””"、，,；;]+?)[」”"]?'
        r'[、，,\s]+ID\s*为[「“"]?(\d{5,})[」”"]?.*?(?:卡片|社区)',
        line,
        re.I,
    )
    if identity_card:
        target, expected_id = (value.strip() for value in identity_card.groups())
        return _business_action(
            'nn_click_identity_card',
            f'点击名称为 {target}、ID 为 {expected_id} 的同一张卡片',
            target_text=target,
            expected_id=expected_id,
            require_online='在线' in line,
            display_description=line,
        )
    if is_login_success_assertion(line) or any(kw in line for kw in ['完成登录', '登录并', '点击登录并']):
        if any(kw in line for kw in ['断言', '验证', '检查', '确认', '成功登录', '是否成功登录', '登录成功']):
            return {'action_type': 'assert', 'description': line, 'input_value': line, 'assert_type': 'login_success', 'assert_value': '登录成功', 'element': None}
        return _business_action('nn_complete_login', '提交 NN 登录并校验登录态', display_description=line)



    if '断言' in line or '验证' in line or '检查' in line:
        if is_login_success_assertion(line):
            return {'action_type': 'assert', 'description': line, 'input_value': line, 'assert_type': 'login_success', 'assert_value': '登录成功', 'element': None}
        if is_top_search_overlay_assertion(line):
            expected_texts = extract_assert_expected_texts(line)
            return {
                'action_type': 'assert',
                'description': line,
                'input_value': line,
                'assert_type': 'top_search_overlay',
                'assert_value': '+'.join(expected_texts),
                'expected_texts': expected_texts,
                'require_multiple_results': any(kw in line for kw in ['多个社区', '多条社区', '多个结果', '多条结果']),
                'element': None,
            }
        if is_clicked_community_identity_assertion(line):
            return {
                'action_type': 'assert',
                'description': line,
                'input_value': line,
                'assert_type': 'clicked_community_identity',
                'element': None,
            }
        if any(keyword in line for keyword in ['不可用', '禁用', 'disabled']) and any(keyword in line for keyword in ['按钮', 'button']):
            target = _extract_first_quoted_text(line)
            if target:
                return {
                    'action_type': 'assert',
                    'description': line,
                    'input_value': line,
                    'assert_type': 'disabled',
                    'assert_value': target,
                    'target_text': target,
                    'element': None,
                }
        if any(keyword in line for keyword in ['复选', '勾选', '已勾选']) and any(keyword in line for keyword in ['默认', '已勾选', '选中']):
            target = _extract_first_quoted_text(line)
            if target:
                return {
                    'action_type': 'assert', 'description': line, 'input_value': line,
                    'assert_type': 'checked', 'assert_value': target, 'target_text': target, 'element': None,
                }
        if is_community_detail_assertion(line):
            target = _extract_first_quoted_text(line) or '绝地求生'
            return {
                'action_type': 'assert',
                'description': line,
                'input_value': line,
                'assert_type': 'community_detail',
                'assert_value': target,
                'target_text': target,
                'element': None,
            }
        expected_texts = extract_assert_expected_texts(line)
        return {'action_type': 'assert', 'description': line, 'input_value': line, 'assert_type': 'text_contains', 'assert_value': '+'.join(expected_texts), 'expected_texts': expected_texts, 'element': None}

    m = re.search(r'等待\s*(\d+)\s*秒', line)
    if m:
        return {'action_type': 'wait', 'description': f'等待 {m.group(1)} 秒', 'input_value': m.group(1), 'element': None}

    m = re.match(r'^\s*(?:\d+[.、]\s*)?(勾选|选中|勾上|选择)[\s"\u201c]*(.+?)[\s"\u201d]*$', line)
    if m:
        text = _clean_click_target(m.group(2))
        return _click_action(f'勾选 {text}', line, target_text=text)

    m = re.search(r'(点击|按(?!钮)|点)[\s"\u201c]*(.+?)[\s"\u201d]*$', line)
    if m:
        text = _clean_click_target(m.group(2))
        if text in {'钮', '按钮'}:
            return None
        return _click_action(f'点击 {text}', line, target_text=text)

    m = re.search(r'输入\s*[：:]?\s*(.+)', line)
    if m:
        value = _strip_quotes(m.group(1))
        length_match = re.fullmatch(r'(\d+)\s*个?字符[。.]?', value)
        if length_match:
            count = int(length_match.group(1))
            return {
                'action_type': 'type',
                'description': f'输入 {count} 个测试字符',
                'input_value': '测' * count,
                'element': None,
            }
        return {'action_type': 'type', 'description': f'输入: {value}', 'input_value': value, 'element': None}

    if '如果有弹窗' in line or '如果弹窗' in line or '关闭弹窗' in line or '关闭对话框' in line:
        return {'action_type': 'try_click', 'description': '尝试关闭弹窗（如果存在）', 'input_value': '', 'element': None}

    return None


def _split_task_lines(task_desc: str, with_sections: bool = False) -> List[str]:
    if not task_desc:
        return []
    raw_lines = [
        line.strip()
        for line in str(task_desc).replace(chr(13) + chr(10), chr(10)).split(chr(10))
        if line.strip() and not re.match(r'^\s{0,3}#{1,6}\s+\S', line)
    ]
    action_kw = r'(?:访问|如果有弹窗|如果弹窗|关闭弹窗|再?点击|输入|勾选|选中|完成|断言|验证|检查|等待|撤回|按(?!钮)|并(?:勾选|断言|验证|检查))'
    split_lines = []
    section = 'context'
    for line in raw_lines:
        heading = re.match(r'^(目标地址|前置条件(?:补充)?|前置场景|测试数据|操作步骤|预期结果)\s*[：:]?', line)
        if heading:
            section_name = heading.group(1)
            section = 'operations' if section_name == '操作步骤' else ('expected' if section_name == '预期结果' else 'context')
            continue
        # A numbered case step often combines navigation and several clicks.
        # Preserve each action as an executable step instead of returning after
        # the first URL match.
        protected = re.sub(
            r'(https?://[^\s，。；;]+)',
            lambda m: m.group(0).replace(',', '<<<COMMA>>>').replace(';', '<<<SEMICOLON>>>'),
            line,
        )
        should_expand = (
            bool(re.search(r'访问\s*https?://[^\s，。；;]+', line)) and line.count('点击') >= 1
        ) or line.count('点击') >= 2 or bool(re.match(r'^\s*(?:\d+[.、]\s*)?不(?:选择|填写)', line))
        if should_expand:
            parts = re.split(r'(?<=[，,；;。])\s*(?=(?:再?点击|输入|勾选|选中|断言|验证|检查|等待|按(?!钮)))', protected)
        elif len(raw_lines) == 1:
            parts = re.split(r'[。；;,]\s*|\s+(?=' + action_kw + r')', protected)
        else:
            parts = [protected]
        for part in parts:
            normalized = part.replace('<<<COMMA>>>', ',').replace('<<<SEMICOLON>>>', ';').strip(' ，,；;')
            if normalized:
                split_lines.append((normalized, section) if with_sections else normalized)
    return split_lines



def _template_mentions_login(template_steps, template_name='') -> bool:
    text = str(template_name or '')
    for item in template_steps or []:
        if isinstance(item, dict):
            text += ' ' + str(item.get('description') or item.get('text') or item.get('name') or '')
        else:
            text += ' ' + str(item or '')
    return any(kw in text for kw in ['登录', '登陆', '手机号', '验证码', 'login'])


def _case_is_self_contained_login_flow(case_description: str) -> bool:
    text = str(case_description or '')
    has_open = any(kw in text for kw in ['登录入口', '登录弹窗', '登陆入口', '登陆弹窗'])
    has_credential = any(kw in text for kw in ['手机号', '验证码', '账号', '用户名', '密码'])
    has_submit_or_assert = any(kw in text for kw in ['登录/注册', '登录按钮', '点击登录', '登录成功', '成功登录', '是否成功登录'])
    has_compound_login = bool(re.search(
        r'完成\s*(?:账号|手机号).{0,80}验证码.{0,40}(?:登录|登陆)',
        text,
    ))
    requires_logged_out_state = any(marker in text for marker in (
        '浏览器未登录', '处于未登录状态', '无有效登录会话', '未登录访问',
        '未登录直达', '未登录状态',
    ))
    return (has_open and has_credential and has_submit_or_assert) or has_compound_login or requires_logged_out_state


def should_skip_setup_template(case_description: str, template_steps=None, template_name: str = '') -> bool:
    """Avoid applying a login setup template to a case that is itself testing login.

    This prevents the setup from logging in first and the case then looking for a
    login entry/button that no longer exists.
    """
    if not _template_mentions_login(template_steps, template_name):
        return False
    if _case_is_self_contained_login_flow(case_description):
        return True
    # An unbound-game-ID scenario is an explicit account-state test. Applying
    # the shared login template changes it into a logged-in account profile and
    # makes the intended empty state impossible to observe.
    return any(marker in str(case_description or '') for marker in (
        '未绑定游戏 ID', '未绑定游戏ID', '未输入游戏 ID', '未输入游戏ID',
    ))


def _parse_minimum_count(description: str) -> Optional[int]:
    match = re.search(r'(?:至少|不少于|最少)\s*(?:展示|显示|存在|有)?\s*([0-9一二三四五六七八九十]+)\s*(?:张|个|条)?', str(description or ''))
    if not match:
        return None
    raw = match.group(1)
    if raw.isdigit():
        return int(raw)
    chinese = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    if raw in chinese:
        return chinese[raw]
    if len(raw) == 2 and raw[0] == '十' and raw[1] in chinese:
        return 10 + chinese[raw[1]]
    if len(raw) == 2 and raw[1] == '十' and raw[0] in chinese:
        return chinese[raw[0]] * 10
    return None


def _build_composite_assertion_contract(description: str, expected_texts) -> Optional[Action]:
    desc = str(description or '')
    has_quoted_targets = bool(re.search(r'["“「][^"”」]{1,80}["”」]', desc))
    predicates = []
    selected_target = ''
    if any(token in desc for token in ['选中状态', '处于选中', '已选中', '当前选中']):
        selected_target = (expected_texts or [''])[0]
        if selected_target:
            predicates.append({'kind': 'selected', 'target': selected_target, 'scope': 'left'})
    if expected_texts and has_quoted_targets:
        main_expected_texts = [text for text in expected_texts if text != selected_target]
        scope = 'main' if any(token in desc for token in ['主内容区', '主内容', '中间区域']) else 'all'
        if main_expected_texts:
            predicates.append({'kind': 'text_presence', 'expected_texts': main_expected_texts, 'scope': scope})
    minimum = _parse_minimum_count(desc)
    if minimum is not None and any(token in desc for token in ['卡片', '列表项', '结果']):
        predicates.append({'kind': 'min_visible_cards', 'minimum': minimum, 'scope': 'main'})
    return {'kind': 'composite', 'predicates': predicates} if predicates else None


def _build_card_collection_contract(description: str) -> Optional[Action]:
    desc = str(description or '')
    if not any(token in desc for token in ['卡片', '列表项', '结果项']):
        return None
    predicates = []
    if any(token in desc for token in ('不再显示', '不显示', '未显示', '不存在', '消失', '隐藏')):
        predicates.append({'kind': 'card_collection_absence', 'scope': 'main'})
    minimum = _parse_minimum_count(desc)
    if minimum is not None:
        predicates.append({'kind': 'min_visible_cards', 'minimum': minimum, 'scope': 'main'})
    elif any(token in desc for token in ('卡片列表', '展示卡片', '仍展示', '存在卡片')):
        predicates.append({'kind': 'min_visible_cards', 'minimum': 1, 'scope': 'main'})
    field_map = (
        ('avatar', ('头像', '封面', '图标')),
        ('name', ('名称', '名字', '标题')),
        ('id', ('社区 ID', '社区ID', ' ID', '编号')),
        ('online', ('在线人数', '在线')),
    )
    required_fields = [name for name, tokens in field_map if any(token in desc for token in tokens)]
    if required_fields and any(token in desc for token in ['每张', '每个', '所有']):
        predicates.append({'kind': 'card_fields', 'fields': required_fields, 'scope': 'main'})
    elif required_fields and '任一' in desc:
        predicates.append({'kind': 'card_fields', 'fields': required_fields, 'scope': 'main', 'match_mode': 'any', 'minimum': min(2, len(required_fields))})
    if any(token in desc for token in ['对应卡片', '同一卡片', '不与其他卡片', '内容串位', '不串位']):
        predicates.append({'kind': 'card_field_association', 'field': 'intro', 'scope': 'main', 'optional': '存在时' in desc})
    metadata_map = (
        ('time', ('发布时间', '时间', '日期')),
        ('author', ('作者', '来源')),
        ('summary', ('内容摘要', '摘要')),
        ('tag', ('标签',)),
        ('comments', ('评论数', '评论')),
    )
    metadata = [field for field, tokens in metadata_map if any(token in desc for token in tokens)]
    if '标题' in desc and len(metadata) >= 2 and any(token in desc for token in ('至少两类', '至少2类', '至少 2 类')):
        predicates.append({'kind': 'card_metadata', 'fields': metadata, 'minimum': 2, 'scope': 'main'})
    return {'kind': 'composite', 'predicates': predicates} if predicates else None


def _quoted_texts_by_region(description: str, region: str) -> List[str]:
    """Return literal labels only when the author explicitly supplied them.

    This deliberately does not turn narrative prose into a text assertion.  A
    quoted label is a stable UI contract; the surrounding sentence is not.
    """
    if not region:
        return []
    before_region = str(description or '').split(region, 1)[0]
    return _dedupe_keep_order(re.findall(r'["“「]([^"”」]{1,80})["”」]', before_region))


def _build_semantic_assertion_plan(description: str) -> Optional[Action]:
    """Compile collection and visual assertions into reusable predicates.

    The compiler intentionally recognizes assertion *shapes* rather than page
    names.  That keeps a new community/game page from requiring a new regex
    patch just because its cards are called rooms, teams, or search results.
    """
    desc = str(description or '')
    # Card assertions already have a mature, card-specific evaluator below.
    # Preserve it while this generic layer handles rows, rooms and list items.
    if '卡片' in desc:
        return None

    # FAQ rows look like other repeated blocks in the DOM, but their contract
    # is different: the answer must belong to the question row itself.  Do not
    # let the generic collection heuristic select unrelated article/feed rows
    # that merely happen to be visible higher on the page.
    is_faq_answer_contract = (
        any(term in desc for term in ('FAQ', 'faq', '\u5e38\u89c1\u95ee\u9898', '\u95ee\u9898'))
        and any(term in desc for term in ('\u8bf4\u660e', '\u7b54\u6848', '\u56de\u7b54', '\u89e3\u7b54'))
        and any(term in desc for term in ('\u6bcf\u4e2a', '\u6bcf\u6761', '\u6240\u6709', '\u6bcf\u9879'))
    )
    if is_faq_answer_contract:
        return {
            'kind': 'assertion_plan',
            'predicates': [{'kind': 'faq_item_descriptions', 'scope': 'all'}],
        }
    predicates = []
    collection_words = ('条目', '列表项', '卡片', '结果', '房间', '语音房', '频道', '记录')
    has_collection = any(word in desc for word in collection_words)
    has_every_item = any(word in desc for word in ('每个', '每条', '每张', '所有', '任一'))
    collection_hints = ['room-item', 'room'] if any(word in desc for word in ('语音房', '房间')) else []
    collection_scope = 'all' if collection_hints else 'main'

    if has_collection and any(word in desc for word in ('多个', '多条', '至少', '不少于', '几条')):
        predicates.append({
            'kind': 'collection_count',
            'minimum': _parse_minimum_count(desc) or 2,
            'scope': collection_scope,
            'hints': collection_hints,
        })

    field_map = (
        ('number', ('房间号', '房间序号', '编号', 'ID', 'id')),
        ('name', ('名称', '名字', '标题')),
        ('capacity', ('人数', '容量', '在线')),
        ('description', ('简介', '描述', '说明', '说明文本')),
    )
    fields = [field for field, words in field_map if any(word in desc for word in words)]
    if (has_collection or has_every_item) and has_every_item and fields:
        predicates.append({
            'kind': 'collection_item_fields',
            'fields': fields,
            'scope': collection_scope,
            'hints': collection_hints,
        })

    if any(word in desc for word in ('不覆盖', '不重叠', '遮挡', '串位')):
        predicates.append({
            'kind': 'layout_no_overlap',
            'scope': collection_scope,
            'collection': has_collection,
            'hints': collection_hints,
            'protected': ['number', 'capacity', 'action'],
        })

    # Explicit labels are independently verifiable UI contracts regardless of
    # whether the author calls the region "bottom" or simply says "display".
    if has_collection and any(word in desc for word in ('展示', '存在', '显示')):
        labels = _dedupe_keep_order(re.findall(r'["“「]([^"”」]{1,80})["”」]', desc))
        if labels:
            predicates.append({
                'kind': 'text_group_presence',
                'expected_texts': labels,
                'scope': 'bottom' if '底部' in desc else 'main',
                'match_mode': 'any' if '等名称' in desc or '等名' in desc else 'all',
            })

    return {
        'kind': 'assertion_plan',
        'version': 1,
        'confidence': 'high' if predicates else 'low',
        'fallback_policy': 'review_required',
        'predicates': predicates,
    } if predicates else None


def _build_page_contract(description: str) -> Optional[Action]:
    """Compile page-level assertions that have an exact, durable target."""
    desc = str(description or '')
    predicates = []
    url_match = re.search(r'https?://[^\s，。；;"”」]+', desc)
    relative_match = re.search(r'(?<!:)\/(?:[A-Za-z0-9._~!$&\'()*+,;=:@%-]+\/)*[A-Za-z0-9._~!$&\'()*+,;=:@%-]+', desc)
    if any(word in desc for word in ('地址', 'URL', '链接', '路径', '跳转', '进入', '返回', '停留')):
        if url_match:
            predicates.append({'kind': 'url_contains', 'value': url_match.group(0).rstrip('/')})
        elif relative_match:
            predicates.append({'kind': 'url_contains', 'value': relative_match.group(0).rstrip('/')})

    if any(term in desc for term in ('未跳转登录页', '未进入登录页', '不跳转登录页', '没有跳转登录页')):
        predicates.append({'kind': 'url_not_auth'})

    title_match = re.search(
        r'(?:页面标题|浏览器标题|标题)\s*(?:为|是|包含|显示)\s*(.+?)'
        r'(?=(?:[，,]\s*(?:且|并|无|没有|未)|[。；;]|$))',
        desc,
    )
    # "弹窗标题" describes rendered dialog content, never document.title.
    if title_match and not re.search(r'(?:\u5f39\u7a97|\u5bf9\u8bdd\u6846)', desc):
        title = _strip_quotes(title_match.group(1)).strip(' ，,。；;')
        if title:
            predicates.append({'kind': 'page_title', 'value': title})

    if any(term in desc for term in ('白屏', '404', '脚本错误', '脚本异常', '错误遮罩')) and any(
        term in desc for term in ('无', '没有', '未出现', '不显示', '不存在')
    ):
        predicates.append({'kind': 'page_health'})

    labels = _dedupe_keep_order(re.findall(r'["“「]([^"”」]{1,80})["”」]', desc))
    negative = any(word in desc for word in ('不显示', '未显示', '不可见', '不存在', '消失', '隐藏'))
    if labels and negative:
        predicates.append({'kind': 'text_absence', 'expected_texts': labels, 'scope': 'all'})

    return {
        'kind': 'assertion_plan',
        'version': 1,
        'confidence': 'high',
        'fallback_policy': 'review_required',
        'predicates': predicates,
    } if predicates else None


def _build_state_assertion_plan(description: str) -> Optional[Action]:
    """Compile durable UI state assertions shared by forms, filters and dialogs."""
    desc = str(description or '')
    predicates = []
    if '每次操作' in desc and '筛选' in desc and any(term in desc for term in ('页面不跳转', '不跳转', '停留当前页')):
        predicates.append({'kind': 'rapid_filter_switch'})

    if '加载状态' in desc and any(term in desc for term in ('当前结果区域', '结果区域', '全屏白屏', '布局剧烈抖动')):
        predicates.append({'kind': 'loading_scope', 'scope': 'result'})

    if '战绩结果区域' in desc and any(term in desc for term in ('已加载', '展示', '显示', '单一', '不重复')):
        predicates.append({'kind': 'battle_result_ready'})

    modal_count = re.search(
        r'(?:DOM中)?(?:仅|只)?存在\s*(\d+)\s*个?[“”"\']?([^“”"\'，。；;]{1,40}?)[“”"\']?(?:弹窗|对话框)',
        desc,
    )
    if modal_count:
        predicates.append({
            'kind': 'modal_count',
            'target': modal_count.group(2).strip(),
            'expected_count': int(modal_count.group(1)),
        })

    final_filters = re.search(r'最终筛选为\s*([^，。；;]+)', desc)
    if final_filters and any(term in desc for term in ('无重复卡片', '不重复卡片', '只展示最终条件数据')):
        expected_filters = _dedupe_keep_order(
            value.strip() for value in re.split(r'[、，,]+', final_filters.group(1)) if value.strip()
        )
        if expected_filters:
            predicates.append({
                'kind': 'filter_result_consistency',
                'expected_filters': expected_filters,
                'require_unique_cards': True,
            })

    if is_login_success_assertion(desc):
        predicates.append({'kind': 'login_state'})

    if any(term in desc for term in (
        '弹出登录入口', '显示登录入口', '出现登录入口', '唤起登录流程',
        '进入登录流程', '跳转到登录流程', '跳转至登录流程', '打开登录弹窗',
        '显示登录弹窗', '出现登录弹窗', '需要登录',
    )):
        predicates.append({'kind': 'login_prompt_visible', 'allow_auth_url': True})

    field_aliases = (
        ('phone', ('手机号', '手机号码', '账号')),
        ('verification_code', ('验证码', '校验码')),
        ('password', ('密码',)),
        ('game_id', ('游戏ID', '游戏 ID', 'PUBGID', 'PUBG ID')),
    )
    field = next((name for name, aliases in field_aliases if any(alias in desc for alias in aliases)), '')
    if field and any(term in desc for term in ('输入框', '框')):
        length_match = re.search(r'(?:显示|为|包含|已有)?\s*(\d+)\s*位(?:内容|字符|数字)?', desc)
        value_match = re.search(
            r'(?:输入框|框)(?:中|内)?\s*(?:显示|为|内容为|值为|已有)\s*[「“"\']?'
            r'([^，。；;」”"\']+)',
            desc,
        )
        if length_match:
            predicates.append({'kind': 'input_length', 'field': field, 'length': int(length_match.group(1))})
        elif value_match:
            value = _strip_quotes(value_match.group(1)).strip()
            if value:
                predicates.append({'kind': 'input_value', 'field': field, 'value': value})
        elif field == 'game_id' and any(term in desc for term in ('已清空', '为空', '无内容', '空字符串')):
            predicates.append({'kind': 'input_length', 'field': field, 'length': 0})

    search_empty_label = _extract_first_quoted_text(desc)
    if (
        search_empty_label
        and any(term in search_empty_label for term in ('搜索的用户', '搜索的游戏', '战队社区'))
        and any(term in desc for term in ('0 条结果', '0条结果', '空状态', '无搜索内容', '没有找到'))
    ):
        predicates.append({'kind': 'search_empty_state', 'section_label': search_empty_label})

    if any(term in desc for term in ('处理中', '提交中', '登录中', '加载中', '防止重复提交', '不会重复提交')) and any(
        term in desc for term in ('按钮', '提交', '登录', '登陆')
    ):
        target = _extract_first_quoted_text(desc)
        if not target:
            target = '登录' if any(term in desc for term in ('登录', '登陆')) else '提交'
        predicates.append({'kind': 'control_busy', 'target': target})

    absent_modal = re.search(r'(?:不显示|未显示|不存在|不可见|没有出现)\s*([^，。；;]{1,40}?)(?:弹窗|对话框)', desc)
    if absent_modal:
        predicates.append({'kind': 'modal_absent', 'target': absent_modal.group(1).strip()})

    if any(term in desc for term in ('不可直接返回私有数据', '不可直接返回数据', '不能直接返回私有数据', '不能直接返回数据')):
        terms = []
        if '战绩' in desc:
            terms.append('战绩')
        if '查询' in desc:
            terms.append('查询结果')
        predicates.append({'kind': 'protected_result_absent', 'terms': terms})

    if '战绩插件' in desc and any(term in desc for term in ('显示', '展示', '返回', '停留', '进入')):
        predicates.append({'kind': 'page_feature', 'feature': '战绩插件主内容', 'terms': ['战绩']})
    elif '社区公共内容' in desc and any(term in desc for term in ('显示', '展示', '可展示')):
        predicates.append({'kind': 'page_feature', 'feature': '社区公共内容', 'terms': ['社区']})

    if any(term in desc for term in ('可重新发起查询', '可以重新发起查询', '可再次查询', '可以再次查询')):
        predicates.append({'kind': 'control_available', 'target': '查询'})

    if '弹窗' in desc and any(word in desc for word in ('打开', '显示', '可见', '保持')):
        if not any(item.get('kind') == 'login_prompt_visible' for item in predicates):
            predicates.append({'kind': 'modal_visible'})

    validation_labels = _dedupe_keep_order(re.findall(r'["“「]([^"”」]{1,80})["”」]', desc))
    if any(word in desc for word in ('必填校验', '校验提示', '错误状态', '验证提示')) and validation_labels:
        predicates.append({
            'kind': 'form_validation_error',
            'fields': validation_labels,
            'match_mode': 'any' if '或' in desc else 'all',
        })

    counter = re.search(r'`?\s*(\d+)\s*/\s*(\d+)\s*`?', desc)
    limit = re.search(r'(?:不超过|最多|上限|限制).{0,12}?(\d+)\s*个?字符', desc)
    if counter:
        predicates.append({
            'kind': 'input_counter',
            'current': int(counter.group(1)),
            'maximum': int(counter.group(2)),
        })
    if limit:
        predicates.append({'kind': 'input_max_length', 'maximum': int(limit.group(1))})

    if any(word in desc for word in ('筛选结果恢复', '恢复为当前分类', '不残留刚才的关键词')):
        predicates.append({'kind': 'filter_reset_state', 'require_collection_or_empty': True})

    explicit_empty_state = bool(re.search(
        r'(?:展示|显示|出现|为|呈现).{0,12}(?:空状态|无结果|暂无数据|暂无结果)|(?:空状态|无结果|暂无数据|暂无结果).{0,12}(?:展示|显示|出现)',
        desc,
    )) and not bool(re.search(r'(?:列表|结果).{0,8}或(?:空状态|无结果|暂无数据|暂无结果)', desc))
    if explicit_empty_state and not search_empty_label:
        predicates.append({'kind': 'empty_state', 'scope': 'main'})

    direct_id = re.search(r'ID\s*为\s*(\d+)', desc, re.I)
    direct_name = re.search(r'名为\s*[「“\"]?([^，。；;、的」”\"]{2,80})', desc)
    if direct_id and direct_name and any(word in desc for word in ('进入', '页面', '页面展示')):
        labels = _dedupe_keep_order(re.findall(r'(?:展示|显示)([^，。；;]+)', desc))
        required_terms = [term.strip().lstrip('了') for term in re.split(r'[、和以及]', labels[0]) if term.strip()] if labels else []
        required_features = []
        feature_map = (
            ('team_intro', ('战队介绍', '战队简介', '社区介绍')),
            ('voice_rooms', ('语音房间', '语音房', '语音频道')),
            ('sidebar_menu', ('侧边栏功能菜单', '侧边栏菜单', '侧边功能菜单')),
        )
        for feature, terms in feature_map:
            if any(term in desc for term in terms):
                required_features.append(feature)
                required_terms = [term for term in required_terms if term not in terms]
        predicates.append({
            'kind': 'entity_identity',
            'id': direct_id.group(1),
            'name': _strip_quotes(direct_name.group(1)).strip(),
            'required_terms': required_terms,
            'required_features': required_features,
        })

    return {
        'kind': 'assertion_plan',
        'version': 1,
        'confidence': 'high',
        'fallback_policy': 'review_required',
        'predicates': predicates,
    } if predicates else None


def build_assertion_contract(step: Action) -> Optional[Action]:
    """Compile every assertion into a stable, data-driven verification contract."""
    if step.get('action_type') != 'assert':
        return None
    description = str(step.get('description') or step.get('input_value') or '')
    expected_texts = step.get('expected_texts') or extract_assert_expected_texts(description)
    assert_type = step.get('assert_type')

    if assert_type == 'page_health':
        return {'kind': 'page_health'}
    if assert_type == 'disabled':
        return {'kind': 'control_state', 'state': 'disabled', 'target': step.get('target_text') or step.get('assert_value')}
    if assert_type == 'checked':
        return {'kind': 'control_state', 'state': 'checked', 'target': step.get('target_text') or step.get('assert_value')}
    if is_top_search_overlay_assertion(description) or assert_type == 'top_search_overlay':
        requires_history = any(term in description for term in (
            '\u641c\u7d22\u5386\u53f2', '\u5386\u53f2\u8bb0\u5f55', '\u5386\u53f2\u641c\u7d22',
        ))
        contract = {
            'kind': 'search_overlay',
            'expected_texts': expected_texts,
            'min_results': 2 if any(kw in description for kw in ['多个社区', '多条社区', '多个结果', '多条结果']) else 0,
        }
        if requires_history:
            contract['require_history'] = True
        return contract
    if is_clicked_community_identity_assertion(description) or assert_type == 'clicked_community_identity':
        return {'kind': 'referenced_identity', 'reference': 'last_clicked_entity', 'fields': ['name', 'id']}
    if assert_type == 'community_detail' or is_community_detail_assertion(description):
        return {'kind': 'community_detail', 'target': step.get('target_text') or step.get('assert_value')}
    card_collection = _build_card_collection_contract(description)
    if card_collection:
        # A navigation assertion can require both a destination identity and
        # the disappearance of the source card listing.  Preserve explicit
        # quoted identity labels instead of letting the card predicate hide
        # the first half of the requirement.
        if any(item.get('kind') == 'card_collection_absence' for item in card_collection.get('predicates', [])):
            composite = _build_composite_assertion_contract(description, expected_texts)
            if composite:
                card_collection['predicates'].extend(composite.get('predicates') or [])
        return card_collection
    plans = [
        _build_state_assertion_plan(description),
        _build_semantic_assertion_plan(description),
        _build_page_contract(description),
    ]
    active_plans = [plan for plan in plans if (plan or {}).get('predicates')]
    if len(active_plans) == 1:
        return active_plans[0]
    predicates = []
    seen_predicates = set()
    for plan in active_plans:
        for predicate in (plan or {}).get('predicates') or []:
            key = repr(sorted(predicate.items(), key=lambda item: item[0]))
            if key in seen_predicates:
                continue
            seen_predicates.add(key)
            predicates.append(predicate)
    if predicates:
        return {
            'kind': 'assertion_plan',
            'version': 1,
            'confidence': 'high',
            'fallback_policy': 'review_required',
            'predicates': predicates,
        }
    composite = _build_composite_assertion_contract(description, expected_texts)
    if composite:
        return composite
    # Unsupported prose must not become a whole-sentence text lookup.  It is
    # still an executable AI assertion: the runtime supplies DOM and a
    # screenshot to the configured assertion model.  This keeps imports from
    # requiring a brittle, fixed assertion phrase while never fabricating a
    # deterministic text check.
    return {
        'kind': 'ai_semantic',
        'reason': '需要基于页面 DOM 和截图进行语义断言',
        'description': description,
        'expected_texts': expected_texts,
    }

def compile_task_description(task_desc: str) -> List[Action]:
    steps = []
    last_click_target = ''
    pending_click_sequence: List[str] = []
    pending_community_result: Dict[str, Any] = {}
    sectioned_case = bool(re.search(r'(?m)^\s*(?:操作步骤|预期结果)\s*[:：]', str(task_desc or '')))
    target_match = re.search(
        r'(?:目标地址\s*[:：]?|访问)\s*(?:浏览器|NN\s*客户端)?\s*(https?://[^\s，。；;]+)',
        str(task_desc or ''),
    )
    target_url = target_match.group(1).rstrip('/') if target_match else ''
    target_header_match = re.search(
        r'目标地址\s*[:：]\s*(?:浏览器|NN\s*客户端)?\s*(https?://[^\s，。；;]+)',
        str(task_desc or ''),
    )
    has_explicit_visit = bool(re.search(r'(?m)^\s*(?:\d+\s*[、.．:：]\s*)?访问\s*https?://', str(task_desc or '')))
    if target_header_match and not has_explicit_visit:
        target_url = target_header_match.group(1).rstrip('/')
        steps.append({
            'action_type': 'goto',
            'description': f'访问页面 {target_url}',
            'input_value': target_url,
            'element': None,
        })
    is_member_hall_case = '/hall' in target_url or '/channel/' in target_url
    setup_article_detail = bool(re.search(
        r'前置场景\s*[：:].*(?:已)?打开.*文章详情', str(task_desc or ''), re.S
    ))
    if setup_article_detail:
        steps.append(_business_action(
            'nn_open_article_detail',
            '打开一篇可见文章详情作为用例前置场景',
            display_description='前置场景：已打开一篇文章详情',
        ))

    for line, section in _split_task_lines(task_desc, with_sections=True):
        # Expected-result prose is evidence, not another sequence of UI
        # instructions.  Compiling it as actions caused phrases such as
        # "评论输入入口" to become a bogus type action with value "入口".
        normalized_line = re.sub(r'^\s*\d+\s*[、.．]\s*', '', str(line or '')).strip()
        if sectioned_case and section != 'operations':
            # Explicit assertions remain executable specifications.  Other
            # expected-result prose is kept as documentation and must never be
            # mistaken for a click/type instruction.
            if section != 'expected' or not re.match(r'^(?:断言|验证|检查|确认)', normalized_line):
                continue
        if (
            '发布中' in normalized_line
            and '本人' in normalized_line
            and '删除' in normalized_line
            and any(marker in normalized_line for marker in ('继续扫描', '直到列表', '全部删除', '逐条'))
        ):
            steps.append(_business_action(
                'nn_delete_all_current_user_published_articles',
                '清理发布中列表内当前账号的全部文章',
                display_description=str(line or '').strip(),
            ))
            continue

        # Member hall controls are icon-only and the page also contains global
        # download/navigation buttons. Never send chat operations to the
        # generic page-wide click and input heuristics below.
        if is_member_hall_case:
            if normalized_line.startswith('断言') and '人数' in normalized_line and '麦克风' in normalized_line and '耳机' in normalized_line:
                steps.append(_business_action(
                    'nn_hall_verify_channel_controls',
                    '验证目标语音房人数状态与底部账号、麦克风、耳机控制布局',
                    display_description=str(line or '').strip(),
                ))
                continue
            member_search_value = re.search(r'(?:搜索成员(?:输入框)?).*?(?:输入(?!框)|填写)\s*[：:]?\s*([^，。；;\s]+)', normalized_line)
            if member_search_value and not any(marker in normalized_line for marker in ('完整昵称', '第一位成员昵称')):
                steps.append(_business_action(
                    'nn_hall_search_member',
                    '使用右侧成员搜索框按指定关键字筛选并等待结果稳定',
                    input_value=member_search_value.group(1).strip(),
                    search_mode='literal',
                    display_description=str(line or '').strip(),
                ))
                continue
            if normalized_line.startswith('断言') and '成员大厅' in normalized_line and any(marker in normalized_line for marker in ('未跳转', '不跳转', '仍停留', '停留在')):
                steps.append(_business_action(
                    'nn_hall_verify_hall_route',
                    '验证成员搜索后仍停留在成员大厅路由',
                    display_description=str(line or '').strip(),
                ))
                continue
            if normalized_line.startswith('断言') and '无结果状态' in normalized_line and any(marker in normalized_line for marker in ('遮挡', '顶部导航', '中央消息流', '底部输入区')):
                steps.append(_business_action(
                    'nn_hall_verify_member_empty_state_layout',
                    '验证成员搜索空结果仅位于右侧成员列表区域',
                    display_description=str(line or '').strip(),
                ))
                continue
            # Layout health after a member search is a DOM contract, not a
            # visual judgement.  Long member nicknames may legitimately end
            # near the panel edge, so screenshot-based assertions have caused
            # false positives here.  Verify the actual right-panel geometry,
            # mounted application shell and active full-screen loaders instead.
            if normalized_line.startswith('断言') and any(marker in normalized_line for marker in ('白屏', '持续加载', '右侧区域溢出', '右侧面板溢出')):
                steps.append(_business_action(
                    'nn_hall_verify_member_search_layout_health',
                    '验证成员搜索后页面健康且右侧成员面板无真实横向溢出',
                    display_description=str(line or '').strip(),
                ))
                continue
            if normalized_line.startswith('断言') and any(marker in normalized_line for marker in ('成员搜索框', '成员搜索结果', '搜索结果昵称', '可见搜索结果', '右侧成员列表')):
                min_count_match=re.search(r'至少\s*(\d+)\s*个(?:成员)?(?:条目|成员)?', normalized_line)
                steps.append(_business_action(
                    'nn_hall_verify_member_search',
                    '验证右侧成员搜索框和结果列表的精确筛选关系',
                    min_count=int(min_count_match.group(1)) if min_count_match else 1,
                    display_description=str(line or '').strip(),
                ))
                continue
            if '邀请/分享' in normalized_line and any(word in normalized_line for word in ('点击', '打开')):
                steps.append(_business_action(
                    'nn_hall_open_invite_share',
                    '打开成员大厅顶部邀请分享面板',
                    display_description=str(line or '').strip(),
                ))
                continue
            if ('邀请好友' in normalized_line or '邀请分享' in normalized_line) and any(word in normalized_line for word in ('关闭', '关掉')):
                steps.append(_business_action(
                    'nn_hall_close_invite_share',
                    '关闭成员大厅邀请分享面板',
                    display_description=str(line or '').strip(),
                ))
                continue
            if ('撤回' in normalized_line and any(word in normalized_line for word in ('系统提示', '系统通知'))
                    and any(word in normalized_line for word in ('验证', '检查', '查看', '断言'))):
                steps.append(_business_action(
                    'nn_hall_verify_retract_notice',
                    '验证本次撤回生成的成员大厅系统提示',
                    display_description=str(line or '').strip(),
                ))
                continue
            if '搜索成员' in normalized_line and '完整昵称' in normalized_line:
                steps.append(_business_action(
                    'nn_hall_search_member',
                    '使用右侧成员搜索框按首位成员完整昵称精确筛选',
                    search_mode='full_name',
                    display_description=str(line or '').strip(),
                ))
                continue
            if '第一位成员昵称' in normalized_line and re.search(r'前\s*1\s*(?:至|-|到)\s*2\s*个字符', normalized_line):
                steps.append(_business_action(
                    'nn_hall_search_member',
                    '使用右侧成员搜索框按首位成员昵称前缀筛选',
                    search_mode='prefix',
                    display_description=str(line or '').strip(),
                ))
                continue
            if '清空搜索框' in normalized_line or ('清空' in normalized_line and '搜索' in normalized_line and '成员列表恢复' not in normalized_line):
                steps.append(_business_action(
                    'nn_hall_clear_member_search',
                    '清空右侧成员搜索并验证成员列表恢复',
                    display_description=str(line or '').strip(),
                ))
                continue
            hall_message_matches = re.findall(r'(HALL_\$\{timestamp\(\)\}[^，。；\s]+)', normalized_line)
            hall_message_match = re.search(r'(HALL_\$\{timestamp\(\)\}[^，。；\s]+)', normalized_line)
            hall_message = re.sub(r'(?:并发送|并提交)$', '', hall_message_match.group(1).strip()) if hall_message_match else ''
            # A single sentence can carry an ordered send sequence.  Preserve
            # every message instead of silently losing all but the first one.
            if len(hall_message_matches) > 1 and re.search(r'(?:发送|提交|回车)', normalized_line) and '不要发送' not in normalized_line:
                for index, message in enumerate(hall_message_matches):
                    steps.append(_business_action(
                        'nn_hall_send_message',
                        '按顺序发送成员大厅唯一消息',
                        input_value=re.sub(r'(?:并发送|并提交)$', '', message.strip()),
                        # These are runtime slots, not a statement that the
                        # second message is a UI reply.  They retain both exact
                        # values for reverse-order cleanup.
                        message_role='original' if index == 0 else 'reply',
                        display_description=str(line or '').strip(),
                    ))
                continue
            # “不执行撤回” is an explicit non-destructive instruction, never a
            # request to invoke the destructive retract action.
            if re.search(r'(?:不|无需|不要).{0,12}撤回', normalized_line):
                if any(word in normalized_line for word in ('关闭', '关掉', '菜单')):
                    steps.append(_business_action(
                        'nn_hall_close_message_menus',
                        '关闭成员大厅消息操作菜单且不变更消息内容',
                        display_description=str(line or '').strip(),
                    ))
                continue
            retract_intent = bool(re.search(r'(?:点击|选择|执行|确认).{0,16}撤回|撤回(?:本次|该|消息|后|操作)|并撤回', normalized_line))
            if retract_intent:
                action = 'nn_hall_retract_runtime_messages' if ('依次' in normalized_line or '原始消息' in normalized_line) else 'nn_hall_retract_runtime_message'
                if not (steps and steps[-1].get('business_action') == action):
                    steps.append(_business_action(action, '撤回本次成员大厅测试消息', message_role='emoji' if ('表情' in normalized_line or '贴纸' in normalized_line) else 'last', display_description=str(line or '').strip()))
                continue
            if '表情' in normalized_line or '贴纸' in normalized_line:
                if '定位' in normalized_line and not any(word in normalized_line for word in ('点击', '打开', '关闭')):
                    continue
                if any(word in normalized_line for word in ('关闭', '关掉', '再次点击', '面板外')):
                    steps.append(_business_action('nn_hall_close_emoji_panel', '关闭成员大厅表情面板', display_description=str(line or '').strip()))
                    continue
                if any(word in normalized_line for word in ('选择', '选取', '选一个', '可见表情')):
                    steps.append(_business_action('nn_hall_select_emoji', '选择成员大厅可见表情或贴纸', display_description=str(line or '').strip()))
                    continue
                if any(word in normalized_line for word in ('发送', '提交')):
                    steps.append(_business_action('nn_hall_send_selected_emoji', '发送已选择的成员大厅表情', display_description=str(line or '').strip()))
                    continue
                if any(word in normalized_line for word in ('点击', '打开')):
                    steps.append(_business_action('nn_hall_open_emoji_panel', '打开成员大厅表情面板', display_description=str(line or '').strip()))
                    continue
            if hall_message:
                send_message_intent = bool(re.search(r'(?:点击|使用|发送|提交).{0,12}(?:消息|按钮|快捷键|回车)|并发送', normalized_line))
                if send_message_intent and '不要发送' not in normalized_line:
                    role = 'original' if ('原始' in normalized_line or '回复原消息' in normalized_line) else ('reply' if '回复' in normalized_line else 'last')
                    steps.append(_business_action('nn_hall_send_message', '发送成员大厅唯一消息', input_value=hall_message, message_role=role, display_description=str(line or '').strip()))
                    continue
                steps.append(_business_action('nn_hall_fill_message', '在成员大厅输入框输入唯一消息', input_value=hall_message, display_description=str(line or '').strip()))
                continue
            if '回复' in normalized_line and any(word in normalized_line for word in ('取消', '关闭', '退出')):
                steps.append(_business_action('nn_hall_cancel_reply', '取消成员大厅回复状态', display_description=str(line or '').strip()))
                continue
            if '回复' in normalized_line and any(word in normalized_line for word in ('点击', '打开')):
                steps.append(_business_action('nn_hall_reply_runtime_message', '回复本次成员大厅消息', display_description=str(line or '').strip()))
                continue
            if '广告' in normalized_line and any(word in normalized_line for word in ('关闭图标', '关闭', 'X')):
                steps.append(_business_action('nn_hall_close_top_ad', '关闭成员大厅右上广告（存在时）', display_description=str(line or '').strip()))
                continue
            if any(word in normalized_line for word in ('发送按钮', '快捷键提交', '回车键发送')):
                steps.append(_business_action('nn_hall_send_message', '发送成员大厅已输入消息', display_description=str(line or '').strip()))
                continue

        battle_record_query = _extract_battle_record_query(line)
        if battle_record_query:
            steps.append(battle_record_query)
            continue
        rapid_filter_switch = _extract_rapid_filter_switch(line)
        if rapid_filter_switch:
            steps.append(rapid_filter_switch)
            continue
        if re.fullmatch(r'(?:等待)?全部请求(?:结束|完成|返回)', normalized_line):
            steps.append(_business_action(
                'nn_wait_for_results_idle',
                '等待结果区域请求结束并稳定',
                timeout_seconds=12,
                display_description=str(line or '').strip(),
            ))
            continue
        # These are observation instructions. Their executable assertions are
        # compiled from the corresponding expected-result lines below.
        if normalized_line in ('观察加载状态', '统计结果弹窗数量'):
            continue
        if (
            re.search(r'每次点击后.*(?:选中状态|排行列表|吃鸡榜)', normalized_line)
            and any(item.get('business_action') == 'nn_switch_chicken_rank_periods' for item in steps)
        ):
            continue
        if re.search(r'吃鸡榜.*(?:日榜|周榜|总榜|地区榜)|依次点击[“"「]日榜', normalized_line):
            steps.append(_business_action(
                'nn_switch_chicken_rank_periods',
                '依次切换吃鸡榜日榜、周榜、总榜、地区榜并校验排行区域',
                rank_periods=['日榜', '周榜', '总榜', '地区榜'],
                display_description=str(line or '').strip(),
            ))
            continue
        # Imported article cases often express a complete creation flow in one
        # declarative sentence. Keep that sentence executable instead of
        # silently dropping it because it does not contain a literal click.
        article_publish_match = re.search(
            r'(?:新建|创建)并发布\s*(活动|公告|攻略)\s*文章\s+([^，。；;\s]+)',
            normalized_line,
        )
        if article_publish_match:
            article_type, title = article_publish_match.groups()
            title = _strip_quotes(title).strip()
            steps.extend([
                _business_action(
                    'nn_open_article_editor',
                    '打开文章发布编辑器',
                    display_description=str(line or '').strip(),
                ),
                _business_action(
                    'nn_select_article_type',
                    f'选择文章发布类型：{article_type}',
                    target_text=article_type,
                    article_type=article_type,
                    display_description=str(line or '').strip(),
                ),
                _business_action(
                    'nn_fill_article_title',
                    '输入文章标题',
                    input_value=title,
                    display_description=str(line or '').strip(),
                ),
                _business_action(
                    'nn_fill_article_body',
                    '输入文章正文',
                    input_value=f'自动化验证正文：{title}',
                    display_description=str(line or '').strip(),
                ),
                _business_action(
                    'nn_submit_article',
                    '发布文章',
                    display_description=str(line or '').strip(),
                ),
            ])
            continue
        article_type_change_match = re.search(
            r'(?:在[“"「]?发布中[”"」]?.{0,80}(?:打开|进入).{0,40}编辑|编辑界面.{0,40})'
            r'.{0,120}?将发布类型从[“"「]?(活动|公告|攻略)[”"」]?修改为[“"「]?(活动|公告|攻略)[”"」]?',
            normalized_line,
        )
        if article_type_change_match:
            _, article_type = article_type_change_match.groups()
            steps.extend([
                _business_action(
                    'nn_open_article_published_for_edit',
                    '在发布中定位本次运行标题并打开编辑器',
                    display_description=str(line or '').strip(),
                ),
                _business_action(
                    'nn_select_article_type',
                    f'选择文章发布类型：{article_type}',
                    target_text=article_type,
                    article_type=article_type,
                    display_description=str(line or '').strip(),
                ),
                _business_action(
                    'nn_submit_article',
                    '发布文章',
                    display_description=str(line or '').strip(),
                ),
            ])
            continue
        article_type_immutable_match = re.search(
            r'(?:断言|验证|确认).{0,80}(活动|公告|攻略)发布.{0,100}(?:不可修改|不展示.{0,20}选择发布类型|没有.{0,20}选择发布类型)',
            normalized_line,
        )
        if article_type_immutable_match:
            article_type = article_type_immutable_match.group(1)
            steps.append(_business_action(
                'nn_verify_article_type_immutable',
                f'验证已发布{article_type}文章编辑态类型不可修改',
                target_text=article_type,
                article_type=article_type,
                display_description=str(line or '').strip(),
            ))
            continue
        if re.search(r'(?:关闭|退出).{0,24}(?:文章)?编辑器', normalized_line):
            steps.append(_business_action(
                'nn_close_article_editor',
                '关闭文章编辑器',
                display_description=str(line or '').strip(),
            ))
            continue
        if re.search(r'(?:完整可见|可见).{0,30}文章(?:卡片)?.*(?:记录|标题)|同一文章卡片.*标题区域', normalized_line):
            if not any(item.get('business_action') == 'nn_open_article_detail' for item in steps):
                steps.append(_business_action(
                    'nn_open_article_detail',
                    '打开一篇完整可见文章详情并保留标题身份',
                    display_description=str(line or '').strip(),
                ))
            continue
        community_target = re.search(r'目标卡片.*(?:名称为|名为)[“"「]([^”"」]+)[”"」]', normalized_line)
        if community_target and any(token in normalized_line for token in ('在线', '简介', '介绍')):
            requirements = []
            if '在线' in normalized_line:
                requirements.append('online_count')
            if '简介' in normalized_line or '介绍' in normalized_line:
                requirements.append('community_intro')
            pending_community_result = {'target': community_target.group(1).strip(), 'required_signals': requirements}
            continue
        if pending_community_result and re.search(r'(?:点击|点).*(?:目标卡片|该目标卡片)', normalized_line):
            steps.append(_business_action(
                'nn_click_community_result',
                f'点击满足约束的社区搜索结果: {pending_community_result["target"]}',
                target_text=pending_community_result['target'],
                entity_type='community',
                required_signals=pending_community_result['required_signals'],
                display_description=str(line or '').strip(),
            ))
            pending_community_result = {}
            continue
        if re.match(r'^不(?:点击|执行|触发)', normalized_line):
            # A negative operation is a boundary condition, not an action.
            # Its expected state belongs to the expected-result section.
            continue
        compound_login = re.search(
            r'完成\s*(?:账号|手机号)\s*[：:]?\s*([0-9A-Za-z_@.+-]+)\s*[、,，]\s*'
            r'验证码\s*[：:]?\s*([0-9A-Za-z]+)\s*(?:登录|登陆)',
            normalized_line,
        )
        if compound_login:
            phone, code = compound_login.group(1), compound_login.group(2)
            steps.extend([
                _business_action('nn_fill_phone', '输入手机号', input_value=phone, field='手机号', display_description=str(line or '').strip()),
                _business_action('nn_fill_verification_code', '输入验证码', input_value=code, field='验证码', display_description=str(line or '').strip()),
                _business_action('nn_complete_login', '提交 NN 登录并校验登录态', display_description=str(line or '').strip()),
            ])
            continue
        sequence_targets = _dedupe_keep_order(re.findall(r'["“「]([^"”」]{1,80})["”」]', normalized_line))
        if '依次点击' in normalized_line and len(sequence_targets) >= 2:
            pending_click_sequence = sequence_targets
            continue
        if pending_click_sequence and '每次点击后' in normalized_line and any(word in normalized_line for word in ('断言', '验证', '检查')):
            for target in pending_click_sequence:
                click_step = (
                    _community_plugin_click(target, normalized_line)
                    if target in _COMMUNITY_PLUGIN_TARGETS
                    else compile_natural_language_line(f'点击「{target}」')
                )
                if click_step:
                    steps.append(click_step)
                    last_click_target = target
                steps.append({
                    'action_type': 'assert',
                    'description': f'断言左侧插件「{target}」处于选中状态',
                    'input_value': f'断言左侧插件「{target}」处于选中状态',
                    'assertion_contract': {
                        'kind': 'composite',
                        'predicates': [{'kind': 'selected', 'target': target, 'scope': 'left'}],
                    },
                    'element': None,
                })
                steps.append({
                    'action_type': 'assert',
                    'description': '断言页面无白屏、404、登录页或脚本异常提示',
                    'input_value': '断言页面无白屏、404、登录页或脚本异常提示',
                    'assert_type': 'page_health',
                    'assertion_contract': {'kind': 'page_health'},
                    'element': None,
                })
            pending_click_sequence = []
            continue
        repeat_click = re.search(r'再次点击\s*["“「]([^"”」]{1,80})["”」][，,、]?(.*)', normalized_line)
        if repeat_click and any(word in repeat_click.group(2) for word in ('断言', '验证', '检查')):
            target = _strip_quotes(repeat_click.group(1)).strip()
            click_step = (
                _community_plugin_click(target, normalized_line)
                if target in _COMMUNITY_PLUGIN_TARGETS
                else compile_natural_language_line(f'点击「{target}」')
            )
            if click_step:
                steps.append(click_step)
                last_click_target = target
            assertion_text = repeat_click.group(2).strip()
            if assertion_text and not re.match(r'^(断言|验证|检查)', assertion_text):
                assertion_text = '断言' + assertion_text
            step = compile_natural_language_line(assertion_text)
            if step:
                contract = build_assertion_contract(step)
                if contract:
                    step['assertion_contract'] = contract
                steps.append(step)
            continue
        continued_length = re.search(r'继续输入第\s*(\d+)\s*个?字符', str(line or ''))
        if continued_length and any(word in str(line) for word in ('断言', '验证', '检查')):
            count = int(continued_length.group(1))
            steps.append({
                'action_type': 'type',
                'description': f'输入 {count} 个测试字符',
                'input_value': '测' * count,
                'element': None,
            })
        # Article draft CRUD is stateful.  Compile it into semantic actions
        # that carry the runtime title through the management dialog instead
        # of reducing each sentence to a page-wide text click.
        if re.search(r'草稿箱.{0,80}(?:打开编辑|编辑操作|点击编辑|草稿编辑页)', normalized_line):
            steps.append(_business_action(
                'nn_open_article_draft_for_edit',
                '在草稿箱定位本次运行标题并打开编辑器',
                display_description=normalized_line,
            ))
            continue
        if re.search(r'草稿箱.{0,80}(?:删除操作|点击删除|删除该)', normalized_line):
            steps.append(_business_action(
                'nn_delete_article_draft',
                '在草稿箱定位本次运行标题并打开删除确认',
                display_description=normalized_line,
            ))
            continue
        if re.search(r'发布中.{0,80}(?:打开编辑|编辑操作|点击编辑)', normalized_line):
            steps.append(_business_action(
                'nn_open_article_published_for_edit',
                '在发布中定位本次运行标题并打开编辑器',
                display_description=normalized_line,
            ))
            continue
        if re.search(r'发布中.{0,80}(?:删除操作|点击删除|删除该)', normalized_line):
            steps.append(_business_action(
                'nn_delete_published_article',
                '在发布中定位本次运行标题并打开删除确认',
                display_description=normalized_line,
            ))
            continue
        if re.search(r'(?:删除确认弹窗|确认弹窗).{0,32}(?:确认删除|确定删除)|(?:确认删除|确定删除)', normalized_line):
            steps.append(_business_action(
                'nn_confirm_article_draft_delete',
                '确认删除本次运行草稿',
                display_description=normalized_line,
            ))
            continue
        if (
            re.search(r'(?:刷新|重新进入|返回).{0,40}草稿箱.{0,60}(?:查询|查找|定位)', normalized_line)
            and any(item.get('business_action') in ('nn_delete_article_draft', 'nn_confirm_article_draft_delete') for item in steps)
        ):
            steps.append(_business_action(
                'nn_verify_article_draft_absent',
                '验证本次运行草稿已从草稿箱删除',
                display_description=normalized_line,
            ))
            continue
        if (
            re.search(r'(?:返回|进入|打开).{0,50}(?:发布中|我的文章).{0,80}(?:查询|查找|定位)', normalized_line)
            and any(item.get('business_action') == 'nn_delete_published_article' for item in steps)
        ):
            steps.append(_business_action(
                'nn_verify_published_article_absent',
                '验证本次运行文章已从发布中删除',
                display_description=normalized_line,
            ))
            continue
        if (
            re.search(r'(?:返回|进入|打开).{0,50}发布中.{0,80}(?:查询|查找|定位)', normalized_line)
            and any(item.get('business_action') == 'nn_submit_article' for item in steps)
        ):
            steps.append(_business_action(
                'nn_verify_article_published',
                '验证本次运行文章已在发布中且不在草稿箱',
                display_description=normalized_line,
            ))
            continue
        article_update_title = re.search(r'(?:将)?标题(?:修改为|改为)\s*[“\"]?([^，。；;”\"]+)', normalized_line)
        article_append_body = re.search(r'(?:在)?正文末尾(?:追加|添加)\s*[“\"]?([^，。；;”\"]+)', normalized_line)
        if article_update_title or article_append_body:
            if article_update_title:
                steps.append(_business_action(
                    'nn_fill_article_title',
                    '修改文章标题',
                    input_value=_strip_quotes(article_update_title.group(1)).strip(),
                    display_description=normalized_line,
                ))
            if article_append_body:
                steps.append(_business_action(
                    'nn_append_article_body',
                    '在文章正文末尾追加内容',
                    input_value=_strip_quotes(article_append_body.group(1)).strip(),
                    display_description=normalized_line,
                ))
            if re.search(r'(?:点击|点).{0,28}(?:存草稿|保存草稿)', normalized_line):
                steps.append(_business_action('nn_save_article_draft', '保存文章草稿', display_description=normalized_line))
            elif re.search(r'(?:点击|点).{0,28}(?:发布|重新发布)|保存或重新发布', normalized_line):
                steps.append(_business_action('nn_submit_article', '发布文章', display_description=normalized_line))
            continue
        if re.search(r'(?:返回|进入|打开).{0,40}(?:我的文章|内容管理|草稿箱).{0,60}(?:草稿箱|查询|查找|定位)', normalized_line):
            if any(item.get('business_action') == 'nn_submit_article' for item in steps):
                steps.append(_business_action(
                    'nn_verify_article_published',
                    '验证本次运行文章已在发布中且不在草稿箱',
                    display_description=normalized_line,
                ))
                continue
            steps.append(_business_action(
                'nn_open_article_management',
                '打开草稿箱并验证本次运行草稿',
                article_tab='draft',
                display_description=normalized_line,
            ))
            continue
        article_input_steps = _extract_article_editor_input_steps(normalized_line)
        if article_input_steps:
            steps.extend(article_input_steps)
            if re.search(r'(?:点击|点).{0,28}(?:存草稿|保存草稿)', normalized_line):
                steps.append(_business_action('nn_save_article_draft', '保存文章草稿', display_description=normalized_line))
            elif re.search(r'(?:点击|点).{0,28}(?:编辑器.{0,16})?发布', normalized_line):
                steps.append(_business_action('nn_submit_article', '发布文章', display_description=normalized_line))
            continue
        activity_article_match = re.search(
            r'(?:活动编辑器.{0,40})?(?:填写|填入).{0,16}标题\s+([^，。；;\s]+).{0,80}?(?:正文|内容)\s*(?:输入|填写|填入)?[“\"]?([^”\"。；;]+)',
            normalized_line,
        )
        if activity_article_match:
            steps.extend([
                _business_action('nn_fill_article_title', '输入文章标题', input_value=activity_article_match.group(1).strip(), display_description=normalized_line),
                _business_action('nn_fill_article_body', '输入文章正文', input_value=_strip_quotes(activity_article_match.group(2)).strip(), display_description=normalized_line),
            ])
            continue
        if re.search(r'评论.{0,32}(?:输入入口|输入框|输入区域)', normalized_line) and re.search(r'(?:点击|点)', normalized_line):
            steps.append(_business_action(
                'nn_focus_article_comment',
                '聚焦文章评论输入框',
                display_description=normalized_line,
            ))
            continue
        comment_value_match = re.search(r'(?:输入|填写)\s*[“\"]([^”\"]+)[”\"]', normalized_line)
        if comment_value_match and any(
            item.get('business_action') in ('nn_open_article_detail', 'nn_focus_article_comment')
            for item in steps
            if item.get('action_type') == 'business_action'
        ):
            steps.append(_business_action(
                'nn_fill_article_comment',
                '输入文章评论',
                input_value=_strip_quotes(comment_value_match.group(1)).strip(),
                display_description=normalized_line,
            ))
            continue
        if re.search(r'内容管理.{0,80}(?:点击|进入).{0,40}发布', normalized_line):
            # The community page exposes publishing from the article toolbar.
            # "内容管理 -> 发布" is imported prose, not a real nested path:
            # content management opens a modal that covers the toolbar.
            steps.append(_business_action(
                'nn_open_article_editor',
                '打开文章发布编辑器',
                display_description=normalized_line,
            ))
            article_type = re.search(r'[「“"]?(活动|公告|攻略)[」”"]?', normalized_line)
            if article_type:
                value = article_type.group(1)
                steps.append(_business_action(
                    'nn_select_article_type', f'选择文章发布类型：{value}',
                    target_text=value, article_type=value, display_description=normalized_line,
                ))
            continue
        step = compile_natural_language_line(line)
        if not step:
            continue
        if (
            step.get('action_type') == 'click'
            and str(step.get('target_text') or '').strip() in _COMMUNITY_PLUGIN_TARGETS
        ):
            step = _community_plugin_click(str(step.get('target_text')).strip(), normalized_line)
        if step.get('action_type') == 'click':
            target = str(step.get('target_text') or '').strip()
            article_actions = [item.get('business_action') for item in steps if item.get('action_type') == 'business_action']
            if target in {'发布', '发布按钮'}:
                if any(name in article_actions for name in ('nn_select_article_type', 'nn_fill_article_title', 'nn_fill_article_body')):
                    step = _business_action('nn_submit_article', '发布文章', display_description=str(line or '').strip())
                else:
                    step = _business_action('nn_open_article_editor', '打开文章发布编辑器', display_description=str(line or '').strip())
            elif target in {'存草稿', '保存草稿'} and any(name in article_actions for name in ('nn_open_article_editor', 'nn_fill_article_title', 'nn_fill_article_body')):
                step = _business_action('nn_save_article_draft', '保存文章草稿', display_description=str(line or '').strip())
            elif target in {'我的文章', '草稿箱', '发布中'} and any(name in article_actions for name in ('nn_open_article_editor', 'nn_fill_article_title', 'nn_fill_article_body', 'nn_save_article_draft', 'nn_submit_article')):
                step = _business_action('nn_open_article_management', '打开文章内容管理', display_description=str(line or '').strip())
        contract = build_assertion_contract(step)
        if contract and ('该插件' in str(step.get('description') or '') or '当前插件' in str(step.get('description') or '')) and last_click_target:
            for predicate in contract.get('predicates') or []:
                if predicate.get('kind') == 'selected':
                    predicate['target'] = last_click_target
        if contract:
            if (
                contract.get('kind') == 'assertion_plan'
                and target_url
                and any(term in str(step.get('description') or '') for term in ('目标地址', '仍停留', '返回', '停留'))
                and not any(item.get('kind') == 'url_contains' for item in contract.get('predicates') or [])
            ):
                contract.setdefault('predicates', []).append({'kind': 'url_contains', 'value': target_url})
            step['assertion_contract'] = contract
        steps.append(step)
        if step.get('action_type') in ('click', 'try_click') and step.get('target_text'):
            last_click_target = str(step['target_text'])
        elif step.get('business_action') == 'nn_click_community_plugin' and step.get('target_text'):
            last_click_target = str(step['target_text'])
        # Generic search still needs a submit signal. Structured top-search
        # actions handle Enter internally because the pseudo input must be
        # opened before filling.
        if step.get('action_type') == 'type' and str(step.get('description', '')).startswith('搜索:'):
            steps.append({'action_type': 'press', 'description': '按回车确认搜索', 'input_value': 'Enter', 'element': None})
        elif step.get('action_type') == 'type' and step.get('press_after'):
            steps.append({
                'action_type': 'press',
                'description': f"按{step.get('press_after')}确认输入",
                'input_value': step.get('press_after'),
                'element': None,
            })
    if is_member_hall_case:
        hall_text = str(task_desc or '')
        action_names = [step.get('business_action') for step in steps]
        # A few imported hall steps start with narrative phrases such as
        # “在消息流中…依次撤回”. They are valid operations but do not begin
        # with the generic action verbs used by the splitter above.
        if '依次撤回' in hall_text and 'nn_hall_retract_runtime_messages' not in action_names:
            steps.append(_business_action('nn_hall_retract_runtime_messages', '依次撤回本次回复和原始消息'))
        if ('表情' in hall_text or '贴纸' in hall_text) and '发送该表情消息' in hall_text:
            emoji_retract = next((step for step in steps if step.get('business_action') == 'nn_hall_retract_runtime_message' and step.get('message_role') == 'emoji'), None)
            if emoji_retract:
                steps.remove(emoji_retract)
            if 'nn_hall_send_selected_emoji' not in [step.get('business_action') for step in steps]:
                steps.append(_business_action('nn_hall_send_selected_emoji', '发送已选择的成员大厅表情'))
            if emoji_retract:
                steps.append(emoji_retract)
    # Imported prose is often split before compilation, turning the invalid
    # "content management, then publish" path into adjacent actions. Collapse
    # that pair here as well as in the whole-sentence branch above.
    normalized_steps = []
    for step in steps:
        if (
            step.get('action_type') == 'business_action'
            and step.get('business_action') == 'nn_open_article_editor'
            and normalized_steps
            and normalized_steps[-1].get('action_type') == 'business_action'
            and normalized_steps[-1].get('business_action') == 'nn_open_article_management'
        ):
            normalized_steps.pop()
        normalized_steps.append(step)
    return normalized_steps
