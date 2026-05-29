import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

# Focus on the tasks with suspiciously low case counts
suspicious = ['TASK_29851E44', 'TASK_B71FB793', 'TASK_D886C3A5', 'TASK_E42BC4CB']
normal = ['TASK_571C7C90', 'TASK_802E8071', 'TASK_A8FDF594']

print("=== SUSPICIOUS TASKS (low case count) ===")
for tid in suspicious:
    t = TestCaseGenerationTask.objects.get(task_id=tid)
    print(f"\n--- {tid} ---")
    print(f"  final_test_cases len: {len(t.final_test_cases) if t.final_test_cases else 0}")
    print(f"  generated_test_cases len: {len(t.generated_test_cases) if t.generated_test_cases else 0}")
    print(f"  review_feedback len: {len(t.review_feedback) if t.review_feedback else 0}")
    print(f"  status: {t.status}, progress: {t.progress}")
    print(f"  output_mode: {t.output_mode}")
    print(f"  stream_buffer len: {len(t.stream_buffer) if t.stream_buffer else 0}")
    
    # Show first 200 chars of final_test_cases
    if t.final_test_cases:
        print(f"  final_test_cases preview: {repr(t.final_test_cases[:200])}")

print("\n\n=== NORMAL TASKS (good case count) ===")
for tid in normal:
    t = TestCaseGenerationTask.objects.get(task_id=tid)
    print(f"\n--- {tid} ---")
    print(f"  final_test_cases len: {len(t.final_test_cases) if t.final_test_cases else 0}")
    print(f"  generated_test_cases len: {len(t.generated_test_cases) if t.generated_test_cases else 0}")
    print(f"  review_feedback len: {len(t.review_feedback) if t.review_feedback else 0}")
    print(f"  status: {t.status}, progress: {t.progress}")
    print(f"  output_mode: {t.output_mode}")
    print(f"  created_at: {t.created_at}")
