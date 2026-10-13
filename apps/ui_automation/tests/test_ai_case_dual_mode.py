from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from unittest.mock import patch

from apps.ui_automation.models import AICase, AIExecutionRecord, DesktopAppProfile
from apps.ui_automation.serializers import AICaseSerializer
from apps.ui_automation.views.ai import AICaseViewSet
from apps.ui_automation.views.ai import _run_ai_case_with_target
from apps.ui_automation.management.commands.run_ai_regression import _task_snapshot_for_target


class BatchEnableDualModeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.order_by('id').first()
        if self.user is None:
            self.user = SimpleNamespace(id=1, is_authenticated=True)
        self.profile = DesktopAppProfile.objects.create(
            name='NN test client',
            executable_path='C:/NN/nn.exe',
            process_name='NN.exe',
            is_active=True,
            created_by_id=self.user.id,
        )
        self.dual_case = AICase.objects.create(
            name='Already dual',
            task_description='https://test-web.nn.com/community/7520/hall',
            web_task_description='browser task',
            desktop_task_description='desktop task',
            execution_target='dual',
            desktop_app_profile=self.profile,
            created_by_id=self.user.id,
        )

    def test_already_generated_windows_case_returns_successful_idempotent_response(self):
        request = APIRequestFactory().post('/', {'ids': [self.dual_case.id]}, format='json')
        force_authenticate(request, user=self.user)

        response = AICaseViewSet.as_view({'post': 'batch_enable_dual_mode'})(request)

        assert response.status_code == 200
        assert response.data['converted_count'] == 0
        assert response.data['skipped_count'] == 1

    def test_desktop_case_generates_browser_task_and_preserves_windows_task(self):
        desktop_task = (
            '\u76ee\u6807\u5730\u5740\uff1aNN \u5ba2\u6237\u7aef /community/7520/channel/1001091992\n'
            '1. \u70b9\u51fb\u6210\u5458\u5361\u7247\n'
            '2. \u65ad\u8a00\u5361\u7247\u4fe1\u606f\u5b8c\u6574'
        )
        desktop_case = AICase.objects.create(
            name='Desktop only case',
            task_description=desktop_task,
            desktop_task_description=desktop_task,
            execution_target='desktop',
            desktop_app_profile=self.profile,
            created_by_id=self.user.id,
        )
        request = APIRequestFactory().post('/', {'ids': [desktop_case.id]}, format='json')
        force_authenticate(request, user=self.user)

        response = AICaseViewSet.as_view({'post': 'batch_enable_browser_mode'})(request)

        assert response.status_code == 200
        assert response.data['converted_count'] == 1
        desktop_case.refresh_from_db()
        assert desktop_case.execution_target == 'dual'
        assert desktop_case.desktop_task_description == desktop_task
        assert desktop_case.web_task_description.startswith(
            '\u76ee\u6807\u5730\u5740\uff1ahttps://test-web.nn.com/community/7520/channel/1001091992'
        )
        assert desktop_case.task_description == desktop_case.web_task_description

    def test_legacy_dual_case_uses_generic_task_as_browser_fallback(self):
        legacy_case = AICase.objects.create(
            name='Legacy dual case',
            task_description='https://test-web.nn.com/community/7520/hall',
            web_task_description='',
            desktop_task_description='NN client /community/7520/hall',
            execution_target='dual',
            desktop_app_profile=self.profile,
            created_by_id=self.user.id,
        )

        data = AICaseSerializer(legacy_case).data

        assert data['web_task_description'] == legacy_case.task_description

    @patch('apps.ui_automation.views.ai.threading.Thread')
    def test_batch_run_uses_selected_browser_variant_for_dual_case(self, thread):
        self.dual_case.web_task_description = 'browser task for batch'
        self.dual_case.desktop_task_description = 'desktop task for batch'
        self.dual_case.save(update_fields=['web_task_description', 'desktop_task_description'])
        request = APIRequestFactory().post('/', {
            'case_ids': [self.dual_case.id],
            'run_mode': 'sequential',
            'execution_target': 'web',
        }, format='json')
        force_authenticate(request, user=self.user)

        response = AICaseViewSet.as_view({'post': 'batch_record'})(request)

        assert response.status_code == 200
        record = AIExecutionRecord.objects.get(id=response.data['records'][0]['id'])
        assert record.execution_target == 'web'
        assert record.task_description == 'browser task for batch'
        thread.return_value.start.assert_called_once()

    def test_batch_run_rejects_concurrent_article_writes_to_protect_the_test_account(self):
        article_case = AICase.objects.create(
            name='Article publish case',
            task_description='操作步骤：创建文章并点击发布。',
            web_task_description='操作步骤：创建文章并点击发布。',
            execution_target='web',
            created_by_id=self.user.id,
        )
        request = APIRequestFactory().post('/', {
            'case_ids': [article_case.id],
            'run_mode': 'concurrent',
            'execution_target': 'web',
        }, format='json')
        force_authenticate(request, user=self.user)

        response = AICaseViewSet.as_view({'post': 'batch_record'})(request)

        assert response.status_code == 400
        assert '依次执行' in response.data['error']

    @patch('apps.ui_automation.views.ai._preflight_nn_desktop_session')
    def test_batch_run_rejects_before_creating_records_when_nn_agent_login_is_rejected(self, preflight):
        preflight.side_effect = RuntimeError('验证码错误，请重新输入！')
        request = APIRequestFactory().post('/', {
            'case_ids': [self.dual_case.id],
            'run_mode': 'sequential',
            'execution_target': 'desktop',
        }, format='json')
        force_authenticate(request, user=self.user)

        response = AICaseViewSet.as_view({'post': 'batch_record'})(request)

        assert response.status_code == 400
        assert '验证码错误' in response.data['error']
        assert not AIExecutionRecord.objects.filter(ai_case=self.dual_case).exists()

    @patch('apps.ui_automation.views.ai._run_with_playwright_sync')
    def test_web_dispatch_uses_the_execution_record_snapshot(self, runner):
        record = SimpleNamespace(task_description='browser snapshot', id=991)
        case = SimpleNamespace(
            execution_target='dual',
            web_task_description='current browser variant',
            task_description='stale shared description',
            setup_template=None,
        )

        _run_ai_case_with_target(record, case, lambda: False, execution_target='web')

        assert runner.call_args.args[1] == 'browser snapshot'

    def test_regression_snapshot_uses_selected_desktop_variant(self):
        self.dual_case.web_task_description = 'browser regression task'
        self.dual_case.desktop_task_description = 'desktop regression task'
        self.dual_case.save(update_fields=['web_task_description', 'desktop_task_description'])

        assert _task_snapshot_for_target(self.dual_case, 'desktop') == 'desktop regression task'
        assert _task_snapshot_for_target(self.dual_case, 'web') == 'browser regression task'
