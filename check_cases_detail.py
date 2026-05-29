import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

# 对比新旧任务的 final_test_cases 内容
print('=== OLD: TASK_28CE3DB1 (112 cases, 28718 chars) ===')
t_old = TestCaseGenerationTask.objects.get(task_id='TASK_28CE3DB1')
content_old = t_old.final_test_cases or ''
# 统计表格行数（| 分隔的行）
lines_old = [l for l in content_old.split('\n') if '|' in l and l.strip().startswith('|')]
print(f'Total lines with |: {len(lines_old)}')
print(f'First 500 chars:\n{content_old[:500]}')
print(f'\n...Last 300 chars:\n{content_old[-300:]}')

print('\n\n=== NEW: TASK_B71FB793 (17 cases, 3916 chars) ===')
t_new = TestCaseGenerationTask.objects.get(task_id='TASK_B71FB793')
content_new = t_new.final_test_cases or ''
lines_new = [l for l in content_new.split('\n') if '|' in l and l.strip().startswith('|')]
print(f'Total lines with |: {len(lines_new)}')
print(f'First 800 chars:\n{content_new[:800]}')

print('\n\n=== NEW: TASK_29851E44 (18 cases, 4419 chars) ===')
t_new2 = TestCaseGenerationTask.objects.get(task_id='TASK_29851E44')
content_new2 = t_new2.final_test_cases or ''
lines_new2 = [l for l in content_new2.split('\n') if '|' in l and l.strip().startswith('|')]
print(f'Total lines with |: {len(lines_new2)}')
print(f'First 800 chars:\n{content_new2[:800]}')
