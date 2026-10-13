from types import SimpleNamespace

from django.db.utils import OperationalError

from apps.ui_automation.views import _helpers


class _FlakyExecutionRecord:
    def __init__(self):
        self.save_calls = 0

    def save(self, *, update_fields):
        self.save_calls += 1
        if self.save_calls == 1:
            raise OperationalError(2006, 'MySQL server has gone away')


def test_execution_record_save_reconnects_after_mysql_disconnect(monkeypatch):
    record = _FlakyExecutionRecord()
    closed_connections = []

    monkeypatch.setattr(_helpers, 'close_old_connections', lambda: None)
    monkeypatch.setattr(_helpers, 'connection', SimpleNamespace(close=lambda: closed_connections.append(True)))
    monkeypatch.setattr(_helpers.time, 'sleep', lambda _: None)

    _helpers._save_execution_record_with_retry(record, update_fields=['status'])

    assert record.save_calls == 2
    assert closed_connections == [True]
