import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()

from apps.requirement_analysis.models import TestCaseGenerationTask

t = TestCaseGenerationTask.objects.get(task_id='TASK_B71FB793')

print(f'Task ID: {t.task_id}')
print(f'Status: {t.status}')
print(f'Progress: {t.progress}%')

# Get all field names
field_names = [f.name for f in t._meta.get_fields()]
print(f'\nFields: {field_names}')

# Print all field values
print('\n=== All field values ===')
for field in field_names:
    try:
        value = getattr(t, field)
        if isinstance(value, str) and len(value) > 100:
            print(f'{field}: {len(value)} chars')
        else:
            print(f'{field}: {value}')
    except Exception as e:
        print(f'{field}: ERROR - {e}')
