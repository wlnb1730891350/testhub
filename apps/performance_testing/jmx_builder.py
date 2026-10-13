import json
import xml.etree.ElementTree as ET
from urllib.parse import urlparse


THREAD_GROUP_ELEMENTS = {
    'ThreadGroup',
    'SetupThreadGroup',
    'PostThreadGroup',
}


def default_script_config(base_url=''):
    return {
        'variables': {
            'base_url': base_url or 'http://localhost',
        },
        'thread_groups': [
            {
                'name': '默认线程组',
                'threads': 10,
                'ramp_up': 10,
                'loops': 1,
                'duration': 60,
                'variables': {},
                'steps': [
                    {
                        'type': 'http_request',
                        'name': '首页请求',
                        'method': 'GET',
                        'url': '{{base_url}}/',
                        'headers': {},
                        'params': {},
                        'body': '',
                        'assertions': [
                            {'type': 'response_code', 'value': '200'},
                        ],
                    }
                ],
            }
        ],
    }


def normalize_config(config, base_url=''):
    if not isinstance(config, dict):
        config = {}

    normalized = {
        'variables': _dict_value(config.get('variables')),
        'thread_groups': [],
    }

    if base_url and not normalized['variables'].get('base_url'):
        normalized['variables']['base_url'] = base_url
    if not normalized['variables']:
        normalized['variables'] = default_script_config(base_url).get('variables', {})

    thread_groups = config.get('thread_groups')
    if not isinstance(thread_groups, list) or not thread_groups:
        thread_groups = default_script_config(base_url).get('thread_groups', [])

    for index, group in enumerate(thread_groups, 1):
        if not isinstance(group, dict):
            continue
        steps = group.get('steps')
        if not isinstance(steps, list):
            steps = []
        normalized['thread_groups'].append({
            'name': group.get('name') or f'线程组 {index}',
            'threads': _positive_int(group.get('threads'), 1),
            'ramp_up': _non_negative_int(group.get('ramp_up'), 1),
            'loops': _loop_count(group.get('loops'), 1),
            'duration': _non_negative_int(group.get('duration'), 0),
            'variables': _dict_value(group.get('variables') or group.get('user_defined_variables')),
            'steps': [step for step in steps if isinstance(step, dict)],
            'datasets': group.get('datasets') if isinstance(group.get('datasets'), list) else [],
        })

    if not normalized['thread_groups']:
        normalized['thread_groups'] = default_script_config(base_url).get('thread_groups', [])

    return normalized


