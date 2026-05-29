import django, os, sys
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

t = TestCaseGenerationTask.objects.filter(task_id='TASK_A8FDF594').first()
if t:
    print(f"Task: {t.task_id}")
    print(f"Title: {t.title}")
    print(f"Status: {t.status}")
    content = t.requirement_text or ''
    if content:
        print(f"Req content chars: {len(content)}")
        # 搜索"隐私"
        if '隐私' in content:
            idx = content.find('隐私')
            print(f"\n*** Found '隐私' at position {idx} ***")
            start = max(0, idx - 100)
            end = min(len(content), idx + 200)
            print(f"Context: ...{content[start:end]}...")
        else:
            print("\n'隐私' NOT found in requirement document")
            # 看看文档有哪些章节/模块
            import re
            headers = re.findall(r'^#{1,3}\s+(.+)$', content, re.MULTILINE)
            print(f"\nDocument headers ({len(headers)}):")
            for h in headers[:30]:
                print(f"  - {h}")
    else:
        print("No linked requirement")
else:
    print("Task not found")
