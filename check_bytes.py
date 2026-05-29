import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

t = TestCaseGenerationTask.objects.get(task_id='TASK_571C7C90')
if t.final_test_cases:
    content = t.final_test_cases
    print('Content type:', type(content))
    print('First 100 bytes repr:', repr(content[:100]))
    
    # Try to detect encoding
    try:
        encoded = content.encode('latin1')
        print('Re-encoded as latin1:', repr(encoded[:100]))
        decoded = encoded.decode('gbk', errors='replace')
        print('Decoded as GBK:', decoded[:100])
    except Exception as e:
        print('Decode error:', e)
