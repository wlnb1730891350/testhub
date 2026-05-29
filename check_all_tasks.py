import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

tasks = TestCaseGenerationTask.objects.filter(status='completed').order_by('-created_at')

print(f"{'TaskID':<20} {'FinalLen':>10} {'GenLen':>10} {'CaseCount':>10} {'EncodingOK':>12}")
print("-" * 75)

for t in tasks:
    final_len = len(t.final_test_cases) if t.final_test_cases else 0
    gen_len = len(t.generated_test_cases) if t.generated_test_cases else 0
    
    # Check encoding - try to detect if content is garbled
    encoding_ok = "unknown"
    if t.final_test_cases:
        # Check for common garbled patterns (replacement chars)
        content = t.final_test_cases
        # If we see replacement character patterns, it's likely garbled
        if '\ufffd' in content:
            encoding_ok = "GARBLED"
        else:
            # Try to find Chinese characters
            chinese_count = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
            total_printable = sum(1 for c in content if c.isprintable())
            if chinese_count > 5:
                encoding_ok = f"CN:{chinese_count}"
            elif total_printable > 50:
                encoding_ok = "ASCII/EN"
            else:
                encoding_ok = "SHORT/EMPTY"
    
    # Count test cases by counting table rows
    case_count = 0
    if t.final_test_cases:
        lines = t.final_test_cases.split('\n')
        table_lines = [l for l in lines if '|' in l and '---' not in l and l.strip().startswith('|')]
        case_count = max(0, len(table_lines) - 1)  # minus header
    
    print(f"{t.task_id:<20} {final_len:>10} {gen_len:>10} {case_count:>10} {encoding_ok:>12}")
