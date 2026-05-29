import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import PromptConfig, AIModelConfig

print('=== All PromptConfigs ===')
for p in PromptConfig.objects.all().order_by('id'):
    fields = [f for f in ['prompt_type', 'name', 'config_type'] if hasattr(p, f)]
    info = f'ID={p.id} | active={p.is_active} | len={len(p.content) if p.content else 0}'
    for f in fields:
        val = getattr(p, f, None)
        if val: info += f' | {f}={val}'
    print(info)

print('\n=== Active AI Model Configs ===')
for m in AIModelConfig.objects.filter(is_active=True).order_by('id'):
    print(f'ID={m.id} | role={m.role} | model={m.model_name} | base_url={m.base_url}')
