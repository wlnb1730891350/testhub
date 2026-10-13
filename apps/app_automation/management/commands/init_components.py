# -*- coding: utf-8 -*-
"""Initialize the built-in APP automation component library."""
from django.core.management.base import BaseCommand

from apps.app_automation.models import AppComponent


SELECTOR_FIELDS = {
    'selector_type': {'type': 'string'},
    'selector': {'type': 'string'},
    'timeout': {'type': 'number', 'minimum': 0},
    'retry_times': {'type': 'number', 'minimum': 0},
    'retry_interval': {'type': 'number', 'minimum': 0},
}


def component(name, component_type, category, properties, required, default_config, sort_order):
    return {
        'name': name,
        'type': component_type,
        'category': category,
        'description': f'{name}（UIAutomator2 原生执行）',
        'schema': {'type': 'object', 'properties': properties, 'required': required},
        'default_config': default_config,
        'enabled': True,
        'sort_order': sort_order,
    }


BUILT_IN_COMPONENTS = [
    component(
        '点击元素', 'click', '交互', SELECTOR_FIELDS, ['selector_type', 'selector'],
        {'selector_type': 'resource_id', 'selector': '', 'timeout': 5, 'retry_times': 0, 'retry_interval': 0.5}, 10,
    ),
    component(
        '可选点击', 'click_if_present', '交互', SELECTOR_FIELDS, ['selector_type', 'selector'],
        {'selector_type': 'resource_id', 'selector': '', 'timeout': 0.5, 'retry_times': 0, 'retry_interval': 0.5}, 15,
    ),
    component(
        '输入文本', 'input', '交互', {
            **SELECTOR_FIELDS,
            'value': {'type': 'string'}, 'clear': {'type': 'boolean'}, 'send_enter': {'type': 'boolean'},
        }, ['selector_type', 'selector', 'value'], {
            'selector_type': 'resource_id', 'selector': '', 'value': '', 'clear': True,
            'send_enter': False, 'timeout': 5, 'retry_times': 0, 'retry_interval': 0.5,
        }, 20,
    ),
    component(
        '等待元素', 'wait', '等待', SELECTOR_FIELDS, ['selector_type', 'selector'],
        {'selector_type': 'resource_id', 'selector': '', 'timeout': 8, 'retry_times': 0, 'retry_interval': 0.5}, 30,
    ),
    component(
        '等待时间', 'sleep', '等待', {'duration': {'type': 'number', 'minimum': 0}}, ['duration'],
        {'duration': 1}, 40,
    ),
    component(
        '文本或存在性断言', 'assert', '断言', {
            **SELECTOR_FIELDS,
            'assert_type': {'type': 'string'}, 'expected': {'type': 'string'},
            'match_mode': {'type': 'string'}, 'expected_exists': {'type': 'boolean'},
        }, ['assert_type'], {
            'assert_type': 'exists', 'selector_type': 'resource_id', 'selector': '', 'expected': '',
            'match_mode': 'exact', 'expected_exists': True, 'timeout': 5,
            'retry_times': 0, 'retry_interval': 0.5,
        }, 50,
    ),
    component(
        '坐标滑动', 'swipe', '交互', {
            'start': {'type': 'string'}, 'end': {'type': 'string'}, 'duration': {'type': 'number', 'minimum': 0},
        }, ['start', 'end'], {'start': '', 'end': '', 'duration': 0.5}, 60,
    ),
    component(
        '滑动查找元素', 'swipe_to', '交互', {
            'target_selector_type': {'type': 'string'}, 'target_selector': {'type': 'string'},
            'direction': {'type': 'string'}, 'max_swipes': {'type': 'number', 'minimum': 1},
            'interval': {'type': 'number', 'minimum': 0},
        }, ['target_selector_type', 'target_selector'], {
            'target_selector_type': 'resource_id', 'target_selector': '', 'direction': 'up',
            'max_swipes': 5, 'interval': 0.4,
        }, 70,
    ),
    component('截图', 'screenshot', '辅助', {}, [], {}, 80),
    component(
        '设置变量', 'set_variable', '变量', {
            'name': {'type': 'string'}, 'value': {'type': 'string'}, 'scope': {'type': 'string'},
        }, ['name'], {'name': '', 'value': '', 'scope': 'local'}, 90,
    ),
    component(
        '删除变量', 'unset_variable', '变量', {
            'name': {'type': 'string'}, 'scope': {'type': 'string'},
        }, ['name'], {'name': '', 'scope': 'local'}, 100,
    ),
]


class Command(BaseCommand):
    help = '初始化 APP 自动化基础组件库（已存在的组件不会被覆盖）'

    def handle(self, *args, **options):
        created = 0
        for definition in BUILT_IN_COMPONENTS:
            _, was_created = AppComponent.objects.get_or_create(
                type=definition['type'], defaults=definition,
            )
            created += int(was_created)
        self.stdout.write(self.style.SUCCESS(
            f'APP 基础组件初始化完成：新增 {created} 个，已有 {len(BUILT_IN_COMPONENTS) - created} 个。'
        ))
