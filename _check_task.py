import os, sys, json

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
    gc = task.generated_test_cases or ''
    rt = task.requirement_text or ''
    
    with open('_task_output.md', 'w', encoding='utf-8') as f:
        f.write(f"# Task: {task.title}\n")
        f.write(f"Task ID: {task.task_id}\n")
        f.write(f"Status: {task.status}\n")
        f.write(f"Generated cases length: {len(gc)}\n")
        f.write(f"Requirement text length: {len(rt)}\n\n")
        f.write("## Requirement Text\n")
        f.write(rt)
        f.write("\n\n## Generated Test Cases\n")
        f.write(gc)
    
    print(f"Written to _task_output.md ({len(gc)} chars)")
else:
    print("No task found")
