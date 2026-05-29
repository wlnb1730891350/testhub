import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask, AIModelService

# Deep dive: simulate the exact merge that happened
t = TestCaseGenerationTask.objects.get(task_id='TASK_B71FB793')
gen = t.generated_test_cases or ''
final = t.final_test_cases or ''

orig_header, orig_cases, orig_prefix, orig_suffix = AIModelService.extract_cases_from_markdown_table(gen)
rev_header, rev_cases, rev_prefix, rev_suffix = AIModelService.extract_cases_from_markdown_table(final)

print('=== Original (generated) cases ===')
print(f'Total: {len(orig_cases)}')
for cid in sorted(orig_cases.keys()):
    row, is_del = orig_cases[cid]
    # Show module from first cell
    cells = [c.strip() for c in row.split('|')[1:-1]]
    mod = cells[0] if cells else '?'
    print(f'  {cid}: module={mod}')

print(f'\n=== Final (as revised) cases ===')
print(f'Total: {len(rev_cases)}')
for cid in sorted(rev_cases.keys()):
    row, is_del = rev_cases[cid]
    cells = [c.strip() for c in row.split('|')[1:-1]]
    mod = cells[0] if cells else '?'
    print(f'  {cid}: module={mod}, delete={is_del}')

# Check overlap
orig_ids = set(orig_cases.keys())
rev_ids = set(rev_cases.keys())
overlap = orig_ids & rev_ids
only_orig = orig_ids - rev_ids
only_rev = rev_ids - orig_ids

print(f'\n=== Overlap analysis ===')
print(f'Overlap (in both): {len(overlap)} -> {sorted(overlap)}')
print(f'Only in original (should be preserved): {len(only_orig)} -> {sorted(only_orig)[:20]}...')
print(f'Only in revised (treated as new): {len(only_rev)} -> {sorted(only_rev)}')

# Simulate what the merge WOULD produce
merged = {cid: row for cid, (row, _) in orig_cases.items()}
mod_count = 0
new_count = 0
del_count = 0
for cid, (row, is_del) in rev_cases.items():
    if is_del:
        if cid in merged:
            del merged[cid]
            del_count += 1
    else:
        if cid in merged:
            mod_count += 1
        else:
            new_count += 1
        merged[cid] = row

print(f'\n=== Simulated merge result ===')
print(f'Original: {len(orig_cases)}')
print(f'Modified: {mod_count}')
print(f'New: {new_count}')
print(f'Deleted: {del_count}')
print(f'Untouched (preserved): {len(orig_cases) - mod_count - del_count}')
print(f'Final total: {len(merged)}')

# But the ACTUAL final has only 17 rows...
actual_final_rows = len([l for l in final.split('\n') if l.strip().startswith('|') and l.strip() != '|----------|' and not l.strip().startswith('| 所属')])
print(f'\n*** ACTUAL final_test_cases rows: {actual_final_rows} ***')
print(f'*** Simulated merge would give: {len(merged)} ***')
print(f'*** MISMATCH! Something else is wrong. ***')
