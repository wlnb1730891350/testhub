from apps.ui_automation.recording_engine import RecordingEngine
from apps.ui_automation.views.ai import _normalize_recorded_actions


def test_recording_engine_clean_actions_dedupes_redundant_click_and_fill():
    actions = [
        {"action_type": "click", "locator_value": "#phone", "element_text": "手机号"},
        {"action_type": "fill", "locator_value": "#phone", "element_text": "手机号", "input_value": "13800138000"},
        {"action_type": "fill", "locator_value": "#phone", "element_text": "手机号", "input_value": "13800138001"},
        {"action_type": "click", "locator_value": ".submit", "element_text": "登录"},
        {"action_type": "click", "locator_value": ".submit", "element_text": "登录"},
    ]

    cleaned = RecordingEngine._clean_actions(actions)

    assert [item["action_type"] for item in cleaned] == ["fill", "click"]
    assert cleaned[0]["input_value"] == "13800138001"
    assert cleaned[1]["locator_value"] == ".submit"


def test_normalize_recorded_actions_filters_noise_and_reindexes_steps():
    actions = [
        {"action_type": "goto", "locator_value": "", "description": "打开页面"},
        {"action_type": "click", "locator_value": "#phone", "element_name": "手机号输入框"},
        {"action_type": "type", "locator_value": "#phone", "element_name": "手机号输入框", "input_value": "13800138000"},
        {"action_type": "press", "input_value": "Shift"},
        {"action_type": "click", "locator_value": ".close-btn", "element_name": "关闭"},
        {"action_type": "click", "locator_value": ".close-btn", "element_name": "关闭"},
    ]

    cleaned = _normalize_recorded_actions(actions)

    assert [item["action_type"] for item in cleaned] == ["fill", "click"]
    assert [item["step_number"] for item in cleaned] == [1, 2]
    assert cleaned[0]["input_value"] == "13800138000"