class JMeterPlanBuilder:
    """Build a JMeter JMX document from TestHub's structured performance config."""

    def __init__(self, config, testname='TestHub Performance Test', base_url='', realtime_config=None):
        self.config = normalize_config(config, base_url=base_url)
        self.testname = testname
        self.realtime_config = realtime_config or {}

    def build_string(self):
        root = ET.Element('jmeterTestPlan', {
            'version': '1.2',
            'properties': '5.0',
            'jmeter': '5.6.3',
        })
        root_hash = ET.SubElement(root, 'hashTree')

        root_hash.append(self._build_test_plan())
        plan_tree = ET.SubElement(root_hash, 'hashTree')

        if self.realtime_config.get('enabled'):
            plan_tree.append(self._build_backend_listener())
            ET.SubElement(plan_tree, 'hashTree')

        for group in self.config['thread_groups']:
            plan_tree.append(self._build_thread_group(group))
            group_tree = ET.SubElement(plan_tree, 'hashTree')
            self._append_thread_group_children(group_tree, group)

        self._indent(root)
        return ET.tostring(root, encoding='utf-8', xml_declaration=True).decode('utf-8')

    def _build_test_plan(self):
        test_plan = ET.Element('TestPlan', {
            'guiclass': 'TestPlanGui',
            'testclass': 'TestPlan',
            'testname': self.testname,
            'enabled': 'true',
        })
        _string_prop(test_plan, 'TestPlan.comments', '')
        _bool_prop(test_plan, 'TestPlan.functional_mode', False)
        _bool_prop(test_plan, 'TestPlan.tearDown_on_shutdown', True)
        _bool_prop(test_plan, 'TestPlan.serialize_threadgroups', False)

        variables = ET.SubElement(test_plan, 'elementProp', {
            'name': 'TestPlan.user_defined_variables',
            'elementType': 'Arguments',
            'guiclass': 'ArgumentsPanel',
            'testclass': 'Arguments',
            'testname': '用户定义的变量',
            'enabled': 'true',
        })
        collection = ET.SubElement(variables, 'collectionProp', {'name': 'Arguments.arguments'})
        for key, value in (self.config.get('variables') or {}).items():
            collection.append(_argument(str(key), str(value)))

        _string_prop(test_plan, 'TestPlan.user_define_classpath', '')
        return test_plan

    def _build_thread_group(self, group):
        thread_group = ET.Element('ThreadGroup', {
            'guiclass': 'ThreadGroupGui',
            'testclass': 'ThreadGroup',
            'testname': group.get('name') or '线程组',
            'enabled': 'true',
        })
        _string_prop(thread_group, 'ThreadGroup.on_sample_error', group.get('on_sample_error') or 'continue')
        controller = ET.SubElement(thread_group, 'elementProp', {
            'name': 'ThreadGroup.main_controller',
            'elementType': 'LoopController',
            'guiclass': 'LoopControlPanel',
            'testclass': 'LoopController',
            'testname': 'Loop Controller',
            'enabled': 'true',
        })
        loops = _loop_count(group.get('loops'), 1)
        _bool_prop(controller, 'LoopController.continue_forever', loops == -1)
        _string_prop(controller, 'LoopController.loops', str(loops))
        _string_prop(thread_group, 'ThreadGroup.num_threads', str(_positive_int(group.get('threads'), 1)))
        _string_prop(thread_group, 'ThreadGroup.ramp_time', str(_non_negative_int(group.get('ramp_up'), 1)))
        _bool_prop(thread_group, 'ThreadGroup.same_user_on_next_iteration', True)
        duration = _non_negative_int(group.get('duration'), 0)
        _bool_prop(thread_group, 'ThreadGroup.scheduler', duration > 0)
        _string_prop(thread_group, 'ThreadGroup.duration', str(duration) if duration > 0 else '')
        _string_prop(thread_group, 'ThreadGroup.delay', '')
        return thread_group

    def _append_thread_group_children(self, group_tree, group):
        group_tree.append(self._build_cookie_manager())
        ET.SubElement(group_tree, 'hashTree')

        variables = group.get('variables') or group.get('user_defined_variables') or {}
        if variables:
            group_tree.append(self._build_user_defined_variables(variables))
            ET.SubElement(group_tree, 'hashTree')

        for dataset in group.get('datasets') or []:
            if not isinstance(dataset, dict):
                continue
            group_tree.append(self._build_csv_dataset(dataset))
            ET.SubElement(group_tree, 'hashTree')

        for step in group.get('steps') or []:
            if step.get('type', 'http_request') != 'http_request':
                continue
            group_tree.append(self._build_http_sampler(step))
            sampler_tree = ET.SubElement(group_tree, 'hashTree')
            self._append_sampler_children(sampler_tree, step)

    def _build_cookie_manager(self):
        manager = ET.Element('CookieManager', {
            'guiclass': 'CookiePanel',
            'testclass': 'CookieManager',
            'testname': 'HTTP Cookie管理器',
            'enabled': 'true',
        })
        ET.SubElement(manager, 'collectionProp', {'name': 'CookieManager.cookies'})
        _bool_prop(manager, 'CookieManager.clearEachIteration', False)
        _bool_prop(manager, 'CookieManager.controlledByThreadGroup', False)
        return manager

    def _build_backend_listener(self):
        listener = ET.Element('BackendListener', {
            'guiclass': 'BackendListenerGui',
            'testclass': 'BackendListener',
            'testname': 'InfluxDB 实时报告',
            'enabled': 'true',
        })
        args = ET.SubElement(listener, 'elementProp', {
            'name': 'arguments',
            'elementType': 'Arguments',
            'guiclass': 'ArgumentsPanel',
            'testclass': 'Arguments',
            'enabled': 'true',
        })
        collection = ET.SubElement(args, 'collectionProp', {'name': 'Arguments.arguments'})
        for key, value in self._backend_listener_arguments():
            collection.append(_argument(str(key), str(value)))

        _string_prop(
            listener,
            'classname',
            self.realtime_config.get('backend_class') or 'org.apache.jmeter.visualizers.backend.influxdb.InfluxdbBackendListenerClient',
        )
        _string_prop(listener, 'QUEUE_SIZE', str(_positive_int(self.realtime_config.get('queue_size'), 5000)))
        return listener

    def _backend_listener_arguments(self):
        arguments = [
            ('influxdbMetricsSender', self.realtime_config.get('influxdb_metrics_sender') or 'org.apache.jmeter.visualizers.backend.influxdb.HttpMetricsSender'),
            ('influxdbUrl', self.realtime_config.get('influxdb_url') or 'http://localhost:8086/write?db=jmeter'),
            ('influxdbToken', self.realtime_config.get('influxdb_token') or ''),
            ('application', self.realtime_config.get('application') or 'testhub'),
            ('measurement', self.realtime_config.get('measurement') or 'jmeter'),
            ('summaryOnly', str(bool(self.realtime_config.get('summary_only'))).lower()),
            ('samplersRegex', self.realtime_config.get('samplers_regex') or '.*'),
            ('percentiles', self.realtime_config.get('percentiles') or '99;95;90'),
            ('testTitle', self.realtime_config.get('test_title') or self.testname),
            ('eventTags', self.realtime_config.get('event_tags') or ''),
        ]
        for key, value in (self.realtime_config.get('custom_tags') or {}).items():
            tag_name = _tag_name(key)
            if tag_name:
                arguments.append((f'TAG_{tag_name}', value))
        return arguments

    def _build_user_defined_variables(self, variables):
        args = ET.Element('Arguments', {
            'guiclass': 'ArgumentsPanel',
            'testclass': 'Arguments',
            'testname': '用户定义的变量',
            'enabled': 'true',
        })
        collection = ET.SubElement(args, 'collectionProp', {'name': 'Arguments.arguments'})
        for key, value in _items(variables):
            collection.append(_argument(str(key), str(value)))
        return args

    def _build_csv_dataset(self, dataset):
        config = ET.Element('CSVDataSet', {
            'guiclass': 'TestBeanGUI',
            'testclass': 'CSVDataSet',
            'testname': dataset.get('name') or 'CSV 数据集',
            'enabled': str(dataset.get('enabled', True)).lower(),
        })
        _string_prop(config, 'delimiter', dataset.get('delimiter') or ',')
        _string_prop(config, 'fileEncoding', dataset.get('file_encoding') or 'UTF-8')
        _string_prop(config, 'filename', dataset.get('filename') or '')
        _bool_prop(config, 'ignoreFirstLine', bool(dataset.get('ignore_first_line', True)))
        _bool_prop(config, 'quotedData', bool(dataset.get('quoted_data', False)))
        _bool_prop(config, 'recycle', bool(dataset.get('recycle', True)))
        _string_prop(config, 'shareMode', dataset.get('share_mode') or 'shareMode.all')
        _bool_prop(config, 'stopThread', bool(dataset.get('stop_thread', False)))
        variables = dataset.get('variables') or dataset.get('variable_names') or []
        if isinstance(variables, list):
            variables = ','.join(str(item) for item in variables if item)
        _string_prop(config, 'variableNames', str(variables or ''))
        return config

    def _build_http_sampler(self, step):
        sampler = ET.Element('HTTPSamplerProxy', {
            'guiclass': 'HttpTestSampleGui',
            'testclass': 'HTTPSamplerProxy',
            'testname': step.get('name') or 'HTTP请求',
            'enabled': str(step.get('enabled', True)).lower(),
        })

        args = ET.SubElement(sampler, 'elementProp', {
            'name': 'HTTPsampler.Arguments',
            'elementType': 'Arguments',
            'guiclass': 'HTTPArgumentsPanel',
            'testclass': 'Arguments',
            'testname': '用户定义的变量',
            'enabled': 'true',
        })
        collection = ET.SubElement(args, 'collectionProp', {'name': 'Arguments.arguments'})

        method = str(step.get('method') or 'GET').upper()
        body = step.get('body')
        if body not in ('', None) and method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            body_value = json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else str(body)
            ET.SubElement(sampler, 'boolProp', {'name': 'HTTPSampler.postBodyRaw'}).text = 'true'
            collection.append(_http_argument('', body_value, always_encode=False))
        else:
            for key, value in _items(step.get('params')):
                collection.append(_http_argument(str(key), str(value), always_encode=True))

        url_info = self._split_url(step.get('url') or '')
        _string_prop(sampler, 'HTTPSampler.domain', url_info['domain'])
        _string_prop(sampler, 'HTTPSampler.port', url_info['port'])
        _string_prop(sampler, 'HTTPSampler.protocol', url_info['protocol'])
        _string_prop(sampler, 'HTTPSampler.contentEncoding', step.get('content_encoding') or 'UTF-8')
        _string_prop(sampler, 'HTTPSampler.path', url_info['path'])
        _string_prop(sampler, 'HTTPSampler.method', method)
        _bool_prop(sampler, 'HTTPSampler.follow_redirects', bool(step.get('follow_redirects', True)))
        _bool_prop(sampler, 'HTTPSampler.auto_redirects', bool(step.get('auto_redirects', False)))
        _bool_prop(sampler, 'HTTPSampler.use_keepalive', bool(step.get('use_keepalive', True)))
        _bool_prop(sampler, 'HTTPSampler.DO_MULTIPART_POST', bool(step.get('multipart', False)))
        _string_prop(sampler, 'HTTPSampler.embedded_url_re', '')
        _string_prop(sampler, 'HTTPSampler.connect_timeout', str(step.get('connect_timeout') or ''))
        _string_prop(sampler, 'HTTPSampler.response_timeout', str(step.get('response_timeout') or ''))
        return sampler

    def _append_sampler_children(self, sampler_tree, step):
        headers = dict(_items(step.get('headers')))
        if headers:
            sampler_tree.append(self._build_header_manager(headers))
            ET.SubElement(sampler_tree, 'hashTree')

        timer = step.get('timer') or {}
        if timer:
            timer_node = self._build_timer(timer)
            if timer_node is not None:
                sampler_tree.append(timer_node)
                ET.SubElement(sampler_tree, 'hashTree')

        for assertion in step.get('assertions') or []:
            if not isinstance(assertion, dict):
                continue
            assertion_node = self._build_response_assertion(assertion)
            if assertion_node is not None:
                sampler_tree.append(assertion_node)
                ET.SubElement(sampler_tree, 'hashTree')

    def _build_header_manager(self, headers):
        manager = ET.Element('HeaderManager', {
            'guiclass': 'HeaderPanel',
            'testclass': 'HeaderManager',
            'testname': 'HTTP信息头管理器',
            'enabled': 'true',
        })
        collection = ET.SubElement(manager, 'collectionProp', {'name': 'HeaderManager.headers'})
        for key, value in headers.items():
            header = ET.SubElement(collection, 'elementProp', {'name': '', 'elementType': 'Header'})
            _string_prop(header, 'Header.name', key)
            _string_prop(header, 'Header.value', value)
        return manager

    def _build_timer(self, timer):
        timer_type = timer.get('type') or 'constant'
        if timer_type == 'uniform_random':
            node = ET.Element('UniformRandomTimer', {
                'guiclass': 'UniformRandomTimerGui',
                'testclass': 'UniformRandomTimer',
                'testname': timer.get('name') or '随机定时器',
                'enabled': str(timer.get('enabled', True)).lower(),
            })
            _string_prop(node, 'ConstantTimer.delay', str(_non_negative_int(timer.get('offset'), 0)))
            _string_prop(node, 'RandomTimer.range', str(_non_negative_int(timer.get('range'), 1000)))
            return node

        node = ET.Element('ConstantTimer', {
            'guiclass': 'ConstantTimerGui',
            'testclass': 'ConstantTimer',
            'testname': timer.get('name') or '固定定时器',
            'enabled': str(timer.get('enabled', True)).lower(),
        })
        _string_prop(node, 'ConstantTimer.delay', str(_non_negative_int(timer.get('delay'), 0)))
        return node

    def _build_response_assertion(self, assertion):
        assertion_type = assertion.get('type') or 'contains'
        value = assertion.get('value')
        if value in (None, ''):
            return None

        node = ET.Element('ResponseAssertion', {
            'guiclass': 'AssertionGui',
            'testclass': 'ResponseAssertion',
            'testname': assertion.get('name') or '响应断言',
            'enabled': str(assertion.get('enabled', True)).lower(),
        })
        collection = ET.SubElement(node, 'collectionProp', {'name': 'Asserion.test_strings'})
        _string_prop(collection, str(value), str(value))
        field = 'Assertion.response_data'
        test_type = 2
        if assertion_type == 'response_code':
            field = 'Assertion.response_code'
            test_type = 8
        elif assertion_type == 'not_contains':
            test_type = 6
        _string_prop(node, 'Assertion.custom_message', assertion.get('message') or '')
        _string_prop(node, 'Assertion.test_field', field)
        _bool_prop(node, 'Assertion.assume_success', False)
        _int_prop(node, 'Assertion.test_type', test_type)
        return node

    def _split_url(self, raw_url):
        raw_url = raw_url.replace('{{base_url}}', '${base_url}')
        if raw_url.startswith('${') or raw_url.startswith('/'):
            return {'protocol': '', 'domain': '', 'port': '', 'path': raw_url or '/'}

        parsed = urlparse(raw_url)
        if parsed.scheme and parsed.netloc:
            path = parsed.path or '/'
            if parsed.query:
                path = f'{path}?{parsed.query}'
            return {
                'protocol': parsed.scheme,
                'domain': parsed.hostname or '',
                'port': str(parsed.port or ''),
                'path': path,
            }
        return {'protocol': '', 'domain': '', 'port': '', 'path': raw_url or '/'}

    def _indent(self, root):
        try:
            ET.indent(root, space='  ')
        except AttributeError:
            pass


