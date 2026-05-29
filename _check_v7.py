import os, sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
import django
django.setup()
from apps.requirement_analysis.models import PromptConfig
p = PromptConfig.objects.filter(prompt_type='writer').first()
with open("db_content_v7_check.txt", "w", encoding="utf-8") as f:
    f.write(p.content)
print(f"Done: {len(p.content)} chars")
