"""Transactional cleanup for permissions changed by an AI UI case.

The executor keeps the cleanup plan in memory for the lifetime of one page
session.  Only changes observed as ``unauthorized -> authorized`` are added to
the plan, so a case cannot revoke a permission that existed before it started.
"""
from __future__ import annotations

from typing import Any, Dict, List


class PermissionCleanupManager:
    def __init__(self, execution_record=None):
        self.execution_record = execution_record
        self.entries: List[Dict[str, Any]] = []
        self.results: List[Dict[str, Any]] = []

    def register(self, step: Dict[str, Any], before: Dict[str, Any], after: Dict[str, Any]) -> None:
        entry = {
            'permission': str(step.get('permission_text') or step.get('permission_key') or '').strip(),
            'subject': str(step.get('subject_text') or step.get('target_text') or '').strip(),
            'before': before,
            'after': after,
            'step_description': str(step.get('display_description') or step.get('description') or ''),
            'step': {
                key: value for key, value in step.items()
                if key in {
                    'business_action', 'permission_text', 'permission_key',
                    'subject_text', 'target_text', 'permission_scope_selector',
                    'target_selector', 'grant_selector', 'revoke_selector',
                }
            },
        }
        self.entries.append(entry)
        self._log(
            f"[Permission Cleanup] 已登记回收：对象={entry['subject'] or '未指定'}，"
            f"权限={entry['permission'] or '未指定'}（本次由用例新增）"
        )

    def _log(self, message: str) -> None:
        if self.execution_record is not None:
            self.execution_record.logs += message + chr(10)

    async def cleanup(self, page, actions) -> List[Dict[str, Any]]:
        """Revoke registered changes in reverse order and verify each result."""
        self.results = []
        for index, entry in enumerate(reversed(self.entries), 1):
            step = dict(entry.get('step') or {})
            step.update({
                'business_action': 'nn_revoke_permission',
                'cleanup_entry': entry,
                'display_description': f"回收权限：{entry.get('permission') or '未指定'}",
            })
            try:
                result = await actions.revoke_permission(step)
            except Exception as exc:  # cleanup must continue to the next item
                result = {
                    'status': 'failed',
                    'error': f'回收权限异常: {str(exc)[:240]}',
                    'message': f'回收权限异常: {str(exc)[:240]}',
                }
            normalized = {
                'order': index,
                'subject': entry.get('subject', ''),
                'permission': entry.get('permission', ''),
                'status': result.get('status', 'failed'),
                'message': result.get('message', ''),
                'error': result.get('error', ''),
                'evidence': result.get('element') or result.get('evidence') or {},
            }
            self.results.append(normalized)
            if normalized['status'] == 'completed':
                self._log(
                    f"[Permission Cleanup] 回收成功：对象={normalized['subject'] or '未指定'}，"
                    f"权限={normalized['permission'] or '未指定'}"
                )
            else:
                self._log(
                    f"[Permission Cleanup] 回收失败：对象={normalized['subject'] or '未指定'}，"
                    f"权限={normalized['permission'] or '未指定'}，原因={normalized['error'] or normalized['message']}"
                )
        return self.results

    @property
    def failed(self) -> bool:
        return any(item.get('status') != 'completed' for item in self.results)

    def as_report_data(self) -> Dict[str, Any]:
        return {
            'required': bool(self.entries),
            'registered_count': len(self.entries),
            'completed_count': len([item for item in self.results if item.get('status') == 'completed']),
            'failed_count': len([item for item in self.results if item.get('status') != 'completed']),
            'results': self.results,
        }
