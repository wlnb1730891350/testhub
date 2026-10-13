from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from django.utils import timezone
import json
import time
import logging

from ..models import (
    UiProject, TestCase, TestCaseExecution,
    UiScheduledTask, UiNotificationLog, UiTaskNotificationSetting
)
from ..serializers import (
    UiScheduledTaskSerializer, UiNotificationLogSerializer, UiTaskNotificationSettingSerializer,
)
from ..operation_logger import log_operation

logger = logging.getLogger(__name__)


class UiScheduledTaskViewSet(viewsets.ModelViewSet):
    """UI定时任务视图集"""
    queryset = UiScheduledTask.objects.all()
    serializer_class = UiScheduledTaskSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['task_type', 'status', 'trigger_type', 'project']
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'next_run_time', 'last_run_time']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        return UiScheduledTask.objects.filter(project__in=accessible_projects)

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        log_operation('create', 'scheduled_task', instance.id, instance.name, self.request.user)

    def perform_update(self, serializer):
        instance = serializer.save()
        log_operation('edit', 'scheduled_task', instance.id, instance.name, self.request.user)

    def perform_destroy(self, instance):
        log_operation('delete', 'scheduled_task', instance.id, instance.name, self.request.user)
        instance.delete()

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        task = self.get_object()
        task.status = 'PAUSED'
        task.save()
        return Response({'message': '任务已暂停', 'status': task.status})

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        task = self.get_object()
        task.status = 'ACTIVE'
        task.next_run_time = task.calculate_next_run()
        task.save()
        return Response({'message': '任务已恢复', 'status': task.status})

    @action(detail=True, methods=['post'])
    def run_now(self, request, pk=None):
        task = self.get_object()
        try:
            task.last_run_time = timezone.now()
            task.total_runs += 1
            task.next_run_time = task.calculate_next_run()
            task.save()

            if task.task_type == 'TEST_SUITE':
                if not task.test_suite:
                    return Response({
                        'error': '该任务未配置测试套件'
                    }, status=status.HTTP_400_BAD_REQUEST)

                test_suite = task.test_suite
                test_case_count = test_suite.suite_test_cases.count()

                if test_case_count == 0:
                    return Response({
                        'error': '该测试套件未包含任何测试用例，无法执行'
                    }, status=status.HTTP_400_BAD_REQUEST)

                test_suite.execution_status = 'running'
                test_suite.save()

                import threading
                from ..test_executor import TestExecutor

                def run_test():
                    try:
                        executor = TestExecutor(
                            test_suite=test_suite,
                            engine=task.engine,
                            browser=task.browser,
                            headless=task.headless,
                            executed_by=task.created_by
                        )
                        executor.run()
                        task.successful_runs += 1
                        task.last_result = {'status': 'success', 'message': '测试套件执行成功'}
                        task.error_message = ''
                        task.save()
                        self._send_task_notification(task, success=True)
                    except Exception as e:
                        task.failed_runs += 1
                        task.last_result = {'status': 'failed', 'message': str(e)}
                        task.error_message = str(e)
                        test_suite.execution_status = 'failed'
                        test_suite.save()
                        task.save()
                        self._send_task_notification(task, success=False)

                thread = threading.Thread(target=run_test)
                thread.daemon = True
                thread.start()

                log_operation('run', 'scheduled_task', task.id, task.name, request.user)

                return Response({
                    'message': '测试套件开始执行',
                    'task_id': task.id,
                    'task_name': task.name,
                    'test_suite': test_suite.name,
                    'test_case_count': test_case_count,
                    'engine': task.engine,
                    'browser': task.browser,
                    'headless': task.headless
                }, status=status.HTTP_200_OK)

            elif task.task_type == 'TEST_CASE':
                if not task.test_cases or len(task.test_cases) == 0:
                    return Response({
                        'error': '该任务未配置测试用例'
                    }, status=status.HTTP_400_BAD_REQUEST)

                test_case_ids = task.test_cases
                test_cases = TestCase.objects.filter(id__in=test_case_ids)
                test_case_count = test_cases.count()

                if test_case_count == 0:
                    return Response({
                        'error': '找不到配置的测试用例'
                    }, status=status.HTTP_400_BAD_REQUEST)

                import threading

                def run_test_cases():
                    success_count = 0
                    failed_count = 0
                    try:
                        for test_case in test_cases:
                            execution = TestCaseExecution.objects.create(
                                test_case=test_case,
                                project=task.project,
                                execution_source='scheduled',
                                status='running',
                                engine=task.engine,
                                browser=task.browser,
                                headless=task.headless,
                                created_by=task.created_by,
                                started_at=timezone.now()
                            )
                            try:
                                logger.info(f"开始执行定时任务的测试用例: {test_case.name} (ID: {test_case.id})")
                                start_time = time.time()
                                test_steps = list(test_case.steps.all().order_by('step_number'))
                                steps_data = []
                                for step in test_steps:
                                    step_data = {
                                        'step': step,
                                        'action_type': step.action_type,
                                        'description': step.description,
                                        'input_value': step.input_value,
                                        'wait_time': step.wait_time,
                                        'assert_type': step.assert_type,
                                        'assert_value': step.assert_value,
                                    }
                                    if step.element:
                                        step_data['element_data'] = {
                                            'locator_strategy': step.element.locator_strategy.name if step.element.locator_strategy else 'css',
                                            'locator_value': step.element.locator_value,
                                            'name': step.element.name,
                                            'wait_timeout': step.element.wait_timeout,
                                            'force_action': step.element.force_action
                                        }
                                    else:
                                        step_data['element_data'] = None
                                    steps_data.append(step_data)

                                step_results = []
                                screenshots = []
                                execution_logs = []
                                execution_result = {'status': 'passed', 'error_message': None}

                                if task.engine == 'selenium':
                                    from ..selenium_engine import SeleniumTestEngine
                                    is_available, error_msg = SeleniumTestEngine.check_browser_available(task.browser)
                                    if not is_available:
                                        execution.status = 'failed'
                                        execution.error_message = error_msg
                                        execution.execution_logs = json.dumps([{
                                            'step_number': 0,
                                            'action_type': '浏览器检查',
                                            'description': '执行前浏览器环境检查',
                                            'success': False,
                                            'error': error_msg
                                        }], ensure_ascii=False)
                                        execution.finished_at = timezone.now()
                                        execution.save()
                                        failed_count += 1
                                        continue

                                    engine = SeleniumTestEngine(browser_type=task.browser, headless=task.headless)
                                    try:
                                        engine.start()
                                        execution_logs.append("✓ 浏览器启动成功")
                                        if test_case.project.base_url:
                                            success, nav_log = engine.navigate(test_case.project.base_url)
                                            execution_logs.append(nav_log)
                                            if not success:
                                                execution_result['status'] = 'failed'
                                                execution_result['error_message'] = "导航到测试页面失败"
                                                raise Exception("导航到测试页面失败")
                                        for i, step_info in enumerate(steps_data, 1):
                                            step = step_info['step']
                                            action_type = step_info['action_type']
                                            element_data = step_info['element_data']
                                            success, step_log, screenshot_base64 = engine.execute_step(step, element_data or {})
                                            step_results.append({
                                                'step_number': i,
                                                'action_type': action_type,
                                                'description': step_info['description'] or '',
                                                'success': success,
                                                'error': None if success else step_log
                                            })
                                            if not success:
                                                execution_result['status'] = 'failed'
                                                execution_result['error_message'] = step_log
                                                if not screenshot_base64:
                                                    screenshot_base64 = engine.capture_screenshot()
                                                if screenshot_base64:
                                                    screenshots.append({
                                                        'url': screenshot_base64,
                                                        'description': f'步骤 {i} 失败截图',
                                                        'step_number': i,
                                                        'timestamp': timezone.now().isoformat()
                                                    })
                                                break
                                            if action_type == 'screenshot' and screenshot_base64:
                                                screenshots.append({
                                                    'url': screenshot_base64,
                                                    'description': f'步骤 {i}: {step_info["description"] or "手动截图"}',
                                                    'step_number': i,
                                                    'timestamp': timezone.now().isoformat()
                                                })
                                    finally:
                                        engine.stop()
                                else:
                                    import asyncio
                                    from asgiref.sync import sync_to_async
                                    from ..playwright_engine import PlaywrightTestEngine

                                    async def run_playwright_test():
                                        browser_map = {
                                            'chrome': 'chromium',
                                            'firefox': 'firefox',
                                            'safari': 'webkit'
                                        }
                                        browser_type = browser_map.get(task.browser, 'chromium')
                                        engine = PlaywrightTestEngine(browser_type=browser_type, headless=task.headless)
                                        try:
                                            await engine.start()
                                            execution_logs.append("✓ 浏览器启动成功")
                                            base_url = await sync_to_async(lambda: test_case.project.base_url)()
                                            if base_url:
                                                success, nav_log = await engine.navigate(base_url)
                                                execution_logs.append(nav_log)
                                                if not success:
                                                    execution_result['status'] = 'failed'
                                                    execution_result['error_message'] = "导航到测试页面失败"
                                                    return False
                                            for i, step_info in enumerate(steps_data, 1):
                                                step = step_info['step']
                                                action_type = step_info['action_type']
                                                element_data = step_info['element_data']
                                                success, step_log, screenshot_base64 = await engine.execute_step(step, element_data or {})
                                                step_results.append({
                                                    'step_number': i,
                                                    'action_type': action_type,
                                                    'description': step_info['description'] or '',
                                                    'success': success,
                                                    'error': None if success else step_log
                                                })
                                                if not success:
                                                    execution_result['status'] = 'failed'
                                                    execution_result['error_message'] = step_log
                                                    if not screenshot_base64:
                                                        screenshot_base64 = await engine.capture_screenshot()
                                                    if screenshot_base64:
                                                        screenshots.append({
                                                            'url': screenshot_base64,
                                                            'description': f'步骤 {i} 失败截图',
                                                            'step_number': i,
                                                            'timestamp': timezone.now().isoformat()
                                                        })
                                                    return False
                                                if action_type == 'screenshot' and screenshot_base64:
                                                    screenshots.append({
                                                        'url': screenshot_base64,
                                                        'description': f'步骤 {i}: {step_info["description"] or "手动截图"}',
                                                        'step_number': i,
                                                        'timestamp': timezone.now().isoformat()
                                                    })
                                            return True
                                        finally:
                                            await engine.stop()

                                    loop = asyncio.new_event_loop()
                                    asyncio.set_event_loop(loop)
                                    try:
                                        loop.run_until_complete(run_playwright_test())
                                    finally:
                                        loop.close()

                                total_time = round(time.time() - start_time, 2)
                                execution.status = execution_result['status']
                                execution.error_message = execution_result['error_message'] or ''
                                execution.execution_logs = json.dumps(step_results, ensure_ascii=False)
                                execution.execution_time = total_time
                                execution.screenshots = screenshots
                                execution.finished_at = timezone.now()
                                execution.save()

                                if execution.status == 'passed':
                                    success_count += 1
                                    logger.info(f"测试用例 {test_case.name} 执行成功")
                                else:
                                    failed_count += 1
                                    logger.warning(f"测试用例 {test_case.name} 执行失败: {execution.error_message}")
                            except Exception as e:
                                logger.error(f"执行测试用例 {test_case.name} 时发生异常: {str(e)}")
                                execution.status = 'failed'
                                execution.error_message = str(e)
                                execution.finished_at = timezone.now()
                                execution.save()
                                failed_count += 1

                        if failed_count == 0:
                            task.successful_runs += 1
                            task.last_result = {
                                'status': 'success',
                                'message': f'执行完成: {success_count}个成功',
                                'success_count': success_count,
                                'failed_count': failed_count
                            }
                            task.error_message = ''
                            task.save()
                            self._send_task_notification(task, success=True)
                        else:
                            task.failed_runs += 1
                            task.last_result = {
                                'status': 'partial',
                                'message': f'执行完成: {success_count}个成功, {failed_count}个失败',
                                'success_count': success_count,
                                'failed_count': failed_count
                            }
                            task.error_message = f'{failed_count}个测试用例执行失败'
                            task.save()
                            self._send_task_notification(task, success=False)
                    except Exception as e:
                        logger.error(f"执行定时任务测试用例时发生异常: {str(e)}")
                        task.failed_runs += 1
                        task.last_result = {'status': 'failed', 'message': str(e)}
                        task.error_message = str(e)
                        task.save()
                        self._send_task_notification(task, success=False)

                thread = threading.Thread(target=run_test_cases)
                thread.daemon = True
                thread.start()

                log_operation('run', 'scheduled_task', task.id, task.name, request.user)

                return Response({
                    'message': '测试用例开始执行',
                    'task_id': task.id,
                    'task_name': task.name,
                    'test_case_count': test_case_count,
                    'engine': task.engine,
                    'browser': task.browser,
                    'headless': task.headless
                }, status=status.HTTP_200_OK)

            else:
                return Response({
                    'error': '不支持的任务类型'
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f'执行定时任务失败: {str(e)}')
            return Response({
                'error': f'执行失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _send_task_notification(self, task, success):
        try:
            logger.info(f"准备发送任务 {task.id} 的通知，执行结果: {'成功' if success else '失败'}")
            if success and not task.notify_on_success:
                logger.info("任务执行成功但未启用成功通知")
                return
            if not success and not task.notify_on_failure:
                logger.info("任务执行失败但未启用失败通知")
                return
            if not task.notification_type:
                logger.info("未设置通知类型")
                return
            logger.info(f"通知类型: {task.notification_type}")
            if task.notification_type in ['webhook', 'both']:
                logger.info("发送Webhook通知")
                self._send_webhook_notification(task, success)
            if task.notification_type in ['email', 'both']:
                logger.info("发送邮件通知")
                self._send_email_notification(task, success)
        except Exception as e:
            logger.error(f"发送通知失败: {str(e)}", exc_info=True)

    def _send_webhook_notification(self, task, success):
        try:
            import requests
            logger.info("=== 开始发送Webhook通知 ===")
            try:
                from apps.core.models import UnifiedNotificationConfig
                all_webhook_configs = UnifiedNotificationConfig.objects.filter(
                    config_type__in=['webhook_wechat', 'webhook_feishu', 'webhook_dingtalk'],
                    is_active=True
                )
                logger.info("使用统一通知配置 (UnifiedNotificationConfig)")
            except ImportError as e:
                logger.error(f"无法导入统一通知配置: {e}")
                logger.warning("通知发送失败：无法找到通知配置模块")
                return
            except Exception as e:
                logger.error(f"获取通知配置时出错: {e}")
                return

            all_webhook_bots = []
            for config in all_webhook_configs:
                bots = config.get_webhook_bots()
                if bots:
                    for bot in bots:
                        if bot.get('enabled', True) and bot.get('enable_ui_automation', True):
                            all_webhook_bots.append(bot)
                            logger.info(f"添加机器人: {bot.get('name')} (UI自动化测试已启用)")
                        elif bot.get('enabled', True):
                            logger.info(f"配置中心机器人 {bot.get('name')} 未启用UI自动化测试，跳过")

            if not all_webhook_bots:
                logger.warning("没有找到任何启用的webhook机器人配置")
                return

            logger.info(f"找到 {len(all_webhook_bots)} 个启用的webhook机器人配置")

            status_text = '成功' if success else '失败'
            task_type_text = '测试套件执行' if task.task_type == 'TEST_SUITE' else '测试用例执行'
            last_result = task.last_result or {}
            result_message = last_result.get('message', '')
            success_count = last_result.get('success_count', 0)
            failed_count = last_result.get('failed_count', 0)

            for bot in all_webhook_bots:
                if not bot.get('enabled', True) or not bot.get('webhook_url'):
                    logger.info(f"跳过未启用或无URL的机器人: {bot.get('name', 'Unknown')}")
                    continue

                bot_type = bot.get('type', 'unknown')
                webhook_url = bot['webhook_url']
                logger.info(f"发送通知到 {bot_type} 机器人: {bot.get('name', 'Unknown')}")

                local_run_time = timezone.localtime(task.last_run_time).strftime(
                    '%Y-%m-%d %H:%M:%S') if task.last_run_time else '未知'
                detail_content = f"""任务名称: {task.name}

执行状态: {status_text}

执行时间: {local_run_time}

任务类型: {task_type_text}

执行引擎: {task.engine.upper()}

浏览器: {task.browser.capitalize()}"""

                if result_message:
                    detail_content += f"\n\n执行结果: {result_message}"
                if success_count > 0 or failed_count > 0:
                    detail_content += f"\n\n成功: {success_count} 个，失败: {failed_count} 个"

                if bot_type == 'wechat':
                    message_data = {
                        "msgtype": "markdown",
                        "markdown": {
                            "content": f"""**UI自动化定时任务执行{status_text}**

{detail_content}"""
                        }
                    }
                elif bot_type == 'feishu':
                    message_data = {
                        "msg_type": "interactive",
                        "card": {
                            "elements": [{
                                "tag": "div",
                                "text": {
                                    "content": f"**UI自动化定时任务执行{status_text}**\n\n{detail_content}",
                                    "tag": "lark_md"
                                }
                            }],
                            "header": {
                                "title": {
                                    "content": f"UI自动化定时任务执行{status_text}",
                                    "tag": "plain_text"
                                },
                                "template": "green" if success else "red"
                            }
                        }
                    }
                elif bot_type == 'dingtalk':
                    message_data = {
                        "msgtype": "markdown",
                        "markdown": {
                            "title": f"UI自动化定时任务执行{status_text}",
                            "text": f"""**UI自动化定时任务执行{status_text}**

{detail_content}"""
                        }
                    }
                    secret = bot.get('secret')
                    if secret:
                        import time
                        import hmac
                        import hashlib
                        import base64
                        import urllib.parse
                        timestamp = str(round(time.time() * 1000))
                        string_to_sign = f'{timestamp}\n{secret}'
                        string_to_sign_enc = string_to_sign.encode('utf-8')
                        secret_enc = secret.encode('utf-8')
                        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
                        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
                        if '?' in webhook_url:
                            webhook_url += f'&timestamp={timestamp}&sign={sign}'
                        else:
                            webhook_url += f'?timestamp={timestamp}&sign={sign}'
                else:
                    logger.warning(f"未知的机器人类型: {bot_type}")
                    continue

                try:
                    logger.info(f"发送请求到: {webhook_url}")
                    logger.info(f"消息数据: {json.dumps(message_data, ensure_ascii=False, indent=2)}")
                    response = requests.post(
                        webhook_url,
                        json=message_data,
                        headers={'Content-Type': 'application/json'},
                        timeout=10
                    )
                    logger.info(f"响应状态码: {response.status_code}")
                    logger.info(f"响应内容: {response.text}")
                    if response.status_code == 200:
                        logger.info(f"成功发送通知到 {bot.get('name', 'Unknown')}")
                        UiNotificationLog.objects.create(
                            task=task,
                            task_name=task.name,
                            task_type=task.task_type,
                            notification_type='task_execution',
                            sender_name='系统Webhook通知',
                            sender_email='system@notification.com',
                            recipient_info=[{'name': bot.get('name', 'Unknown'), 'webhook_url': webhook_url}],
                            webhook_bot_info=bot,
                            notification_content=json.dumps(message_data, ensure_ascii=False),
                            status='success',
                            response_info={'status_code': response.status_code, 'response': response.text},
                            sent_at=timezone.now()
                        )
                    else:
                        logger.error(f"发送通知失败，状态码: {response.status_code}, 响应: {response.text}")
                        UiNotificationLog.objects.create(
                            task=task,
                            task_name=task.name,
                            task_type=task.task_type,
                            notification_type='task_execution',
                            sender_name='系统Webhook通知',
                            sender_email='system@notification.com',
                            recipient_info=[{'name': bot.get('name', 'Unknown'), 'webhook_url': webhook_url}],
                            webhook_bot_info=bot,
                            notification_content=json.dumps(message_data, ensure_ascii=False),
                            status='failed',
                            error_message=f'HTTP {response.status_code}: {response.text}',
                            response_info={'status_code': response.status_code, 'response': response.text}
                        )
                except requests.exceptions.RequestException as e:
                    logger.error(f"发送webhook请求失败: {str(e)}")
                    UiNotificationLog.objects.create(
                        task=task,
                        task_name=task.name,
                        task_type=task.task_type,
                        notification_type='task_execution',
                        sender_name='系统Webhook通知',
                        sender_email='system@notification.com',
                        recipient_info=[{'name': bot.get('name', 'Unknown'), 'webhook_url': webhook_url}],
                        webhook_bot_info=bot,
                        notification_content=json.dumps(message_data, ensure_ascii=False),
                        status='failed',
                        error_message=str(e)
                    )
        except Exception as e:
            logger.error(f"发送Webhook通知失败: {str(e)}", exc_info=True)

    def _send_email_notification(self, task, success):
        try:
            from django.core.mail import send_mail
            from django.conf import settings
            logger.info("=== 开始发送邮件通知 ===")
            recipients = []
            if task.notify_emails:
                if isinstance(task.notify_emails, list):
                    recipients = task.notify_emails
                else:
                    recipients = [task.notify_emails]
            if not recipients:
                logger.warning("没有找到任何邮件收件人")
                return
            status_text = '成功' if success else '失败'
            task_type_text = '测试套件执行' if task.task_type == 'TEST_SUITE' else '测试用例执行'
            subject = f"UI自动化定时任务执行{status_text}: {task.name}"
            last_result = task.last_result or {}
            result_message = last_result.get('message', '')
            local_run_time = timezone.localtime(task.last_run_time).strftime(
                '%Y-%m-%d %H:%M:%S') if task.last_run_time else '未知'
            message = f"""
任务名称: {task.name}
执行状态: {status_text}
执行时间: {local_run_time}
任务类型: {task_type_text}
执行引擎: {task.engine.upper()}
浏览器: {task.browser.capitalize()}

执行结果:
{result_message if result_message else '无详细信息'}

错误信息:
{task.error_message if task.error_message else '无错误信息'}
            """
            from_email = settings.DEFAULT_FROM_EMAIL
            logger.info(f"准备发送邮件，发件人: {from_email}, 收件人: {recipients}")
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email,
                recipient_list=recipients,
                fail_silently=False,
            )
            logger.info("邮件发送成功")
            UiNotificationLog.objects.create(
                task=task,
                task_name=task.name,
                task_type=task.task_type,
                notification_type='task_execution',
                sender_name='系统邮件通知',
                sender_email=from_email,
                recipient_info=[{'email': email} for email in recipients],
                notification_content=message,
                status='success',
                sent_at=timezone.now()
            )
        except Exception as e:
            logger.error(f"发送邮件通知失败: {str(e)}", exc_info=True)
            try:
                UiNotificationLog.objects.create(
                    task=task,
                    task_name=task.name,
                    task_type=task.task_type,
                    notification_type='task_execution',
                    sender_name='系统邮件通知',
                    sender_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_info=[{'email': email} for email in recipients] if recipients else [],
                    notification_content=f"发送邮件通知失败: {str(e)}",
                    status='failed',
                    error_message=str(e)
                )
            except Exception:
                pass


class UiNotificationLogViewSet(viewsets.ReadOnlyModelViewSet):
    """UI通知日志视图集（只读）"""
    queryset = UiNotificationLog.objects.all()
    serializer_class = UiNotificationLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'notification_type']
    search_fields = ['task_name', 'notification_content']
    ordering_fields = ['created_at', 'sent_at']
    ordering = ['-created_at']

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        log = self.get_object()
        if log.status == 'failed':
            log.retry_count += 1
            log.is_retried = True
            log.save()
            return Response({'message': '通知已加入重试队列'})
        return Response({'error': '只能重试失败的通知'}, status=status.HTTP_400_BAD_REQUEST)


class UiTaskNotificationSettingViewSet(viewsets.ModelViewSet):
    """UI任务通知设置视图集"""
    queryset = UiTaskNotificationSetting.objects.all()
    serializer_class = UiTaskNotificationSettingSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['task', 'is_enabled', 'notification_type']
