from apps.ui_automation.models import AIExecutionRecord, AICase, SetupTemplate
from apps.ui_automation.reports import AIExecutionReportGenerator
from apps.ui_automation.views._helpers import _reportable_execution_steps


def test_reportable_execution_steps_excludes_inline_screenshot_data():
    persisted = _reportable_execution_steps([{
        'step_number': 1,
        'description': '打开页面',
        'status': 'completed',
        'screenshot': 'base64-image-data',
    }])

    assert persisted == [{
        'step_number': 1,
        'description': '打开页面',
        'status': 'completed',
    }]


def test_summary_report_uses_structured_desktop_steps_and_target():
    record = AIExecutionRecord(
        case_name='Desktop report',
        status='passed',
        execution_mode='text',
        execution_target='desktop',
        planned_tasks=[{'id': 'desktop_1', 'description': 'Open desktop page', 'status': 'completed'}],
        steps_completed=[{
            'step_number': 1,
            'action_type': 'semantic_action',
            'description': 'Open desktop page',
            'status': 'completed',
        }],
    )

    report = AIExecutionReportGenerator(record).generate_summary_report()

    assert report['overview']['total_steps'] == 1
    assert report['overview']['total_actions'] == 1
    assert report['execution_details']['execution_target'] == 'Windows'


def test_generate_detailed_report_uses_description_and_summarizes_element():
    record = AIExecutionRecord(
        case_name='AI login report',
        status='passed',
        execution_mode='text',
        planned_tasks=[
            {'id': 'task_1', 'description': '打开登录弹窗', 'status': 'completed'},
            {'id': 'task_2', 'description': '断言登录成功', 'status': 'completed'},
        ],
        steps_completed=[
            {
                'step_number': 7,
                'action_type': 'business_action',
                'description': '提交 NN 登录并校验登录态',
                'status': 'completed',
                'element': {
                    'detail': {
                        'text': '登录 / 注册',
                        'selector': '[data-ai-automation-click-target="submit"]',
                    },
                    'selector': '[data-ai-automation-click-target="submit"]',
                },
            },
            {
                'step_number': 8,
                'action_type': 'assert',
                'description': '完成登录后，检查默认头像是否变化，判断是否成功登录',
                'status': 'completed',
                'element': None,
            },
            {
                'step_number': 9,
                'status': 'completed',
                'element': None,
            },
        ],
    )

    report = AIExecutionReportGenerator(record).generate_detailed_report()
    steps = report['detailed_steps']

    assert [step['step_number'] for step in steps] == [7, 8]
    assert steps[0]['action'] == '提交 NN 登录并校验登录态'
    assert steps[0]['element'] == '登录 / 注册'
    assert steps[1]['action'] == '完成登录后，检查默认头像是否变化，判断是否成功登录'
    assert steps[1]['element'] == ''


def test_detailed_report_prefers_original_task_description_with_setup_template():
    setup_template = SetupTemplate(
        name='登录NN测试环境',
        steps=[
            {'description': '打开 NN 登录弹窗'},
            {'description': '输入手机号'},
            {'description': '输入验证码'},
            {'description': '勾选已阅读并同意用户协议'},
            {'description': '提交 NN 登录并校验登录态'},
        ],
    )
    ai_case = AICase(
        name='test',
        setup_template=setup_template,
        task_description=(
            '1、在顶部导航栏中间的社区搜索框中搜索“绝地求生”\n'
            '2、点击社区搜索结果下的“绝地求生社区”，必须满足两个条件：有在线人数数和社区简介\n'
            '3、断言已进入“绝地求生”目标社区详情页，且左侧社区面板显示PUBG中国官方社区'
        ),
    )
    record = AIExecutionRecord(
        ai_case=ai_case,
        case_name='AI community flow',
        task_description=ai_case.task_description,
        status='failed',
        execution_mode='text',
        planned_tasks=[
            {'id': 'task_1', 'description': '打开 NN 登录弹窗', 'status': 'completed'},
            {'id': 'task_2', 'description': '输入手机号', 'status': 'completed'},
            {'id': 'task_3', 'description': '输入验证码', 'status': 'completed'},
            {'id': 'task_4', 'description': '勾选已阅读并同意用户协议', 'status': 'completed'},
            {'id': 'task_5', 'description': '提交 NN 登录并校验登录态', 'status': 'completed'},
            {'id': 'task_6', 'description': '顶部社区搜索框搜索:绝地求生', 'status': 'completed'},
            {'id': 'task_7', 'description': '点击社区搜索结果:绝地求生', 'status': 'failed'},
            {'id': 'task_8', 'description': '断言已进入“绝地求生”目标社区详情页，且左侧社区面板显示PUBG中国官方社区', 'status': 'failed'},
        ],
        steps_completed=[
            {
                'step_number': 7,
                'action_type': 'business_action',
                'description': '点击社区搜索结果:绝地求生',
                'status': 'failed',
                'error': 'Page.evaluate: SyntaxError: Invalid regular expression: missing /',
                'element': None,
            }
        ],
    )

    report = AIExecutionReportGenerator(record).generate_detailed_report()
    steps = report['detailed_steps']

    assert len(steps) == 1
    assert steps[0]['step_number'] == 7
    assert steps[0]['action'] == '2、点击社区搜索结果下的“绝地求生社区”，必须满足两个条件：有在线人数数和社区简介'


