from types import SimpleNamespace

import pytest

from apps.ui_automation.views import _helpers


@pytest.fixture(autouse=True)
def clear_auth_session_cache():
    with _helpers._AUTH_SESSION_CACHE_LOCK:
        _helpers._AUTH_SESSION_CACHE.clear()
        _helpers._AUTH_SESSION_LOGIN_LOCKS.clear()
    yield
    with _helpers._AUTH_SESSION_CACHE_LOCK:
        _helpers._AUTH_SESSION_CACHE.clear()
        _helpers._AUTH_SESSION_LOGIN_LOCKS.clear()


def test_auth_cache_is_scoped_to_origin_and_setup_template():
    template = SimpleNamespace(pk=7, name='NN 登录')

    test3_key = _helpers._login_session_cache_key(
        'https://test3-web.nn.com/community/7520/hall', template,
    )
    test_key = _helpers._login_session_cache_key(
        'https://test-web.nn.com/community/7520/hall', template,
    )
    other_template_key = _helpers._login_session_cache_key(
        'https://test3-web.nn.com/community/7520/hall', SimpleNamespace(pk=8, name='NN 登录'),
    )

    assert test3_key != test_key
    assert test3_key != other_template_key


def test_auth_cache_expires_and_returns_a_copy():
    state = {'cookies': [{'name': 'session', 'value': 'secret'}], 'origins': []}
    assert _helpers._store_cached_auth_state('cache-key', state, now=100)

    cached = _helpers._get_cached_auth_state('cache-key', now=101)
    cached['cookies'][0]['value'] = 'changed'
    assert _helpers._get_cached_auth_state('cache-key', now=102)['cookies'][0]['value'] == 'secret'
    assert _helpers._get_cached_auth_state(
        'cache-key', now=100 + _helpers._AUTH_SESSION_CACHE_TTL_SECONDS,
    ) is None


def test_filter_authenticated_state_keeps_only_target_auth_material():
    state = {
        'cookies': [
            {'name': 'sid', 'value': 'ok', 'domain': '.test3-web.nn.com'},
            {'name': 'other', 'value': 'no', 'domain': '.test-web.nn.com'},
        ],
        'origins': [
            {
                'origin': 'https://test3-web.nn.com',
                'localStorage': [
                    {'name': 'accessToken', 'value': 'token'},
                    {'name': 'lastUserActivityReport_10001', 'value': 'active'},
                    {'name': 'bhUserInfo', 'value': '{"id": 10001}'},
                    {'name': 'articleDraft', 'value': 'must-not-leak'},
                ],
            },
            {
                'origin': 'https://test-web.nn.com',
                'localStorage': [{'name': 'accessToken', 'value': 'other-token'}],
            },
        ],
    }

    filtered = _helpers._filter_authenticated_storage_state(state, 'https://test3-web.nn.com/community/7520/hall')

    assert filtered['cookies'] == [state['cookies'][0]]
    assert filtered['origins'] == [{
        'origin': 'https://test3-web.nn.com',
        'localStorage': [
            {'name': 'accessToken', 'value': 'token'},
            {'name': 'lastUserActivityReport_10001', 'value': 'active'},
            {'name': 'bhUserInfo', 'value': '{"id": 10001}'},
        ],
    }]


def test_login_completion_detection_only_matches_real_completion_actions():
    assert _helpers._is_login_completion_step({
        'action_type': 'business_action', 'business_action': 'nn_complete_login',
    })
    assert _helpers._is_login_completion_step({
        'action_type': 'assert', 'description': '断言已登录且登录态有效',
    })
    assert not _helpers._is_login_completion_step({
        'action_type': 'business_action', 'business_action': 'nn_fill_phone',
    })
