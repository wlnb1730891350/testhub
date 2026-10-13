import xml.etree.ElementTree as ET


DANGEROUS_ELEMENTS = {
    'JSR223Sampler',
    'JSR223PreProcessor',
    'JSR223PostProcessor',
    'JSR223Assertion',
    'BeanShellSampler',
    'BeanShellPreProcessor',
    'BeanShellPostProcessor',
    'BeanShellAssertion',
    'SystemSampler',
    'JavaSampler',
    'BSFSampler',
    'OSProcessSampler',
}

THREAD_GROUP_ELEMENTS = {
    'ThreadGroup',
    'SetupThreadGroup',
    'PostThreadGroup',
}


class JMXImportError(ValueError):
    pass


class JMXImporter:
    """Parse a safe HTTP-focused subset of JMeter JMX into TestHub config."""

    def parse(self, content):
        try:
            root = ET.fromstring(content)
        except ET.ParseError as exc:
            raise JMXImportError(f'JMX XML 解析失败: {exc}') from exc

        warnings = []
        dangerous = sorted({elem.tag for elem in root.iter() if _strip_ns(elem.tag) in DANGEROUS_ELEMENTS})
        if dangerous:
            warnings.append(
                f"检测到高风险组件: {', '.join(dangerous)}。"
                '纯 JMX 模式会保留原始组件，在线编排模式仅导入可识别的 HTTP 子集。'
            )

        variables = self._parse_variables(root)
        dataset_indexes = {id(dataset): index for index, dataset in enumerate(root.iter('CSVDataSet'))}
        all_datasets = self._parse_datasets(root, dataset_indexes)
        thread_groups = self._parse_thread_groups(root, warnings, dataset_indexes)

        if not thread_groups:
            samplers = self._parse_samplers(root, warnings)
            if samplers:
                thread_groups.append({
                    'name': '导入线程组',
                    'threads': 1,
                    'ramp_up': 1,
                    'loops': 1,
                    'duration': 0,
                    'steps': samplers,
                    'datasets': [],
                })

        if not thread_groups:
            raise JMXImportError('未识别到可导入的线程组或 HTTP 请求')

        total_requests = sum(len(group.get('steps') or []) for group in thread_groups)
        return {
            'title': self._first_attr(root, 'TestPlan', 'testname') or 'Imported JMX',
            'config': {
                'variables': variables,
                'thread_groups': thread_groups,
                'datasets': all_datasets,
            },
            'thread_group_count': len(thread_groups),
            'dataset_count': len(all_datasets),
            'total_requests': total_requests,
            'warnings': warnings,
            'dangerous_elements': dangerous,
            'executable': not dangerous,
        }

    def _parse_variables(self, root):
        variables = {}
        for test_plan in root.iter('TestPlan'):
            for arg in test_plan.findall(".//elementProp[@elementType='Argument']"):
                name = _get_prop(arg, 'Argument.name') or arg.get('name')
                value = _get_prop(arg, 'Argument.value')
                if name:
                    variables[name] = value
        return variables

    def _parse_thread_groups(self, root, warnings, dataset_indexes=None):
        result = []
        group_index = 0
        for parent in root.iter('hashTree'):
            children = list(parent)
            for index, child in enumerate(children):
                if _strip_ns(child.tag) not in THREAD_GROUP_ELEMENTS:
                    continue
                tree = children[index + 1] if index + 1 < len(children) and _strip_ns(children[index + 1].tag) == 'hashTree' else None
                group = {
                    'jmx_index': group_index,
                    'name': child.get('testname') or '线程组',
                    'threads': _int_prop(child, 'ThreadGroup.num_threads', 1),
                    'ramp_up': _int_prop(child, 'ThreadGroup.ramp_time', 1),
                    'loops': _loop_count(child),
                    'duration': _int_prop(child, 'ThreadGroup.duration', 0),
                    'variables': self._parse_user_defined_variables(tree or child),
                    'steps': self._parse_samplers(tree or child, warnings),
                    'datasets': self._parse_datasets(tree or child, dataset_indexes),
                }
                result.append(group)
                group_index += 1
        return result

    def _parse_user_defined_variables(self, root):
        variables = {}
        if root is None:
            return variables

        for parent in root.iter('hashTree'):
            children = list(parent)
            for child in children:
                if _strip_ns(child.tag) != 'Arguments':
                    continue
                if child.get('testname') not in ('用户定义的变量', 'User Defined Variables', None):
                    continue
                for arg in child.findall(".//elementProp[@elementType='Argument']"):
                    name = _get_prop(arg, 'Argument.name') or arg.get('name')
                    value = _get_prop(arg, 'Argument.value')
                    if name:
                        variables[name] = value
        return variables

    def _parse_samplers(self, root, warnings):
        if root is None:
            return []

        samplers = []
        for parent in root.iter('hashTree'):
            children = list(parent)
            for index, child in enumerate(children):
                if _strip_ns(child.tag) != 'HTTPSamplerProxy':
                    continue
                sampler_tree = children[index + 1] if index + 1 < len(children) and _strip_ns(children[index + 1].tag) == 'hashTree' else None
                samplers.append(self._parse_sampler(child, sampler_tree))

        if not samplers:
            for sampler in root.iter('HTTPSamplerProxy'):
                samplers.append(self._parse_sampler(sampler, None))

        unsupported_count = sum(1 for elem in root.iter() if _strip_ns(elem.tag).endswith('Sampler') and _strip_ns(elem.tag) != 'HTTPSamplerProxy')
        if unsupported_count:
            warnings.append(f'已跳过 {unsupported_count} 个非 HTTP Sampler')
        return samplers

    def _parse_sampler(self, sampler, sampler_tree):
        protocol = _get_prop(sampler, 'HTTPSampler.protocol')
        domain = _get_prop(sampler, 'HTTPSampler.domain')
        port = _get_prop(sampler, 'HTTPSampler.port')
        path = _get_prop(sampler, 'HTTPSampler.path') or '/'
        if domain:
            netloc = f'{domain}:{port}' if port else domain
            url = f'{protocol or "http"}://{netloc}{path}'
        else:
            url = path

        step = {
            'type': 'http_request',
            'name': sampler.get('testname') or 'HTTP请求',
            'method': (_get_prop(sampler, 'HTTPSampler.method') or 'GET').upper(),
            'url': url.replace('${base_url}', '{{base_url}}'),
            'headers': self._parse_headers(sampler_tree),
            'params': {},
            'body': self._parse_body(sampler),
            'assertions': self._parse_assertions(sampler_tree),
        }
        return step

    def _parse_headers(self, sampler_tree):
        headers = {}
        if sampler_tree is None:
            return headers
        for manager in sampler_tree.iter('HeaderManager'):
            for header in manager.findall(".//elementProp[@elementType='Header']"):
                name = _get_prop(header, 'Header.name')
                value = _get_prop(header, 'Header.value')
                if name:
                    headers[name] = value
        return headers

    def _parse_assertions(self, sampler_tree):
        assertions = []
        if sampler_tree is None:
            return assertions
        for assertion in sampler_tree.iter('ResponseAssertion'):
            field = _get_prop(assertion, 'Assertion.test_field')
            assertion_type = 'contains'
            if field == 'Assertion.response_code':
                assertion_type = 'response_code'
            for collection in assertion.findall(".//collectionProp[@name='Asserion.test_strings']"):
                for child in collection:
                    value = child.text or child.get('name') or ''
                    if value:
                        assertions.append({
                            'type': assertion_type,
                            'value': value,
                            'name': assertion.get('testname') or '响应断言',
                        })
        return assertions

    def _parse_body(self, sampler):
        post_body_raw = _get_prop(sampler, 'HTTPSampler.postBodyRaw') == 'true'
        if not post_body_raw:
            return ''
        values = []
        for argument in sampler.findall(".//elementProp[@elementType='HTTPArgument']"):
            value = _get_prop(argument, 'Argument.value')
            if value:
                values.append(value)
        return '\n'.join(values)

    def _parse_datasets(self, root, dataset_indexes=None):
        datasets = []
        if root is None:
            return datasets
        dataset_indexes = dataset_indexes or {}
        for dataset in root.iter('CSVDataSet'):
            variables = _get_prop(dataset, 'variableNames') or ''
            item = {
                'name': dataset.get('testname') or 'CSV 数据集',
                'filename': _get_prop(dataset, 'filename'),
                'variables': [item.strip() for item in variables.split(',') if item.strip()],
                'delimiter': _get_prop(dataset, 'delimiter') or ',',
                'ignore_first_line': _get_prop(dataset, 'ignoreFirstLine') == 'true',
            }
            if id(dataset) in dataset_indexes:
                item['jmx_index'] = dataset_indexes[id(dataset)]
            datasets.append(item)
        return datasets

    def _first_attr(self, root, tag, attr):
        for elem in root.iter(tag):
            return elem.get(attr)
        return ''


def _strip_ns(tag):
    return tag.rsplit('}', 1)[-1]


def _get_prop(elem, prop_name):
    if elem is None:
        return ''
    for child in elem:
        if child.get('name') == prop_name:
            return child.text or ''
    return ''


def _int_prop(elem, prop_name, default):
    try:
        return int(_get_prop(elem, prop_name) or default)
    except (TypeError, ValueError):
        return default


def _loop_count(thread_group):
    controller = thread_group.find(".//elementProp[@name='ThreadGroup.main_controller']")
    if controller is None:
        return 1
    if _get_prop(controller, 'LoopController.continue_forever') == 'true':
        return -1
    return _int_prop(controller, 'LoopController.loops', 1)
