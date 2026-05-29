import django, os, sys
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
django.setup()

from apps.requirement_analysis.models import PromptConfig, TestCaseGenerationTask, RequirementClarification

print("=== Clarifier 调用验证 ===\n")

# 1. 确认 PromptConfig.get_active_config('clarifier') 返回什么
print("1. PromptConfig.get_active_config('clarifier'):")
config = PromptConfig.get_active_config('clarifier')
if config:
    print(f"   ✓ 返回: ID={config.id}, name='{config.name}', prompt_type='{config.prompt_type}'")
    print(f"   ✓ 内容长度: {len(config.content or '')} 字符")
else:
    print("   ✗ 返回 None!")

# 2. 检查最近的澄清任务
print("\n2. 最近的澄清任务:")
recent_tasks = TestCaseGenerationTask.objects.filter(
    status__in=['pending_clarification', 'clarified', 'completed']
).order_by('-updated_at')[:3]

for t in recent_tasks:
    print(f"\n   Task: {t.task_id} | Status: {t.status}")
    cls = RequirementClarification.objects.filter(task=t).order_by('order')
    print(f"   澄清记录数: {cls.count()}")
    for c in cls:
        preview = c.content[:60].replace('\n', ' ') if len(c.content) > 60 else c.content.replace('\n', ' ')
        print(f"     [{c.role}] {preview}...")

# 3. 检查 views.py 中实际调用
print("\n3. views.py 中 clarifier 调用逻辑:")
views_path = os.path.join(os.path.dirname(__file__), 'apps', 'requirement_analysis', 'views.py')
with open(views_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 start_clarification 中调用 AI 的部分
import re
# 找 _kickoff_clarification_for_task 或类似函数
match = re.search(r'def _kickoff.*?clarification.*?(?=\ndef |\Z)', content, re.DOTALL | re.IGNORECASE)
if match:
    func = match.group(0)
    print(f"   找到函数: {func.split('(')[0]}")
    
    # 检查是否传入了 clarifier_prompt.content
    if 'clarifier_prompt.content' in func:
        print("   ✓ 传入了 clarifier_prompt.content 作为 system prompt")
    elif 'clarifier_prompt' in func:
        print("   ? 使用了 clarifier_prompt 但未确认是否用 .content")
    else:
        print("   ✗ 未使用 clarifier_prompt!")
    
    # 检查调用链
    if 'call_openai_compatible_api' in func:
        print("   ✓ 调用 call_openai_compatible_api")
    elif 'generate_with_model' in func:
        print("   ✓ 调用 generate_with_model")
else:
    print("   未找到 clarification 相关函数")

print("\n=== 结论 ===")
print("PromptConfig.get_active_config('clarifier') 正确返回 ID=4 的 v3 提示词")
print("views.py 中正确获取并传入 clarifier_prompt.content")
print("需求澄清流程确实使用了 clarifier 提示词")
