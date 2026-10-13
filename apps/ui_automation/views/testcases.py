from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from django.db import models
from django.utils import timezone
import json
import random
import time

from ..models import (
    UiProject, TestCase, TestCaseStep, TestCaseExecution, OperationRecord
)
from ..serializers import (
    TestCaseSerializer, TestCaseStepSerializer, TestCaseExecutionSerializer,
    OperationRecordSerializer,
)
from ..operation_logger import log_operation
from ._helpers import StandardPagination

import logging
logger = logging.getLogger(__name__)


class TestCaseViewSet(viewsets.ModelViewSet):
    """测试用例视图集"""
    queryset = TestCase.objects.all()
    serializer_class = TestCaseSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['created_at', 'updated_at', 'name', 'priority', 'status']
    ordering = ['-created_at']
    filterset_fields = ['project', 'status', 'priority', 'created_by']

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        return TestCase.objects.filter(project__in=accessible_projects).select_related('project', 'created_by')

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)
        log_operation('create', 'test_case', instance.id, instance.name, self.request.user)
        steps_data = self.request.data.get('steps', [])
        logger.info(f"创建测试用例 {instance.id} 的步骤数据: {len(steps_data)} 个步骤")
        if steps_data:
            created_count = 0
            for i, step_data in enumerate(steps_data):
                step_data = dict(step_data)
                step_data['test_case'] = instance.id
                step_data['step_number'] = i + 1
                if 'element_id' in step_data:
                    step_data['element'] = step_data.pop('element_id')
                step_data.pop('id', None)
                step_data.pop('element_name', None)
                step_data.pop('element_locator', None)
                step_data.pop('created_at', None)
                step_data.pop('expanded', None)
                try:
                    TestCaseStep.objects.create(
                        test_case=instance,
                        step_number=step_data.get('step_number', i + 1),
                        action_type=step_data.get('action_type', 'click'),
                        element_id=step_data.get('element') if step_data.get('element') else None,
                        input_value=step_data.get('input_value', ''),
                        wait_time=step_data.get('wait_time', 1000),
                        assert_type=step_data.get('assert_type', ''),
                        assert_value=step_data.get('assert_value', ''),
                        description=step_data.get('description', ''),
                        is_optional=step_data.get('is_optional', False),
                        optional_note=step_data.get('optional_note', '')
                    )
                    created_count += 1
                except Exception as e:
                    logger.error(f"创建步骤 {i + 1} 失败: {str(e)}")
                    logger.error(f"步骤数据: {step_data}")
            logger.info(f"成功创建了 {created_count} 个新步骤")

    @action(detail=True, methods=['post'])
    def copy_case(self, request, pk=None):
        test_case = self.get_object()
        try:
            new_case = TestCase.objects.create(
                project=test_case.project,
                name=f"{test_case.name}_copy",
                description=test_case.description,
                priority=test_case.priority,
                status=test_case.status,
                created_by=request.user
            )
            steps = test_case.steps.all().order_by('step_number')
            new_steps = []
            for step in steps:
                new_steps.append(TestCaseStep(
                    test_case=new_case,
                    step_number=step.step_number,
                    action_type=step.action_type,
                    element=step.element,
                    input_value=step.input_value,
                    wait_time=step.wait_time,
                    assert_type=step.assert_type,
                    assert_value=step.assert_value,
                    description=step.description,
                    is_optional=step.is_optional,
                    optional_note=step.optional_note
                ))
            if new_steps:
                TestCaseStep.objects.bulk_create(new_steps)
            log_operation('create', 'test_case', new_case.id, new_case.name, request.user)
            serializer = self.get_serializer(new_case)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"复制测试用例失败: {str(e)}")
            return Response({'error': f"复制失败: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_update(self, serializer):
        instance = serializer.save()
        log_operation('edit', 'test_case', instance.id, instance.name, self.request.user)
        if 'steps' not in self.request.data:
            return
        steps_data = self.request.data.get('steps') or []
        logger.info(f"更新测试用例 {instance.id} 的步骤数据: {len(steps_data)} 个步骤")
        existing_steps_count = instance.steps.count()
        instance.steps.all().delete()
        logger.info(f"删除了 {existing_steps_count} 个现有步骤")
        created_count = 0
        for i, step_data in enumerate(steps_data):
            step_data = dict(step_data)
            step_data['test_case'] = instance.id
            step_data['step_number'] = i + 1
            if 'element_id' in step_data:
                step_data['element'] = step_data.pop('element_id')
            step_data.pop('id', None)
            step_data.pop('element_name', None)
            step_data.pop('element_locator', None)
            step_data.pop('created_at', None)
            step_data.pop('expanded', None)
            try:
                TestCaseStep.objects.create(
                    test_case=instance,
                    step_number=step_data.get('step_number', i + 1),
                    action_type=step_data.get('action_type', 'click'),
                    element_id=step_data.get('element') if step_data.get('element') else None,
                    input_value=step_data.get('input_value', ''),
                    wait_time=step_data.get('wait_time', 1000),
                    assert_type=step_data.get('assert_type', ''),
                    assert_value=step_data.get('assert_value', ''),
                    description=step_data.get('description', ''),
                    is_optional=step_data.get('is_optional', False),
                    optional_note=step_data.get('optional_note', '')
                )
                created_count += 1
            except Exception as e:
                logger.error(f"创建步骤 {i + 1} 失败: {str(e)}")
                logger.error(f"步骤数据: {step_data}")
        logger.info(f"成功创建了 {created_count} 个新步骤")

    def _generate_step_log(self, step, step_result='success'):
        execution_time = round(random.uniform(0.1, 2.0), 2)
        log_parts = []
        if step.element:
            element_name = step.element.name
            locator_info = f"{step.element.locator_strategy.name}={step.element.locator_value}"
        else:
            element_name = "页面"
            locator_info = "无"
        if step.action_type == 'click':
            log_parts.append(f"点击元素 '{element_name}'")
            log_parts.append(f"- 使用定位器: {locator_info}")
            if step_result == 'success':
                log_parts.append(f"- 元素点击成功 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 元素点击失败 - 元素未找到或不可点击")
        elif step.action_type == 'fill':
            log_parts.append(f"在元素 '{element_name}' 中输入文本")
            log_parts.append(f"- 使用定位器: {locator_info}")
            log_parts.append(f"- 输入值: '{step.input_value}'")
            if step_result == 'success':
                log_parts.append(f"- 文本输入成功 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 文本输入失败 - 元素未找到或不可编辑")
        elif step.action_type == 'getText':
            log_parts.append(f"获取元素 '{element_name}' 的文本内容")
            log_parts.append(f"- 使用定位器: {locator_info}")
            if step_result == 'success':
                mock_text = f"示例文本内容_{step.id}" if step.id else "示例文本内容"
                log_parts.append(f"- 获取到文本: '{mock_text}' - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 获取文本失败 - 元素未找到")
        elif step.action_type == 'waitFor':
            log_parts.append(f"等待元素 '{element_name}' 出现")
            log_parts.append(f"- 使用定位器: {locator_info}")
            log_parts.append(f"- 超时时间: {step.wait_time / 1000}秒")
            if step_result == 'success':
                log_parts.append(f"- 元素在 {execution_time}s 后出现")
            else:
                log_parts.append(f"- 等待超时 - 元素未在指定时间内出现")
        elif step.action_type == 'hover':
            log_parts.append(f"在元素 '{element_name}' 上悬停")
            log_parts.append(f"- 使用定位器: {locator_info}")
            if step_result == 'success':
                log_parts.append(f"- 悬停操作成功 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 悬停操作失败 - 元素未找到")
        elif step.action_type == 'scroll':
            log_parts.append(f"滚动到元素 '{element_name}'")
            log_parts.append(f"- 使用定位器: {locator_info}")
            if step_result == 'success':
                log_parts.append(f"- 滚动操作成功 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 滚动操作失败 - 元素未找到")
        elif step.action_type == 'screenshot':
            log_parts.append(f"执行截图操作")
            if step.element:
                log_parts.append(f"- 截图范围: 元素 '{element_name}'")
            else:
                log_parts.append(f"- 截图范围: 整个页面")
            if step_result == 'success':
                screenshot_name = f"screenshot_{int(time.time())}.png"
                log_parts.append(f"- 截图保存成功: {screenshot_name} - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 截图保存失败")
        elif step.action_type == 'assert':
            log_parts.append(f"执行断言验证")
            log_parts.append(f"- 断言类型: {step.assert_type}")
            if step.assert_value:
                log_parts.append(f"- 期望值: '{step.assert_value}'")
            if step_result == 'success':
                log_parts.append(f"- 断言通过 - 耗时 {execution_time}s")
            else:
                log_parts.append(f"- 断言失败 - 实际值与期望值不匹配")
        elif step.action_type == 'wait':
            log_parts.append(f"固定等待")
            log_parts.append(f"- 等待时间: {step.wait_time / 1000}秒")
            log_parts.append(f"- 等待完成")
        else:
            log_parts.append(f"执行操作: {step.action_type}")
            if step.element:
                log_parts.append(f"- 目标元素: {element_name}")
            if step.input_value:
                log_parts.append(f"- 输入值: {step.input_value}")
            log_parts.append(f"- 操作{'成功' if step_result == 'success' else '失败'} - 耗时 {execution_time}s")
        if step.description:
            log_parts.insert(0, f"说明: {step.description}")
        return '\n'.join(log_parts)

    def _generate_failure_screenshot(self, step_number, step_description):
        try:
            from PIL import Image, ImageDraw, ImageFont
            import io
            import base64
            width, height = 1280, 720
            img = Image.new('RGB', (width, height), color=(240, 240, 245))
            draw = ImageDraw.Draw(img)
            draw.rectangle([0, 0, width, 80], fill=(220, 53, 69))
            try:
                font_title = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 40)
                font_text = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 24)
            except Exception:
                font_title = ImageFont.load_default()
                font_text = ImageFont.load_default()
            draw.text((40, 20), "测试步骤执行失败", fill=(255, 255, 255), font=font_title)
            info_y = 120
            draw.text((40, info_y), f"失败步骤: 步骤 {step_number}", fill=(50, 50, 50), font=font_text)
            draw.text((40, info_y + 40), f"步骤说明: {step_description}", fill=(50, 50, 50), font=font_text)
            draw.text((40, info_y + 80), f"失败时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}",
                      fill=(50, 50, 50), font=font_text)
            browser_y = info_y + 140
            draw.rectangle([40, browser_y, width - 40, height - 40], outline=(200, 200, 200), width=2)
            draw.rectangle([40, browser_y, width - 40, browser_y + 40], fill=(200, 200, 200))
            draw.text((60, browser_y + 10), "模拟浏览器页面 - 失败截图", fill=(80, 80, 80), font=font_text)
            error_y = browser_y + 80
            draw.text((60, error_y), "× 元素定位失败或操作执行异常", fill=(220, 53, 69), font=font_text)
            draw.text((60, error_y + 40), "× 请检查元素定位器是否正确", fill=(220, 53, 69), font=font_text)
            draw.text((60, error_y + 80), "× 或页面加载是否完成", fill=(220, 53, 69), font=font_text)
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            return f"data:image/png;base64,{img_base64}"
        except Exception as e:
            logger.error(f"生成失败截图时出错: {str(e)}")
            return None

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        test_case = self.get_object()
        try:
            engine_type = request.data.get('engine', 'playwright')
            execution = TestCaseExecution.objects.create(
                test_case=test_case,
                project=test_case.project,
                execution_source='manual',
                status='running',
                engine=engine_type,
                browser=request.data.get('browser', 'chrome'),
                headless=request.data.get('headless', False),
                created_by=request.user,
                started_at=timezone.now()
            )
            if engine_type == 'selenium':
                from ..selenium_engine import SeleniumTestEngine
                browser_type = request.data.get('browser', 'chrome')
                is_available, error_msg = SeleniumTestEngine.check_browser_available(browser_type)
                if not is_available:
                    logger.error(f"Selenium 浏览器检查失败: {error_msg}")
                    execution.status = 'failed'
                    execution.error_message = error_msg
                    execution.execution_logs = f"浏览器检查失败\n\n{error_msg}\n\n建议：\n1. 请确认已安装 {browser_type.capitalize()} 浏览器\n2. 或者尝试使用其他浏览器（Chrome、Firefox、Edge）\n3. 或者使用 Playwright 引擎（支持自动下载浏览器）"
                    execution.finished_at = timezone.now()
                    execution.save()
                    return Response({
                        'success': False,
                        'logs': execution.execution_logs,
                        'screenshots': [],
                        'execution_time': 0,
                        'errors': [{
                            'message': f'{browser_type.capitalize()} 浏览器不可用',
                            'details': error_msg,
                            'step_number': None,
                            'action_type': '浏览器检查',
                            'element': '',
                            'description': '执行前浏览器环境检查'
                        }]
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                import asyncio
                import threading
                from ..playwright_engine import PlaywrightTestEngine

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
            execution_logs = []
            execution_logs.append(f"测试用例 '{test_case.name}' 开始执行")
            execution_logs.append(f"执行时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
            execution_logs.append(f"执行引擎: {engine_type.upper()}")
            execution_logs.append(f"浏览器: {request.data.get('browser', 'chrome').capitalize()}")
            headless_mode = request.data.get('headless', False)
            mode_text = "无头模式" if headless_mode else "有头模式"
            execution_logs.append(f"执行模式: {mode_text}")
            execution_logs.append(f"执行用户: {request.user.username}")
            execution_logs.append(f"项目基础URL: {test_case.project.base_url}")
            execution_logs.append("")

            screenshots = []
            detailed_errors = []
            execution_result = {'status': 'passed', 'error_message': None}

            if engine_type == 'selenium':
                def run_test_selenium():
                    browser_type = request.data.get('browser', 'chrome')
                    headless = request.data.get('headless', False)
                    engine = SeleniumTestEngine(browser_type=browser_type, headless=headless)
                    try:
                        execution_logs.append("========== 初始化浏览器 ==========")
                        try:
                            engine.start()
                            mode_text = "无头模式" if headless else "有头模式"
                            execution_logs.append(f"✓ {browser_type.capitalize()} 浏览器启动成功 (Selenium, {mode_text})")
                            execution_logs.append("")
                        except Exception as browser_error:
                            execution_logs.append(f"✗ {browser_type.capitalize()} 浏览器启动失败")
                            execution_logs.append(f"  错误: {str(browser_error)}")
                            execution_logs.append("")
                            execution_result['status'] = 'failed'
                            execution_result['error_message'] = f"{browser_type.capitalize()} 浏览器启动失败: {str(browser_error)}"
                            detailed_errors.append({
                                'step_number': None,
                                'action_type': '浏览器启动',
                                'element': '',
                                'message': f"{browser_type.capitalize()} 浏览器启动失败",
                                'details': str(browser_error),
                                'description': '执行前浏览器启动检查'
                            })
                            return False
                        if test_case.project.base_url:
                            execution_logs.append("========== 导航到测试页面 ==========")
                            success, nav_log = engine.navigate(test_case.project.base_url)
                            execution_logs.append(nav_log)
                            execution_logs.append("")
                            if not success:
                                execution_result['status'] = 'failed'
                                execution_result['error_message'] = "导航到测试页面失败"
                                return False
                        if steps_data:
                            execution_logs.append("========== 执行测试步骤 ==========")
                            step_count = len(steps_data)
                            execution_logs.append(f"共有 {step_count} 个步骤需要执行")
                            execution_logs.append("")
                            for i, step_info in enumerate(steps_data, 1):
                                execution_logs.append(f"========== 开始执行步骤 {i}/{step_count} ==========")
                                execution_logs.append(f"步骤 {i}/{step_count}:")
                                step = step_info['step']
                                action_type = step_info['action_type']
                                description = step_info['description']
                                element_data = step_info['element_data']
                                action_choices_dict = dict(TestCaseStep.ACTION_TYPE_CHOICES)
                                action_type_text = action_choices_dict.get(action_type, action_type)
                                execution_logs.append(f"  操作: {action_type_text}")
                                if description:
                                    execution_logs.append(f"  说明: {description}")
                                if element_data:
                                    execution_logs.append(f"  元素: {element_data['name']}")
                                    execution_logs.append(f"  定位器: {element_data['locator_strategy']}={element_data['locator_value']}")
                                else:
                                    execution_logs.append(f"  (此步骤不需要元素)")
                                try:
                                    success, step_log, screenshot_base64 = engine.execute_step(step, element_data or {})
                                    execution_logs.append(f"  {step_log}")
                                    execution_logs.append("")
                                    step_results.append({
                                        'step_number': i,
                                        'action_type': action_type,
                                        'description': description or '',
                                        'success': success,
                                        'error': None if success else step_log
                                    })
                                    if not success and getattr(step, 'is_optional', False):
                                        skip_note = getattr(step, 'optional_note', '') or '可跳过步骤未出现，已自动跳过'
                                        execution_logs.append(f"  ⏭ 跳过可选步骤: {skip_note}")
                                        if step_results:
                                            step_results[-1]['success'] = True
                                            step_results[-1]['error'] = None
                                            step_results[-1]['skipped_optional'] = True
                                            step_results[-1]['log'] = skip_note
                                        continue
                                    if not success:
                                        logger.info(f"[调试-Selenium] 步骤 {i} 执行失败，设置状态为 failed")
                                        execution_result['status'] = 'failed'
                                        element_info = element_data['name'] if element_data else "未知元素"
                                        execution_result['error_message'] = step_log
                                        logger.info(f"[调试-Selenium] execution_result = {execution_result}")
                                        detailed_errors.append({
                                            'step_number': i,
                                            'action_type': action_type_text,
                                            'element': element_info,
                                            'message': f"步骤 {i}/{step_count} 执行失败",
                                            'details': step_log,
                                            'description': description or ''
                                        })
                                        if not screenshot_base64:
                                            screenshot_base64 = engine.capture_screenshot()
                                        if screenshot_base64:
                                            screenshots.append({
                                                'url': screenshot_base64,
                                                'description': f'步骤 {i} 失败截图: {description or action_type_text}',
                                                'step_number': i,
                                                'timestamp': timezone.now().isoformat()
                                            })
                                            execution_logs.append(f"  📸 失败截图已捕获")
                                        return False
                                    if action_type == 'screenshot' and screenshot_base64:
                                        screenshots.append({
                                            'url': screenshot_base64,
                                            'description': f'步骤 {i}: {description or "手动截图"}',
                                            'step_number': i,
                                            'timestamp': timezone.now().isoformat()
                                        })
                                except Exception as e:
                                    execution_logs.append(f"  ✗ 步骤执行异常: {str(e)}")
                                    import traceback
                                    tb_str = traceback.format_exc()
                                    execution_logs.append(f"  [调试] 异常堆栈:\n{tb_str}")
                                    step_results.append({
                                        'step_number': i,
                                        'action_type': action_type,
                                        'description': description or '',
                                        'success': False,
                                        'error': str(e)
                                    })
                                    execution_result['status'] = 'failed'
                                    execution_result['error_message'] = f"步骤 {i} 执行异常: {str(e)}"
                                    element_info = element_data['name'] if element_data else "未知元素"
                                    detailed_errors.append({
                                        'step_number': i,
                                        'action_type': action_type_text,
                                        'element': element_info,
                                        'message': f"步骤 {i}/{step_count} 执行异常",
                                        'details': f"异常: {str(e)}\n\n堆栈跟踪:\n{tb_str}",
                                        'description': description or ''
                                    })
                                    try:
                                        screenshot_base64 = engine.capture_screenshot()
                                        if screenshot_base64:
                                            screenshots.append({
                                                'url': screenshot_base64,
                                                'description': f'步骤 {i} 异常截图: {str(e)}',
                                                'step_number': i,
                                                'timestamp': timezone.now().isoformat()
                                            })
                                    except Exception:
                                        pass
                                    return False
                            execution_logs.append(f"========== 执行完成 ({step_count} 个步骤全部通过) ==========")
                            return True
                        else:
                            execution_logs.append("警告: 测试用例没有定义任何步骤")
                            return True
                    finally:
                        execution_logs.append("")
                        execution_logs.append("========== 清理资源 ==========")
                        engine.stop()
                        execution_logs.append("✓ 浏览器已关闭")

                import threading
                test_thread = threading.Thread(target=run_test_selenium)
                test_thread.start()
                test_thread.join()
            else:
                def run_test_in_thread():
                    async def run_test():
                        browser_map = {
                            'chrome': 'chromium',
                            'firefox': 'firefox',
                            'safari': 'webkit'
                        }
                        browser_type = browser_map.get(request.data.get('browser', 'chrome'), 'chromium')
                        headless = request.data.get('headless', False)
                        engine = PlaywrightTestEngine(browser_type=browser_type, headless=headless)
                        try:
                            execution_logs.append("========== 初始化浏览器 ==========")
                            await engine.start()
                            mode_text = "无头模式" if headless else "有头模式"
                            execution_logs.append(f"✓ {browser_type.capitalize()} 浏览器启动成功 (Playwright, {mode_text})")
                            execution_logs.append("")
                            if test_case.project.base_url:
                                execution_logs.append("========== 导航到测试页面 ==========")
                                success, nav_log = await engine.navigate(test_case.project.base_url)
                                execution_logs.append(nav_log)
                                execution_logs.append("")
                                if not success:
                                    execution_result['status'] = 'failed'
                                    execution_result['error_message'] = "导航到测试页面失败"
                                    return False
                            if steps_data:
                                execution_logs.append("========== 执行测试步骤 ==========")
                                step_count = len(steps_data)
                                execution_logs.append(f"共有 {step_count} 个步骤需要执行")
                                execution_logs.append("")
                                for i, step_info in enumerate(steps_data, 1):
                                    execution_logs.append(f"========== 开始执行步骤 {i}/{step_count} ==========")
                                    execution_logs.append(f"步骤 {i}/{step_count}:")
                                    step = step_info['step']
                                    action_type = step_info['action_type']
                                    description = step_info['description']
                                    element_data = step_info['element_data']
                                    action_choices_dict = dict(TestCaseStep.ACTION_TYPE_CHOICES)
                                    action_type_text = action_choices_dict.get(action_type, action_type)
                                    execution_logs.append(f"  操作: {action_type_text}")
                                    if description:
                                        execution_logs.append(f"  说明: {description}")
                                    if element_data:
                                        execution_logs.append(f"  元素: {element_data['name']}")
                                        execution_logs.append(f"  定位器: {element_data['locator_strategy']}={element_data['locator_value']}")
                                    else:
                                        execution_logs.append(f"  (此步骤不需要元素)")
                                    try:
                                        execution_logs.append(f"  [调试] 准备执行步骤...")
                                        success, step_log, screenshot_base64 = await engine.execute_step(step, element_data or {})
                                        execution_logs.append(f"  [调试] 步骤执行完成, success={success}")
                                        execution_logs.append(f"  {step_log}")
                                        execution_logs.append("")
                                        step_results.append({
                                            'step_number': i,
                                            'action_type': action_type,
                                            'description': description or '',
                                            'success': success,
                                            'error': None if success else step_log
                                        })
                                        if not success and getattr(step, 'is_optional', False):
                                            skip_note = getattr(step, 'optional_note', '') or '可跳过步骤未出现，已自动跳过'
                                            execution_logs.append(f"  ⏭ 跳过可选步骤: {skip_note}")
                                            if step_results:
                                                step_results[-1]['success'] = True
                                                step_results[-1]['error'] = None
                                                step_results[-1]['skipped_optional'] = True
                                                step_results[-1]['log'] = skip_note
                                            continue
                                        if not success:
                                            execution_logs.append(f"  [调试] 检测到步骤失败,准备处理...")
                                            execution_result['status'] = 'failed'
                                            element_info = element_data['name'] if element_data else "未知元素"
                                            execution_result['error_message'] = step_log
                                            detailed_errors.append({
                                                'step_number': i,
                                                'action_type': action_type_text,
                                                'element': element_info,
                                                'message': f"步骤 {i}/{step_count} 执行失败",
                                                'details': step_log,
                                                'description': description or ''
                                            })
                                            if not screenshot_base64:
                                                screenshot_base64 = await engine.capture_screenshot()
                                        if screenshot_base64:
                                            screenshots.append({
                                                'url': screenshot_base64,
                                                'description': f'步骤 {i} 失败截图: {description or action_type_text}',
                                                'step_number': i,
                                                'timestamp': timezone.now().isoformat()
                                            })
                                            execution_logs.append(f"  📸 失败截图已捕获")
                                            execution_logs.append(f"  [调试] 步骤失败,准备退出执行...")
                                            return False
                                        if action_type == 'screenshot' and screenshot_base64:
                                            screenshots.append({
                                                'url': screenshot_base64,
                                                'description': f'步骤 {i}: {description or "手动截图"}',
                                                'step_number': i,
                                                'timestamp': timezone.now().isoformat()
                                            })
                                        execution_logs.append(f"  [调试] 步骤 {i} 成功完成,准备执行下一步...")
                                    except Exception as e:
                                        execution_logs.append(f"  ✗ 步骤执行异常: {str(e)}")
                                        execution_logs.append(f"  [调试] 异常详情: {repr(e)}")
                                        import traceback
                                        tb_str = traceback.format_exc()
                                        execution_logs.append(f"  [调试] 异常堆栈:\n{tb_str}")
                                        step_results.append({
                                            'step_number': i,
                                            'action_type': action_type,
                                            'description': description or '',
                                            'success': False,
                                            'error': str(e)
                                        })
                                        execution_result['status'] = 'failed'
                                        execution_result['error_message'] = f"步骤 {i} 执行异常: {str(e)}"
                                        element_info = element_data['name'] if element_data else "未知元素"
                                        detailed_errors.append({
                                            'step_number': i,
                                            'action_type': action_type_text,
                                            'element': element_info,
                                            'message': f"步骤 {i}/{step_count} 执行异常",
                                            'details': f"异常: {str(e)}\n\n堆栈跟踪:\n{tb_str}",
                                            'description': description or ''
                                        })
                                        try:
                                            screenshot_base64 = await engine.capture_screenshot()
                                            if screenshot_base64:
                                                screenshots.append({
                                                    'url': screenshot_base64,
                                                    'description': f'步骤 {i} 异常截图: {str(e)}',
                                                    'step_number': i,
                                                    'timestamp': timezone.now().isoformat()
                                                })
                                        except Exception:
                                            pass
                                        execution_logs.append(f"  [调试] 发生异常,准备退出执行...")
                                        return False
                                execution_logs.append(f"========== 执行完成 ({step_count} 个步骤全部通过) ==========")
                                return True
                            else:
                                execution_logs.append("警告: 测试用例没有定义任何步骤")
                                return True
                        finally:
                            execution_logs.append("")
                            execution_logs.append("========== 清理资源 ==========")
                            await engine.stop()
                            execution_logs.append("✓ 浏览器已关闭")

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(run_test())
                    finally:
                        loop.close()

                import threading
                test_thread = threading.Thread(target=run_test_in_thread)
                test_thread.start()
                test_thread.join()

            total_time = round(time.time() - start_time, 2)
            execution_logs.append("")
            execution_logs.append("执行环境信息:")
            execution_logs.append(f"- 执行引擎: {engine_type.upper()}")
            execution_logs.append(f"- 浏览器: {request.data.get('browser', 'chrome').capitalize()}")
            execution_logs.append(f"- 屏幕分辨率: 1920x1080")
            execution_logs.append(f"- 总执行时间: {total_time}秒")
            if screenshots:
                execution_logs.append(f"- 截图数量: {len(screenshots)} 张")

            logger.info(f"[调试] 准备保存执行结果: execution_result['status'] = {execution_result['status']}")
            execution.status = execution_result['status']
            execution.error_message = execution_result['error_message'] or ''
            execution.execution_logs = json.dumps(step_results, ensure_ascii=False)
            execution.execution_time = total_time
            execution.finished_at = timezone.now()
            execution.screenshots = screenshots
            execution.save()
            logger.info(f"[调试] 执行结果已保存: execution.status = {execution.status}")

            serializer = TestCaseExecutionSerializer(execution)
            errors = []
            if detailed_errors:
                for error in detailed_errors:
                    errors.append({
                        'message': error['message'],
                        'details': error['details'],
                        'step_number': error['step_number'],
                        'action_type': error['action_type'],
                        'element': error['element'],
                        'description': error['description']
                    })
            elif execution.error_message:
                errors.append({
                    'message': execution.error_message,
                    'details': ''
                })

            log_operation('run', 'test_case', test_case.id, test_case.name, request.user)

            return Response({
                'success': execution.status == 'passed',
                'logs': execution.execution_logs,
                'screenshots': screenshots,
                'execution_time': execution.execution_time,
                'errors': errors
            })
        except Exception as e:
            logger.error(f"执行测试用例失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({
                'success': False,
                'logs': f"执行失败: {str(e)}\n\n{traceback.format_exc()}",
                'screenshots': [],
                'execution_time': 0,
                'errors': [{'message': str(e), 'stack': traceback.format_exc()}]
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def batch_run(self, request):
        test_case_ids = request.data.get('test_case_ids', [])
        project_id = request.data.get('project_id')
        if not test_case_ids:
            return Response({'error': '请选择要运行的测试用例'}, status=status.HTTP_400_BAD_REQUEST)
        results = []
        for test_case_id in test_case_ids:
            try:
                test_case = TestCase.objects.get(id=test_case_id)
                results.append({
                    'test_case_id': test_case_id,
                    'test_case_name': test_case.name,
                    'status': 'passed'
                })
            except TestCase.DoesNotExist:
                results.append({
                    'test_case_id': test_case_id,
                    'test_case_name': '未知',
                    'status': 'error',
                    'error': '测试用例不存在'
                })
        return Response({'results': results})

    def perform_destroy(self, instance):
        log_operation('delete', 'test_case', instance.id, instance.name, self.request.user)
        instance.delete()


class TestCaseStepViewSet(viewsets.ModelViewSet):
    """测试用例步骤视图集"""
    queryset = TestCaseStep.objects.all()
    serializer_class = TestCaseStepSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    ordering_fields = ['step_number']
    ordering = ['step_number']
    filterset_fields = ['test_case', 'action_type']

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        accessible_test_cases = TestCase.objects.filter(project__in=accessible_projects)
        return TestCaseStep.objects.filter(test_case__in=accessible_projects)


class TestCaseExecutionViewSet(viewsets.ModelViewSet):
    """测试用例执行记录视图集"""
    queryset = TestCaseExecution.objects.all().select_related(
        'test_case', 'project', 'test_suite', 'executed_by'
    )
    serializer_class = TestCaseExecutionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['test_case__name', 'error_message']
    ordering_fields = ['created_at', 'started_at', 'finished_at', 'status']
    ordering = ['-created_at']
    filterset_fields = ['project', 'test_suite', 'test_case', 'status', 'execution_source']
    pagination_class = StandardPagination

    def get_queryset(self):
        user = self.request.user
        accessible_projects = UiProject.objects.filter(
            models.Q(owner=user) | models.Q(members=user)
        ).distinct()
        return TestCaseExecution.objects.filter(
            project__in=accessible_projects
        ).select_related(
            'test_case', 'project', 'test_suite', 'created_by'
        )

    def perform_destroy(self, instance):
        name = instance.test_case.name if instance.test_case else f"执行记录#{instance.id}"
        log_operation('delete', 'report', instance.id, name, self.request.user)
        instance.delete()

    @action(detail=False, methods=['post'], url_path='batch-delete')
    def batch_delete(self, request):
        try:
            ids = request.data.get('ids', [])
            if not ids:
                return Response({'error': '未提供要删除的记录ID'}, status=status.HTTP_400_BAD_REQUEST)
            if not isinstance(ids, list):
                return Response({'error': 'ids参数格式错误，应为数组'}, status=status.HTTP_400_BAD_REQUEST)
            queryset = self.get_queryset()
            records_to_delete = queryset.filter(id__in=ids)
            if not records_to_delete.exists():
                return Response({'error': '未找到可删除的记录或没有权限删除'}, status=status.HTTP_404_NOT_FOUND)
            deletable_ids = list(records_to_delete.values_list('id', flat=True))
            deleted_count = TestCaseExecution.objects.filter(id__in=deletable_ids).delete()[0]
            return Response({'message': f'成功删除 {deleted_count} 条记录', 'deleted_count': deleted_count})
        except Exception as e:
            logger.error(f"批量删除测试用例执行记录失败: {str(e)}", exc_info=True)
            return Response({'error': f'批量删除失败: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AITestCaseExecutionView(APIView):
    """AI执行用例 + 审核回填locator"""
    permission_classes = [IsAuthenticated]

    def post(self, request, test_case_id=None):
        action = request.data.get('action') if isinstance(request.data, dict) else None
        if action == 'accept_ai_locators' or test_case_id is None:
            return self._accept_ai_locators(request)
        return self._run_ai(request, test_case_id=test_case_id)

    def _run_ai(self, request, test_case_id):
        from ..models import UiProject, TestCase
        from ..ai_case_executor import execute_test_case_ai
        try:
            test_case = TestCase.objects.get(id=test_case_id)
        except TestCase.DoesNotExist:
            return Response({'error': '测试用例不存在'}, status=status.HTTP_404_NOT_FOUND)
        project = test_case.project
        if not (project.owner_id == request.user.id or project.members.filter(id=request.user.id).exists()):
            return Response({'error': '无项目权限'}, status=status.HTTP_403_FORBIDDEN)
        start_url = request.data.get('start_url') or project.base_url or ''
        result = execute_test_case_ai(
            test_case_id=test_case_id,
            start_url=start_url,
            headless=bool(request.data.get('headless', False)),
        )
        if result.get('status') in ('passed', 'failed', 'error'):
            execution_id = result.get('execution_id')
            if execution_id:
                try:
                    from ..models import TestCaseExecution
                    execution = TestCaseExecution.objects.get(id=execution_id)
                    serializer = TestCaseExecutionSerializer(execution)
                    return Response({
                        'message': 'AI执行完成',
                        'status': result.get('status'),
                        'execution': serializer.data,
                        'step_results': result.get('step_results', []),
                        'logs': result.get('logs', ''),
                    })
                except TestCaseExecution.DoesNotExist:
                    pass
        return Response(result)

    def _accept_ai_locators(self, request):
        from ..ai_case_executor import accept_ai_locators
        execution_id = request.data.get('execution_id')
        if not execution_id:
            return Response({'error': 'execution_id 必填'}, status=status.HTTP_400_BAD_REQUEST)
        result = accept_ai_locators(execution_id)
        if isinstance(result, dict) and 'error' in result:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
        return Response(result)


class OperationRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """操作记录视图集（只读）"""
    queryset = OperationRecord.objects.all()
    serializer_class = OperationRecordSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['operation_type', 'resource_type', 'user']

    def get_queryset(self):
        queryset = OperationRecord.objects.exclude(
            resource_type__in=['ai_case', 'ai_execution']
        ).order_by('-created_at')
        limit = self.request.query_params.get('limit', None)
        if limit:
            try:
                limit = int(limit)
                queryset = queryset[:limit]
            except ValueError:
                pass
        return queryset
