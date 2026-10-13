import asyncio
import base64
import json
from io import BytesIO

from PIL import Image

import pytest

from apps.ui_automation.desktop_engine import (
    DesktopAutomationError,
    _bring_window_to_foreground,
    _control_content,
    _desktop_task_instructions,
    _cdp_dom_assertion_for_index,
    _cdp_route_from_task_description,
    _cdp_community_from_route,
    _cdp_agent_startupinfo,
    _capture_cdp_screenshot,
    _ensure_cdp_endpoint,
    _elevated_cdp_launcher_command,
    _cdp_target_route,
    _cdp_setup_actions,
    _reset_cdp_case_state,
    _normalize_cdp_dom_assertion_result,
    _persist_desktop_execution_gif,
    _plan_desktop_action,
    _find_ready_window,
    _is_community_detail_assertion,
    _is_community_home_presence_assertion,
    _community_home_content_entry_label,
    _is_community_home_content_detail_assertion,
    _is_community_home_faq_scroll_instruction,
    _is_community_home_faq_expand_instruction,
    _is_community_home_faq_assertion,
    _is_team_home_content_assertion,
    _is_community_search_user_empty_assertion,
    _is_community_search_community_results_assertion,
    _is_community_home_setup_instruction,
    _is_community_search_result_click,
    _is_affiliated_community_page_assertion,
    _is_team_detail_assertion,
    _is_cdp_connection_error,
    _is_battle_page_presence_assertion,
    _is_battle_stats_data_assertion,
    _battle_query_input_value,
    _battle_query_expected_value,
    _is_battle_query_visibility_assertion,
    _expected_cdp_route_assertion,
    _is_hall_layout_assertion,
    _is_hall_menu_consistency_instruction,
    _is_hall_other_member_fixture_assertion,
    _is_hall_message_recall_instruction,
    _is_hall_message_recall_assertion,
    _is_hall_invite_assertion,
    _is_hall_system_notification_assertion,
    _cdp_replace_focused_input,
    _is_hall_generated_message_send_confirmation,
    _is_hall_generated_message_ui_assertion,
    _order_desktop_task_instructions,
    _is_hall_emoji_selection_instruction,
    _is_hall_emoji_send_instruction,
    _is_hall_emoji_recall_instruction,
    _is_hall_emoji_message_assertion,
    _hall_unique_message_assertion_kind,
    _is_article_latest_tab_assertion,
    _is_article_list_metadata_assertion,
    _is_read_only_cdp_instruction,
    _is_renderer_health_assertion,
    _is_article_publish_entry_assertion,
    _is_article_publish_open_instruction,
    _is_article_publish_type_assertion,
    _is_article_preview_instruction,
    _is_article_preview_assertion,
    _is_recruitment_dialog_assertion,
    _is_recruitment_default_publish_assertion,
    _is_team_home_filter_panel_assertion,
    _is_team_home_filter_open_instruction,
    _is_team_home_filter_tab_switch_instruction,
    _is_team_home_filter_search_instruction,
    _is_team_home_filter_search_assertion,
    _is_community_plugin_switch_stability_instruction,
    _is_community_plugin_switch_stability_verification,
    _is_battle_query_clear_instruction,
    _is_login_state_assertion,
    _ensure_cdp_nn_login,
    _ensure_cdp_hall_message_context,
    _is_wait_only_instruction,
    _requested_wait_seconds,
    _planned_step_from_action,
    _plan_desktop_action,
    _validate_visual_assertion_result,
    _validate_config,
    _visual_assertion_crop_boxes,
    _visual_assertion_interpretation,
)
from apps.ui_automation.views.ai import _cdp_login_credentials_from_setup_template


def test_persist_desktop_execution_gif_builds_replay_from_step_screenshots(tmp_path, monkeypatch):
    monkeypatch.setattr('apps.ui_automation.desktop_engine.settings.MEDIA_ROOT', str(tmp_path))
    screenshot_dir = tmp_path / 'ui_automation' / 'desktop_execution' / '9'
    screenshot_dir.mkdir(parents=True)
    screenshot_path = screenshot_dir / 'step_1.png'
    Image.new('RGB', (32, 20), (10, 20, 30)).save(screenshot_path)

    class Record:
        id = 9
        gif_path = ''
        logs = ''

        def save(self, **kwargs):
            self.saved_fields = kwargs.get('update_fields')

    record = Record()
    assert _persist_desktop_execution_gif(record, [{
        'screenshot': '/media/ui_automation/desktop_execution/9/step_1.png',
        'description': 'Wait for desktop state',
    }]) is True
    assert record.gif_path == '/media/ui_automation/desktop_execution/9/execution.gif'
    assert (screenshot_dir / 'execution.gif').is_file()


class _CdpScreenshotPage:
    def __init__(self, frames):
        self.frames = list(frames)
        self.capture_count = 0
        self.paint_wait_count = 0

    async def call(self, method, params):
        assert method == 'Page.captureScreenshot'
        self.capture_count += 1
        frame = self.frames.pop(0) if self.frames else b''
        return {'data': base64.b64encode(frame).decode('ascii')}

    async def evaluate(self, expression):
        assert 'requestAnimationFrame' in expression
        self.paint_wait_count += 1
        return True


class _FocusedInputPage:
    def __init__(self, max_length=15):
        self.max_length = max_length
        self.calls = []

    async def evaluate(self, expression):
        assert 'activeElement' in expression
        return self.max_length

    async def call(self, method, params):
        self.calls.append((method, params))
        return {}


