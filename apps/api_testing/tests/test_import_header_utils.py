from apps.api_testing.import_export.header_utils import normalize_import_headers


def test_normalize_import_headers_filters_saz_like_extra_headers():
    headers = [
        {'name': ':method', 'value': 'GET', 'extra': 'ignored'},
        {'name': ':path', 'value': '/api/user'},
        {'name': 'Host', 'value': 'example.com'},
        {'name': 'Accept', 'value': '*/*'},
        {'name': 'Sec-Fetch-Mode', 'value': 'cors'},
        {'name': 'Authorization', 'value': 'Bearer token', 'type': 'text'},
        {'name': 'Content-Type', 'value': 'application/json', 'system': True},
        {'name': 'X-Trace-Id', 'value': 'abc', 'disabled': True, 'description': 'trace'},
    ]

    normalized = normalize_import_headers(headers)

    assert normalized == [
        {'key': 'Authorization', 'value': 'Bearer token', 'enabled': True, 'description': ''},
        {'key': 'Content-Type', 'value': 'application/json', 'enabled': True, 'description': ''},
        {'key': 'X-Trace-Id', 'value': 'abc', 'enabled': False, 'description': 'trace'},
    ]


def test_normalize_import_headers_filters_dict_input():
    normalized = normalize_import_headers({
        'Host': 'example.com',
        'Content-Length': '12',
        'X-Env': 'test',
    })

    assert normalized == [
        {'key': 'X-Env', 'value': 'test', 'enabled': True, 'description': ''},
    ]
