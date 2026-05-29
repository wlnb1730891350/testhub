import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()
from apps.requirement_analysis.models import PromptConfig

# Read v11 prompt
with open('writer_prompt_v11.txt', 'r', encoding='utf-8') as f:
    v11_content = f.read()

# Update the active writer prompt
writer = PromptConfig.objects.filter(prompt_type='writer', is_active=True).first()
if writer:
    old_len = len(writer.content)
    writer.content = v11_content
    writer.name = 'V11-模块防遗漏版本（强制覆盖统计表）'
    writer.save()
    print(f"Writer Prompt updated to V11")
    print(f"Old length: {old_len} chars")
    print(f"New length: {len(v11_content)} chars")
    print(f"New name: {writer.name}")
else:
    print("No active Writer Prompt found")