class UploadedJMXPlanBuilder:
    """Patch an uploaded JMX while preserving its original test plan structure."""

    def __init__(self, content, config, testname='TestHub Uploaded JMX', realtime_config=None):
        if isinstance(content, bytes):
            content = content.decode('utf-8-sig', errors='ignore')
        self.root = ET.fromstring(content)
        self.config = config if isinstance(config, dict) else {}
        self.testname = testname
        self.realtime_config = realtime_config or {}

    def build_string(self):
        self._apply_thread_group_overrides()
        self._apply_dataset_overrides()
        self._ensure_backend_listener()
        try:
            ET.indent(self.root, space='  ')
        except AttributeError:
            pass
        return ET.tostring(self.root, encoding='utf-8', xml_declaration=True).decode('utf-8')

    def _apply_thread_group_overrides(self):
        nodes = [node for node in self.root.iter() if _local_name(node.tag) in THREAD_GROUP_ELEMENTS]
        groups = self.config.get('thread_groups') if isinstance(self.config.get('thread_groups'), list) else []
        for fallback_index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            node = _indexed_node(nodes, group.get('jmx_index'), fallback_index)
            if node is None:
                continue
            self._update_thread_group(node, group)

    def _update_thread_group(self, node, group):
        if group.get('threads') not in (None, ''):
            _set_string_prop(node, 'ThreadGroup.num_threads', str(_positive_int(group.get('threads'), 1)))
        if group.get('ramp_up') not in (None, ''):
            _set_string_prop(node, 'ThreadGroup.ramp_time', str(_non_negative_int(group.get('ramp_up'), 1)))
        if group.get('duration') not in (None, ''):
            duration = _non_negative_int(group.get('duration'), 0)
            _set_bool_prop(node, 'ThreadGroup.scheduler', duration > 0)
            _set_string_prop(node, 'ThreadGroup.duration', str(duration) if duration > 0 else '')
        if group.get('loops') not in (None, ''):
            loops = _loop_count(group.get('loops'), 1)
            controller = _thread_group_loop_controller(node)
            _set_bool_prop(controller, 'LoopController.continue_forever', loops == -1)
            _set_string_prop(controller, 'LoopController.loops', str(loops))

    def _apply_dataset_overrides(self):
        nodes = [node for node in self.root.iter() if _local_name(node.tag) == 'CSVDataSet']
        datasets = self._dataset_overrides()
        for fallback_index, dataset in enumerate(datasets):
            if not isinstance(dataset, dict):
                continue
            node = _indexed_node(nodes, dataset.get('jmx_index'), fallback_index)
            if node is None:
                continue
            self._update_dataset(node, dataset)

    def _dataset_overrides(self):
        datasets = self.config.get('datasets')
        if isinstance(datasets, list) and datasets:
            return datasets

        flattened = []
        seen = set()
        groups = self.config.get('thread_groups') if isinstance(self.config.get('thread_groups'), list) else []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get('datasets'), list):
                continue
            for dataset in group.get('datasets') or []:
                if not isinstance(dataset, dict):
                    continue
                key = dataset.get('jmx_index')
                if key is not None and key in seen:
                    continue
                if key is not None:
                    seen.add(key)
                flattened.append(dataset)
        return flattened

    def _update_dataset(self, node, dataset):
        if dataset.get('filename') not in (None, ''):
            _set_string_prop(node, 'filename', dataset.get('filename'))
        variables = dataset.get('variables') or dataset.get('variable_names')
        if variables:
            if isinstance(variables, list):
                variables = ','.join(str(item) for item in variables if item)
            _set_string_prop(node, 'variableNames', variables)
        if dataset.get('delimiter') not in (None, ''):
            _set_string_prop(node, 'delimiter', dataset.get('delimiter'))
        if 'ignore_first_line' in dataset:
            _set_bool_prop(node, 'ignoreFirstLine', bool(dataset.get('ignore_first_line')))

    def _ensure_backend_listener(self):
        if not self.realtime_config.get('enabled'):
            return
        plan_tree = self._test_plan_tree()
        if plan_tree is None:
            return

        self._remove_testhub_backend_listener(plan_tree)
        listener = JMeterPlanBuilder(
            default_script_config(),
            testname=self.testname,
            realtime_config=self.realtime_config,
        )._build_backend_listener()
        plan_tree.insert(0, ET.Element('hashTree'))
        plan_tree.insert(0, listener)

    def _test_plan_tree(self):
        for parent in self.root.iter():
            if _local_name(parent.tag) != 'hashTree':
                continue
            children = list(parent)
            for index, child in enumerate(children):
                if _local_name(child.tag) != 'TestPlan':
                    continue
                if index + 1 < len(children) and _local_name(children[index + 1].tag) == 'hashTree':
                    return children[index + 1]
        return None

    def _remove_testhub_backend_listener(self, plan_tree):
        index = 0
        while index < len(list(plan_tree)):
            children = list(plan_tree)
            child = children[index]
            is_testhub_listener = (
                _local_name(child.tag) == 'BackendListener'
                and child.get('testname') == 'InfluxDB 实时报告'
            )
            if not is_testhub_listener:
                index += 1
                continue
            plan_tree.remove(child)
            if index < len(children) - 1 and _local_name(children[index + 1].tag) == 'hashTree':
                plan_tree.remove(children[index + 1])


