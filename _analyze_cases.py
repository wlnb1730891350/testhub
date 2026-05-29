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
    ftc = task.final_test_cases or ''
    with open('_final_cases_full.md', 'w', encoding='utf-8') as f:
        f.write(ftc)
    
    # Count module sections
    import re
    sections = re.findall(r'## (.+)', ftc)
    print(f"Sections found: {sections}")
    print(f"Total chars: {len(ftc)}")
    
    # Count case IDs by prefix
    all_ids = re.findall(r'\|\s*\*{0,2}([A-Z]+-\d+)\*{0,2}\s*\|', ftc)
    from collections import Counter
    prefix_counts = Counter()
    for cid in all_ids:
        prefix = cid.split('-')[0]
        prefix_counts[prefix] += 1
    print(f"\nCase ID counts by prefix:")
    for prefix, count in sorted(prefix_counts.items()):
        print(f"  {prefix}: {count} cases")
    print(f"Total cases: {len(all_ids)}")
    
    # Check for 抽奖 keyword
    lottery_count = ftc.count('抽奖')
    print(f"\n'抽奖' keyword count in final_test_cases: {lottery_count}")
else:
    print("No task found")
