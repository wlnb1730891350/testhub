import django, os, sys
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
django.setup()
from apps.requirement_analysis.models import PromptConfig

configs = PromptConfig.objects.all().order_by('id')
print("=== PromptConfig 列表 ===")
for c in configs:
    print(f"ID={c.id} | prompt_type={c.prompt_type} | name={c.name}")
    print(f"  状态: {'启用' if c.is_active else '禁用'}")
    print()
