import asyncio

from apps.ui_automation.views._helpers import _build_text_assertion_targets, _strict_text_assertion


class _FakePage:
    def __init__(self):
        self.script = ''
        self.payload = None

    async def evaluate(self, script, payload):
        self.script = script
        self.payload = payload
        return {'passed': True, 'missing': []}


def test_right_side_assertion_uses_semantic_region_and_input_placeholder_text():
    page = _FakePage()

    result = asyncio.run(
        _strict_text_assertion(
            page,
            ['我的战绩', '未输入游戏ID', '输入游戏ID'],
            '断言右侧展示「我的战绩」「未输入游戏ID」和「输入游戏ID」输入框。',
        )
    )

    assert result['passed'] is True
    assert page.payload == {
        'expected': ['我的战绩', '未输入游戏ID', '输入游戏ID'],
        'targets': [
            {'expected': '我的战绩', 'variants': [{'text': '我的战绩', 'mode': 'exact'}]},
            {'expected': '未输入游戏ID', 'variants': [{'text': '未输入游戏ID', 'mode': 'exact'}]},
            {'expected': '输入游戏ID', 'variants': [{'text': '输入游戏ID', 'mode': 'exact'}]},
        ],
        'region': 'right',
    }
    assert 'control.placeholder' in page.script
    assert "region === 'right'" in page.script


def test_unscoped_assertion_searches_all_visible_page_regions():
    page = _FakePage()

    asyncio.run(_strict_text_assertion(page, ['社区首页'], '断言页面展示「社区首页」。'))

    assert page.payload['region'] == 'all'


def test_version_like_display_suffix_adds_a_traceable_stable_alias():
    assert _build_text_assertion_targets(['战绩查询(修改后)']) == [
        {
            'expected': '战绩查询(修改后)',
            'variants': [
                {'text': '战绩查询(修改后)', 'mode': 'exact'},
                {'text': '战绩查询', 'mode': 'stable_alias'},
            ],
        }
    ]


def test_business_suffix_does_not_silently_downgrade_to_a_stable_alias():
    assert _build_text_assertion_targets(['战绩查询(正式版)']) == [
        {
            'expected': '战绩查询(正式版)',
            'variants': [{'text': '战绩查询(正式版)', 'mode': 'exact'}],
        }
    ]
