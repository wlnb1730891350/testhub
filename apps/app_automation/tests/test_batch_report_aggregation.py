# -*- coding: utf-8 -*-
import json
import os
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.app_automation.executors.test_executor import AppTestExecutor


class AppBatchReportAggregationTests(SimpleTestCase):
    def test_logical_case_identity_distinguishes_bridge_test_results(self):
        with tempfile.TemporaryDirectory() as results_dir:
            result_path = os.path.join(results_dir, 'case-result.json')
            with open(result_path, 'w', encoding='utf-8') as result_file:
                json.dump({'name': 'bridge test', 'historyId': 'shared', 'testCaseId': 'shared'}, result_file)

            executor = AppTestExecutor()
            executor._assign_logical_case_identity(results_dir, 501)

            with open(result_path, encoding='utf-8') as result_file:
                result = json.load(result_file)
            self.assertNotEqual(result['historyId'], 'shared')
            self.assertEqual(result['historyId'], result['testCaseId'])
            self.assertIn({'name': 'app_test_case_id', 'value': '501'}, result['parameters'])

    def test_batch_report_collects_results_from_all_child_executions(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                executor = AppTestExecutor()
                for execution_id in (101, 102):
                    results_dir = executor._get_allure_results_dir(execution_id)
                    os.makedirs(results_dir, exist_ok=True)
                    with open(os.path.join(results_dir, f'{execution_id}-result.json'), 'w', encoding='utf-8') as result_file:
                        json.dump({'name': f'case-{execution_id}', 'status': 'passed'}, result_file)

                expected_report_dir = os.path.join(media_root, 'expected-batch-report')
                with patch.object(executor, '_generate_allure_report_from_dirs', return_value=expected_report_dir) as generate:
                    report_path = executor.generate_batch_allure_report(99, [101, 102])

                self.assertEqual(report_path, expected_report_dir)
                result_dir, report_dir = generate.call_args.args
                self.assertTrue(report_dir.endswith('batch_99'))
                self.assertTrue(os.path.exists(os.path.join(result_dir, '101-result.json')))
                self.assertTrue(os.path.exists(os.path.join(result_dir, '102-result.json')))
