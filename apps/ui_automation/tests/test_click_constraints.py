import pytest

from apps.ui_automation.click_constraints import extract_click_constraints
from apps.ui_automation.views._helpers import _find_element_for_type


class _FakeConstraintLocator:
    def __init__(self):
        self.first = self

    async def count(self):
        return 1

    async def is_visible(self, timeout=2000):
        return True


class _FakeConstraintPage:
    def __init__(self):
        self.payload = None
        self.selector = None
        self.locator_obj = _FakeConstraintLocator()

    async def evaluate(self, script, payload):
        self.payload = payload
        return {
            'found': True,
            'selector': '[data-ai-automation-click-target="constraint"]',
            'detail': {
                'matchedTarget': (payload.get('target_texts') or [''])[0],
                'matchedSignals': payload.get('required_signals') or [],
                'matchedTexts': payload.get('required_texts') or [],
            },
        }

    def locator(self, selector):
        self.selector = selector
        return self.locator_obj


@pytest.mark.asyncio
async def test_find_element_for_type_uses_constraint_aware_click_scan():
    page = _FakeConstraintPage()
    step = {
        'action_type': 'click',
        'description': '点击 MacBook Pro',
        'display_description': '点击商品列表右侧的“MacBook Pro”，要求显示 512G 和 官方',
        'click_constraints': {
            'target_texts': ['MacBook Pro'],
            'required_signals': ['official'],
            'required_texts': ['512G'],
            'position_terms': ['right'],
            'context_terms': ['list', 'sidebar'],
        },
    }

    loc = await _find_element_for_type(page, step)

    assert loc is page.locator_obj
    assert page.selector == '[data-ai-automation-click-target="constraint"]'
    assert page.payload['target_texts'] == ['MacBook Pro']
    assert page.payload['required_signals'] == ['official']
    assert page.payload['required_texts'] == ['512G']
    assert page.payload['position_terms'] == ['right']
    assert page.payload['context_terms'] == ['list', 'sidebar']


def test_extract_click_constraints_uses_named_corner_quoted_card_title():
    constraints = extract_click_constraints(
        '点击主内容区存在名称为「test0915」的战队社区卡片；该卡片同时显示「LV9」「ID10079288」和在线人数。'
    )

    assert constraints['target_texts'][0] == 'test0915'
    assert 'card' in constraints['context_terms']


class _NoConstraintCandidatePage:
    def __init__(self):
        self.payload = None
        self.locator_called = False

    async def evaluate(self, script, payload):
        self.payload = payload
        return {'found': False, 'reason': 'no_constraint_candidate'}

    def locator(self, selector):
        self.locator_called = True
        raise AssertionError(f'constraint miss must not fall back to {selector}')


@pytest.mark.asyncio
async def test_find_element_for_type_rejects_generic_fallback_after_constraint_miss():
    page = _NoConstraintCandidatePage()
    step = {
        'action_type': 'click',
        'description': '点击 test0915',
        'display_description': '点击主内容区名称为「test0915」的战队社区卡片',
        'click_constraints': {
            'target_texts': ['test0915'],
            'context_terms': ['card'],
        },
    }

    assert await _find_element_for_type(page, step) is None
    assert page.payload['target_texts'] == ['test0915']
    assert page.locator_called is False
