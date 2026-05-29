import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

# Check new task details - especially stream_buffer vs final_test_cases
for tid in ['TASK_B71FB793', 'TASK_29851E44']:
    t = TestCaseGenerationTask.objects.get(task_id=tid)
    print(f'=== {tid} ===')
    print(f'  status: {t.status}')
    print(f'  final_test_cases len: {len(t.final_test_cases) if t.final_test_cases else 0}')
    print(f'  generated_test_cases len: {len(t.generated_test_cases) if t.generated_test_cases else 0}')
    print(f'  stream_buffer len: {len(t.stream_buffer) if t.stream_buffer else 0}')
    print(f'  stream_position: {t.stream_position}')
    print(f'  review_feedback len: {len(t.review_feedback) if t.review_feedback else 0}')
    
    # Count table rows in final_test_cases
    fc = t.final_test_cases or ''
    rows = [l for l in fc.split('\n') if l.strip().startswith('|') and l.strip() != '|----------|']
    print(f'  table rows (final): {len(rows)}')
    
    # Show first few rows of module column to see coverage
    for i, row in enumerate(rows[:5]):
        cells = [c.strip() for c in row.split('|')[1:-1]]
        module = cells[0] if cells else '?'
        case_id = cells[1] if len(cells) > 1 else '?'
        print(f'    row{i}: module={module}, id={case_id}')
    print()
