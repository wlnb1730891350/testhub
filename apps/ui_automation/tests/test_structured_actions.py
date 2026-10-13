import pytest

from apps.ui_automation.structured_actions import (
    compile_natural_language_line,
    compile_task_description,
    extract_assert_expected_texts,
    is_login_success_assertion,
)
from apps.ui_automation.case_normalizer import normalize_imported_case
from apps.ui_automation.views._helpers import (
    _assert_community_detail,
    _evaluate_filter_runtime_predicate,
    _evaluate_page_health,
)


def test_compile_top_navigation_community_search_to_business_action():
    step = compile_natural_language_line('在顶部导航栏中间的社区搜索框中搜索“绝地求生”')

    assert step['action_type'] == 'business_action'
    assert step['business_action'] == 'nn_top_community_search'
    assert step['input_value'] == '绝地求生'
    assert step['target_scope'] == 'top_navigation'


def test_hall_invite_and_retract_notice_compile_to_scoped_actions():
    steps = compile_task_description(
        '目标地址：https://example.com/community/1/hall\n'
        '操作步骤：\n'
        '1. 点击顶部显示“邀请/分享”的按钮。\n'
        '2. 点击邀请好友弹窗右上角的关闭图标。\n'
        '3. 验证本次撤回生成的系统提示。'
    )

    assert [step.get('business_action') for step in steps] == [
        None,
        'nn_hall_open_invite_share',
        'nn_hall_close_invite_share',
        'nn_hall_verify_retract_notice',
    ]


def test_compile_combined_top_search_click_input_and_enter_keeps_keyword():
    step = compile_natural_language_line('点击顶部搜索框，输入「自动化不存在社区987654」，按回车执行搜索。')

    assert step['action_type'] == 'business_action'
    assert step['business_action'] == 'nn_top_community_search'
    assert step['input_value'] == '自动化不存在社区987654'


def test_community_plugin_navigation_uses_a_state_convergent_action():
    steps = compile_task_description(
        '操作步骤：\n'
        '1. 依次点击「全员大厅」、「战绩查询(修改后)」、「PUBG福利商店」。\n'
        '2. 每次点击后断言对应插件处于选中状态。'
    )

    plugin_steps = [step for step in steps if step.get('business_action') == 'nn_click_community_plugin']
    assert [step['target_text'] for step in plugin_steps] == ['全员大厅', '战绩查询(修改后)', 'PUBG福利商店']


def test_article_case_does_not_execute_expected_result_prose_as_input_actions():
    steps = compile_task_description(
        '目标地址：https://example.com/community/1/plugin/communityHome\n'
        '操作步骤：\n'
        '1. 点击文章内容区上方的“发布”按钮。\n'
        '预期结果：\n'
        '1. 展示文章标题输入区域、正文编辑区域和发布操作入口。'
    )

    assert [step['business_action'] for step in steps if step.get('action_type') == 'business_action'] == [
        'nn_open_article_editor',
    ]


def test_browser_labeled_target_address_is_compiled_as_navigation():
    steps = compile_task_description(
        '\u76ee\u6807\u5730\u5740\uff1a\u6d4f\u89c8\u5668 https://test3-web.nn.com/community/7520/channel/1001091992\n'
        '\u64cd\u4f5c\u6b65\u9aa4\uff1a\n'
        '1. \u7b49\u5f85\u9875\u9762\u7a33\u5b9a'
    )

    assert steps[0]['action_type'] == 'goto'
    assert steps[0]['input_value'] == 'https://test3-web.nn.com/community/7520/channel/1001091992'
    assert not any(step.get('action_type') == 'type' and step.get('input_value') == '区域、正文编辑区域和发布操作入口。' for step in steps)


def test_article_title_and_body_in_one_sentence_compile_to_two_field_actions():
    steps = compile_task_description(
        '操作步骤：\n'
        '1. 标题输入 AUTOTEST_ART_001，正文输入“文章自动化验证内容”。'
    )

    assert [(step['business_action'], step['input_value']) for step in steps] == [
        ('nn_fill_article_title', 'AUTOTEST_ART_001'),
        ('nn_fill_article_body', '文章自动化验证内容'),
    ]


def test_article_type_conversion_prose_compiles_to_a_full_publish_and_edit_flow():
    steps = compile_task_description(
        '操作步骤：\n'
        '1. 新建并发布活动文章 AT_${timestamp()}_A。\n'
        '2. 在“发布中”打开该文章编辑界面，将发布类型从“活动”修改为“公告”，保存或重新发布。'
    )

    assert [step.get('business_action') for step in steps if step.get('business_action')] == [
        'nn_open_article_editor',
        'nn_select_article_type',
        'nn_fill_article_title',
        'nn_fill_article_body',
        'nn_submit_article',
        'nn_open_article_published_for_edit',
        'nn_select_article_type',
        'nn_submit_article',
    ]
    assert steps[2]['input_value'] == 'AT_${timestamp()}_A'
    assert steps[6]['article_type'] == '公告'


def test_article_immutable_type_assertion_is_scoped_to_the_article_editor():
    steps = compile_task_description(
        '操作步骤：\n'
        '1. 断言活动发布文章在编辑器中不可修改，且不展示“选择发布类型”。\n'
        '2. 关闭文章编辑器。'
    )

    assert [step.get('business_action') for step in steps] == [
        'nn_verify_article_type_immutable',
        'nn_close_article_editor',
    ]


