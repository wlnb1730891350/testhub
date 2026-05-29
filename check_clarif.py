import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import RequirementClarification

clarifications = RequirementClarification.objects.filter(task__task_id='TASK_B71FB793').order_by('order')
for c in clarifications:
    preview = c.content[:200] if c.content else '(empty)'
    print(f'ID={c.id} | role={c.role} | order={c.order} | content={preview}')
print(f'Total: {len(clarifications)} records')
