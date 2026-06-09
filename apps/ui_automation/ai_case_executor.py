"""
AI-Driven Test Case Executor
桥接 TestCase/TestCaseStep 与 browser-use AI agent
让AI按照结构化步骤执行，用智能定位兜底，执行完录制实际操作
"""
import json
import logging
import threading
from datetime import datetime
from django.utils import timezone

logger = logging.getLogger('django')


def build_step_prompt(steps):
    """
    将 TestCaseStep 列表转换为 AI 可执行的结构化 prompt
    每个步骤包含: 动作类型、目标元素描述、输入值、断言期望
    """
    lines = ["请按以下步骤依次执行操作，每完成一步请报告结果：\n"]

    for step in steps.order_by('step_number'):
        step_num = step.step_number
        action = step.action_type
        desc = step.description or ''
        input_val = step.input_value or ''

        # 获取元素定位信息
        element_info = ''
        if step.element:
            el = step.element
            element_info = f'元素名称: {el.name}'
            if el.locator:
                element_info += f', 定位器: {el.locator}'
            if el.element_type:
                element_info += f', 类型: {el.element_type}'

        # 构建步骤描述
        if action == 'click':
            target = element_info or desc or input_val
            lines.append(f"步骤{step_num}: 点击 - {target}")

        elif action == 'fill':
            target = element_info or desc
            lines.append(f"步骤{step_num}: 在 {target} 中输入 '{input_val}'")

        elif action == 'getText':
            target = element_info or desc
            lines.append(f"步骤{step_num}: 获取 {target} 的文本内容")

        elif action == 'assert' or action == 'aiAssert':
            assert_desc = step.assert_value or desc
            lines.append(f"步骤{step_num}: 断言 - {assert_desc}")

        elif action == 'press':
            lines.append(f"步骤{step_num}: 按键 - {input_val or desc}")

        elif action == 'wait':
            wait_ms = step.wait_time or 1000
            lines.append(f"步骤{step_num}: 等待 {wait_ms}ms")

        elif action == 'hover':
            target = element_info or desc
            lines.append(f"步骤{step_num}: 悬停到 {target}")

        elif action == 'scroll':
            lines.append(f"步骤{step_num}: 滚动页面 - {desc or '向下滚动'}")

        elif action == 'switchTab':
            lines.append(f"步骤{step_num}: 切换标签页 - {desc or '切换到新标签页'}")

        else:
            lines.append(f"步骤{step_num}: {action} - {desc or input_val}")

    lines.append("\n注意事项：")
    lines.append("- 如果指定的定位器找不到元素，请智能识别页面上最可能的目标元素来完成操作")
    lines.append("- 每步操作后请截图记录当前页面状态")
    lines.append("- 如果某步骤失败，请记录失败原因并继续执行后续步骤")
    lines.append("- 所有步骤执行完毕后，请报告总体结果（通过/失败）")

    return '\n'.join(lines)


def parse_ai_result(ai_result, steps):
    """
    解析 AI agent 的执行结果，转换为结构化的步骤结果
    返回: [{step_number, status, actual_locator, screenshot, error, duration}]
    """
    step_results = []

    if not ai_result:
        return step_results

    # AI result 可能是字符串或字典
    if isinstance(ai_result, str):
        try:
            ai_result = json.loads(ai_result)
        except (json.JSONDecodeError, TypeError):
            # 纯文本结果，尝试按行解析
            return _parse_text_result(ai_result, steps)

    if isinstance(ai_result, dict):
        # 结构化结果
        completed_tasks = ai_result.get('completed_tasks', [])
        all_tasks = ai_result.get('all_tasks', ai_result.get('planned_tasks', []))

        for step in steps.order_by('step_number'):
            task_idx = step.step_number - 1
            result = {
                'step_number': step.step_number,
                'action_type': step.action_type,
                'status': 'pending',
                'actual_locator': '',
                'screenshot': '',
                'error': '',
                'duration': 0,
            }

            # 在 completed_tasks 中查找对应结果
            if task_idx < len(completed_tasks):
                task = completed_tasks[task_idx]
                result['status'] = 'passed' if task.get('status') == 'completed' else 'failed'
                result['error'] = task.get('error', '')
                result['actual_locator'] = task.get('actual_locator', '')
            elif task_idx < len(all_tasks):
                task = all_tasks[task_idx]
                status = task.get('status', 'pending')
                result['status'] = 'passed' if status == 'completed' else ('failed' if status == 'failed' else 'skipped')
                result['error'] = task.get('error', '')

            step_results.append(result)

    return step_results


def _parse_text_result(text, steps):
    """从纯文本 AI 输出中解析步骤结果"""
    step_results = []
    for step in steps.order_by('step_number'):
        result = {
            'step_number': step.step_number,
            'action_type': step.action_type,
            'status': 'pending',
            'actual_locator': '',
            'screenshot': '',
            'error': '',
            'duration': 0,
        }
        # 简单匹配: 查找 "步骤N" 相关的文本
        keyword = f"步骤{step.step_number}"
        if keyword in text:
            # 检查是否标记为完成
            if any(w in text for w in ['完成', '成功', 'passed', '✅']):
                result['status'] = 'passed'
            elif any(w in text for w in ['失败', '失败', 'failed', '❌', '错误']):
                result['status'] = 'failed'
                # 提取错误信息
                idx = text.find(keyword)
                if idx >= 0:
                    snippet = text[idx:idx+200]
                    result['error'] = snippet.split('\n')[0][:200]
        else:
            result['status'] = 'skipped'

        step_results.append(result)
    return step_results