def test_article_detail_precondition_adds_a_real_setup_action():
    steps = compile_task_description(
        '目标地址：https://example.com/community/1/plugin/communityHome\n'
        '前置场景：已打开一篇公开文章详情。\n'
        '操作步骤：\n'
        '1. 点击文章详情右上角的关闭按钮。'
    )

    assert [step.get('business_action') for step in steps] == [
        None,
        'nn_open_article_detail',
        'nn_close_article_detail',
    ]


def test_article_publish_type_selection_uses_a_scoped_business_action():
    step = compile_natural_language_line('在“选择发布类型”中点击“公告”。')

    assert step['business_action'] == 'nn_select_article_type'
    assert step['article_type'] == '公告'


def test_article_content_management_publish_prose_uses_the_real_toolbar_entry():
    steps = compile_task_description(
        '操作步骤：\n'
        '1. 点击“内容管理”，再点击“发布”。\n'
        '2. 在“选择发布类型”中点击“公告”。'
    )

    assert [step.get('business_action') for step in steps] == [
        'nn_open_article_editor',
        'nn_select_article_type',
    ]


def test_opening_article_detail_from_the_home_feed_is_a_real_setup_action():
    step = compile_natural_language_line('从首页打开一篇公开文章详情。')

    assert step['business_action'] == 'nn_open_article_detail'


def test_article_comment_flow_keeps_input_as_an_input_and_skips_negative_publish():
    steps = compile_task_description(
        '前置场景：已打开一篇公开文章详情。\n'
        '操作步骤：\n'
        '1. 点击评论区域“理性发言，友善互动”输入入口。\n'
        '2. 输入“文章评论输入验证”。\n'
        '3. 不点击评论发布操作。'
    )

    assert [step.get('business_action') for step in steps] == [
        'nn_open_article_detail',
        'nn_focus_article_comment',
        'nn_fill_article_comment',
    ]
    assert steps[-1]['input_value'] == '文章评论输入验证'


def test_article_draft_edit_uses_runtime_title_crud_actions():
    steps = compile_task_description(
        '操作步骤：\n'
        '1. 标题输入 AT_${timestamp()}，正文输入“编辑前内容”，点击“存草稿”。\n'
        '2. 进入“草稿箱”，定位本次唯一标题并打开编辑操作。\n'
        '3. 将标题修改为 AT_${timestamp()}_V2，并在正文末尾追加“已编辑”，点击“存草稿”。\n'
        '4. 返回草稿箱查询修改后的标题。'
    )

    assert [step.get('business_action') for step in steps] == [
        'nn_fill_article_title',
        'nn_fill_article_body',
        'nn_save_article_draft',
        'nn_open_article_draft_for_edit',
        'nn_fill_article_title',
        'nn_append_article_body',
        'nn_save_article_draft',
        'nn_open_article_management',
    ]


def test_article_draft_delete_requires_confirm_and_absence_verification():
    steps = compile_task_description(
        '操作步骤：\n'
        '1. 进入“草稿箱”，定位该唯一标题的草稿，点击删除操作。\n'
        '2. 在删除确认弹窗中确认删除。\n'
        '3. 刷新或重新进入草稿箱，查询该唯一标题。'
    )

    assert [step.get('business_action') for step in steps] == [
        'nn_delete_article_draft',
        'nn_confirm_article_draft_delete',
        'nn_verify_article_draft_absent',
    ]


def test_article_draft_management_flow_closes_the_editor_before_querying_the_draft():
    steps = compile_task_description(
        '操作步骤：\n'
        '1. 标题输入 AT_${timestamp()}，正文输入“草稿内容”，点击“存草稿”。\n'
        '2. 打开内容管理，在草稿箱中查询本次草稿。'
    )

    assert [step.get('business_action') for step in steps] == [
        'nn_fill_article_title',
        'nn_fill_article_body',
        'nn_save_article_draft',
        'nn_open_article_management',
    ]


def test_compile_recruitment_submit_to_a_dialog_scoped_business_action():
    step = compile_natural_language_line('点击「确定发布」。')

    assert step['action_type'] == 'business_action'
    assert step['business_action'] == 'nn_submit_recruitment'


def test_compile_recruitment_entry_to_a_dialog_scoped_business_action():
    step = compile_natural_language_line('点击「招募队友」')

    assert step['action_type'] == 'business_action'
    assert step['business_action'] == 'nn_open_recruitment'


def test_compile_top_search_overlay_assertion_not_community_detail():
    step = compile_natural_language_line('断言搜索框获得焦点，页面展示「开放的游戏官方社区」以及存在多个社区')

    assert step['assert_type'] == 'top_search_overlay'
    assert step['expected_texts'] == ['开放的游戏官方社区']
    assert step['require_multiple_results'] is True


def test_compile_search_history_overlay_requires_a_real_history_state():
    step = compile_task_description(
        '\u65ad\u8a00\u9876\u90e8\u641c\u7d22\u6846\u5c55\u793a\u641c\u7d22\u5386\u53f2\u8bb0\u5f55\u4ee5\u53ca\u6e05\u7a7a\u5165\u53e3\u3002'
    )[0]

    assert step['assertion_contract']['kind'] == 'search_overlay'
    assert step['assertion_contract']['require_history'] is True


