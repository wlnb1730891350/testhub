# Check the exact code structure around the merge + save logic
# The issue might be that task.save() is called but the value was already overwritten

# Let's trace the exact flow:
# 1. final_callback writes to task.final_test_cases during streaming (AI's raw output, 17 cases)
# 2. revise_test_cases_based_on_review returns the full content (17 cases)
# 3. merge_revised_cases merges generated (55) + revised (17) = merged (59 cases)
# 4. renumber_test_cases processes merged (59) -> should return 59
# 5. task.final_test_cases = renumbered_cases (59)
# 6. task.save() saves to DB

# But the DB has only 17 cases...

# POSSIBILITY 1: renumber_test_cases returns empty/wrong content
# POSSIBILITY 2: There's an exception between merge and save
# POSSIBILITY 3: The streaming callback saved to DB before merge, and merge failed silently

# Let's check the actual values at runtime
import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()

from apps.requirement_analysis.models import TestCaseGenerationTask, AIModelService

t = TestCaseGenerationTask.objects.get(task_id='TASK_B71FB793')
gen = t.generated_test_cases or ''
final = t.final_test_cases or ''

# Simulate the EXACT flow from views.py
print('=== Simulating views.py flow ===')

# Step 1: parse generated
orig_header, orig_cases, orig_prefix, orig_suffix = AIModelService.extract_cases_from_markdown_table(gen)
print(f'1. Generated: {len(orig_cases)} cases')

# Step 2: parse final (this is what revising AI returned)
rev_header, rev_cases, rev_prefix, rev_suffix = AIModelService.extract_cases_from_markdown_table(final)
print(f'2. Revised (AI output): {len(rev_cases)} cases')

# Step 3: merge
merge_result = AIModelService.merge_revised_cases(gen, final)
merged = merge_result['merged_content']
stats = merge_result['stats']
print(f'3. Merged: {stats["final_count"]} cases (original={stats["original_count"]}, revised={stats["revised_count"]})')
print(f'   Modified={stats["modified_count"]}, New={stats["new_count"]}, Deleted={stats["deleted_count"]}')

# Step 4: sort
sorted_result = AIModelService.sort_test_cases_by_id(merged)
print(f'4. Sorted: {len(sorted_result)} chars')

# Step 5: renumber
renumbered = AIModelService.renumber_test_cases(sorted_result)
print(f'5. Renumbered: {len(renumbered)} chars')

# Count actual rows
rows = [l for l in renumbered.split('\n') if l.strip().startswith('|') and '---' not in l and '所属模块' not in l]
print(f'6. Final rows: {len(rows)}')

# Compare to actual DB value
print(f'\n=== DB actual: {len(final)} chars, {len([l for l in final.split("\\n") if l.strip().startswith("|") and "---" not in l and "所属模块" not in l])} rows ===')
