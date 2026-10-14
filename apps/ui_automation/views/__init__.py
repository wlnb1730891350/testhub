from .projects import (
    UiProjectViewSet,
    LocatorStrategyViewSet,
    ElementViewSet,
    ElementGroupViewSet,
    PageObjectViewSet,
    PageObjectElementViewSet,
)
from .scripts import (
    ScriptStepViewSet,
    ScriptElementUsageViewSet,
    TestScriptViewSet,
)
from .suites import (
    TestSuiteViewSet,
    TestExecutionViewSet,
    ScreenshotViewSet,
)
from .testcases import (
    TestCaseViewSet,
    TestCaseStepViewSet,
    TestCaseExecutionViewSet,
    OperationRecordViewSet,
    AITestCaseExecutionView,
)
from .scheduled import (
    UiScheduledTaskViewSet,
    UiNotificationLogViewSet,
    UiTaskNotificationSettingViewSet,
)
from .ai import (
    AICaseCategoryViewSet,
    DesktopAppProfileViewSet,
    AICaseViewSet,
    AIExecutionRecordViewSet,
    AIAssertionView,
)
from .misc import (
    UiDashboardViewSet,
    RecordingSessionViewSet,
    SetupTemplateViewSet,
)


def ai_recording_actions_from_execution_record(record):
    """Compatibility wrapper for tests/callers expecting module-level access."""
    viewset = AIExecutionRecordViewSet()
    return viewset._ai_recording_actions_from_execution_record(record)

__all__ = [
    'UiProjectViewSet',
    'LocatorStrategyViewSet',
    'ElementViewSet',
    'ElementGroupViewSet',
    'PageObjectViewSet',
    'PageObjectElementViewSet',
    'ScriptStepViewSet',
    'ScriptElementUsageViewSet',
    'TestScriptViewSet',
    'TestSuiteViewSet',
    'TestExecutionViewSet',
    'ScreenshotViewSet',
    'TestCaseViewSet',
    'TestCaseStepViewSet',
    'TestCaseExecutionViewSet',
    'OperationRecordViewSet',
    'AITestCaseExecutionView',
    'UiScheduledTaskViewSet',
    'UiNotificationLogViewSet',
    'UiTaskNotificationSettingViewSet',
    'AICaseCategoryViewSet',
    'DesktopAppProfileViewSet',
    'AICaseViewSet',
    'AIExecutionRecordViewSet',
    'AIAssertionView',
    'UiDashboardViewSet',
    'RecordingSessionViewSet',
    'SetupTemplateViewSet',
    'ai_recording_actions_from_execution_record',
]