def test_compile_clicked_community_identity_assertion():
    step = compile_natural_language_line(
        '断言进入的社区页展示与被点击卡片一致的社区名称和社区 ID，且未进入其他同名或相似名称社区。'
    )

    assert step['assert_type'] == 'clicked_community_identity'


def test_assertions_compile_to_data_driven_contracts():
    steps = compile_task_description(
        '断言搜索框获得焦点，页面展示「开放的游戏官方社区」以及存在多个社区\n'
        '断言进入的社区页展示与被点击卡片一致的社区名称和社区 ID'
    )

    assert steps[0]['assertion_contract'] == {
        'kind': 'search_overlay',
        'expected_texts': ['开放的游戏官方社区'],
        'min_results': 2,
    }
    assert steps[1]['assertion_contract']['kind'] == 'referenced_identity'


def test_composite_assertion_contract_handles_selected_text_and_card_count():
    steps = compile_task_description(
        '断言左侧「旗下社区」处于选中状态，主内容区展示「旗下社区」和「创建战队社区」按钮。\n'
        '断言主内容区至少展示三张战队社区卡片。'
    )

    first = steps[0]['assertion_contract']
    second = steps[1]['assertion_contract']
    assert first['kind'] == 'composite'
    assert first['predicates'][0] == {'kind': 'selected', 'target': '旗下社区', 'scope': 'left'}
    assert first['predicates'][1]['kind'] == 'text_presence'
    assert second == {'kind': 'composite', 'predicates': [{'kind': 'min_visible_cards', 'minimum': 3, 'scope': 'main'}]}


def test_card_collection_assertions_never_fall_back_to_sentence_text():
    steps = compile_task_description(
        '断言每张可见战队社区卡片展示社区头像、社区名称、社区 ID 和“在线”人数。\n'
        '断言社区简介存在时显示在对应卡片内，不与其他卡片内容串位。'
    )

    assert steps[0]['assertion_contract'] == {
        'kind': 'composite',
        'predicates': [{'kind': 'card_fields', 'fields': ['avatar', 'name', 'id', 'online'], 'scope': 'main'}],
    }
    assert steps[1]['assertion_contract'] == {
        'kind': 'composite',
        'predicates': [{'kind': 'card_field_association', 'field': 'intro', 'scope': 'main', 'optional': True}],
    }


def test_card_listing_absence_is_not_dropped_from_a_navigation_assertion():
    step = compile_task_description(
        '断言社区头部展示 ID「10079288」，左侧社区名称展示「test0915」，且不再显示旗下社区卡片列表。'
    )[0]

    predicates = step['assertion_contract']['predicates']
    assert {'kind': 'card_collection_absence', 'scope': 'main'} in predicates
    assert {'kind': 'text_presence', 'expected_texts': ['10079288', 'test0915'], 'scope': 'all'} in predicates


def test_voice_room_assertions_compile_to_a_semantic_plan_not_prose_text_lookup():
    steps = compile_task_description(
        '断言页面展示多个语音房条目。\n'
        '断言每个可见语音房展示房间序号、房间名称和人数容量信息。\n'
        '断言语音房底部展示「游戏语音房」「娱乐活动」「互动语音」等名称，长名称不覆盖人数或操作图标。'
    )

    assert steps[0]['assertion_contract']['kind'] == 'assertion_plan'
    assert steps[0]['assertion_contract']['predicates'] == [
        {'kind': 'collection_count', 'minimum': 2, 'scope': 'all', 'hints': ['room-item', 'room']},
    ]
    assert steps[1]['assertion_contract']['predicates'] == [
        {'kind': 'collection_item_fields', 'fields': ['number', 'name', 'capacity'], 'scope': 'all', 'hints': ['room-item', 'room']},
    ]
    assert [item['kind'] for item in steps[2]['assertion_contract']['predicates']] == [
        'layout_no_overlap', 'text_group_presence',
    ]


def test_faq_answer_assertion_uses_its_own_question_rows():
    step = compile_task_description(
        '\u65ad\u8a00\u6bcf\u4e2a\u53ef\u89c1\u95ee\u9898\u5747\u5c55\u793a\u5bf9\u5e94\u8bf4\u660e\u6587\u672c\u3002'
    )[0]

    assert step['assertion_contract'] == {
        'kind': 'assertion_plan',
        'predicates': [{'kind': 'faq_item_descriptions', 'scope': 'all'}],
    }


def test_unsupported_assertion_uses_ai_semantic_fallback_not_prose_text_lookup():
    step = compile_task_description('断言页面整体氛围专业且信息层级清晰。')[0]

    assert step['assertion_contract']['kind'] == 'ai_semantic'


def test_page_contracts_compile_url_and_negative_visibility_without_sentence_matching():
    steps = compile_task_description(
        '断言已跳转至 https://example.com/community/7520 。\n'
        '断言“登录弹窗”不存在。'
    )

    assert steps[0]['assertion_contract']['predicates'] == [
        {'kind': 'url_contains', 'value': 'https://example.com/community/7520'},
    ]
    assert steps[1]['assertion_contract']['predicates'] == [
        {'kind': 'text_absence', 'expected_texts': ['登录弹窗'], 'scope': 'all'},
    ]


