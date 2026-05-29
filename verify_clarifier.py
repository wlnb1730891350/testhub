import django, os, sys
sys.stdout.reconfigure(encoding='utf-8')
os.environ['DJANGO_SETTINGS_MODULE'] = 'backend.settings'
django.setup()

from apps.requirement_analysis.models import PromptConfig, TestCaseGenerationTask

# 1. 检查 clarifier 提示词内容
print("=== 1. Clarifier PromptConfig (prompt_type=clarifier, is_active=True) ===")
clarifier = PromptConfig.objects.filter(prompt_type='clarifier', is_active=True).first()
if clarifier:
    print(f"ID: {clarifier.id}")
    print(f"Name: {clarifier.name}")
    print(f"Content preview (first 500 chars):")
    print(clarifier.content[:500] if clarifier.content else "(empty)")
    print("\n...")
    print(f"Content last 300 chars:")
    print(clarifier.content[-300:] if clarifier.content and len(clarifier.content) > 300 else clarifier.content)
else:
    print("ERROR: No active clarifier prompt found!")

print("\n" + "="*60)

# 2. 检查 views.py 中 start_clarification 调用逻辑
print("\n=== 2. Checking views.py for clarifier prompt usage ===")
views_path = os.path.join(os.path.dirname(__file__), 'apps', 'requirement_analysis', 'views.py')
if os.path.exists(views_path):
    with open(views_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 查找 clarifier 相关代码
    import re
    
    # 找 start_clarification 函数
    start_clar_match = re.search(r'def start_clarification.*?(?=\ndef |\Z)', content, re.DOTALL)
    if start_clar_match:
        func_content = start_clar_match.group(0)
        print("Found start_clarification function")
        
        # 检查是否获取 clarifier prompt
        if 'clarifier' in func_content.lower() or 'prompt_type' in func_content:
            print("✓ Function references 'clarifier' or 'prompt_type'")
        else:
            print("✗ Function does NOT reference clarifier/prompt_type - BUG!")
        
        # 检查调用链
        if 'get_prompt_config' in func_content or 'PromptConfig' in func_content:
            print("✓ Uses PromptConfig lookup")
        else:
            print("✗ Does NOT use PromptConfig lookup - may be hardcoded!")
            
        # 检查实际调用 AI 的部分
        ai_call_match = re.search(r'(call_openai_compatible_api|generate_with_model|chat\.completions)', func_content)
        if ai_call_match:
            print(f"✓ Found AI call: {ai_call_match.group(1)}")
        else:
            print("? AI call pattern not found in function")
    else:
        print("ERROR: start_clarification function not found!")
        
    # 全局检查 clarifier 字符串出现位置
    print("\n=== 3. All clarifier references in views.py ===")
    for i, line in enumerate(content.split('\n'), 1):
        if 'clarifier' in line.lower():
            print(f"  Line {i}: {line.strip()[:100]}")
else:
    print(f"ERROR: views.py not found at {views_path}")

print("\n" + "="*60)

# 3. 检查最近的澄清任务日志
print("\n=== 4. Recent clarification tasks ===")
recent_tasks = TestCaseGenerationTask.objects.filter(
    status__in=['pending_clarification', 'clarified', 'completed']
).order_by('-updated_at')[:3]

for t in recent_tasks:
    print(f"\nTask: {t.task_id}")
    print(f"  Status: {t.status}")
    print(f"  Clarification rounds: {t.clarification_rounds}")
    # 检查是否有澄清对话记录
    from apps.requirement_analysis.models import RequirementClarification
    cls = RequirementClarification.objects.filter(task=t).order_by('order')
    print(f"  Clarification records: {cls.count()}")
    for c in cls[:3]:
        print(f"    - {c.role}: {c.content[:50]}..." if len(c.content) > 50 else f"    - {c.role}: {c.content}")