def _argument(name, value):
    arg = ET.Element('elementProp', {'name': name, 'elementType': 'Argument'})
    _string_prop(arg, 'Argument.name', name)
    _string_prop(arg, 'Argument.value', value)
    _string_prop(arg, 'Argument.metadata', '=')
    return arg


def _http_argument(name, value, always_encode=True):
    arg = ET.Element('elementProp', {'name': name, 'elementType': 'HTTPArgument'})
    _bool_prop(arg, 'HTTPArgument.always_encode', always_encode)
    _string_prop(arg, 'Argument.value', value)
    _string_prop(arg, 'Argument.metadata', '=')
    _bool_prop(arg, 'HTTPArgument.use_equals', True)
    _string_prop(arg, 'Argument.name', name)
    return arg


def _string_prop(parent, name, value):
    node = ET.SubElement(parent, 'stringProp', {'name': str(name)})
    node.text = '' if value is None else str(value)
    return node


def _bool_prop(parent, name, value):
    node = ET.SubElement(parent, 'boolProp', {'name': str(name)})
    node.text = 'true' if value else 'false'
    return node


def _int_prop(parent, name, value):
    node = ET.SubElement(parent, 'intProp', {'name': str(name)})
    node.text = str(value)
    return node


def _set_string_prop(parent, name, value):
    return _set_prop(parent, 'stringProp', name, '' if value is None else str(value))