def test_state_assertions_compile_modal_input_filter_and_direct_identity():
    steps = compile_task_description(
        '断言弹窗保持打开。\n'
        '断言输入计数显示 `15/15`。\n'
        '断言内容不超过 15 个字符或展示明确的超长限制提示。\n'
        '断言筛选结果恢复为当前分类的房间列表或空状态，且不残留刚才的关键词。\n'
        '断言成功进入 ID 为 10079288、名为 test0915 的社区页面，页面展示战队介绍和语音房间。'
    )

    assert steps[0]['assertion_contract']['predicates'] == [{'kind': 'modal_visible'}]
    assert steps[1]['assertion_contract']['predicates'] == [
        {'kind': 'input_counter', 'current': 15, 'maximum': 15},
    ]
    assert steps[2]['assertion_contract']['predicates'] == [
        {'kind': 'input_max_length', 'maximum': 15},
    ]
    assert steps[3]['assertion_contract']['predicates'] == [
        {'kind': 'filter_reset_state', 'require_collection_or_empty': True},
    ]
    assert steps[4]['assertion_contract']['predicates'][0]['kind'] == 'entity_identity'


def test_rich_card_metadata_assertion_compiles_to_a_reusable_card_predicate():
    step = compile_task_description(
        '断言卡片展示标题，以及发布时间、作者/来源、内容摘要、标签、评论数中的至少两类信息。'
    )[0]

    assert step['assertion_contract'] == {
        'kind': 'composite',
        'predicates': [{
            'kind': 'card_metadata',
            'fields': ['time', 'author', 'summary', 'tag', 'comments'],
            'minimum': 2,
            'scope': 'main',
        }],
    }


def test_compound_case_line_keeps_navigation_and_all_following_clicks():
    steps = compile_task_description(
        '访问 https://example.com/community/1，点击「旗下社区」，点击名称为「test0915」、ID 为「10079288」且显示“在线”人数的卡片，点击「招募队友」。'
    )

    assert [step['action_type'] for step in steps] == ['goto', 'click', 'business_action', 'business_action']
    assert steps[0]['input_value'] == 'https://example.com/community/1'
    assert steps[2]['business_action'] == 'nn_click_identity_card'
    assert steps[-1]['business_action'] == 'nn_open_recruitment'


def test_non_selection_context_does_not_turn_submit_click_into_checkbox_action():
    step = compile_task_description('不选择区服且不填写招募队友信息，点击「确定发布」。')[0]

    assert step['action_type'] == 'business_action'
    assert step['business_action'] == 'nn_submit_recruitment'


def test_required_form_error_compiles_to_error_state_not_field_text_presence():
    step = compile_task_description(
        '断言表单未发布成功，且「选择区服」或「招募队友信息」显示必填校验提示或错误状态。'
    )[0]

    assert step['assertion_contract']['kind'] == 'assertion_plan'
    assert step['assertion_contract']['predicates'] == [{
        'kind': 'form_validation_error',
        'fields': ['选择区服', '招募队友信息'],
        'match_mode': 'any',
    }]


def test_empty_state_assertion_requires_an_empty_state_predicate():
    step = compile_task_description('断言筛选结果展示空状态。')[0]

    assert step['assertion_contract']['kind'] == 'assertion_plan'
    assert step['assertion_contract']['predicates'] == [{'kind': 'empty_state', 'scope': 'main'}]


def test_page_health_assertion_does_not_become_a_login_assertion():
    step = compile_task_description('断言页面无白屏、404、登录页或脚本异常提示。')[0]

    assert step['action_type'] == 'assert'
    assert step['assert_type'] == 'page_health'
    assert step['assertion_contract'] == {'kind': 'page_health'}


def test_literal_hall_member_search_and_result_assertions_use_scoped_actions():
    steps = compile_task_description(
        '目标地址：https://test3-web.nn.com/community/7520/hall\n'
        '在“搜索成员”输入框输入 高管。\n'
        '断言右侧成员搜索框当前值为 高管。\n'
        '断言右侧成员列表至少展示 1 个昵称包含 高管 的成员条目。\n'
        '断言每个可见搜索结果昵称包含 高管，不展示无关成员。'
    )

    assert [step.get('business_action') for step in steps if step.get('business_action')] == [
        'nn_hall_search_member',
        'nn_hall_verify_member_search',
        'nn_hall_verify_member_search',
        'nn_hall_verify_member_search',
    ]
    assert next(step for step in steps if step.get('business_action') == 'nn_hall_search_member')['input_value'] == '高管'


def test_hall_member_empty_search_compiles_empty_state_and_restore_contracts():
    steps = compile_task_description(
        '目标地址：https://test3-web.nn.com/community/7520/hall\n'
        '操作步骤：\n'
        '1. 在“搜索成员”输入框输入 NO_MEMBER_${timestamp()}。\n'
        '2. 断言右侧成员列表显示无结果状态，且不继续显示输入前的成员条目。\n'
        '3. 清空“搜索成员”输入框。\n'
        '4. 断言右侧成员列表恢复显示至少 3 个成员条目。\n'
        '预期结果：\n'
        '1. 断言无结果状态仅位于右侧成员列表区域，不遮挡中央消息流、顶部导航或底部输入区。'
    )

    actions = [step for step in steps if step.get('business_action')]
    assert [step['business_action'] for step in actions] == [
        'nn_hall_search_member',
        'nn_hall_verify_member_search',
        'nn_hall_clear_member_search',
        'nn_hall_verify_member_search',
        'nn_hall_verify_member_empty_state_layout',
    ]
    assert actions[3]['min_count'] == 3


