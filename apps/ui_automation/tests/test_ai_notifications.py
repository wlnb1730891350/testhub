from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import override_settings
from django.utils import timezone

from apps.core.models import UnifiedNotificationConfig
from apps.core.serializers import UnifiedNotificationConfigSerializer
from apps.ui_automation.ai_notifications import (
    build_ai_batch_report_content,
    build_ai_report_content,
    send_ai_execution_notification,
)


def _record(status='passed'):
    return SimpleNamespace(
        id=220,
        case_name='社区插件切换稳定性',
        status=status,
        project=SimpleNamespace(name='社区自动化'),
        executed_by=SimpleNamespace(username='tester'),
        start_time=timezone.now(),
        duration=12.345,
        planned_tasks=[
            {'status': 'completed'},
            {'status': 'completed'},
            {'status': 'failed' if status == 'failed' else 'completed'},
        ],
        steps_completed=[],
        logs='执行完成' if status == 'passed' else '步骤 3 执行失败: 未找到目标元素',
    )


def test_old_webhook_config_does_not_enable_ai_reports_by_default():
    config = UnifiedNotificationConfig(
        webhook_bots={
            'wechat': {
                'name': '测试群',
                'webhook_url': 'https://example.test/wechat',
                'enabled': True,
            }
        }
    )

    bot = config.get_webhook_bots()[0]

    assert bot['enable_ui_automation'] is True
    assert bot['enable_api_testing'] is True
    assert bot['enable_ai_testing'] is False


def test_notification_config_serializer_preserves_ai_report_switch():
    serializer = UnifiedNotificationConfigSerializer(data={
        'name': '企微机器人配置',
        'config_type': 'webhook_wechat',
        'webhook_bots': {
            'wechat': {
                'name': 'AI报告群',
                'webhook_url': 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key',
                'enabled': True,
                'enable_ui_automation': False,
                'enable_api_testing': False,
                'enable_ai_testing': True,
            }
        },
        'is_active': True,
    })

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data['webhook_bots']['wechat']['enable_ai_testing'] is True


def test_notification_config_rejects_wechat_profile_page_as_webhook():
    serializer = UnifiedNotificationConfigSerializer(data={
        'name': '错误企微配置',
        'config_type': 'webhook_wechat',
        'webhook_bots': {
            'wechat': {
                'name': 'AI报告群',
                'webhook_url': 'https://work.weixin.qq.com/wework_admin/common/openBotProfile/example',
                'enabled': True,
                'enable_ai_testing': True,
            }
        },
        'is_active': True,
    })

    assert serializer.is_valid() is False
    assert 'qyapi.weixin.qq.com/cgi-bin/webhook/send?key=' in str(serializer.errors)


@override_settings(FRONTEND_URL='https://testhub.example.test')
def test_ai_report_content_contains_report_link_and_failure_summary():
    status_text, content = build_ai_report_content(_record(status='failed'))

    assert status_text == '失败'
    assert '报告 ID: 220' in content
    assert '共 3 步，成功 2 步，失败 1 步' in content
    assert '未找到目标元素' in content
    assert 'https://testhub.example.test/ai-intelligent-mode/execution-records?record_id=220' in content


@override_settings(FRONTEND_URL='https://testhub.example.test')
def test_ai_batch_report_content_contains_aggregate_statistics_and_link():
    passed = _record(status='passed')
    failed = _record(status='failed')
    failed.id = 221
    failed.case_name = '社区文章发布'
    failed.end_time = timezone.now()
    passed.end_time = timezone.now()

    status_text, content = build_ai_batch_report_content('batch-001', [passed, failed])

    assert status_text == '失败'
    assert '共 2 条，通过 1 条，失败 1 条' in content
    assert '社区文章发布' in content
    assert 'https://testhub.example.test/ai-intelligent-mode/execution-records?batch_id=batch-001' in content


@patch('apps.ui_automation.ai_notifications.UiNotificationLog.objects.create')
@patch('apps.ui_automation.ai_notifications.requests.post')
@patch('apps.ui_automation.ai_notifications.UnifiedNotificationConfig.objects.filter')
def test_send_ai_report_only_uses_opted_in_bots(config_filter, post, create_log):
    config = Mock()
    config.get_webhook_bots.return_value = [
        {
            'type': 'wechat',
            'name': 'AI报告群',
            'webhook_url': 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=enabled',
            'enabled': True,
            'enable_ai_testing': True,
        },
        {
            'type': 'wechat',
            'name': '普通通知群',
            'webhook_url': 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=disabled',
            'enabled': True,
            'enable_ai_testing': False,
        },
    ]
    config_filter.return_value = [config]
    post.return_value = SimpleNamespace(status_code=200, text='ok')

    results = send_ai_execution_notification(_record())

    assert results == [{'type': 'wechat', 'success': True}]
    post.assert_called_once()
    assert post.call_args.args[0] == 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=enabled'
    assert 'AI测试报告执行成功' in post.call_args.kwargs['json']['markdown']['content']
    create_log.assert_called_once()


@patch('apps.ui_automation.ai_notifications.UiNotificationLog.objects.create')
@patch('apps.ui_automation.ai_notifications.requests.post')
@patch('apps.ui_automation.ai_notifications.UnifiedNotificationConfig.objects.filter')
def test_wechat_http_200_with_nonzero_errcode_is_recorded_as_failed(config_filter, post, create_log):
    config = Mock()
    config.get_webhook_bots.return_value = [{
        'type': 'wechat',
        'name': 'AI报告群',
        'webhook_url': 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key',
        'enabled': True,
        'enable_ai_testing': True,
    }]
    config_filter.return_value = [config]
    post.return_value = SimpleNamespace(
        status_code=200,
        text='{"errcode":93000,"errmsg":"invalid webhook"}',
        json=lambda: {'errcode': 93000, 'errmsg': 'invalid webhook'},
    )

    results = send_ai_execution_notification(_record())

    assert results[0]['success'] is False
    assert 'HTTP 200' in results[0]['error']
    assert create_log.call_args.kwargs['status'] == 'failed'


@patch('apps.ui_automation.ai_notifications.UiNotificationLog.objects.create')
@patch('apps.ui_automation.ai_notifications.requests.post')
@patch('apps.ui_automation.ai_notifications.UnifiedNotificationConfig.objects.filter')
def test_invalid_wechat_webhook_is_rejected_before_http_request(config_filter, post, create_log):
    config = Mock()
    config.get_webhook_bots.return_value = [{
        'type': 'wechat',
        'name': '错误机器人地址',
        'webhook_url': 'https://work.weixin.qq.com/wework_admin/common/openBotProfile/example',
        'enabled': True,
        'enable_ai_testing': True,
    }]
    config_filter.return_value = [config]

    results = send_ai_execution_notification(_record())

    assert results[0]['success'] is False
    assert 'qyapi.weixin.qq.com' in results[0]['error']
    post.assert_not_called()
    assert create_log.call_args.kwargs['status'] == 'failed'


@patch('apps.ui_automation.ai_notifications.UnifiedNotificationConfig.objects.filter')
def test_running_ai_execution_does_not_query_or_send_notifications(config_filter):
    assert send_ai_execution_notification(_record(status='running')) == []
    config_filter.assert_not_called()
