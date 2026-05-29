"""
测试用例批量导入模块
支持 Excel (.xlsx) 和 CSV 文件解析、字段映射、数据验证、批量创建
"""
import csv
import io
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Excel 解析（可选依赖）
try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from apps.testcases.models import TestCase

# ==================== 字段映射 ====================

# 标准字段 → 模型字段
FIELD_MAPPING = {
    'title': 'title',
    '标题': 'title',
    '用例标题': 'title',
    '用例名称': 'title',
    '名称': 'title',
    'description': 'description',
    '描述': 'description',
    '用例描述': 'description',
    'preconditions': 'preconditions',
    '前置条件': 'preconditions',
    'steps': 'steps',
    '操作步骤': 'steps',
    '步骤': 'steps',
    '操作': 'steps',
    'expected_result': 'expected_result',
    '预期结果': 'expected_result',
    '预期': 'expected_result',
    'priority': 'priority',
    '优先级': 'priority',
    'test_type': 'test_type',
    '测试类型': 'test_type',
    '类型': 'test_type',
    'module': 'module',
    '模块': 'module',
    '所属模块': 'module',
    'status': 'status',
    '状态': 'status',
    'tags': 'tags',
    '标签': 'tags',
}

# 优先级标准化
PRIORITY_MAP = {
    'p0': 'critical', '紧急': 'critical', 'critical': 'critical', '最高': 'critical',
    'p1': 'high', '高': 'high', 'high': 'high',
    'p2': 'medium', '中': 'medium', 'medium': 'medium', '中等': 'medium', '普通': 'medium',
    'p3': 'low', '低': 'low', 'low': 'low', '最低': 'low',
    # 数字优先级
    '1': 'critical', '2': 'high', '3': 'medium', '4': 'low',
}

# 测试类型标准化
TYPE_MAP = {
    '功能测试': 'functional', '功能': 'functional', 'functional': 'functional',
    '集成测试': 'integration', '集成': 'integration', 'integration': 'integration',
    'api测试': 'api', 'api': 'api', '接口测试': 'api', '接口': 'api',
    'ui测试': 'ui', 'ui': 'ui', '界面测试': 'ui', '界面': 'ui',
    '性能测试': 'performance', '性能': 'performance', 'performance': 'performance',
    '安全测试': 'security', '安全': 'security', 'security': 'security',
}

# 状态标准化
STATUS_MAP = {
    '草稿': 'draft', 'draft': 'draft',
    '激活': 'active', 'active': 'active', '有效': 'active', '启用': 'active',
    '废弃': 'deprecated', 'deprecated': 'deprecated', '停用': 'deprecated', '作废': 'deprecated',
}


def parse_excel(file_content: bytes, filename: str = '') -> list[dict]:
    """解析 Excel 文件，返回原始行数据列表"""
    if not HAS_OPENPYXL:
        raise ImportError("需要安装 openpyxl: pip install openpyxl")

    wb = openpyxl.load_workbook(io.BytesIO(file_content), read_only=True, data_only=True)
    ws = wb.active

    rows = []
    headers = None
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            # 第一行作为表头
            headers = [str(c).strip() if c else f'col_{j}' for j, c in enumerate(row)]
            continue
        if headers:
            row_dict = {}
            for j, cell in enumerate(row):
                if j < len(headers):
                    val = cell
                    if val is None:
                        val = ''
                    elif isinstance(val, (int, float)):
                        val = str(val)
                    row_dict[headers[j]] = str(val).strip()
            # 跳过完全空行
            if any(v for v in row_dict.values()):
                rows.append(row_dict)

    wb.close()
    return rows


def parse_csv(file_content: bytes, filename: str = '') -> list[dict]:
    """解析 CSV 文件，返回原始行数据列表"""
    # 尝试不同编码
    for encoding in ['utf-8', 'gbk', 'gb2312', 'utf-8-sig']:
        try:
            text = file_content.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        text = file_content.decode('utf-8', errors='replace')

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        # 清理键值对
        cleaned = {k.strip(): (v.strip() if v else '') for k, v in row.items() if k}
        if any(cleaned.values()):
            rows.append(cleaned)
    return rows


def auto_map_columns(raw_headers: list[str]) -> dict[str, str]:
    """自动映射原始表头到标准字段"""
    mapping = {}
    for header in raw_headers:
        normalized = header.lower().strip()
        if normalized in FIELD_MAPPING:
            mapping[header] = FIELD_MAPPING[normalized]
        else:
            # 模糊匹配
            for key, field in FIELD_MAPPING.items():
                if key in normalized or normalized in key:
                    mapping[header] = field
                    break
    return mapping