def _png_bytes(color, with_contrast=False):
    image = Image.new('RGB', (16, 16), color)
    if with_contrast:
        image.putpixel((0, 0), (255, 255, 255))
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def test_cdp_screenshot_retries_a_uniform_dark_compositor_frame(tmp_path, monkeypatch):
    monkeypatch.setattr('apps.ui_automation.desktop_engine.settings.MEDIA_ROOT', str(tmp_path))

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr('apps.ui_automation.desktop_engine.asyncio.sleep', no_sleep)
    page = _CdpScreenshotPage([
        _png_bytes((31, 32, 34)),
        _png_bytes((31, 32, 34)),
        _png_bytes((20, 24, 32), with_contrast=True),
    ])

    result = asyncio.run(_capture_cdp_screenshot(page, 42, 1))

    assert result == 'ui_automation/desktop_execution/42/cdp_step_1.png'
    assert page.capture_count == 3
    assert page.paint_wait_count == 2


def test_cdp_screenshot_does_not_persist_a_uniform_dark_compositor_frame(tmp_path, monkeypatch):
    monkeypatch.setattr('apps.ui_automation.desktop_engine.settings.MEDIA_ROOT', str(tmp_path))

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr('apps.ui_automation.desktop_engine.asyncio.sleep', no_sleep)
    page = _CdpScreenshotPage([_png_bytes((31, 32, 34))] * 10)

    assert asyncio.run(_capture_cdp_screenshot(page, 43, 1)) is None
    assert page.capture_count == 10
    assert page.paint_wait_count == 9
    assert not (tmp_path / 'ui_automation' / 'desktop_execution' / '43' / 'cdp_step_1.png').exists()


def test_cdp_native_input_replace_honors_the_control_max_length():
    page = _FocusedInputPage(max_length=15)

    result = asyncio.run(_cdp_replace_focused_input(page, 'NO_MEMBER_1788576469588'))

    assert result == 'NO_MEMBER_17885'
    assert [method for method, _ in page.calls] == [
        'Input.dispatchKeyEvent', 'Input.dispatchKeyEvent', 'Input.dispatchKeyEvent',
        'Input.dispatchKeyEvent', 'Input.dispatchKeyEvent', 'Input.dispatchKeyEvent',
        'Input.insertText',
    ]
    assert page.calls[-1][1]['text'] == result


class _CdpPlannerResponse:
    def __init__(self, content):
        self.content = content


class _CdpStatePage:
    def __init__(self):
        self.expression = ''

    async def evaluate(self, expression):
        self.expression = expression
        return {
            'removedMarkers': 4,
            'clearedMemberSearch': True,
            'clearedDraft': True,
            'closedOverlays': 1,
            'closedEmojiPanel': True,
        }


class _CdpLoginPage:
    def __init__(self, login_error=''):
        self.expressions = []
        self.calls = []
        self.login_error = login_error

    async def evaluate(self, expression):
        self.expressions.append(expression)
        # The first call checks the current guest state, the second submits
        # the form, and the final poll observes a real authenticated session.
        if len(self.expressions) == 1:
            return {'formVisible': True, 'hasSession': False}
        if len(self.expressions) == 2:
            return {'submitted': True, 'submit_point': {'x': 600, 'y': 400}}
        if self.login_error:
            return {'formVisible': True, 'hasSession': False, 'loginError': self.login_error}
        return {'formVisible': False, 'hasSession': True}

    async def call(self, method, params):
        self.calls.append((method, params))
        return {}


class _CdpAvatarLoginPage(_CdpLoginPage):
    def __init__(self):
        super().__init__()

    async def evaluate(self, expression):
        self.expressions.append(expression)
        if len(self.expressions) == 1:
            return {'formVisible': False, 'hasSession': False}
        if len(self.expressions) == 2:
            return {'formVisible': False, 'entryPoint': {'x': 72, 'y': 862}}
        if len(self.expressions) == 3:
            return {'formVisible': True}
        if len(self.expressions) == 4:
            return {'submitted': True, 'submit_point': {'x': 600, 'y': 400}}
        return {'formVisible': False, 'hasSession': True}


class _CdpHallContextPage:
    def __init__(self):
        self.expressions = []

    async def evaluate(self, expression):
        self.expressions.append(expression)
        return {
            'ready': True,
            'conversationId': '1001012822',
            'messageCount': 4,
            'conversationType': 'GROUP',
            'sendTo': '1001012822',
            'prerequisites': {
                'onHallRoute': True,
                'authenticated': True,
                'composerVisible': True,
                'piniaAvailable': True,
                'activeConversation': True,
            },
        }


class _CdpRecordingPlanner:
    def __init__(self, response):
        self.response = response
        self.prompt = None

    def invoke(self, prompt):
        self.prompt = json.loads(prompt)
        return _CdpPlannerResponse(self.response)


def test_desktop_config_requires_explicit_steps():
    with pytest.raises(DesktopAutomationError, match='non-empty steps'):
        _validate_config({})


def test_cdp_planner_excludes_screenshot_actions():
    planner = _CdpRecordingPlanner('{"action":"wait","seconds":1,"description":"wait"}')

    action = _plan_desktop_action(
        planner,
        'Task',
        'Wait for the page',
        [{'control_id': 'button-1', 'name': 'Continue'}],
        allow_screenshot=False,
    )

    assert action['action'] == 'wait'
    assert 'screenshot' not in planner.prompt['allowed_actions']
    assert 'screenshot' not in planner.prompt['response_schema']['action']


def test_inline_phone_login_is_split_into_atomic_desktop_instructions():
    instructions = _desktop_task_instructions(
        '\u8bbf\u95ee NN \u5ba2\u6237\u7aef \u70b9\u51fb\u767b\u5f55\u5165\u53e3 \u8f93\u5165\u624b\u673a\u53f717680942927 '
        '\u8f93\u5165\u9a8c\u8bc1\u78018888 \u5e76\u52fe\u9009\"\u5df2\u7ecf\u9605\u8bfb\u5e76\u540c\u610f\u7528\u6237\u624b\u518c\" '
        '\u70b9\u51fb\u767b\u5f55\u6309\u94ae \u5b8c\u6210\u767b\u5f55\u3002'
    )

    assert len(instructions) == 7
    assert instructions[2].endswith('17680942927\u3002')
    assert instructions[3].endswith('8888\u3002')
    assert instructions[-1].startswith('\u65ad\u8a00\uff1a')


