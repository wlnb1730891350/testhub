import os, sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import pymysql
pymysql.version_info = (2, 2, 1, "final", 0)
pymysql.__version__ = "2.2.1"
pymysql.install_as_MySQLdb()

import django
django.setup()

from apps.requirement_analysis.models import TestCaseGenerationTask

task = TestCaseGenerationTask.objects.order_by('-created_at').first()
if task:
    with open('_task_fields.txt', 'w', encoding='utf-8') as f:
        f.write(f"generated_test_cases length: {len(task.generated_test_cases or '')}\n")
        f.write(f"final_test_cases length: {len(task.final_test_cases or '')}\n")
        f.write(f"review_feedback length: {len(task.review_feedback or '')}\n")
        f.write(f"output_mode: {task.output_mode}\n")
        f.write(f"status: {task.status}\n")
        
        ftc = task.final_test_cases or ''
        f.write(f"\n--- final_test_cases (first 1000 chars) ---\n")
        f.write(ftc[:1000])
        f.write(f"\n--- final_test_cases (last 1000 chars) ---\n")
        f.write(ftc[-1000:])
    print("Written to _task_fields.txt")
else:
    print("No task found")
