from apps.app_automation.runners.uiautomator2_flow_runner import Uiautomator2FlowRunner


class _Target:
    def __init__(self, exists, on_click=None):
        self._exists = exists
        self._on_click = on_click

    def exists(self, timeout=0):
        return self._exists()

    def click(self):
        if self._on_click:
            self._on_click()


class _TeenModeDialogDevice:
    def __init__(self, show_marker=True):
        self.visible = True
        self.clicked = False
        self.show_marker = show_marker

    def __call__(self, **kwargs):
        if kwargs.get('text') == '我知道了':
            return _Target(lambda: self.visible, self._dismiss)
        if kwargs.get('textContains') == '体验青少年模式':
            return _Target(lambda: self.visible and self.show_marker)
        return _Target(lambda: False)

    def _dismiss(self):
        self.clicked = True
        self.visible = False


class _WakeableDevice:
    def __init__(self):
        self.actions = []
        self.locked = True

    def shell(self, command):
        self.actions.append(f'shell:{command}')

    def screen_on(self):
        self.actions.append('screen_on')

    def window_size(self):
        return 100, 200

    def press(self, key):
        self.actions.append(f'press:{key}')
        if key == 'home':
            self.locked = False

    def __call__(self, **kwargs):
        if kwargs.get('textContains') == '上滑解锁':
            return _Target(lambda: self.locked)
        return _Target(lambda: False)


def test_teen_mode_modal_is_dismissed_before_a_business_step():
    runner = Uiautomator2FlowRunner.__new__(Uiautomator2FlowRunner)
    runner.device = _TeenModeDialogDevice()

    assert runner._dismiss_known_blocking_dialogs() is True
    assert runner.device.clicked is True
    assert runner.device.visible is False


def test_unrelated_i_know_button_is_not_clicked():
    runner = Uiautomator2FlowRunner.__new__(Uiautomator2FlowRunner)
    runner.device = _TeenModeDialogDevice(show_marker=False)

    assert runner._dismiss_known_blocking_dialogs() is False
    assert runner.device.clicked is False


def test_device_is_woken_and_unlocked_before_running_a_case():
    runner = Uiautomator2FlowRunner.__new__(Uiautomator2FlowRunner)
    runner.device = _WakeableDevice()

    runner._prepare_device_for_run()

    assert runner.device.actions == [
        'shell:svc power stayon true',
        'shell:input keyevent 224',
        'screen_on',
        'shell:input swipe 50 168 50 48 200',
        'press:back',
        'press:home',
    ]