def test_cdp_login_credentials_are_read_from_the_selected_setup_template():
    class Template:
        id = 2
        name = '\u767b\u5f55NN\u6d4b\u8bd5\u73af\u5883'
        steps = [
            {'description': '\u8f93\u5165\u8d26\u53f717680942927'},
            {'description': '\u8f93\u5165\u9a8c\u8bc1\u78018888'},
        ]

    assert _cdp_login_credentials_from_setup_template(Template()) == {
        'phone': '17680942927',
        'verification_code': '8888',
        'template_id': 2,
        'template_name': '\u767b\u5f55NN\u6d4b\u8bd5\u73af\u5883',
    }


def test_cdp_nn_login_scopes_submit_to_the_phone_form_panel():
    page = _CdpLoginPage()

    assert asyncio.run(_ensure_cdp_nn_login(page, {
        'cdp_login_credentials': {'phone': '17680942927', 'verification_code': '8888'},
    })) is True

    submit_expression = page.expressions[1]
    assert "const loginPanel = loginForm.closest('.ui-dialog')" in submit_expression
    assert 'loginPanel.querySelectorAll' in submit_expression
    assert '\\u5173\\u6ce8\\u793e\\u533a' in submit_expression
    assert "element.id !== 'app'" in submit_expression
    assert 'const deadline = Date.now() + 2500' in submit_expression
    assert 'HTMLElement.click()' in submit_expression
    assert [method for method, _params in page.calls] == [
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
    ]


def test_cdp_nn_login_opens_the_avatar_entry_with_trusted_cdp_input():
    page = _CdpAvatarLoginPage()

    assert asyncio.run(_ensure_cdp_nn_login(page, {
        'cdp_login_credentials': {'phone': '17680942927', 'verification_code': '8888'},
    })) is True

    assert [method for method, _params in page.calls] == [
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
        'Input.dispatchMouseEvent',
    ]


def test_cdp_nn_login_surfaces_the_desktop_client_rejection_message():
    page = _CdpLoginPage('\u9a8c\u8bc1\u7801\u9519\u8bef\uff0c\u8bf7\u91cd\u65b0\u8f93\u5165\uff01')

    with pytest.raises(DesktopAutomationError, match='NN Agent login rejected: .*\u9a8c\u8bc1\u7801\u9519\u8bef'):
        asyncio.run(_ensure_cdp_nn_login(page, {
            'cdp_login_credentials': {'phone': '17680942927', 'verification_code': '8888'},
        }))


def test_hall_message_context_uses_the_selected_real_group_conversation():
    page = _CdpHallContextPage()

    context = asyncio.run(_ensure_cdp_hall_message_context(page))

    assert context['conversationId'] == '1001012822'
    assert context['conversationType'] == 'GROUP'
    assert context['sendTo'] == '1001012822'
    expression = page.expressions[0]
    assert "value._s.get('chat')" in expression
    assert 'const selected = chat?.state?.selectedChat || chat?.state || {}' in expression
    assert 'const hasMessageContext = Array.isArray(item?.msgList)' in expression
    assert '? chatMap[conversationId]' in expression
    assert "__testhub_hall_conversation_id" in expression


def test_hall_message_recall_instruction_is_not_left_to_the_generic_planner():
    assert _is_hall_message_recall_instruction(
        '操作：依次撤回顺序B和顺序A，完成数据清理。'
    ) is True
    assert _is_hall_message_recall_instruction('操作：点击消息输入框。') is False
    assert _is_hall_message_recall_assertion(
        '断言：撤回清理后两条测试消息均不再作为正常消息显示。'
    ) is True


def test_hall_custom_emoji_flow_is_not_left_to_the_generic_planner():
    assert _is_hall_emoji_selection_instruction('操作：选择一个可见表情或贴纸，确认其进入输入区。') is True
    assert _is_hall_emoji_send_instruction('操作：发送该表情消息，在消息流中定位刚发送的表情消息。') is True
    assert _is_hall_emoji_recall_instruction('操作：打开该表情消息操作菜单并撤回，完成数据清理。') is True
    assert _is_hall_emoji_message_assertion('断言：发送后消息流新增且仅新增 1 条表情消息。') is True
    assert _is_hall_emoji_message_assertion('断言：撤回后该表情消息不再作为普通消息展示。') is True


def test_hall_unique_message_assertions_use_run_scoped_message_evidence():
    assert _hall_unique_message_assertion_kind(
        '断言：两次发送均获得正常页面反馈，输入框不会因第一次发送而锁死或保留旧文本。'
    ) == 'send_feedback'
    assert _hall_unique_message_assertion_kind(
        '断言：消息流中每个唯一正文仅出现 1 次，顺序A位于顺序B之前。'
    ) == 'order'
    assert _hall_unique_message_assertion_kind(
        '断言：未生成重复消息、空白消息或与其他成员消息串位的消息单元。'
    ) == 'integrity'


def test_hall_system_notification_assertion_requires_message_structure():
    assert _is_hall_system_notification_assertion(
        '断言：系统通知标题、通知正文和系统图标属于同一消息单元。'
    ) is True
    assert _is_hall_system_notification_assertion('断言：大厅消息流正常显示。') is False


def test_hall_generated_message_follow_up_steps_use_deterministic_evidence():
    assert _is_hall_generated_message_send_confirmation(
        '操作：点击与该唯一消息对应的发送按钮，或使用客户端支持的发送快捷键提交消息。'
    ) is True
    assert _is_hall_generated_message_ui_assertion(
        '断言：发送操作后输入内容恢复为默认占位状态，页面不跳转且不显示错误提示。'
    ) is True
    assert _is_hall_generated_message_ui_assertion(
        '断言：消息的发送者、头像和时间戳属于同一条消息单元。'
    ) is True
    assert _is_hall_generated_message_ui_assertion('断言：系统通知标题和正文属于同一消息单元。') is False


