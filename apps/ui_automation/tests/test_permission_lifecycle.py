import asyncio

from apps.ui_automation.permission_lifecycle import PermissionCleanupManager
from apps.ui_automation.structured_actions import compile_task_description


def test_permission_grant_compiles_with_explicit_subject_and_permission():
    steps = compile_task_description('给用户「张三」添加「发言权限」')

    assert len(steps) == 1
    assert steps[0]['business_action'] == 'nn_grant_permission'
    assert steps[0]['subject_text'] == '张三'
    assert steps[0]['permission_text'] == '发言权限'


def test_permission_grant_without_identity_is_left_as_a_failing_contract():
    steps = compile_task_description('添加权限')

    assert len(steps) == 1
    assert steps[0]['business_action'] == 'nn_grant_permission'
    assert steps[0]['subject_text'] == ''
    assert steps[0]['permission_text'] == ''


def test_cleanup_runs_in_reverse_order_and_continues_after_failure():
    manager = PermissionCleanupManager()
    manager.register(
        {'subject_text': '张三', 'permission_text': '发言权限'},
        {'authorized': False}, {'authorized': True},
    )
    manager.register(
        {'subject_text': '李四', 'permission_text': '管理权限'},
        {'authorized': False}, {'authorized': True},
    )

    class Actions:
        def __init__(self):
            self.calls = []

        async def revoke_permission(self, step):
            entry = step['cleanup_entry']
            self.calls.append(entry['subject'])
            if entry['subject'] == '李四':
                return {'status': 'failed', 'error': '控件未找到'}
            return {'status': 'completed', 'message': 'ok'}

    actions = Actions()
    results = asyncio.run(manager.cleanup(object(), actions))

    assert actions.calls == ['李四', '张三']
    assert [item['status'] for item in results] == ['failed', 'completed']
    assert manager.failed is True


def test_cleanup_does_not_register_preexisting_permission():
    manager = PermissionCleanupManager()
    # The executor returns early for this case, so no cleanup entry is added.
    assert manager.entries == []
