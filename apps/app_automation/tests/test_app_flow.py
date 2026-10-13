# -*- coding: utf-8 -*-
"""
APP UI Flow 测试
"""
import os
import logging
import pytest
import allure
from apps.app_automation.models import AppTestCase, AppTestExecution
from apps.app_automation.services.execution_engine import create_flow_runner
from apps.app_automation.utils.report_evidence import compress_screenshot_to_gif

logger = logging.getLogger(__name__)


def _is_nonempty_file(path):
    return bool(path and os.path.isfile(path) and os.path.getsize(path) > 0)


def _attach_final_evidence(screenshot_path):
    """Attach the lossless screenshot first; GIF is only an optional preview."""
    if not _is_nonempty_file(screenshot_path):
        raise RuntimeError(f'最终状态截图未生成或为空: {screenshot_path}')

    allure.attach.file(
        screenshot_path,
        name='最终状态截图',
        attachment_type=allure.attachment_type.PNG,
    )

    preview_path = compress_screenshot_to_gif(screenshot_path)
    if preview_path != screenshot_path and _is_nonempty_file(preview_path):
        try:
            allure.attach.file(
                preview_path,
                name='最终状态预览',
                attachment_type=allure.attachment_type.GIF,
            )
        except Exception as exc:
            # The screenshot is already attached. A compact preview must never
            # make the primary visual evidence disappear.
            logger.warning('附加 APP 最终状态 GIF 预览失败: %s', exc)
    return preview_path


def _make_progress_callback(execution_id):
    """
    创建进度回调函数，在 pytest 子进程中直接更新数据库和 WebSocket。
    
    进度映射：步骤执行占整体的 10%~90%，前后留给环境准备和报告生成。
    """
    if not execution_id:
        return None
    
    def _send_ws(eid, status, progress, message):
        """发送 WebSocket 通知（失败不影响主流程）"""
        try:
            from asgiref.sync import async_to_sync
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            if channel_layer:
                async_to_sync(channel_layer.group_send)(
                    f"app_execution_{eid}",
                    {
                        "type": "execution_update",
                        "execution_id": int(eid),
                        "status": status,
                        "progress": progress,
                        "message": message,
                        "report_path": None,
                        "finished_at": None,
                    }
                )
        except Exception as e:
            logger.debug(f"WebSocket 通知失败: {e}")
    
    def callback(current_step, total_steps, step_name, status):
        """
        进度回调：每完成一个步骤更新进度。
        
        进度计算：10 + (current_step / total_steps) * 80
        即步骤全部完成时进度为 90%，留 10% 给报告生成阶段。
        """
        if total_steps <= 0:
            return
        
        # 只在步骤完成（passed/failed）时更新，running 状态不更新避免频繁写库
        if status == 'running':
            return
        
        progress = int(10 + (current_step / total_steps) * 80)
        progress = min(progress, 90)  # 上限 90%，留给报告阶段
        
        message = f"步骤 {current_step}/{total_steps}: {step_name} - {'通过' if status == 'passed' else '失败'}"
        
        try:
            AppTestExecution.objects.filter(id=execution_id).update(progress=progress)
        except Exception as e:
            logger.debug(f"更新执行进度失败: {e}")
        
        _send_ws(execution_id, 'running', progress, message)
    
    return callback


@allure.feature("APP自动化测试")
class TestAppFlow:
    """APP UI Flow 测试类"""
    @allure.story("执行UI Flow")
    def test_execute_ui_flow(self, test_case_id, package_name, execution_id, device_id, username):
        """执行 UI Flow 测试"""
        # 获取测试用例
        test_case = AppTestCase.objects.get(id=test_case_id)
        allure.dynamic.title(f"用例名称: {test_case.name}")
        allure.dynamic.suite("APP自动化测试")
        allure.dynamic.parameter("app_test_case_id", str(test_case.id))
        
        engine = os.environ.get('APP_EXECUTION_ENGINE', 'uiautomator2')
        airtest_base = None
        if engine == 'airtest':
            from apps.app_automation.utils.airtest_base import AirtestBase
            airtest_base = AirtestBase(device_id=device_id, username=username)
            assert airtest_base.setup_airtest(), 'Airtest 环境设置失败'
        runner = create_flow_runner(engine, device_id=device_id, username=username)
        
        if isinstance(test_case.ui_flow, list):
            ui_flow = test_case.ui_flow
        elif isinstance(test_case.ui_flow, dict):
            ui_flow = test_case.ui_flow.get('steps', [])
        else:
            ui_flow = []
        variables = test_case.variables or []
        
        # 创建进度回调
        progress_callback = _make_progress_callback(execution_id)
        final_evidence = None
        final_preview = None
        evidence_error = None
        final_evidence_attached = False
        
        try:
            if package_name:
                with allure.step(f"启动应用: {package_name}"):
                    if engine == 'uiautomator2':
                        runner.start_app(package_name)
                    else:
                        assert airtest_base.open_app(package_name), f"应用启动失败: {package_name}"
            else:
                allure.attach(
                    '未配置应用包名，跳过启动应用步骤',
                    name='启动应用', attachment_type=allure.attachment_type.TEXT
                )

            with allure.step("执行 UI Flow"):
                result = runner.run(
                    ui_flow=ui_flow,
                    variables=variables,
                    runtime={'stop_on_error': True},
                    progress_callback=progress_callback
                )
        finally:
            try:
                final_evidence = runner.capture_final_evidence()
                final_preview = _attach_final_evidence(final_evidence)
                final_evidence_attached = True
            except Exception as exc:
                evidence_error = exc
                # Do not delete the only source when Allure cannot receive it.
                logger.exception('生成或附加 APP 最终状态截图失败，已保留源文件: %s', exc)
            finally:
                if final_evidence_attached:
                    # Allure has copied the primary PNG into its results directory.
                    # Runtime files are safe to remove only after that succeeds.
                    for evidence_path in {final_evidence, final_preview}:
                        if evidence_path and os.path.exists(evidence_path):
                            os.remove(evidence_path)
                finish_run = getattr(runner, 'finish_run', None)
                if callable(finish_run):
                    finish_run()
            if airtest_base:
                airtest_base.teardown_airtest()
        
        # 验证结果
        with allure.step("验证执行结果"):
            assert evidence_error is None, f"未生成可用的最终状态截图: {evidence_error}"
            assert result['failed'] == 0, f"UI Flow 执行失败，失败步骤: {result['failed']}"
            assert result['passed'] > 0, "没有执行任何步骤"
        
        allure.attach(
            f"总步骤: {result['total']}\n"
            f"通过: {result['passed']}\n"
            f"失败: {result['failed']}",
            name="执行统计",
            attachment_type=allure.attachment_type.TEXT
        )