def test_channel_share_entry_is_not_treated_as_a_member_hall_invite_dialog():
    assert _is_hall_invite_assertion('断言：频道顶部存在邀请/分享入口。') is False
    assert _is_hall_invite_assertion('断言：邀请好友弹窗已打开且内容正常。') is True


def test_explicit_wait_duration_is_preserved_for_desktop_cases():
    assert _requested_wait_seconds('操作：等待 2 秒。') == 2
    assert _requested_wait_seconds('操作：等待页面加载。') is None
    assert _requested_wait_seconds('操作：点击后等待 2 秒。') is None


def test_cdp_case_reset_clears_only_case_local_renderer_state():
    page = _CdpStatePage()

    result = asyncio.run(_reset_cdp_case_state(page, 'before'))

    assert result['phase'] == 'before'
    assert result['removedMarkers'] == 4
    assert "key.startsWith('__testhub_')" in page.expression
    assert 'document.documentElement.children' in page.expression
    assert 'removedInjectedOverlays' in page.expression
    assert 'localStorage.removeItem' not in page.expression


def test_login_state_assertion_uses_deterministic_dom_check():
    assert _is_login_state_assertion('\u65ad\u8a00\uff1a\u767b\u5f55\u6210\u529f\u540e\u5934\u50cf\u4e0d\u662f\u9ed8\u8ba4\u5934\u50cf\u3002') is True
    assert _is_login_state_assertion('\u65ad\u8a00\uff1a\u793e\u533a\u5217\u8868\u5df2\u52a0\u8f7d\u3002') is False


def test_battle_page_assertion_uses_stable_route_and_query_concepts():
    assert _is_battle_page_presence_assertion(
        '\u65ad\u8a00\uff1a\u6218\u7ee9\u67e5\u8be2(\u4fee\u6539\u540e)\u6807\u9898\u548c\u300c\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9\u300d\u8f93\u5165\u6846\u53ef\u89c1\u3002'
    ) is True
    assert _is_battle_page_presence_assertion('\u65ad\u8a00\uff1a\u6218\u7ee9\u6570\u636e\u52a0\u8f7d\u5b8c\u6210\u3002') is False


def test_battle_query_input_operations_preserve_literal_values():
    assert _battle_query_input_value('\u64cd\u4f5c\uff1a\u5728\u201c\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9\u201d\u8f93\u5165\u6846\u586b\u5199test') == 'test'
    assert _battle_query_input_value('\u64cd\u4f5c\uff1a\u5728\u201c\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9\u201d\u8f93\u5165\u6846\u586b\u5199\u4e09\u4e2a\u7a7a\u683c') == '   '
    assert _is_battle_query_clear_instruction('\u64cd\u4f5c\uff1a\u6e05\u7a7a\u201c\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9\u201d\u8f93\u5165\u6846') is True
    assert _battle_query_expected_value('\u65ad\u8a00\uff1a\u65ad\u8a00\u201c\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9\u201d\u8f93\u5165\u6846\u5f53\u524d\u503c\u4e3a PUBGID123') == 'PUBGID123'
    assert _battle_query_expected_value('\u65ad\u8a00\uff1a\u65ad\u8a00\u201c\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9\u201d\u8f93\u5165\u6846\u5f53\u524d\u503c\u4e3a\u7a7a') == ''
    assert _is_battle_query_visibility_assertion('\u65ad\u8a00\uff1a\u65ad\u8a00\u201c\u67e5\u8be2\u73a9\u5bb6\u6218\u7ee9\u201d\u8f93\u5165\u6846\u53ef\u89c1\u4e14\u9875\u9762\u5730\u5740\u672a\u8df3\u8f6c') is True


def test_explicit_desktop_route_assertions_use_the_renderer_route():
    assert _expected_cdp_route_assertion('\u65ad\u8a00\uff1a\u5f53\u524d\u5730\u5740\u4fdd\u6301\u4e3a /community/7520/hall\u3002') == '/community/7520/hall'
    assert _expected_cdp_route_assertion('\u64cd\u4f5c\uff1a\u8bbf\u95ee /community/7520/hall\u3002') == ''


def test_hall_layout_assertion_uses_hall_structure_not_a_screenshot_crop():
    assert _is_hall_layout_assertion('\u65ad\u8a00\uff1a\u9875\u9762\u53ef\u89c1\u201c\u6210\u5458\u5927\u5385\u201d\u6807\u9898\u3001\u5de6\u4fa7\u793e\u533a\u5bfc\u822a\u3001\u4e2d\u592e\u6d88\u606f\u6d41\u548c\u53f3\u4fa7\u6210\u5458\u5217\u8868\u56db\u4e2a\u533a\u57df\u3002') is True
    assert _is_hall_layout_assertion('\u65ad\u8a00\uff1a\u9875\u9762\u53ef\u89c1\u6210\u5458\u5927\u5385\u6807\u9898\u3002') is False


def test_article_latest_tab_assertion_uses_the_active_tab_state():
    assert _is_article_latest_tab_assertion('\u65ad\u8a00\uff1a\u201c\u6700\u65b0\u201d\u6807\u7b7e\u5904\u4e8e\u9009\u4e2d\u72b6\u6001\u3002') is True
    assert _is_article_latest_tab_assertion('\u65ad\u8a00\uff1a\u9875\u9762\u5c55\u793a\u201c\u6700\u65b0\u201d\u6807\u7b7e\u3002') is False


def test_article_list_metadata_assertion_requires_a_dynamic_list_expectation():
    assert _is_article_list_metadata_assertion('\u65ad\u8a00\uff1a\u6587\u7ae0\u5217\u8868\u81f3\u5c11\u5c55\u793a\u4e00\u6761\u53ef\u89c1\u6587\u7ae0\uff1b\u6bcf\u6761\u6587\u7ae0\u5c55\u793a\u6807\u9898\u3001\u53d1\u5e03\u65f6\u95f4\u4ee5\u53ca\u8bc4\u8bba\u6570\u3002') is True
    assert _is_article_list_metadata_assertion('\u65ad\u8a00\uff1a\u6587\u7ae0\u5217\u8868\u5df2\u52a0\u8f7d\u3002') is False


