import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import PromptConfig, TestCaseGenerationTask

# Writer prompt -> file
w = PromptConfig.objects.get(id=1)
with open('writer_prompt_current.txt', 'w', encoding='utf-8') as f:
    f.write(w.content)

# Task prompt config IDs
with open('task_prompt_ids.txt', 'w', encoding='utf-8') as f:
    for tid in ['TASK_28CE3DB1', 'TASK_C5082745', 'TASK_D886C3A5', 'TASK_B71FB793', 'TASK_29851E44']:
        t = TestCaseGenerationTask.objects.filter(task_id=tid).first()
        if t:
            f.write(f'{tid} | writer_prompt={t.writer_prompt_config_id} | writer_model={t.writer_model_config_id} | created={t.created_at}\n')

print('Done - check writer_prompt_current.txt and task_prompt_ids.txt')
