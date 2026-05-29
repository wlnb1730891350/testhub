import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

t = TestCaseGenerationTask.objects.get(task_id='TASK_571C7C90')

print("=== TASK_571C7C90 Full Info ===")
print(f"status: {t.status}")
print(f"progress: {t.progress}")
print(f"output_mode: {t.output_mode}")
print(f"generated_test_cases len: {len(t.generated_test_cases) if t.generated_test_cases else 0}")
print(f"final_test_cases len: {len(t.final_test_cases) if t.final_test_cases else 0}")
print(f"review_feedback len: {len(t.review_feedback) if t.review_feedback else 0}")

# Show the actual content of final_test_cases - first 500 chars
if t.final_test_cases:
    print("\n=== final_test_cases first 500 chars ===")
    # Write to file to avoid console encoding issues
    with open('task_571c_preview.txt', 'w', encoding='utf-8') as f:
        f.write(t.final_test_cases[:500])
    print("(written to task_571c_preview.txt)")
    
# Check if parseTestCases would work
if t.final_test_cases:
    content = t.final_test_cases
    lines = content.split('\n')
    table_lines = [l.strip() for l in lines if '|' in l and '---' not in l and l.strip().startswith('|')]
    print(f"\nTable lines count: {len(table_lines)}")
    if table_lines:
        print(f"Header: {table_lines[0]}")
        print(f"First data row: {table_lines[1] if len(table_lines) > 1 else 'N/A'}")