def test_read_only_cdp_instruction_does_not_plan_phantom_clicks():
    assert _is_read_only_cdp_instruction('\u64cd\u4f5c\uff1a\u67e5\u770b\u5f53\u524d\u9009\u4e2d\u7684\u201c\u6700\u65b0\u201d\u6807\u7b7e\u53ca\u5176\u4e0b\u65b9\u6587\u7ae0\u5217\u8868\u3002') is True
    assert _is_read_only_cdp_instruction('\u64cd\u4f5c\uff1a\u5b9a\u4f4d\u6587\u7ae0\u5361\u7247\u5e76\u70b9\u51fb\u3002') is False


def test_renderer_health_assertion_handles_cross_page_error_checks():
    assert _is_renderer_health_assertion('\u65ad\u8a00\uff1a\u9875\u9762\u65e0\u767d\u5c4f\u3001404\u6216\u811a\u672c\u9519\u8bef\u3002') is True
    assert _is_renderer_health_assertion('\u65ad\u8a00\uff1a\u9875\u9762\u5c55\u793a\u6807\u9898\u3002') is False


def test_article_publish_entry_assertion_recognizes_the_publish_editor():
    assert _is_article_publish_entry_assertion('\u65ad\u8a00\uff1a\u6253\u5f00\u6587\u7ae0\u53d1\u5e03\u7f16\u8f91\u754c\u9762\u3002') is True
    assert _is_article_publish_entry_assertion('\u65ad\u8a00\uff1a\u53d1\u5e03\u6309\u94ae\u53ef\u89c1\u3002') is False


def test_article_publish_open_instruction_targets_article_publish_not_confirm_publish():
    assert _is_article_publish_open_instruction('\u64cd\u4f5c\uff1a\u70b9\u51fb\u6587\u7ae0\u5185\u5bb9\u533a\u4e0a\u65b9\u7684\u201c\u53d1\u5e03\u201d\u6309\u94ae\u3002') is True
    assert _is_article_publish_open_instruction('\u64cd\u4f5c\uff1a\u70b9\u51fb\u201c\u786e\u5b9a\u53d1\u5e03\u201d\u3002') is False


def test_article_publish_controls_use_the_current_two_publish_types_and_preview_surface():
    assert _is_article_publish_type_assertion('\u65ad\u8a00\uff1a\u53d1\u5e03\u7c7b\u578b\u540c\u65f6\u63d0\u4f9b\u201c\u53d1\u5e03\u6587\u7ae0\u201d\u4e0e\u201c\u53d1\u5e03H5\u6d3b\u52a8\u201d\u3002') is True
    assert _is_article_publish_type_assertion('\u65ad\u8a00\uff1a\u53d1\u5e03\u6587\u7ae0\u53ef\u89c1\u3002') is False
    assert _is_article_preview_instruction('\u64cd\u4f5c\uff1a\u70b9\u51fb\u201c\u9884\u89c8\u201d\u3002') is True
    assert _is_article_preview_assertion('\u65ad\u8a00\uff1a\u6587\u7ae0\u9884\u89c8\u9762\u677f\u5df2\u6253\u5f00\u3002') is True


def test_community_result_and_detail_instructions_use_deterministic_cdp_handlers():
    home = '\u64cd\u4f5c\uff1a\u542f\u52a8\u6216\u5207\u6362\u5230 NN \u5ba2\u6237\u7aef\uff0c\u8fdb\u5165\u793e\u533a\u9996\u9875\u540e\u518d\u6267\u884c\u4ee5\u4e0b\u6b65\u9aa4\uff1a'
    click = '\u64cd\u4f5c\uff1a\u70b9\u51fb\u793e\u533a\u641c\u7d22\u7ed3\u679c\u4e0b\u7684\u201c\u7edd\u5730\u6c42\u751f\u793e\u533a\u201d\uff0c\u5fc5\u987b\u6709\u5728\u7ebf\u4eba\u6570\u548c\u793e\u533a\u7b80\u4ecb\u3002'
    assertion = '\u65ad\u8a00\uff1a\u65ad\u8a00\u5df2\u8fdb\u5165\u201c\u7edd\u5730\u6c42\u751f\u201d\u76ee\u6807\u793e\u533a\u8be6\u60c5\u9875\uff0c\u4e14\u5de6\u4fa7\u793e\u533a\u9762\u677f\u663e\u793a PUBG\u4e2d\u56fd\u5b98\u65b9\u793e\u533a\u3002'

    assert _is_community_home_setup_instruction(home) is True
    assert _is_community_search_result_click(click) is True
    assert _is_community_search_result_click(
        '\u64cd\u4f5c\uff1a\u70b9\u51fb\u5305\u542b\u7edd\u5730\u6c42\u751f\u793e\u533a\u4fe1\u606f\u548c\u5728\u7ebf\u4eba\u6570\u7684\u793e\u533a\uff0c\u8fdb\u5165\u201c\u7edd\u5730\u6c42\u751f\u201d'
    ) is True
    assert _is_community_detail_assertion(assertion) is True


def test_team_detail_assertion_does_not_match_the_affiliated_list_assertion():
    assertion = '断言：社区头部展示 ID「10079288」，左侧社区名称展示「test0915」，且不再显示旗下社区卡片列表。'

    assert _is_team_detail_assertion(assertion) is True
    assert _is_affiliated_community_page_assertion(assertion) is False


def test_affiliated_list_assertion_handles_selected_state_and_create_entry():
    assertion = '断言：断言左侧「旗下社区」处于选中状态，主内容区展示「旗下社区」和「创建战队社区」按钮。'

    assert _is_affiliated_community_page_assertion(assertion) is True


def test_recruitment_assertion_handles_dialog_state_and_counter_variants():
    assert _is_recruitment_dialog_assertion('断言：断言弹窗保持打开。') is True
    assert _is_recruitment_dialog_assertion('断言：断言输入计数显示 15/15，且文本完整保留。') is True


