import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import AIModelService

t_id = 'TASK_B71FB793'
from apps.requirement_analysis.models import TestCaseGenerationTask
t = TestCaseGenerationTask.objects.get(task_id=t_id)
gen = t.generated_test_cases or ''
final = t.final_test_cases or ''

# Step 1: Extract and merge (simulating what the code does)
orig_header, orig_cases, orig_prefix, orig_suffix = AIModelService.extract_cases_from_markdown_table(gen)
rev_header, rev_cases, rev_prefix, rev_suffix = AIModelService.extract_cases_from_markdown_table(final)

merged_cases = {cid: row for cid, (row, _) in orig_cases.items()}
for case_id, (row, is_del) in rev_cases.items():
    if not is_del:
        merged_cases[case_id] = row

# Reconstruct merged content
output_lines = []
if orig_prefix:
    output_lines.append(orig_prefix)
if orig_header:
    output_lines.extend(orig_header)
for case_id in sorted(merged_cases.keys()):
    output_lines.append(merged_cases[case_id])
if orig_suffix:
    output_lines.append(orig_suffix)

merged_content = '\n'.join(output_lines)

# Step 2: Sort by ID
sorted_content = AIModelService.sort_test_cases_by_id(merged_content)

# Step 3: Renumber
renumbered = AIModelService.renumber_test_cases(sorted_content)

print(f'After merge: {len(merged_cases)} cases')
print(f'Merged content length: {len(merged_content)}')
print(f'Sorted length: {len(sorted_content)}')
print(f'Renumbered length: {len(renumbered)}')

# Count rows in each
for label, content in [('Merged', merged_content), ('Sorted', sorted_content), ('Renumbered', renumbered)]:
    rows = [l for l in content.split('\n') if l.strip().startswith('|') and l.strip() != '|----------|' and '---' not in l]
    # Filter header
    data_rows = [r for r in rows if not any(h in r for h in ['所属模块', '用例ID', '测试目标'])]
    print(f'  {label}: {len(data_rows)} data rows')

# Write for inspection
with open(f'{t_id}_simulated_merge.txt', 'w', encoding='utf-8') as f:
    f.write(renumbered)
