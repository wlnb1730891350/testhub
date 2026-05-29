import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask, PromptConfig

# 查看新任务的详细信息
task_ids = ['TASK_29851E44', 'TASK_B71FB793', 'TASK_D886C3A5', 'TASK_E42BC4CB', 'TASK_4S757D6E', 'TASK_C5082745', 'TASK_28CE3DB1']
for tid in task_ids:
    try:
        t = TestCaseGenerationTask.objects.get(task_id=tid)
        cases_len = len(t.final_test_cases) if t.final_test_cases else 0
        req_preview = t.requirement_text[:60] if t.requirement_text else '(empty)'
        print(f'{tid} | status={t.status} | cases={cases_len}chars | output_mode={t.output_mode} | created={t.created_at} | req={req_preview}')
    except:
        print(f'{tid} | NOT FOUND')

print('\n--- Writer Prompt ---')
writer_cfg = PromptConfig.get_active_config('writer')
if writer_cfg:
    print(f'ID={writer_cfg.id} | len={len(writer_cfg.content)} | preview={writer_cfg.content[:200]}')
else:
    print('No active writer config')

print('\n--- Clarifier Prompt ---')
clarifier_cfg = PromptConfig.get_active_config('clarifier')
if clarifier_cfg:
    print(f'ID={clarifier_cfg.id} | len={len(clarifier_cfg.content)} | preview={clarifier_cfg.content[:200]}')
else:
    print('No active clarifier config')