def test_recruitment_default_publish_assertion_is_explicit():
    assert _is_recruitment_default_publish_assertion(
        '断言：发布至【绝地求生】官方社区复选项默认已勾选。'
    ) is True
    assert _is_recruitment_default_publish_assertion('断言：发布招募信息弹窗已打开。') is False


def test_team_filter_panel_assertion_requires_the_filter_controls():
    assertion = '断言：断言筛选面板展示“全部”“组队”“直播”“互动”“空房”、输入框“全局搜索关键词 房间号”和“刷新”按钮。'

    assert _is_team_home_filter_panel_assertion(assertion) is True


def test_team_filter_open_instruction_is_deterministic():
    assert _is_team_home_filter_open_instruction('操作：点击“筛选”。') is True


def test_team_filter_tab_switch_and_search_instructions_are_deterministic():
    assert _is_team_home_filter_tab_switch_instruction(
        '操作：分别点击「组队」「直播」「互动」「空房」。'
    ) is True
    assert _is_team_home_filter_search_instruction(
        '操作：在「全局搜索关键词 房间号」输入 999999999。'
    ) is True
    assert _is_team_home_filter_search_instruction('操作：清空搜索关键词，点击「刷新」。') is True
    assert _is_team_home_filter_search_assertion('断言：断言筛选结果展示空状态。') is True


def test_community_plugin_switch_stability_instruction_requires_a_complete_switch_sequence():
    assert _is_community_plugin_switch_stability_instruction(
        '操作：依次点击「旗下社区」、「成员大厅」、「战绩查询」和「PUBG福利商店」。'
    ) is True
    assert _is_community_plugin_switch_stability_instruction('操作：点击成员大厅。') is False
    assert _is_community_plugin_switch_stability_verification(
        '操作：每次点击后断言被点击的左侧插件处于选中状态，未出现 404、登录页或脚本异常。'
    ) is True


def test_desktop_config_requires_control_locator_for_interaction():
    with pytest.raises(DesktopAutomationError, match='requires a locator'):
        _validate_config({'steps': [{'action': 'click'}]})


def test_desktop_config_accepts_supported_structured_actions():
    steps = _validate_config({
        'steps': [
            {'action': 'click', 'locator': {'auto_id': 'login', 'control_type': 'Button'}},
            {'action': 'wait', 'seconds': 1},
            {'action': 'click_coordinate', 'x': 120, 'y': 80},
            {'action': 'assert_text', 'locator': {'title': 'Home'}, 'value': 'Home'},
        ]
    })

    assert len(steps) == 4


def test_natural_language_instruction_extraction_keeps_operations_and_assertions():
    instructions = _desktop_task_instructions('''
    操作步骤：
    1. 点击「登录」按钮
    2. 输入手机号
    预期结果：
    1. 断言出现登录成功提示
    ''')

    assert instructions == [
        '操作：点击「登录」按钮',
        '操作：输入手机号',
        '断言：断言出现登录成功提示',
    ]


def test_natural_language_instruction_extraction_recognizes_inline_assertions():
    instructions = _desktop_task_instructions('''
    1. 等待成员列表加载完成
    2. 断言列表展示成员昵称
    ''')

    assert instructions == ['操作：等待成员列表加载完成', '断言：断言列表展示成员昵称']


def test_natural_language_instruction_extraction_ignores_markdown_case_titles():
    instructions = _desktop_task_instructions('''
    ### COM-001 进入社区首页
    1. 访问 NN 客户端 /community/7520/plugin/communityHome。
    2. 断言页面展示社区名称。
    ''')

    assert instructions == [
        '操作：访问 NN 客户端 /community/7520/plugin/communityHome。',
        '断言：断言页面展示社区名称。',
    ]


def test_community_home_assertions_accept_runtime_community_identity_and_content_detail():
    assert _is_community_home_presence_assertion(
        '断言：当前已进入的社区名称、社区 ID 和在线人数均已展示。'
    ) is True
    assert _community_home_content_entry_label('操作：点击首页内容入口「疯狂星期六」。') == '疯狂星期六'
    assert _is_community_home_content_detail_assertion(
        '断言：已进入首页内容详情，展示标题和至少两项详情信息。'
    ) is True
    assert _is_community_home_faq_scroll_instruction('操作：在主内容区向下滚动至常见问题区域。') is True
    assert _is_community_home_faq_expand_instruction('操作：依次展开「组队能解决游戏哪些问题？」与「NN游戏语音与其他语音有什么不同？」。') is True
    assert _is_community_home_faq_assertion('断言：每个可见问题下展示对应说明文本。') is True
    assert _is_battle_stats_data_assertion('断言：展示赛季场次、击杀数、KDA 与至少一条对局记录。') is True
    assert _is_community_search_community_results_assertion('断言：搜索的游戏、战队社区结果列表展示可见结果。') is True
    assert _is_community_search_user_empty_assertion('断言：搜索的用户区域展示 0 个结果空状态。') is True


def test_natural_language_instruction_extraction_keeps_target_address_operations():
    instructions = _desktop_task_instructions('''
    目标地址：NN 客户端 /community/7520/hall
    前置条件：已登录
    前置条件补充：成员大厅数据已准备
    操作步骤：
    1. 访问目标地址，等待成员大厅稳定。
    2. 检查页面主要区域。
    预期结果：
    1. 当前地址保持为 /community/7520/hall。
    ''')

    assert instructions == [
        '操作：访问目标地址，等待成员大厅稳定。',
        '操作：检查页面主要区域。',
        '断言：当前地址保持为 /community/7520/hall。',
    ]


def test_natural_language_instruction_extraction_splits_compound_visit_and_clicks():
    instructions = _desktop_task_instructions('''
    1. 访问 NN 客户端 /community/7520/plugin/communityHome，点击「旗下社区」，点击名称为「test0915」的卡片。
    ''')

    assert instructions == [
        '操作：访问 NN 客户端 /community/7520/plugin/communityHome',
        '操作：点击「旗下社区」',
        '操作：点击名称为「test0915」的卡片。',
    ]


