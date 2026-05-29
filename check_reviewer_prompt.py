import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from apps.requirement_analysis.models import PromptConfig

# Get the reviewer prompt (used for revising)
reviewer = PromptConfig.objects.filter(prompt_type='reviewer', is_active=True).first()
if reviewer:
    print(f"=== Reviewer Prompt (ID={reviewer.id}) ===")
    print(f"Name: {reviewer.name}")
    # Check available fields
    print(f"Available fields: {[f.name for f in PromptConfig._meta.fields]}")
    
    # Get content from the correct field
    content = reviewer.prompt_template if hasattr(reviewer, 'prompt_template') else reviewer.content
    if content:
        print(f"Length: {len(content)} chars")
        # Write to file to avoid encoding issues
        with open('reviewer_prompt_content.txt', 'w', encoding='utf-8') as f:
            f.write(content)
        print("(Content written to reviewer_prompt_content.txt)")
    else:
        print("No content found")
else:
    print("No active reviewer prompt found")