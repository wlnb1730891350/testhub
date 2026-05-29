import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask, AIModelService

# Simulate the merge to see what happened
for tid in ['TASK_B71FB793', 'TASK_29851E44']:
    t = TestCaseGenerationTask.objects.get(task_id=tid)
    gen = t.generated_test_cases or ''
    final = t.final_test_cases or ''
    
    # The revise output is what AI returned during revising phase
    # We don't have it stored separately, but we can check:
    # If merge worked correctly, final should contain all original IDs minus [DELETE] ones
    
    # Let's extract and compare the actual content
    print(f'=== {tid} ===')
    
    # Write generated and final to files for comparison
    with open(f'{tid}_generated.txt', 'w', encoding='utf-8') as f:
        f.write(gen)
    with open(f'{tid}_final.txt', 'w', encoding='utf-8') as f:
        f.write(final)
    
    # Try running merge logic in reverse: what would revised need to look like?
    orig_header, orig_cases, orig_prefix, orig_suffix = AIModelService.extract_cases_from_markdown_table(gen)
    rev_header, rev_cases, rev_prefix, rev_suffix = AIModelService.extract_cases_from_markdown_table(final)
    
    print(f'  Original extracted: {len(orig_cases)} cases')
    print(f'  Final extracted (as if it were revised): {len(rev_cases)} cases')
    print(f'  Original case IDs: {sorted(orig_cases.keys())[:15]}...')
    print(f'  Final case IDs: {sorted(rev_cases.keys())[:15]}...')
    print()

print('Files written for manual inspection')