def _set_bool_prop(parent, name, value):
    return _set_prop(parent, 'boolProp', name, 'true' if value else 'false')


def _set_prop(parent, tag, name, value):
    for child in parent:
        if _local_name(child.tag) == tag and child.get('name') == str(name):
            child.text = value
            return child
    node = ET.SubElement(parent, tag, {'name': str(name)})
    node.text = value
    return node


def _thread_group_loop_controller(thread_group):
    controller = thread_group.find(".//elementProp[@name='ThreadGroup.main_controller']")
    if controller is not None:
        return controller
    return ET.SubElement(thread_group, 'elementProp', {
        'name': 'ThreadGroup.main_controller',
        'elementType': 'LoopController',
        'guiclass': 'LoopControlPanel',
        'testclass': 'LoopController',
        'testname': 'Loop Controller',
        'enabled': 'true',
    })


def _indexed_node(nodes, raw_index, fallback_index):
    index = fallback_index
    try:
        if raw_index not in (None, ''):
            index = int(raw_index)
    except (TypeError, ValueError):
        index = fallback_index
    if 0 <= index < len(nodes):
        return nodes[index]
    if 0 <= fallback_index < len(nodes):
        return nodes[fallback_index]
    return None


def _local_name(tag):
    return str(tag).rsplit('}', 1)[-1]


def _items(value):
    if isinstance(value, dict):
        return [(key, val) for key, val in value.items() if key not in (None, '')]
    if isinstance(value, list):
        result = []
        for item in value:
            if not isinstance(item, dict):
                continue
            if item.get('enabled') is False:
                continue
            key = item.get('key') or item.get('name')
            if key not in (None, ''):
                result.append((key, item.get('value', '')))
        return result
    return []


def _dict_value(value):
    if isinstance(value, dict):
        return dict(value)
    return {str(key): val for key, val in _items(value)}


def _tag_name(value):
    text = ''.join(char if char.isalnum() or char == '_' else '_' for char in str(value or ''))
    return text.strip('_')


def _positive_int(value, default):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _loop_count(value, default):
    try:
        parsed = int(value)
        if parsed == -1 or parsed > 0:
            return parsed
        return default
    except (TypeError, ValueError):
        return default


def _non_negative_int(value, default):
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else default
    except (TypeError, ValueError):
        return default
