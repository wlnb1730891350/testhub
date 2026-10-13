from apps.ui_automation.views._helpers import (
    _login_landing_url_for_target,
    resolve_execution_step_variables,
)
from apps.ui_automation.business_actions import (
    _is_generated_article_title,
    _safe_generated_article_body,
    _safe_generated_article_title,
)
from apps.ui_automation.structured_actions import compile_task_description
from apps.core.variable_resolver import resolve_variables


def test_setup_template_random_phone_is_resolved_and_reused_within_one_run():
    cache = {}
    source = '${random_phone()}'

    first = resolve_execution_step_variables({'input_value': source}, cache)
    second = resolve_execution_step_variables({'input_value': source}, cache)

    assert first['input_value'].isdigit()
    assert len(first['input_value']) == 11
    assert second['input_value'] == first['input_value']
    assert first['_variable_sources']['input_value'] == source


def test_template_phone_instruction_compiles_to_a_phone_business_action():
    source = '${random_phone()}'
    step = compile_task_description(f'输入账号{source}')[0]

    assert step['business_action'] == 'nn_fill_phone'
    assert step['input_value'] == source


def test_template_random_email_compiles_with_a_separate_target_and_value():
    source = '${random_email()}'
    step = compile_task_description(f'输入邮箱{source}')[0]

    assert step['action_type'] == 'type'
    assert step['target_text'] == '邮箱'
    assert step['input_value'] == source


def test_timestamp_expression_is_resolved():
    value = resolve_variables('${timestamp()}')

    assert value.isdigit()
    assert len(value) == 13


def test_generated_article_title_is_identified_without_touching_literal_titles():
    assert _is_generated_article_title(
        {'_variable_sources': {'input_value': 'AT_${timestamp()}'}},
        'AT_1788262689344',
    ) is True
    assert _is_generated_article_title({'_variable_sources': {}}, '社区公告') is False


def test_safe_generated_article_title_is_unique_and_does_not_use_legacy_prefix():
    value = _safe_generated_article_title()
    assert value.startswith('公告更新')
    assert 'AT_' not in value
    assert not any(part.isdigit() and len(part) >= 11 for part in value.split())


def test_safe_generated_article_body_is_natural_and_has_a_short_trace_marker():
    value = _safe_generated_article_body()

    assert value.startswith('社区')
    assert '标识' in value
    assert '自动化验证' not in value


def test_login_landing_url_keeps_origin_and_removes_protected_deep_path():
    assert _login_landing_url_for_target(
        'https://test3-web.nn.com/community/7520/channel/1001091992?room=1'
    ) == 'https://test3-web.nn.com/'