def test_hall_channel_shell_assertion_uses_the_direct_channel_layout_action():
    steps = compile_task_description(
        '目标地址：https://test3-web.nn.com/community/7520/channel/1001091992\n'
        '断言当前语音房展示人数/容量状态，且页面左下角当前账号头像、麦克风和耳机控制同时可见。'
    )

    assert [step.get('business_action') for step in steps if step.get('business_action')] == [
        'nn_hall_verify_channel_controls',
    ]


def test_login_words_do_not_implicitly_mean_login_success():
    assert is_login_success_assertion('断言浏览器处于未登录状态') is False
    assert is_login_success_assertion('断言页面弹出登录入口或跳转到登录流程') is False
    assert is_login_success_assertion('断言登录按钮进入处理中状态且不会重复提交') is False
    assert is_login_success_assertion('断言地址保持不变，未跳转登录页') is False
    assert is_login_success_assertion('断言登录成功后返回目标页面') is True


def test_login_form_fill_accepts_field_first_natural_wording():
    phone = compile_natural_language_line('在登录弹窗手机号输入框填写17680942927')
    code = compile_natural_language_line('在验证码输入框填写8888')

    assert phone['business_action'] == 'nn_fill_phone'
    assert phone['input_value'] == '17680942927'
    assert code['business_action'] == 'nn_fill_verification_code'
    assert code['input_value'] == '8888'


def test_case_metadata_and_preconditions_are_not_executed_as_steps():
    steps = compile_task_description(
        '目标地址：https://test-web.nn.com/community/7520/plugin/zhanji\n'
        '前置条件：浏览器处于未登录状态；测试环境验证码固定为8888\n'
        '操作步骤：\n'
        '1. 访问https://test-web.nn.com/community/7520/plugin/zhanji\n'
        '预期结果：\n'
        '1. 断言页面弹出登录入口或跳转到登录流程'
    )

    assert [step['action_type'] for step in steps] == ['goto', 'assert']
    assert not any('前置条件' in step['description'] for step in steps)


def test_login_flow_assertions_compile_by_semantics_not_fixed_sentence_format():
    steps = compile_task_description(
        '1. 断言页面弹出登录入口或跳转到登录流程\n'
        '2. 断言手机号输入框显示17680942927\n'
        '3. 断言验证码输入框显示4位内容\n'
        '4. 断言登录按钮进入处理中状态且不会重复提交\n'
        '5. 断言登录成功后返回/community/7520/plugin/zhanji，页面显示战绩插件主内容'
    )

    assert steps[0]['assertion_contract']['predicates'][0]['kind'] == 'login_prompt_visible'
    assert steps[1]['assertion_contract']['predicates'] == [{
        'kind': 'input_value', 'field': 'phone', 'value': '17680942927',
    }]
    assert steps[2]['assertion_contract']['predicates'] == [{
        'kind': 'input_length', 'field': 'verification_code', 'length': 4,
    }]
    assert steps[3]['assertion_contract']['predicates'] == [{
        'kind': 'control_busy', 'target': '登录',
    }]
    final_predicates = steps[4]['assertion_contract']['predicates']
    assert {'kind': 'login_state'} in final_predicates
    assert {'kind': 'url_contains', 'value': '/community/7520/plugin/zhanji'} in final_predicates
    assert {'kind': 'page_feature', 'feature': '战绩插件主内容', 'terms': ['战绩']} in final_predicates


def test_login_interception_assertions_compile_without_review_required():
    steps = compile_task_description(
        '断言页面可展示社区公共内容，但需要账号身份的查询操作不可直接返回私有数据\n'
        '断言页面唤起登录流程，不显示玩家查询结果弹窗\n'
        '断言登录成功后仍停留或返回战绩插件页面，可重新发起查询'
    )

    assert all(step['assertion_contract']['kind'] == 'assertion_plan' for step in steps)
    assert all(step['assertion_contract'].get('predicates') for step in steps)
    assert not any(step['assertion_contract']['kind'] == 'review_required' for step in steps)


def test_named_input_with_enter_and_compound_login_expand_to_real_actions():
    steps = compile_task_description(
        '1. 在“查询玩家战绩”输入框填写test并按Enter\n'
        '2. 完成账号17680942927、验证码8888登录'
    )

    assert [step['action_type'] for step in steps] == [
        'business_action', 'business_action', 'business_action', 'business_action',
    ]
    assert steps[0]['business_action'] == 'nn_query_battle_records'
    assert steps[0]['input_value'] == 'test'
    assert [step.get('business_action') for step in steps[1:]] == [
        'nn_fill_phone', 'nn_fill_verification_code', 'nn_complete_login',
    ]


def test_page_title_and_relative_url_assertions_use_browser_state():
    steps = compile_task_description(
        '断言页面标题为 NN.COM，与神队友一起游戏 - NN官方网站，无白屏、404或脚本错误遮罩。\n'
        '断言地址保持为 /community/7520/plugin/zhanji，未跳转登录页。'
    )

    assert {'kind': 'page_title', 'value': 'NN.COM，与神队友一起游戏 - NN官方网站'} in steps[0]['assertion_contract']['predicates']
    assert {'kind': 'page_health'} in steps[0]['assertion_contract']['predicates']
    assert {'kind': 'url_contains', 'value': '/community/7520/plugin/zhanji'} in steps[1]['assertion_contract']['predicates']
    assert {'kind': 'url_not_auth'} in steps[1]['assertion_contract']['predicates']


