"""
Management command to create a tutorial project for UI Automation testing.
This provides beginners with a hands-on learning experience.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.ui_automation.models import (
    UiProject, ElementGroup, Element, LocatorStrategy,
    TestScript, ScriptStep, PageObject, PageObjectElement,
    TestSuite, TestSuiteScript, TestCase, TestSuiteTestCase
)
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = 'Create a tutorial project for UI Automation testing'

    def handle(self, *args, **options):
        self.stdout.write('Creating tutorial project...\n')

        # Get or create admin user
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            user = User.objects.first()
        if not user:
            self.stdout.write(self.style.ERROR('No user found. Please create a user first.'))
            return

        # 1. Create Project
        project, created = UiProject.objects.get_or_create(
            name='TestHub 新手教程',
            defaults={
                'description': 'UI自动化测试新手入门教程项目。通过这个项目，你将学习如何：\n'
                              '1. 创建和管理UI元素\n'
                              '2. 编写测试脚本\n'
                              '3. 组织测试套件\n'
                              '4. 执行测试并查看报告',
                'status': 'IN_PROGRESS',
                'base_url': 'http://localhost:3000',
                'owner': user,
                'start_date': timezone.now().date(),
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created project: {project.name}'))
        else:
            self.stdout.write(self.style.WARNING(f'Project already exists: {project.name}'))

        # 2. Get Locator Strategies
        css_strategy, _ = LocatorStrategy.objects.get_or_create(
            name='css', defaults={'description': 'CSS选择器'}
        )
        xpath_strategy, _ = LocatorStrategy.objects.get_or_create(
            name='xpath', defaults={'description': 'XPath表达式'}
        )
        id_strategy, _ = LocatorStrategy.objects.get_or_create(
            name='id', defaults={'description': '元素ID'}
        )
        text_strategy, _ = LocatorStrategy.objects.get_or_create(
            name='text', defaults={'description': '文本内容'}
        )

        # 3. Create Element Groups
        nav_group, _ = ElementGroup.objects.get_or_create(
            name='导航栏元素',
            project=project,
            defaults={'description': '页面顶部导航栏相关的UI元素', 'order': 1}
        )
        login_group, _ = ElementGroup.objects.get_or_create(
            name='登录模块元素',
            project=project,
            defaults={'description': '登录页面相关的UI元素', 'order': 2}
        )
        dashboard_group, _ = ElementGroup.objects.get_or_create(
            name='仪表盘元素',
            project=project,
            defaults={'description': '首页仪表盘相关的UI元素', 'order': 3}
        )
        ai_module_group, _ = ElementGroup.objects.get_or_create(
            name='AI用例生成模块',
            project=project,
            defaults={'description': 'AI用例生成模块相关的UI元素', 'order': 4}
        )

        # 4. Create Elements - Navigation
        elements = []
        
        # Nav elements
        nav_logo, _ = Element.objects.get_or_create(
            project=project, name='Logo图标',
            defaults={
                'group': nav_group,
                'description': '页面左上角的TestHub Logo',
                'element_type': 'IMAGE',
                'locator_strategy': css_strategy,
                'locator_value': '.logo-image',
                'page': '/home',
                'is_unique': True,
            }
        )
        elements.append(nav_logo)

        nav_home_btn, _ = Element.objects.get_or_create(
            project=project, name='首页按钮',
            defaults={
                'group': nav_group,
                'description': '导航栏中的"首页"按钮',
                'element_type': 'LINK',
                'locator_strategy': css_strategy,
                'locator_value': 'a[href="/home"]',
                'page': '/home',
            }
        )
        elements.append(nav_home_btn)

        nav_ai_btn, _ = Element.objects.get_or_create(
            project=project, name='AI用例生成按钮',
            defaults={
                'group': nav_group,
                'description': '导航栏中的"AI用例生成"按钮',
                'element_type': 'LINK',
                'locator_strategy': css_strategy,
                'locator_value': 'a[href="/ai-generation"]',
                'page': '/home',
            }
        )
        elements.append(nav_ai_btn)

        nav_ui_auto_btn, _ = Element.objects.get_or_create(
            project=project, name='UI自动化测试按钮',
            defaults={
                'group': nav_group,
                'description': '导航栏中的"UI自动化测试"按钮',
                'element_type': 'LINK',
                'locator_strategy': css_strategy,
                'locator_value': 'a[href="/ui-automation"]',
                'page': '/home',
            }
        )
        elements.append(nav_ui_auto_btn)

        user_menu_btn, _ = Element.objects.get_or_create(
            project=project, name='用户菜单按钮',
            defaults={
                'group': nav_group,
                'description': '导航栏右侧的用户头像/菜单按钮',
                'element_type': 'BUTTON',
                'locator_strategy': css_strategy,
                'locator_value': '.user-menu-btn',
                'page': '/home',
                'is_unique': True,
            }
        )
        elements.append(user_menu_btn)

        # Login elements
        username_input, _ = Element.objects.get_or_create(
            project=project, name='用户名输入框',
            defaults={
                'group': login_group,
                'description': '登录页面的用户名输入框',
                'element_type': 'INPUT',
                'locator_strategy': css_strategy,
                'locator_value': 'input[name="username"]',
                'page': '/login',
                'is_unique': True,
            }
        )
        elements.append(username_input)

        password_input, _ = Element.objects.get_or_create(
            project=project, name='密码输入框',
            defaults={
                'group': login_group,
                'description': '登录页面的密码输入框',
                'element_type': 'INPUT',
                'locator_strategy': css_strategy,
                'locator_value': 'input[name="password"]',
                'page': '/login',
                'is_unique': True,
            }
        )
        elements.append(password_input)

        login_btn, _ = Element.objects.get_or_create(
            project=project, name='登录按钮',
            defaults={
                'group': login_group,
                'description': '登录页面的"登录"按钮',
                'element_type': 'BUTTON',
                'locator_strategy': css_strategy,
                'locator_value': 'button[type="submit"]',
                'page': '/login',
                'is_unique': True,
            }
        )
        elements.append(login_btn)

        # Dashboard elements
        task_cards, _ = Element.objects.get_or_create(
            project=project, name='任务卡片列表',
            defaults={
                'group': dashboard_group,
                'description': '仪表盘中的任务卡片列表容器',
                'element_type': 'CONTAINER',
                'locator_strategy': css_strategy,
                'locator_value': '.task-cards-container',
                'page': '/dashboard',
            }
        )
        elements.append(task_cards)

        create_task_btn, _ = Element.objects.get_or_create(
            project=project, name='创建任务按钮',
            defaults={
                'group': dashboard_group,
                'description': '仪表盘中的"创建新任务"按钮',
                'element_type': 'BUTTON',
                'locator_strategy': css_strategy,
                'locator_value': 'button.create-task-btn',
                'page': '/dashboard',
                'is_unique': True,
            }
        )
        elements.append(create_task_btn)

        # AI Module elements
        requirement_input, _ = Element.objects.get_or_create(
            project=project, name='需求输入文本框',
            defaults={
                'group': ai_module_group,
                'description': 'AI用例生成页面的需求输入文本框',
                'element_type': 'INPUT',
                'locator_strategy': css_strategy,
                'locator_value': 'textarea.requirement-input',
                'page': '/ai-generation',
                'is_unique': True,
            }
        )
        elements.append(requirement_input)

        generate_btn, _ = Element.objects.get_or_create(
            project=project, name='生成用例按钮',
            defaults={
                'group': ai_module_group,
                'description': 'AI用例生成页面的"开始生成"按钮',
                'element_type': 'BUTTON',
                'locator_strategy': css_strategy,
                'locator_value': 'button.generate-btn',
                'page': '/ai-generation',
                'is_unique': True,
            }
        )
        elements.append(generate_btn)

        progress_bar, _ = Element.objects.get_or_create(
            project=project, name='生成进度条',
            defaults={
                'group': ai_module_group,
                'description': 'AI用例生成过程中的进度条',
                'element_type': 'CONTAINER',
                'locator_strategy': css_strategy,
                'locator_value': '.generation-progress',
                'page': '/ai-generation',
            }
        )
        elements.append(progress_bar)

        self.stdout.write(self.style.SUCCESS(f'Created {len(elements)} elements'))

        # 5. Create Page Object
        login_page, _ = PageObject.objects.get_or_create(
            project=project, name='登录页面',
            defaults={
                'class_name': 'LoginPage',
                'url_pattern': '/login',
                'description': '登录页面的页面对象，封装了登录相关的所有操作',
            }
        )
        
        # Add elements to page object
        PageObjectElement.objects.get_or_create(
            page_object=login_page, method_name='username_input',
            defaults={'element': username_input, 'is_property': True, 'order': 1}
        )
        PageObjectElement.objects.get_or_create(
            page_object=login_page, method_name='password_input',
            defaults={'element': password_input, 'is_property': True, 'order': 2}
        )
        PageObjectElement.objects.get_or_create(
            page_object=login_page, method_name='login_button',
            defaults={'element': login_btn, 'is_property': True, 'order': 3}
        )
        PageObjectElement.objects.get_or_create(
            page_object=login_page, method_name='login',
            defaults={'element': login_btn, 'is_property': False, 'order': 4}
        )

        self.stdout.write(self.style.SUCCESS(f'Created page object: {login_page.name}'))

        # 6. Create Test Scripts
        login_script, created = TestScript.objects.get_or_create(
            project=project, name='登录功能测试脚本',
            defaults={
                'description': '测试用户登录功能的自动化脚本',
                'script_type': 'CODE',
                'content': '''import asyncio
from playwright.async_api import async_playwright

async def test_login():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # 导航到登录页面
        await page.goto('http://localhost:3000/login')
        
        # 输入用户名
        await page.fill('input[name="username"]', 'admin')
        
        # 输入密码
        await page.fill('input[name="password"]', 'admin123456')
        
        # 点击登录按钮
        await page.click('button[type="submit"]')
        
        # 等待页面跳转
        await page.wait_for_url('**/home')
        
        # 验证登录成功
        assert '/home' in page.url
        print('登录测试通过!')
        
        await browser.close()

if __name__ == '__main__':
    asyncio.run(test_login())''',
                'language': 'python',
                'framework': 'playwright',
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created script: {login_script.name}'))

        # Create script steps for login
        ScriptStep.objects.get_or_create(
            script=login_script, step_order=1,
            defaults={
                'action_type': 'NAVIGATE',
                'description': '打开登录页面',
                'action_params': {'url': 'http://localhost:3000/login'},
                'expected_result': '页面成功加载，显示登录表单',
            }
        )
        ScriptStep.objects.get_or_create(
            script=login_script, step_order=2,
            defaults={
                'action_type': 'INPUT',
                'target_element': username_input,
                'description': '输入用户名 admin',
                'action_params': {'value': 'admin'},
                'expected_result': '输入框显示 "admin"',
            }
        )
        ScriptStep.objects.get_or_create(
            script=login_script, step_order=3,
            defaults={
                'action_type': 'INPUT',
                'target_element': password_input,
                'description': '输入密码',
                'action_params': {'value': 'admin123456'},
                'expected_result': '密码框显示加密内容',
            }
        )
        ScriptStep.objects.get_or_create(
            script=login_script, step_order=4,
            defaults={
                'action_type': 'CLICK',
                'target_element': login_btn,
                'description': '点击登录按钮',
                'expected_result': '页面开始跳转',
            }
        )
        ScriptStep.objects.get_or_create(
            script=login_script, step_order=5,
            defaults={
                'action_type': 'WAIT',
                'description': '等待页面跳转完成',
                'action_params': {'timeout': 5000},
                'expected_result': 'URL 包含 /home',
            }
        )
        ScriptStep.objects.get_or_create(
            script=login_script, step_order=6,
            defaults={
                'action_type': 'VERIFY',
                'description': '验证登录成功',
                'action_params': {'type': 'url_contains', 'value': '/home'},
                'expected_result': '页面URL包含 /home，登录成功',
            }
        )

        # Navigation script
        nav_script, created = TestScript.objects.get_or_create(
            project=project, name='导航功能测试脚本',
            defaults={
                'description': '测试页面导航功能的自动化脚本',
                'script_type': 'CODE',
                'content': '''import asyncio
from playwright.async_api import async_playwright

async def test_navigation():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # 导航到首页
        await page.goto('http://localhost:3000/home')
        
        # 点击 AI用例生成
        await page.click('a[href="/ai-generation"]')
        await page.wait_for_url('**/ai-generation')
        assert '/ai-generation' in page.url
        print('导航到AI用例生成页面成功!')
        
        # 点击 UI自动化测试
        await page.click('a[href="/ui-automation"]')
        await page.wait_for_url('**/ui-automation')
        assert '/ui-automation' in page.url
        print('导航到UI自动化测试页面成功!')
        
        await browser.close()

if __name__ == '__main__':
    asyncio.run(test_navigation())''',
                'language': 'python',
                'framework': 'playwright',
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created script: {nav_script.name}'))

        # 7. Create Test Cases
        login_test_case, _ = TestCase.objects.get_or_create(
            project=project, name='登录功能-正常登录测试',
            defaults={
                'description': '验证使用正确的用户名和密码可以成功登录系统',
                'status': 'ready',
                'priority': 'high',
                'created_by': user,
            }
        )

        login_error_case, _ = TestCase.objects.get_or_create(
            project=project, name='登录功能-错误密码测试',
            defaults={
                'description': '验证使用错误密码登录时，系统显示错误提示',
                'status': 'ready',
                'priority': 'high',
                'created_by': user,
            }
        )

        nav_test_case, _ = TestCase.objects.get_or_create(
            project=project, name='导航功能-页面跳转测试',
            defaults={
                'description': '验证点击导航链接可以正确跳转到对应页面',
                'status': 'ready',
                'priority': 'medium',
                'created_by': user,
            }
        )

        self.stdout.write(self.style.SUCCESS(f'Created {3} test cases'))

        # 8. Create Test Suite
        suite, created = TestSuite.objects.get_or_create(
            project=project, name='新手教程测试套件',
            defaults={
                'description': '包含所有新手教程的测试脚本和用例',
            }
        )
        if created:
            # Add scripts to suite
            TestSuiteScript.objects.get_or_create(
                test_suite=suite, test_script=login_script,
                defaults={'order': 1}
            )
            TestSuiteScript.objects.get_or_create(
                test_suite=suite, test_script=nav_script,
                defaults={'order': 2}
            )
            
            # Add test cases to suite
            TestSuiteTestCase.objects.get_or_create(
                test_suite=suite, test_case=login_test_case,
                defaults={'order': 1}
            )
            TestSuiteTestCase.objects.get_or_create(
                test_suite=suite, test_case=login_error_case,
                defaults={'order': 2}
            )
            TestSuiteTestCase.objects.get_or_create(
                test_suite=suite, test_case=nav_test_case,
                defaults={'order': 3}
            )
            
            self.stdout.write(self.style.SUCCESS(f'Created test suite: {suite.name}'))

        # Summary
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('Tutorial project created successfully!'))
        self.stdout.write('='*60)
        self.stdout.write(f'\nProject: {project.name}')
        self.stdout.write(f'Base URL: {project.base_url}')
        self.stdout.write(f'\nElements created: {Element.objects.filter(project=project).count()}')
        self.stdout.write(f'Scripts created: {TestScript.objects.filter(project=project).count()}')
        self.stdout.write(f'Test cases created: {TestCase.objects.filter(project=project).count()}')
        self.stdout.write(f'Test suites created: {TestSuite.objects.filter(project=project).count()}')
        self.stdout.write(f'Page objects created: {PageObject.objects.filter(project=project).count()}')
        
        self.stdout.write('\n' + '-'*60)
        self.stdout.write('Next steps:')
        self.stdout.write('1. Go to UI自动化测试 → 项目管理')
        self.stdout.write('2. Click on "TestHub 新手教程" project')
        self.stdout.write('3. Explore the elements, scripts, and test cases')
        self.stdout.write('4. Try running the test scripts!')
        self.stdout.write('-'*60)