def execute_test_case_ai(test_case_id, start_url=None, headless=False, callback=None, should_stop=None):
    """
    核心执行函数: 用 AI 执行一个 TestCase 的所有步骤
    """
    from .models import TestCase, TestCaseExecution, TestCaseStep

    test_case = TestCase.objects.get(id=test_case_id)
    steps = TestCaseStep.objects.filter(test_case=test_case)

    if not steps.exists():
        logger.warning(f"TestCase {test_case_id} 没有步骤，跳过执行")
        return {'status': 'error', 'message': '用例没有步骤'}

    # 创建执行记录
    execution = TestCaseExecution.objects.create(
        test_case=test_case,
        engine='ai',
        status='running',
        started_at=timezone.now(),
        logs=f"[{timezone.now()}] AI执行开始\n"
    )

    try:
        # 构建 prompt
        task_prompt = build_step_prompt(steps)
        logger.info(f"AI执行 prompt:\n{task_prompt}")

        # 获取项目 base_url 作为起始地址
        if not start_url and test_case.project.base_url:
            start_url = test_case.project.base_url

        if start_url:
            task_prompt = f"请先打开 {start_url}，然后按以下步骤执行：\n\n{task_prompt}"

        # 回调函数: 更新执行日志
        def step_callback(message):
            if callback:
                callback(message)
            # 追加日志
            execution.logs += f"\n[{timezone.now()}] {message}"
            execution.save(update_fields=['logs'])

        # 调用 AI agent
        from .ai_agent import run_full_process_sync

        def _run():
            return run_full_process_sync(
                task_description=task_prompt,
                step_callback=step_callback,
                should_stop=should_stop,
                enable_gif=True,
                case_name=test_case.name
            )

        # 在新线程中运行（避免阻塞）
        result_container = [None]
        error_container = [None]

        def _target():
            try:
                result_container[0] = _run()
            except Exception as e:
                error_container[0] = e
                logger.error(f"AI执行异常: {e}")

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=300)  # 5分钟超时

        if error_container[0]:
            raise error_container[0]

        ai_result = result_container[0]

        # 解析结果
        step_results = parse_ai_result(ai_result, steps)

        # 计算总体状态
        all_passed = all(r['status'] == 'passed' for r in step_results if r['status'] != 'skipped')
        any_failed = any(r['status'] == 'failed' for r in step_results)

        overall_status = 'passed' if all_passed else ('failed' if any_failed else 'error')

        # 更新执行记录
        completed_at = timezone.now()
        duration = (completed_at - execution.started_at).total_seconds()

        execution.status = overall_status
        execution.completed_at = completed_at
        execution.duration = duration
        execution.logs += f"\n[{completed_at}] AI执行完成，状态: {overall_status}"
        execution.step_results = json.dumps(step_results, ensure_ascii=False)

        # 保存截图路径
        if isinstance(ai_result, dict) and ai_result.get('gif_path'):
            execution.gif_path = ai_result['gif_path']
        if isinstance(ai_result, dict) and ai_result.get('screenshots'):
            execution.screenshots = ai_result['screenshots']

        execution.save()

        # 更新用例状态
        test_case.status = overall_status
        test_case.save(update_fields=['status'])

        logger.info(f"AI执行完成: TestCase={test_case_id}, 状态={overall_status}, 耗时={duration}s")

        return {
            'status': overall_status,
            'execution_id': execution.id,
            'step_results': step_results,
            'duration': duration,
            'logs': execution.logs,
        }

    except Exception as e:
        logger.error(f"AI执行失败: {e}", exc_info=True)
        execution.status = 'error'
        execution.completed_at = timezone.now()
        execution.duration = (execution.completed_at - execution.started_at).total_seconds()
        execution.logs += f"\n[{timezone.now()}] 执行异常: {str(e)}"
        execution.save()
        return {
            'status': 'error',
            'execution_id': execution.id,
            'message': str(e),
            'logs': execution.logs,
        }


def accept_ai_locators(execution_id):
    """
    审核通过: 将 AI 执行中实际使用的 locator 更新回 TestCaseStep
    """
    from .models import TestCaseExecution, TestCaseStep
    import json

    execution = TestCaseExecution.objects.get(id=execution_id)
    if execution.status not in ('passed', 'failed'):
        return {'error': '只能审核已完成的执行记录'}

    step_results = json.loads(execution.step_results) if hasattr(execution, 'step_results') and execution.step_results else []
    steps = TestCaseStep.objects.filter(test_case=execution.test_case).order_by('step_number')

    updated = 0
    for result in step_results:
        step_num = result.get('step_number')
        actual_locator = result.get('actual_locator', '')
        if actual_locator and step_num:
            try:
                step = steps.get(step_number=step_num)
                if step.element and actual_locator:
                    step.element.locator = actual_locator
                    step.element.save(update_fields=['locator'])
                    updated += 1
            except TestCaseStep.DoesNotExist:
                pass

    return {'updated_steps': updated, 'message': f'已更新 {updated} 个步骤的定位器'}
