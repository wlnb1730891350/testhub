import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import PromptConfig, TestCaseGenerationTask

# Writer prompt full content
w = PromptConfig.objects.get(id=1)
print('=== WRITER PROMPT (ID=1) ===')
print(w.content)
print(f'\n=== END ({len(w.content)} chars) ===')

# Check if old tasks used same writer prompt
print('\n\n=== Task prompt config IDs ===')
for tid in ['TASK_28CE3DB1', 'TASK_C5082745', 'TASK_D886C3A5', 'TASK_B71FB793', 'TASK_29851E44']:
    t = TestCaseGenerationTask.objects.filter(task_id=tid).first()
    if t:
        print(f'{tid} | writer_prompt={t.writer_prompt_config_id} | writer_model={t.writer_model_config_id} | created={t.created_at}')
