import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from apps.requirement_analysis.models import PromptConfig

# Get the writer prompt
writer = PromptConfig.objects.filter(prompt_type='writer', is_active=True).first()
if writer:
    print(f"=== Writer Prompt (ID={writer.id}) ===")
    print(f"Name: {writer.name}")
    print(f"Length: {len(writer.content)} chars")
    
    with open('writer_prompt_content.txt', 'w', encoding='utf-8') as f:
        f.write(writer.content)
    print("(Content written to writer_prompt_content.txt)")
else:
    print("No active writer prompt found")