import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

# Check the actual generated vs final for new tasks
for tid in ['TASK_B71FB793', 'TASK_29851E44']:
    t = TestCaseGenerationTask.objects.get(task_id=tid)
    
    gen = t.generated_test_cases or ''
    final = t.final_test_cases or ''
    
    # Count rows in generated (AI raw output from writer)
    gen_rows = [l for l in gen.split('\n') if l.strip().startswith('|') and l.strip() != '|----------|' and not l.strip().startswith('| 所属模块')]
    # Count rows in final
    final_rows = [l for l in final.split('\n') if l.strip().startswith('|') and l.strip() != '|----------|' and not l.strip().startswith('| 所属模块')]
    
    print(f'=== {tid} ===')
    print(f'  generated (writer raw): {len(gen_rows)} data rows, {len(gen)} chars')
    print(f'  final (after review+revise): {len(final_rows)} data rows, {len(final)} chars')
    print(f'  Loss: {len(gen) - len(final)} chars ({(1 - len(final)/len(gen))*100:.0f}% reduction)' if gen else 'N/A')
    
    # Show unique case IDs in generated
    import re
    gen_ids = set(re.findall(r'\|[ \t]*([A-Z]+-\d+)[ \t]*\|', gen))
    final_ids = set(re.findall(r'\|[ \t]*([A-Z]+-\d+)[ \t]*\|', final))
    print(f'  Generated IDs: {sorted(gen_ids)[:10]}{"..." if len(gen_ids) > 10 else ""} ({len(gen_ids)} total)')
    print(f'  Final IDs: {sorted(final_ids)[:10]}{"..." if len(final_ids) > 10 else ""} ({len(final_ids)} total)')
    print(f'  IDs in gen but NOT in final: {gen_ids - final_ids}')
    print()
