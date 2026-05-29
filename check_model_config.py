import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, '.')
django.setup()
from apps.requirement_analysis.models import AIModelConfig

# Check writer model config (ID=5) - max_tokens and other params
m = AIModelConfig.objects.get(id=5)
print(f'Writer Model Config (ID=5):')
print(f'  model_name: {m.model_name}')
print(f'  base_url: {m.base_url}')
print(f'  max_tokens: {m.max_tokens}')
print(f'  temperature: {m.temperature}')
print(f'  top_p: {m.top_p}')
print(f'  is_active: {m.is_active}')

# Also check all fields
print(f'\nAll fields:')
for f in m._meta.fields:
    val = getattr(m, f.name, None)
    if val is not None:
        print(f'  {f.name}: {val}')
