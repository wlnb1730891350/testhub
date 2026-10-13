import asyncio

from apps.ui_automation.business_actions import NNPageActions, execute_business_action


class _FakeLocator:
    def __init__(self):
        self.click_calls = []
        self.first = self

    async def click(self, **kwargs):
        self.click_calls.append(kwargs)


class _FakePage:
    def __init__(self):
        self.payload = None
        self.selector = None
        self.locator_obj = _FakeLocator()

    async def evaluate(self, script, payload):
        self.payload = payload
        return {
            'found': True,
            'selector': '[data-ai-automation-click-target="demo"]',
            'detail': {
                'requiredSignals': payload['requiredSignals'],
            },
        }

    def locator(self, selector):
        self.selector = selector
        return self.locator_obj


def test_click_community_result_passes_required_signals_into_dom_scan():
    page = _FakePage()
    actions = NNPageActions(page)

    result = asyncio.run(actions.click_community_result({
        'target_text': '绝地求生',
        'required_signals': ['online_count', 'community_intro'],
    }))

    assert page.payload['targets'][0] == '绝地求生'
    assert page.payload['targets'][1].startswith(page.payload['targets'][0])
    assert len(page.payload['targets'][1]) > len(page.payload['targets'][0])
    assert page.payload['requiredSignals'] == ['online_count', 'community_intro']
    assert page.selector == '[data-ai-automation-click-target="demo"]'
    assert page.locator_obj.click_calls
    assert result['status'] == 'completed'


def test_open_top_search_executes_and_verifies_real_open_action(monkeypatch):
    captured = {}

    async def fake_top_search(self, step):
        captured.update(step)
        return {'status': 'completed', 'message': 'opened'}

    monkeypatch.setattr(NNPageActions, 'top_community_search', fake_top_search)

    result = asyncio.run(execute_business_action(object(), {'business_action': 'nn_open_top_search'}))

    assert captured['open_only'] is True
    assert result['status'] == 'completed'


def test_article_field_business_actions_dispatch_to_the_specific_field(monkeypatch):
    captured = {}

    async def fake_fill(self, step, field):
        captured['field'] = field
        captured['value'] = step['input_value']
        return {'status': 'completed'}

    monkeypatch.setattr(NNPageActions, 'fill_article_field', fake_fill)

    result = asyncio.run(execute_business_action(
        object(),
        {'business_action': 'nn_fill_article_body', 'input_value': '文章正文'},
    ))

    assert result['status'] == 'completed'
    assert captured == {'field': 'body', 'value': '文章正文'}


def test_article_editor_readiness_contract_requires_a_real_editor_state():
    source = open(
        'apps/ui_automation/business_actions.py', encoding='utf-8'
    ).read()

    assert 'editorPage&&widgets.length>0' in source
    assert 'visible.length > 0 || typePicker' not in source


def test_hall_specific_actions_are_dispatched_before_generic_click_fallback(monkeypatch):
    calls = []

    async def fake_open(self, step):
        calls.append(('open', step['business_action']))
        return {'status': 'completed'}

    async def fake_close(self, step):
        calls.append(('close', step['business_action']))
        return {'status': 'completed'}

    async def fake_notice(self, step):
        calls.append(('notice', step['business_action']))
        return {'status': 'completed'}

    monkeypatch.setattr(NNPageActions, 'open_hall_invite_share', fake_open)
    monkeypatch.setattr(NNPageActions, 'close_hall_invite_share', fake_close)
    monkeypatch.setattr(NNPageActions, 'verify_hall_retract_notice', fake_notice)

    for name in ('nn_hall_open_invite_share', 'nn_hall_close_invite_share', 'nn_hall_verify_retract_notice'):
        result = asyncio.run(execute_business_action(object(), {'business_action': name}))
        assert result['status'] == 'completed'

    assert calls == [
        ('open', 'nn_hall_open_invite_share'),
        ('close', 'nn_hall_close_invite_share'),
        ('notice', 'nn_hall_verify_retract_notice'),
    ]
