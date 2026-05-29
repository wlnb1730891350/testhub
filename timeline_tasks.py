import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

# All completed tasks sorted by creation time
tasks = TestCaseGenerationTask.objects.filter(status='completed').order_by('created_at')

print(f"{'CreatedAt':<22} {'TaskID':<20} {'GenLen':>8} {'FinalLen':>8} {'ReviewLen':>10} {'Cases':>6} {'Ratio':>8}")
print("-" * 95)

for t in tasks:
    final_len = len(t.final_test_cases) if t.final_test_cases else 0
    gen_len = len(t.generated_test_cases) if t.generated_test_cases else 0
    rev_len = len(t.review_feedback) if t.review_feedback else 0
    
    # Count cases
    case_count = 0
    if t.final_test_cases:
        lines = t.final_test_cases.split('\n')
        table_lines = [l for l in lines if '|' in l and '---' not in l and l.strip().startswith('|')]
        case_count = max(0, len(table_lines) - 1)
    
    ratio = f"{final_len/gen_len*100:.0f}%" if gen_len > 0 else "N/A"
    
    created = t.created_at.strftime('%m-%d %H:%M') if t.created_at else '?'
    print(f"{created:<22} {t.task_id:<20} {gen_len:>8} {final_len:>8} {rev_len:>10} {case_count:>6} {ratio:>8}")