def test_dialog_title_is_not_compiled_as_browser_page_title():
    steps = compile_task_description(
        '\u65ad\u8a00\u5c55\u793a\u6807\u9898\u4e3a\u300c\u53d1\u5e03\u62db\u52df\u4fe1\u606f\u300d\u7684\u5f39\u7a97\u3002'
    )

    predicates = steps[0]['assertion_contract']['predicates']
    assert {'kind': 'text_presence', 'expected_texts': ['发布招募信息'], 'scope': 'all'} in predicates
    assert not any(predicate['kind'] == 'page_title' for predicate in predicates)


def test_character_count_instructions_use_real_test_characters_before_asserting_limit():
    steps = compile_task_description(
        '输入 15 个字符。\n'
        '继续输入第 16 个字符，断言内容不超过 15 个字符。'
    )

    assert steps[0]['input_value'] == '测' * 15
    assert steps[1]['input_value'] == '测' * 16
    assert steps[2]['action_type'] == 'assert'


def test_compile_community_result_click_preserves_entity_type():
    step = compile_natural_language_line('点击搜索结果中的绝地求生社区')

    assert step['action_type'] == 'business_action'
    assert step['business_action'] == 'nn_click_community_result'
    assert step['target_text'] == '绝地求生'
    assert step['entity_type'] == 'community'


def test_compile_community_result_click_preserves_required_signals():
    step = compile_natural_language_line('点击社区搜索结果下的“绝地求生社区”，必须满足两个条件：有在线人数数和社区简介')

    assert step['action_type'] == 'business_action'
    assert step['business_action'] == 'nn_click_community_result'
    assert step['target_text'] == '绝地求生'
    assert step['required_signals'] == ['online_count', 'community_intro']
    assert step['display_description'] == '点击社区搜索结果下的“绝地求生社区”，必须满足两个条件：有在线人数数和社区简介'


def test_compile_generic_click_preserves_original_constraints():
    step = compile_natural_language_line('点击商品列表右侧的“MacBook Pro”，要求显示 512G 和 官方')

    assert step['action_type'] == 'click'
    assert step['description'] == '点击 MacBook Pro'
    assert step['display_description'] == '点击商品列表右侧的“MacBook Pro”，要求显示 512G 和 官方'
    assert step['click_constraints']['target_texts'][0] == 'MacBook Pro'
    assert step['click_constraints']['context_terms'] == ['list', 'sidebar']
    assert step['click_constraints']['position_terms'] == ['right']
    assert step['click_constraints']['required_signals'] == ['official']
    assert step['click_constraints']['required_texts'] == ['512G']


def test_compile_page_state_description_as_assertion_not_community_click():
    step = compile_natural_language_line(
        '已进入「旗下社区」页面：左侧导航中的「旗下社区」处于选中状态；主内容区至少展示 3 张战队社区卡片'
    )

    assert step['action_type'] == 'assert'
    assert step['assert_type'] == 'text_contains'


def test_compile_login_entry_and_submit_to_separate_business_actions():
    open_step = compile_natural_language_line('点击登录入口打开登录弹窗')
    submit_step = compile_natural_language_line('点击登录/注册  按钮')

    assert open_step['business_action'] == 'nn_open_login'
    assert submit_step['business_action'] == 'nn_complete_login'


def test_compile_task_description_keeps_current_case_order_without_bogus_button_suffix():
    task = '\n'.join([
        '访问 https://test6-web.nn.com/',
        '点击登录/注册  按钮',
        '在顶部导航栏中间的社区搜索框中搜索“绝地求生”',
        '点击搜索结果中的绝地求生社区',
        '断言页面包含“绝地求生”和“PUBG中国官方社区”',
    ])
    steps = compile_task_description(task)

    descriptions = [s['description'] for s in steps]
    assert not any(desc == '点击 钮' for desc in descriptions)
    assert [s['action_type'] for s in steps] == ['goto', 'business_action', 'business_action', 'business_action', 'assert']
    assert steps[-1]['assert_type'] == 'community_detail'
    assert steps[-1]['target_text'] == '绝地求生'


def test_compile_task_description_ignores_markdown_case_heading():
    steps = compile_task_description(
        '### COM-010 按完整身份进入搜索结果社区\n'
        '1. 访问 https://test6-web.nn.com/community/7520/plugin/communityHome 。\n'
        '2. 点击顶部搜索框，输入「PUBG」，按回车执行搜索。'
    )

    assert [step['action_type'] for step in steps] == ['goto', 'business_action']
    assert not any('COM-010' in step['description'] for step in steps)


def test_assert_text_extraction_splits_chinese_connectors_and_plus():
    assert extract_assert_expected_texts('断言左侧页面能找到绝地求生+pubg中国官方社区字样') == ['绝地求生', 'pubg中国官方社区']
    assert extract_assert_expected_texts('断言页面包含“绝地求生”和“PUBG中国官方社区”') == ['绝地求生', 'PUBG中国官方社区']


def test_assert_text_extraction_prioritizes_all_quoted_targets():
    assert extract_assert_expected_texts(
        '断言右侧展示「我的战绩」「未输入游戏ID」和「输入游戏ID」输入框'
    ) == ['我的战绩', '未输入游戏ID', '输入游戏ID']


def test_assert_text_extraction_expands_composed_rank_title_and_period():
    assert extract_assert_expected_texts('断言右侧展示标题「吃鸡日榜」') == ['吃鸡榜', '日榜']


