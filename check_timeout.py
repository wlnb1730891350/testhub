import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import TestCaseGenerationTask

# Check: maybe the issue is that revised_cases (the actual AI output from revising phase)
# is different from final_test_cases. Let's check if there's a timeout happening.

t = TestCaseGenerationTask.objects.get(task_id='TASK_B71FB793')

print('Task status flow analysis:')
print(f'  Current status: {t.status}')
print(f'  generated_test_cases len: {len(t.generated_test_cases or "")}')
print(f'  final_test_cases len: {len(t.final_test_cases or "")}')
print(f'  review_feedback len: {len(t.review_feedback or "")}')

# The key question: is final_test_cases the result of merge, 
# or is it the raw output from the revising AI (because of timeout/fallback)?
gen_len = len(t.generated_test_cases or '')
final_len = len(t.final_test_cases or '')

# If the revising AI returned ~4000 chars and it's similar to final,
# then final IS the revising AI output (not merged)
# If final should be ~10000+ (merge of 9490 gen + some new), but it's only 3916,
# then either:
# 1. Timeout occurred -> fell back to something unexpected
# 2. The revise AI returned a complete rewrite (not incremental) 
#    AND the code path saved it directly without merge

print(f'\n\nHypothesis check:')
print(f'  generated (writer): {gen_len} chars')
print(f'  review_feedback: {len(t.review_feedback or "")} chars')  
print(f'  final: {final_len} chars')
print(f'  Is final closer to review ({len(t.review_feedback or "")}) than to generated ({gen_len})? ')
print(f'    |final - review| = {abs(final_len - len(t.review_feedback or ""))}')
print(f'    |final - generated| = {abs(final_len - gen_len)}')

# Most likely: the revising phase TIMED OUT (review_timeout=120s)
# and the fallback logic has a bug
print(f'\n  *** If timeout=120s and revising took longer, ***')
print(f'  *** the code falls back to "revised_cases = generated_cases" ***')
print(f'  *** BUT then still runs merge! That would be: merge(gen, gen) = gen ***')
print(f'  *** But final is much shorter than gen... ***')