def test_wait_only_instruction_completes_after_one_wait():
    assert _is_wait_only_instruction('操作：等待成员列表加载完成') is True
    assert _is_wait_only_instruction('操作：等待加载完成后点击登录') is False


def test_visual_assertion_result_rejects_unknown_status_and_normalizes_evidence():
    assert _validate_visual_assertion_result({'status': 'passed', 'reason': 'visible'}) == {
        'status': 'passed', 'reason': 'visible', 'evidence': [],
    }

    with pytest.raises(DesktopAutomationError, match='invalid status'):
        _validate_visual_assertion_result({'status': 'maybe'})


def test_team_content_assertion_does_not_use_home_faq_expand_contract():
    team_content = (
        '\u65ad\u8a00\uff1a\u793e\u533a\u4ecb\u7ecd\u6587\u672c\u4e0e\u5e38\u89c1\u95ee\u9898\u4e2d\u5c55\u793a'
        '\u201c\u7ec4\u961f\u80fd\u89e3\u51b3\u6e38\u620f\u54ea\u4e9b\u95ee\u9898\uff1f\u201d\u3002'
    )

    assert _is_team_home_content_assertion(team_content) is True
    assert _is_community_home_faq_assertion(team_content) is False


def test_cdp_dom_assertion_configuration_is_selected_by_assertion_index():
    config = {
        'cdp_dom_assertions': [
            {'assertion_index': 2, 'expression': 'true'},
        ]
    }

    assert _cdp_dom_assertion_for_index(config, 1) is None
    assert _cdp_dom_assertion_for_index(config, 2)['expression'] == 'true'


def test_cdp_dom_assertion_normalizes_boolean_and_structured_results():
    assertion = {'success_message': 'ok', 'failure_message': 'not ok'}

    assert _normalize_cdp_dom_assertion_result(True, assertion) == {
        'status': 'passed', 'reason': 'ok', 'evidence': [],
    }
    assert _normalize_cdp_dom_assertion_result({'passed': False, 'reason': 'missing', 'evidence': ['right pane']}, assertion) == {
        'status': 'failed', 'reason': 'missing', 'evidence': ['right pane'],
    }


def test_cdp_target_route_requires_explicit_mapping_for_web_case_urls():
    task = 'Target: https://example.test/community/7520/hall'

    assert _cdp_target_route({}, task) == ''
    assert _cdp_target_route({'map_web_target_route': True}, task) == '/community/7520/hall'
    assert _cdp_target_route({'cdp_route': '#/community/52198/channel/1001093718'}, task) == '/community/52198/channel/1001093718'


def test_cdp_target_route_accepts_explicit_nn_client_relative_route():
    task = '\u76ee\u6807\u5730\u5740\uff1aNN \u5ba2\u6237\u7aef /community/7520/plugin/zhanji'

    assert _cdp_target_route({'map_web_target_route': True}, task) == '/community/7520/plugin/zhanji'


def test_relative_route_instruction_is_detectable_without_a_web_url():
    assert _cdp_route_from_task_description('\u64cd\u4f5c\uff1a\u8bbf\u95ee NN \u5ba2\u6237\u7aef /community/7520/plugin/communityHome \u3002') == '/community/7520/plugin/communityHome'


def test_hall_menu_consistency_accepts_two_message_assertion_wording():
    instruction = '断言：两条消息的操作菜单均展示当前产品实际提供的可用操作，且顺序一致；检查过程中不执行删除、撤回。'

    assert _is_hall_menu_consistency_instruction(instruction) is True
    assert _is_hall_other_member_fixture_assertion(
        '断言：其他成员夹具消息与本人唯一消息均在同一大厅消息流中可定位，发送者归属正确。'
    ) is True


def test_hall_cleanup_runs_after_non_cleanup_assertions():
    instructions = [
        '操作：发送唯一文本消息 HALL_${timestamp()}_菜单一致性验证。',
        '操作：依次撤回本用例生成的两条 HALL_ 测试消息，完成数据清理。',
        '断言：两条消息的操作菜单均展示当前产品实际提供的可用操作，且顺序一致。',
        '断言：清理完成后两条唯一正文均不再作为普通消息展示。',
    ]

    assert _order_desktop_task_instructions(instructions) == [
        instructions[0], instructions[2], instructions[1], instructions[3],
    ]


def test_cdp_community_from_route_extracts_only_nn_community_routes():
    assert _cdp_community_from_route('#/community/52198/plugin/communityHome') == '52198'
    assert _cdp_community_from_route('/community/7520/channel/1001091992') == '7520'
    assert _cdp_community_from_route('/settings/account') == ''


def test_cdp_startup_reports_a_noninteractive_agent_error_when_autostart_is_not_enabled(monkeypatch):
    monkeypatch.setattr('apps.ui_automation.desktop_engine._cdp_renderer_page_is_available', lambda _url: False)

    with pytest.raises(DesktopAutomationError, match='long-lived Agent'):
        asyncio.run(_ensure_cdp_endpoint('http://127.0.0.1:9222', {}))


def test_cdp_agent_startupinfo_is_only_requested_for_silent_windows_launches(monkeypatch):
    monkeypatch.setattr('apps.ui_automation.desktop_engine.os.name', 'posix')

    assert _cdp_agent_startupinfo(True) is None
    assert _cdp_agent_startupinfo(False) is None