def test_detailed_report_prefers_task_description_over_stale_display_description():
    original_task_description = (
        '1、打开顶部社区搜索框\n'
        '2、点击社区搜索结果下的“绝地求生社区”，必须满足两个条件：有在线人数和社区简介\n'
        '3、断言已进入目标社区详情页'
    )
    stale_display_description = '2、点击社区搜索结果下的“绝地求生”社区，必须 满足两个条件：有在线人数和社区简介'

    record = AIExecutionRecord(
        case_name='AI community flow',
        task_description=original_task_description,
        status='failed',
        execution_mode='text',
        planned_tasks=[
            {'id': 'task_1', 'description': '打开顶部社区搜索框', 'status': 'completed'},
            {
                'id': 'task_2',
                'description': '点击社区搜索结果: 绝地求生',
                'display_description': stale_display_description,
                'status': 'failed',
            },
            {'id': 'task_3', 'description': '断言已进入目标社区详情页', 'status': 'pending'},
        ],
        steps_completed=[
            {
                'step_number': 2,
                'action_type': 'business_action',
                'description': '点击社区搜索结果: 绝地求生',
                'display_description': stale_display_description,
                'status': 'failed',
                'element': None,
            }
        ],
    )

    report = AIExecutionReportGenerator(record).generate_detailed_report()
    steps = report['detailed_steps']

    assert len(steps) == 1
    assert steps[0]['step_number'] == 2
    assert steps[0]['action'] == '2、点击社区搜索结果下的“绝地求生社区”，必须满足两个条件：有在线人数和社区简介'


def test_summary_report_timeline_prefers_original_task_description_with_setup_template():
    setup_template = SetupTemplate(
        name='登录NN测试环境',
        steps=[
            {'description': '打开 NN 登录弹窗'},
            {'description': '输入手机号'},
            {'description': '输入验证码'},
            {'description': '勾选已阅读并同意用户协议'},
            {'description': '提交 NN 登录并校验登录态'},
        ],
    )
    ai_case = AICase(
        name='test',
        setup_template=setup_template,
        task_description=(
            '1、在顶部导航栏中间的社区搜索框中搜索“绝地求生”\n'
            '2、点击社区搜索结果下的“绝地求生社区”，必须满足两个条件：有在线人数数和社区简介\n'
            '3、断言已进入“绝地求生”目标社区详情页，且左侧社区面板显示PUBG中国官方社区'
        ),
    )
    record = AIExecutionRecord(
        ai_case=ai_case,
        case_name='AI community flow',
        task_description=ai_case.task_description,
        status='failed',
        execution_mode='text',
        planned_tasks=[
            {'id': 'task_1', 'description': '打开 NN 登录弹窗', 'status': 'completed'},
            {'id': 'task_2', 'description': '输入手机号', 'status': 'completed'},
            {'id': 'task_3', 'description': '输入验证码', 'status': 'completed'},
            {'id': 'task_4', 'description': '勾选已阅读并同意用户协议', 'status': 'completed'},
            {'id': 'task_5', 'description': '提交 NN 登录并校验登录态', 'status': 'completed'},
            {'id': 'task_6', 'description': '顶部社区搜索框搜索:绝地求生', 'status': 'completed'},
            {'id': 'task_7', 'description': '点击社区搜索结果:绝地求生', 'status': 'completed'},
            {'id': 'task_8', 'description': '断言已进入“绝地求生”目标社区详情页，且左侧社区面板显示PUBG中国官方社区', 'status': 'failed'},
        ],
    )

    report = AIExecutionReportGenerator(record).generate_summary_report()
    timeline = report['timeline']

    assert len(timeline) == 8
    assert timeline[5]['description'] == '1、在顶部导航栏中间的社区搜索框中搜索“绝地求生”'
    assert timeline[6]['description'] == '2、点击社区搜索结果下的“绝地求生社区”，必须满足两个条件：有在线人数数和社区简介'
    assert timeline[7]['description'] == '3、断言已进入“绝地求生”目标社区详情页，且左侧社区面板显示PUBG中国官方社区'
