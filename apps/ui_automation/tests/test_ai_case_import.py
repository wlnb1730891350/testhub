from apps.ui_automation.views.ai import AICaseViewSet


def test_markdown_import_ignores_section_headings_when_case_ids_exist():
    content = """# Community AI Cases

## \u4e00\u3001\u9996\u9875

### COM-001 \u8fdb\u5165\u9996\u9875
1. \u8bbf\u95ee\u793a\u4f8b\u5730\u5740

## \u4e8c\u3001\u641c\u7d22

### COM-002 \u641c\u7d22\u7a7a\u7ed3\u679c
1. \u8f93\u5165\u4e0d\u5b58\u5728\u7684\u5173\u952e\u8bcd
"""

    blocks = AICaseViewSet._extract_markdown_cases(content)

    assert len(blocks) == 2
    assert blocks[0].startswith('### COM-001')
    assert blocks[1].startswith('### COM-002')


def test_markdown_import_keeps_heading_split_for_unstructured_documents():
    content = """# Login
1. Open login page

## Submit
1. Submit credentials
"""

    blocks = AICaseViewSet._extract_markdown_cases(content)

    assert len(blocks) == 2
    assert blocks[0].startswith('# Login')
    assert blocks[1].startswith('## Submit')
