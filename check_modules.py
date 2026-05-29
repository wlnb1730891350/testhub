import django, os, json, re, sys
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

# 查最新任务
t = TestCaseGenerationTask.objects.all().order_by('-created_at').first()
if not t:
    print("No tasks found")
    exit()

print(f"=== Task: {t.task_id} | status: {t.status} ===")
content = t.final_test_cases or t.generated_test_cases or ''

# 提取模块：查找 markdown 表格中 |所属模块|xxx| 或 |模块|xxx| 的模式
modules = set()
# 匹配表格行: |模块名|用例ID|...
for m in re.finditer(r'^\|\s*(\S[^\|]{0,30}?)\s*\|\s*(\w+-\d+)', content, re.MULTILINE):
    mod = m.group(1).strip()
    if mod and mod not in ('所属模块', '模块', 'Module', '---'):
        modules.add(mod)

print(f"Total chars: {len(content)}")
print(f"Modules ({len(modules)}): {sorted(modules)}")

# 检查是否有"隐私"
has_privacy = any('隐私' in m for m in modules)
print(f"Has '隐私' module: {has_privacy}")

# 如果没有，看看前几行内容
if not has_privacy:
    lines = content.split('\n')[:15]
    print("\n--- First 15 lines ---")
    for i, line in enumerate(lines):
        print(f"  {i}: {line}")
