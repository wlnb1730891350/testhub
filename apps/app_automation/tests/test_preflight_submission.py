# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.app_automation.models import AppDevice, AppTestCase, AppTestExecution, AppTestBatchReport


READY_PREFLIGHT = {
    'ready': True,
    'checks': [
        {'key': 'adb', 'name': 'ADB 可用性', 'passed': True, 'message': 'ADB 可用'},
        {'key': 'device', 'name': '设备连接与授权', 'passed': True, 'message': '设备已连接并授权'},
    ],
    'device': {'name': 'Test Device', 'android_version': '14', 'screen_size': '1080x2400'},
}


class AppExecutionSubmissionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='app-runner', password='pass12345')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.queue_check = patch(
            'apps.app_automation.views.test_case_views.check_execution_queue',
            return_value=(True, ''),
        )
        self.queue_check.start()
        self.addCleanup(self.queue_check.stop)
        self.device = AppDevice.objects.create(device_id='emulator-5554', name='Test Device', status='online')
        self.test_case = AppTestCase.objects.create(
            name='可执行用例', ui_flow={'steps': [{'action': 'tap', 'target': '登录'}]}, created_by=self.user
        )

    @patch('apps.app_automation.views.test_case_views.preflight_device')
    def test_preflight_failure_does_not_create_execution(self, preflight):
        preflight.return_value = {**READY_PREFLIGHT, 'ready': False}

        response = self.client.post(
            f'/api/app-automation/test-cases/{self.test_case.id}/execute/',
            {'device_id': self.device.device_id}, format='json'
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(AppTestExecution.objects.count(), 0)

    @patch('apps.app_automation.tasks.execute_app_test_task.delay')
    @patch('apps.app_automation.views.test_case_views.preflight_device', return_value=READY_PREFLIGHT)
    def test_submission_reserves_device_and_rejects_second_job(self, _preflight, delay):
        delay.return_value = SimpleNamespace(id='celery-task-1')

        first = self.client.post(
            f'/api/app-automation/test-cases/{self.test_case.id}/execute/',
            {'device_id': self.device.device_id}, format='json'
        )
        second = self.client.post(
            f'/api/app-automation/test-cases/{self.test_case.id}/execute/',
            {'device_id': self.device.device_id}, format='json'
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        self.assertIn('正在排队或执行', second.data['message'])
        self.device.refresh_from_db()
        self.assertEqual(self.device.status, 'locked')
        self.assertEqual(AppTestExecution.objects.filter(status='pending').count(), 1)

    @patch('apps.app_automation.tasks.execute_app_suite_task.delay')
    @patch('apps.app_automation.views.test_case_views.preflight_device', return_value=READY_PREFLIGHT)
    def test_batch_submission_creates_one_ordered_task(self, _preflight, delay):
        second_case = AppTestCase.objects.create(
            name='第二个可执行用例', ui_flow=[{'action': 'tap', 'target': '首页'}], created_by=self.user
        )
        delay.return_value = SimpleNamespace(id='celery-batch-1')

        response = self.client.post('/api/app-automation/test-cases/execute-batch/', {
            'device_id': self.device.device_id,
            'case_ids': [self.test_case.id, second_case.id],
        }, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AppTestExecution.objects.filter(status='pending').count(), 2)
        batch_report = AppTestBatchReport.objects.get()
        self.assertEqual(batch_report.total_cases, 2)
        self.assertEqual(
            AppTestExecution.objects.filter(batch_report=batch_report).count(), 2
        )
        delay.assert_called_once()
        self.assertEqual(delay.call_args.kwargs['suite_id'], None)
        self.assertEqual(delay.call_args.kwargs['batch_report_id'], batch_report.id)
        self.assertEqual(delay.call_args.kwargs['execution_ids'], list(
            AppTestExecution.objects.order_by('id').values_list('id', flat=True)
        ))
        reports_response = self.client.get('/api/app-automation/batch-reports/')
        self.assertEqual(reports_response.status_code, 200)
        self.assertEqual(reports_response.data['count'], 1)
        detail_response = self.client.get(f'/api/app-automation/batch-reports/{batch_report.id}/executions/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(len(detail_response.data['data']), 2)

    def test_queue_failure_does_not_create_execution_or_lock_device(self):
        self.queue_check.stop()
        with patch(
            'apps.app_automation.views.test_case_views.check_execution_queue',
            return_value=(False, '执行队列不可用，请启动 Redis 服务后重试'),
        ):
            response = self.client.post(
                f'/api/app-automation/test-cases/{self.test_case.id}/execute/',
                {'device_id': self.device.device_id}, format='json'
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(AppTestExecution.objects.count(), 0)
        self.device.refresh_from_db()
        self.assertNotEqual(self.device.status, 'locked')

    def test_delete_pending_execution_releases_unused_device(self):
        self.device.lock(self.user)
        execution = AppTestExecution.objects.create(
            test_case=self.test_case,
            device=self.device,
            user=self.user,
            status='pending',
        )

        response = self.client.delete(f'/api/app-automation/executions/{execution.id}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(AppTestExecution.objects.filter(id=execution.id).exists())
        self.device.refresh_from_db()
        self.assertNotEqual(self.device.status, 'locked')
