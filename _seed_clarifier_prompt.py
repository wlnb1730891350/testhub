import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
sys.path.insert(0, r'C:\Users\a\.qclaw\workspace\testhub_platform')
django.setup()

from apps.requirement_analysis.models import PromptConfig
from django.contrib.auth import get_user_model

U = get_user_model()
admin = U.objects.filter(is_superuser=True).first()
print('admin:', admin)

content = '''你是资深测试架构师，负责在为需求生成测试用例之前对需求文档进行严谨的评审与澄清。

【你的目标】
1. 仔细阅读用户提供的需求文档，识别其中存在的：
   - 关键信息缺失（如：边界值、错误处理策略、性能指标、安全要求、用户角色权限、数据规则等）
   - 表述歧义或矛盾点
   - 隐含假设（用户未说但需要确认才能写测试用例的点）
   - 异常分支与极端场景遗漏
2. 通过多轮对话与用户澄清这些问题，每轮只问 3-6 个最关键的问题，避免一次抛太多让用户疲惫。
3. 当用户回答足够清晰、足以支撑测试用例编写时，必须在回复的最后单独成行输出标记：
   [CLARIFICATION_DONE]
   并简短总结已澄清的关键点。否则不要输出该标记。

【输出规范】
- 用中文回复。
- 使用 Markdown 编号列表组织问题，每个问题简短聚焦、便于用户逐条作答。
- 不要在澄清阶段生成任何测试用例，也不要给出长篇推理过程。
- 如果用户表示"信息已充分"或"直接生成"，立即输出 [CLARIFICATION_DONE] 并简短总结。
'''

obj, created = PromptConfig.objects.update_or_create(
    prompt_type='clarifier',
    name='默认需求澄清提示词 v1',
    defaults={'content': content, 'is_active': True, 'created_by': admin},
)
print('created:', created, 'id:', obj.id, 'is_active:', obj.is_active)
print('active clarifier:', PromptConfig.get_active_config('clarifier'))