def test_compile_disabled_button_assertion_as_state_assertion():
    step = compile_natural_language_line('不输入游戏 ID，断言「战绩授权」按钮不可用')

    assert step['action_type'] == 'assert'
    assert step['assert_type'] == 'disabled'
    assert step['target_text'] == '战绩授权'


def test_compile_identity_card_click_preserves_name_id_and_online_constraints():
    step = compile_natural_language_line(
        '点击名称为「test0915」、ID 为「10079288」且显示“在线”人数的卡片。'
    )

    assert step['business_action'] == 'nn_click_identity_card'
    assert step['target_text'] == 'test0915'
    assert step['expected_id'] == '10079288'
    assert step['require_online'] is True


def test_game_id_value_assertion_compiles_to_control_value_contract():
    step = compile_task_description('断言“输入游戏ID”输入框值为「PUBGID123」')[0]

    assert step['assertion_contract']['kind'] == 'assertion_plan'
    assert step['assertion_contract']['predicates'] == [{
        'kind': 'input_value', 'field': 'game_id', 'value': 'PUBGID123',
    }]


def test_search_section_empty_state_stays_scoped_to_the_named_section():
    step = compile_task_description(
        '断言「搜索的用户」区域也展示 0 条结果的空状态。'
    )[0]

    assert {'kind': 'search_empty_state', 'section_label': '搜索的用户'} in step['assertion_contract']['predicates']


def test_compile_generic_search_keeps_press_enter_for_compatibility():
    steps = compile_task_description('搜索 绝地求生')

    assert [s['action_type'] for s in steps] == ['type', 'press']
    assert steps[0]['input_value'] == '绝地求生'
    assert steps[1]['input_value'] == 'Enter'


def test_normalize_imported_case_makes_page_only_scenario_runnable():
    normalized = normalize_imported_case(
        '目标地址：https://test-web.nn.com/community/7520/plugin/zhanji\n'
        '前置条件：测试代理返回 HTTP 500\n'
        '操作步骤：\n'
        '1. 查看主内容区\n'
        '预期结果：\n'
        '1. 页面显示失败提示'
    )

    assert normalized.requires_controlled_environment is True
    assert '1. 访问 https://test-web.nn.com/community/7520/plugin/zhanji' in normalized.task_description
    assert '2. 等待页面就绪' in normalized.task_description
    assert '1. 断言页面显示失败提示' in normalized.task_description
    assert [step['action_type'] for step in compile_task_description(normalized.task_description)] == ['goto', 'wait', 'assert']


def test_unstructured_assertion_uses_ai_semantic_fallback_instead_of_review():
    step = compile_task_description('断言比赛列表加载完成')[0]

    assert step['assertion_contract']['kind'] == 'ai_semantic'


def test_page_state_operations_compile_to_runtime_actions():
    steps = compile_task_description('\n'.join([
        '访问战绩插件页面',
        '等待初始化请求失败',
        '刷新战绩插件页面',
        '切换到1366×768',
    ]))

    assert [step['action_type'] for step in steps] == ['wait', 'wait', 'reload', 'set_viewport']
    assert steps[-1]['viewport'] == {'width': 1366, 'height': 768}


def test_enter_instruction_compiles_to_keyboard_press_not_click():
    step = compile_task_description('按 Enter 发起查询')[0]

    assert step['action_type'] == 'press'
    assert step['input_value'] == 'Enter'


def test_compile_rapid_result_filter_case_to_executable_actions_and_contracts():
    steps = compile_task_description('\n'.join([
        '目标地址：https://test-web.nn.com/community/7520/plugin/zhanji',
        '前置条件：玩家PUBG_UI_FULL_01有完整筛选数据；查询结果弹窗已打开',
        '操作步骤：',
        '1. 查询玩家PUBG_UI_FULL_01',
        '2. 在5秒内依次切换普通、FPP、冠军、竞技、TPP、全部比赛',
        '3. 观察加载状态',
        '4. 统计结果弹窗数量',
        '5. 等待全部请求结束',
        '预期结果：',
        '1. 断言每次操作均更新对应筛选值，页面不跳转',
        '2. 断言加载状态只出现在当前结果区域，不出现全屏白屏或布局剧烈抖动',
        '3. 断言DOM中仅存在1个“查询结果”弹窗',
        '4. 断言最终筛选为竞技、TPP、全部比赛，列表只展示最终条件数据且无重复卡片',
    ]))

    assert [step['action_type'] for step in steps] == [
        'goto', 'business_action', 'business_action', 'business_action', 'assert', 'assert', 'assert', 'assert',
    ]
    assert steps[1]['business_action'] == 'nn_query_battle_records'
    assert steps[1]['player_name'] == 'PUBG_UI_FULL_01'
    switch = steps[2]
    assert switch['business_action'] == 'nn_rapid_filter_switch'
    assert switch['filter_values'] == ['普通', 'FPP', '冠军', '竞技', 'TPP', '全部比赛']
    assert switch['time_budget_seconds'] == 5
    assert steps[3]['business_action'] == 'nn_wait_for_results_idle'

    contracts = [step['assertion_contract'] for step in steps if step['action_type'] == 'assert']
    assert {'kind': 'rapid_filter_switch'} in contracts[0]['predicates']
    assert {'kind': 'loading_scope', 'scope': 'result'} in contracts[1]['predicates']
    assert {'kind': 'modal_count', 'target': '查询结果', 'expected_count': 1} in contracts[2]['predicates']
    assert {
        'kind': 'filter_result_consistency',
        'expected_filters': ['竞技', 'TPP', '全部比赛'],
        'require_unique_cards': True,
    } in contracts[3]['predicates']