def standardize_priority(value: str) -> str:
    """标准化优先级"""
    return PRIORITY_MAP.get(value.lower().strip(), 'medium')


def standardize_type(value: str) -> str:
    """标准化测试类型"""
    return TYPE_MAP.get(value.lower().strip(), 'functional')


def standardize_status(value: str) -> str:
    """标准化状态"""
    return STATUS_MAP.get(value.lower().strip(), 'draft')


def validate_row(row: dict, index: int) -> tuple[bool, list[str]]:
    """验证单行数据，返回 (是否有效, 错误列表)"""
    errors = []
    if not row.get('title'):
        errors.append(f"第{index+1}行: 缺少标题")
    if not row.get('expected_result'):
        errors.append(f"第{index+1}行: 缺少预期结果")
    return len(errors) == 0, errors


def parse_import_file(file_content: bytes, filename: str, column_mapping: Optional[dict] = None) -> dict:
    """
    解析导入文件，返回结构化数据
    
    Returns:
        {
            'headers': [...],           # 原始表头
            'mapped_fields': {...},     # 映射关系 {原始列名: 标准字段名}
            'rows': [...],              # 标准化后的行数据
            'total_rows': int,
            'preview': [...],           # 前10行预览
        }
    """
    # 根据文件类型解析
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('xlsx', 'xls'):
        raw_rows = parse_excel(file_content, filename)
    elif ext == 'csv':
        raw_rows = parse_csv(file_content, filename)
    else:
        raise ValueError(f"不支持的文件格式: {ext}，请上传 .xlsx 或 .csv 文件")

    if not raw_rows:
        raise ValueError("文件为空或无有效数据行")

    # 获取表头
    headers = list(raw_rows[0].keys())

    # 字段映射
    if column_mapping:
        mapped = column_mapping
    else:
        mapped = auto_map_columns(headers)

    # 标准化每行数据
    standardized = []
    for i, raw_row in enumerate(raw_rows):
        row = {}
        for raw_header, std_field in mapped.items():
            val = raw_row.get(raw_header, '')
            if std_field == 'priority':
                val = standardize_priority(val)
            elif std_field == 'test_type':
                val = standardize_type(val)
            elif std_field == 'status':
                val = standardize_status(val)
            elif std_field == 'tags':
                val = [t.strip() for t in re.split(r'[,，;；|/]', val) if t.strip()] if val else []
            row[std_field] = val
        # 确保必需字段存在
        row.setdefault('title', '')
        row.setdefault('description', '')
        row.setdefault('preconditions', '')
        row.setdefault('steps', '')
        row.setdefault('expected_result', '')
        row.setdefault('priority', 'medium')
        row.setdefault('test_type', 'functional')
        row.setdefault('module', '')
        row.setdefault('status', 'draft')
        row.setdefault('tags', [])
        standardized.append(row)

    return {
        'headers': headers,
        'mapped_fields': mapped,
        'rows': standardized,
        'total_rows': len(standardized),
        'preview': standardized[:10],
    }


def batch_import_test_cases(rows: list[dict], project, author) -> dict:
    """
    批量创建测试用例
    
    Returns:
        {
            'success_count': int,
            'error_count': int,
            'errors': [...],
            'created_ids': [...],
        }
    """
    created = []
    errors = []

    for i, row in enumerate(rows):
        try:
            # 验证
            valid, row_errors = validate_row(row, i)
            if not valid:
                errors.extend(row_errors)
                continue

            # 创建用例
            tc = TestCase.objects.create(
                project=project,
                title=row['title'],
                description=row.get('description', ''),
                preconditions=row.get('preconditions', ''),
                steps=row.get('steps', ''),
                expected_result=row['expected_result'],
                priority=row.get('priority', 'medium'),
                test_type=row.get('test_type', 'functional'),
                module=row.get('module', ''),
                status=row.get('status', 'draft'),
                tags=row.get('tags', []),
                author=author,
            )
            created.append(tc.id)
        except Exception as e:
            errors.append(f"第{i+1}行创建失败: {str(e)}")

    return {
        'success_count': len(created),
        'error_count': len(errors),
        'errors': errors,
        'created_ids': created,
    }