def test_elevated_cdp_launcher_stops_only_the_isolated_agent_before_starting_it():
    command = _elevated_cdp_launcher_command('C:/NN/nn.exe', [
        '--remote-debugging-port=9222',
        '--user-data-dir=G:/agent-profile',
    ])

    assert command[:3] == ['powershell.exe', '-NoProfile', '-Command']
    assert '-Verb RunAs' in command[3]
    encoded = command[3].split("'-EncodedCommand','", 1)[1].split("') -Verb", 1)[0]
    payload = base64.b64decode(encoded).decode('utf-16le')
    assert "Get-CimInstance Win32_Process" in payload
    assert "Get-Process -Name 'nn'" not in payload
    assert 'c:\\nn\\nn.exe' in payload
    assert 'g:\\agent-profile' in payload
    assert 'Stop-Process -Id $_.ProcessId -Force' in payload
    assert '--remote-debugging-port=9222' in payload


def test_cdp_setup_actions_require_deterministic_expressions():
    assert _cdp_setup_actions({'cdp_setup_actions': [{'expression': 'true'}]}) == [{'expression': 'true'}]

    with pytest.raises(DesktopAutomationError, match='requires an expression'):
        _cdp_setup_actions({'cdp_setup_actions': [{}]})


def test_cdp_connection_error_recognizes_websockets_close_variants():
    assert _is_cdp_connection_error(RuntimeError('no close frame received or sent')) is True
    assert _is_cdp_connection_error(RuntimeError('sent 1000 (OK); no close frame received')) is True
    assert _is_cdp_connection_error(RuntimeError('element was not found')) is False


def test_visual_assertion_uses_directional_crop_for_sidebar_assertions():
    crops = _visual_assertion_crop_boxes('断言右侧成员列表展示头像和昵称', 1280, 900)

    assert crops == [('right-side target area', (820, 0, 1280, 900))]


def test_visual_assertion_uses_detail_crops_for_general_layout_assertions():
    crops = _visual_assertion_crop_boxes('断言成员头像、昵称和在线状态的布局不重叠、不串位', 1280, 900)

    assert [label for label, _ in crops] == ['left detail area', 'center detail area', 'right detail area']


def test_visual_assertion_treats_avatar_status_dot_as_an_intentional_attachment():
    guidance = _visual_assertion_interpretation('断言成员头像、昵称、在线状态和身份标识的布局不重叠、不串位')

    assert 'valid same-row attachment' in guidance
    assert _visual_assertion_interpretation('断言成员昵称完整显示') == ''


def test_planner_action_must_reference_a_visible_control():
    controls = [{'control_id': 'c1', 'name': '登录', 'auto_id': 'login', 'control_type': 'Button', 'class_name': ''}]

    step = _planned_step_from_action({'action': 'click', 'control_id': 'c1'}, controls)
    assert step['locator'] == {'auto_id': 'login', 'control_type': 'Button'}

    with pytest.raises(DesktopAutomationError, match='not visible'):
        _planned_step_from_action({'action': 'click', 'control_id': 'unknown'}, controls)


class _ElementInfo:
    def __init__(self, control_type):
        self.control_type = control_type


class _Window:
    def __init__(self, control_type, visible=True):
        self.element_info = _ElementInfo(control_type)
        self.visible = visible
        self.wait_calls = []

    def is_visible(self):
        return self.visible

    def is_minimized(self):
        return False

    def wait(self, state, timeout):
        self.wait_calls.append((state, timeout))


class _App:
    def __init__(self, windows):
        self._windows = windows

    def windows(self):
        return self._windows


class _Desktop:
    def __init__(self, window):
        self._window = window

    def window(self, **_locator):
        return self._window


class _RestoredDesktop:
    def __init__(self, native_window, window):
        self.native_window = native_window
        self.window_after_restore = window

    def window(self, **_locator):
        if not self.native_window.restored:
            raise RuntimeError('Window is minimized')
        return self.window_after_restore


def test_window_selection_ignores_internal_panes_for_unqualified_launch():
    pane = _Window('Pane')
    main_window = _Window('Window')

    selected = _find_ready_window(_App([pane, main_window]), _Desktop(None), {}, timeout=1)

    assert selected is main_window
    assert main_window.wait_calls


def test_window_selection_uses_desktop_lookup_when_process_bound_window_is_missing():
    target = _Window('Window')

    selected = _find_ready_window(_App([]), _Desktop(target), {'title_re': '.*Notepad.*'}, timeout=1)

    assert selected is target


class _MinimizedWindow(_Window):
    def __init__(self, control_type):
        super().__init__(control_type)
        self.minimized = True
        self.restored = False

    def is_minimized(self):
        return self.minimized

    def restore(self):
        self.restored = True
        self.minimized = False

    def set_focus(self):
        self.focused = True


def test_window_selection_restores_a_minimized_native_window_before_using_uia_window():
    native_target = _MinimizedWindow('Window')
    uia_target = _Window('Window')

    selected = _find_ready_window(
        _App([]),
        _RestoredDesktop(native_target, uia_target),
        {'title_re': '.*NN.*'},
        timeout=1,
        native_desktop=_Desktop(native_target),
    )

    assert selected is uia_target
    assert native_target.restored


def test_foreground_helper_restores_and_focuses_target_window():
    target = _MinimizedWindow('Window')

    _bring_window_to_foreground(target)

    assert target.restored
    assert target.focused


class _PlannerResponse:
    content = '{"action": "done"}'


class _Planner:
    def __init__(self):
        self.prompt = None

    def invoke(self, prompt):
        self.prompt = prompt
        return _PlannerResponse()


def test_planner_receives_prior_actions_and_current_control_values():
    planner = _Planner()
    controls = [{'control_id': 'c1', 'name': '', 'value': 'already entered', 'control_type': 'Edit'}]
    history = [{'action': 'fill', 'control_id': 'c1', 'value': 'already entered'}]

    action = _plan_desktop_action(planner, 'task', '操作：输入文本', controls, history)

    assert action == {'action': 'done'}
    assert 'previous_actions' in planner.prompt
    assert 'already entered' in planner.prompt


class _EditableControl:
    def get_value(self):
        return 'actual input value'

    def texts(self):
        return ['Text editor']


def test_control_content_prefers_editable_value_and_keeps_accessible_label():
    assert _control_content(_EditableControl()) == 'actual input value Text editor'