def test_rapid_filter_assertions_use_business_action_evidence_not_prose_text():
    evidence = {
        'business_actions': [{
            'name': 'nn_rapid_filter_switch',
            'status': 'completed',
            'result': {'element': {'detail': {
                'missing': [],
                'allSelected': True,
                'withinBudget': True,
                'pathUnchanged': True,
                'loadingEvents': [{'target': '竞技', 'count': 1, 'globalCount': 0}],
                'finalLoading': {'count': 0, 'globalCount': 0},
                'layoutJankObserved': False,
            }}},
        }],
    }

    assert _evaluate_filter_runtime_predicate({'kind': 'rapid_filter_switch'}, evidence)['passed'] is True
    assert _evaluate_filter_runtime_predicate({'kind': 'loading_scope', 'scope': 'result'}, evidence)['passed'] is True


def test_login_case_skips_login_setup_template_to_avoid_double_login():
    from apps.ui_automation.structured_actions import should_skip_setup_template

    case_desc = '\n'.join([
        '访问 https://test6-web.nn.com/',
        '点击登录入口打开登录弹窗',
        '输入手机号 [REDACTED]',
        '输入验证码 [REDACTED]',
        '点击登录/注册  按钮',
        '断言是否成功登录',
    ])
    template_steps = [
        {'description': '点击登录入口打开登录弹窗'},
        {'description': '输入手机号 [REDACTED]'},
        {'description': '点击登录/注册  按钮'},
    ]

    assert should_skip_setup_template(case_desc, template_steps, '登录NN测试环境') is True
    assert should_skip_setup_template('点击搜索结果中的绝地求生社区', template_steps, '登录NN测试环境') is False
    assert should_skip_setup_template(
        '前置条件：浏览器未登录\n完成账号17680942927、验证码8888登录',
        template_steps,
        '登录NN测试环境',
    ) is True


def test_compile_community_detail_assertion_to_specialized_assert():
    step = compile_natural_language_line('断言已进入“绝地求生”目标社区详情页，且左侧社区面板显示 PUBG中国官方社区')

    assert step['action_type'] == 'assert'
    assert step['assert_type'] == 'community_detail'
    assert step['target_text'] == '绝地求生'

def test_compile_community_result_click_with_right_side_card_wording():
    step = compile_natural_language_line('点击右侧搜索结果卡片中的“绝地求生”社区')

    assert step['action_type'] == 'business_action'
    assert step['business_action'] == 'nn_click_community_result'
    assert step['target_text'] == '绝地求生'
    assert step['entity_type'] == 'community'


@pytest.mark.asyncio
async def test_evaluate_page_health_detects_browser_too_old_fallback():
    class FakePage:
        async def evaluate(self, script):
            return {
                'healthy': False,
                'reason': '页面命中“浏览器版本过低”兼容性降级页',
                'evidence': {'title': 'NN.COM', 'bodyText': '浏览器版本过低'}
            }

    result = await _evaluate_page_health(FakePage())
    assert result['healthy'] is False
    assert '浏览器版本过低' in result['reason']


@pytest.mark.asyncio
async def test_evaluate_page_health_detects_empty_unmounted_app():
    class FakePage:
        async def evaluate(self, script):
            return {
                'healthy': False,
                'reason': '#app 存在但未挂载内容，疑似前端资源/脚本未正常初始化',
                'evidence': {'appExists': True, 'appMounted': False, 'bodyText': ''}
            }

    result = await _evaluate_page_health(FakePage())
    assert result['healthy'] is False
    assert '#app' in result['reason']


@pytest.mark.asyncio
async def test_assert_community_detail_accepts_title_and_official_without_hall_candidate():
    class FakePage:
        async def evaluate(self, script, target):
            assert target == '绝地求生'
            return {
                'passed': False,
                'target': target,
                'url': 'https://test6-web.nn.com/community/7520/plugin/articleDetail/49400',
                'titleCandidate': {'text': '绝地求生 99+', 'cls': 'title', 'rect': {'x': 74, 'y': 248, 'w': 276, 'h': 38}, 'tag': 'div'},
                'officialCandidate': {'text': 'PUBG中国官方社区', 'cls': 'official', 'rect': {'x': 102, 'y': 213, 'w': 105, 'h': 18}, 'tag': 'span'},
                'communityHallCandidate': None,
                'sampleTitles': [{'text': '绝地求生', 'rect': {'x': 112, 'y': 255, 'w': 72, 'h': 24}, 'cls': 'title-text'}],
                'sampleOfficials': [{'text': 'PUBG中国官方社区', 'rect': {'x': 102, 'y': 213, 'w': 105, 'h': 18}, 'cls': 'official-text'}],
                'sampleHalls': [],
                'bodyText': '10 PUBG中国官方社区 82在线 绝地求生 99+ PUBG福利商店 成员大厅 99+'
            }

    result = await _assert_community_detail(FakePage(), '绝地求生')
    assert result['passed'] is True
    assert result['signals']['hasTitleSignal'] is True
    assert result['signals']['hasOfficialSignal'] is True
    assert result['signals']['hasHallSignal'] is True
