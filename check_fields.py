import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()

# The revising AI output should be stored... somewhere
# Let's check if there's a field for it
from apps.requirement_analysis.models import TestCaseGenerationTask
t = TestCaseGenerationTask.objects.get(task_id='TASK_B71FB793')

# Check all text fields
print('All text fields in task:')
for f in t._meta.fields:
    fname = f.name
    val = getattr(t, fname, None)
    if val and isinstance(val, str) and len(val) > 100:
        print(f'  {fname}: {len(val)} chars')
