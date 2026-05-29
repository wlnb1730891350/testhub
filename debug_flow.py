import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()

from apps.requirement_analysis.models import TestCaseGenerationTask, AIModelService

t = TestCaseGenerationTask.objects.get(task_id='TASK_B71FB793')
gen = t.generated_test_cases or ''
final = t.final_test_cases or ''

# Step by step with output inspection
print('=== Step 1: Generated cases ===')
orig_header, orig_cases, _, _ = AIModelService.extract_cases_from_markdown_table(gen)
print(f'Count: {len(orig_cases)}')

print('\n=== Step 2: Revised (AI output) ===')
rev_header, rev_cases, _, _ = AIModelService.extract_cases_from_markdown_table(final)
print(f'Count: {len(rev_cases)}')
print(f'IDs: {sorted(rev_cases.keys())}')

print('\n=== Step 3: Merge ===')
merge_result = AIModelService.merge_revised_cases(gen, final)
merged = merge_result['merged_content']
print(f'Length: {len(merged)} chars')
print(f'Stats: {merge_result["stats"]}')

# Write merged to file for inspection
with open('debug_merged.txt', 'w', encoding='utf-8') as f:
    f.write(merged)
print('Wrote merged to debug_merged.txt')

print('\n=== Step 4: Sort ===')
sorted_result = AIModelService.sort_test_cases_by_id(merged)
print(f'Length: {len(sorted_result)} chars')
# Check if sorted is same as merged
if sorted_result == merged:
    print('Sorted == Merged (no change)')
else:
    print('Sorted != Merged (CHANGED!)')

# Write sorted to file
with open('debug_sorted.txt', 'w', encoding='utf-8') as f:
    f.write(sorted_result)
print('Wrote sorted to debug_sorted.txt')

print('\n=== Step 5: Renumber ===')
renumbered = AIModelService.renumber_test_cases(sorted_result)
print(f'Length: {len(renumbered)} chars')

# Write renumbered to file
with open('debug_renumbered.txt', 'w', encoding='utf-8') as f:
    f.write(renumbered)
print('Wrote renumbered to debug_renumbered.txt')

# Final comparison
print(f'\n=== Comparison ===')
print(f'Merged: {len(merged)} chars')
print(f'Sorted: {len(sorted_result)} chars')
print(f'Renumbered: {len(renumbered)} chars')
print(f'DB actual: {len(final)} chars')
