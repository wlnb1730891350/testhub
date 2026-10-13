import pytest

from apps.ui_automation.views import ai_recording_actions_from_execution_record


class DummyRecord:
    def __init__(self, logs='', planned_tasks=None, steps_completed=None, task_description=''):
        self.logs = logs
        self.planned_tasks = planned_tasks or []
        self.steps_completed = steps_completed or []
        self.task_description = task_description


def test_ai_recording_actions_prefer_planned_completed_tasks():
    record = DummyRecord(
        planned_tasks=[
            {'id': 1, 'description': '访问 https://test6-web.nn.com/', 'status': 'completed'},
            {'id': 2, 'description': '输入手机号 17680942927', 'status': 'completed'},
            {'id': 3, 'description': '输入验证码 8888', 'status': 'completed'},
            {'id': 4, 'description': '完成登录并断言成功', 'status': 'pending'},
        ]
    )

    actions = ai_recording_actions_from_execution_record(record)

    assert [a['action_type'] for a in actions] == ['click', 'fill', 'fill']
    assert '登录入口' in actions[0]['description'] or '默认头像' in actions[0]['description']
    assert actions[1]['input_value'] == '17680942927'
    assert actions[2]['input_value'] == '8888'
    assert all(a['locator_strategy'] for a in actions)


def test_ai_recording_actions_fallback_to_task_description_lines():
    record = DummyRecord(task_description='访问https://test6-web.nn.com/\n输入手机号17680942927\n点击登录')

    actions = ai_recording_actions_from_execution_record(record)

    assert len(actions) == 2
    assert actions[0]['action_type'] == 'fill'
    assert actions[0]['input_value'] == '17680942927'
    assert actions[1]['action_type'] == 'click'
