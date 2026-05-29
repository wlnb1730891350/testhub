import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()

from apps.requirement_analysis.models import TestCaseGenerationTask

t = TestCaseGenerationTask.objects.get(task_id='TASK_B71FB793')

print(f'Task ID: {t.task_id}')
print(f'Status: {t.status}')
print(f'Progress: {t.progress}%')
print(f'Enable auto review: {t.enable_auto_review}')
print(f'Reviewer model config: {t.reviewer_model_config}')
print(f'Reviewer prompt config: {t.reviewer_prompt_config}')
print(f'Generated cases length: {len(t.generated_test_cases or "")}')
print(f'Review feedback length: {len(t.review_feedback or "")}')
print(f'Final cases length: {len(t.final_test_cases or "")}')
print(f'Created at: {t.created_at}')
print(f'Updated at: {t.updated_at}')
