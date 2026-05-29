# TestHub AI测试用例生成能力升级 - 任务摘要
## 升级时间
2026-05-14 17:40 UTC+8

## 完成的工作

### 1. Prompt 增强
- **docs/tester.md**: 升级为 v2 版本
  - 增加 Chain-of-Thought 测试用例设计方法论（等价类划分、边界值分析、判定表法、场景法）
  - 增加 Few-Shot 示例（登录功能、订单创建功能的高质量用例表格）
  - 增加完整的用例设计规范（独立性、完整性、覆盖维度）
  - 增加需求分解策略（功能点提取、参与者识别、场景拆解、用例规划）
  - 增加输出格式要求和特殊情况处理指南
- **docs/tester_pro.md**: 升级为 v2 版本
  - 增加详细的评审维度评分标准（功能点覆盖率、场景类型覆盖率、逻辑性、规范性、独立性）
  - 增加评分等级标准（A+到D级）
  - 增加致命缺陷/严重问题/常见不足清单
  - 增加精确到用例ID的问题追踪表格

### 2. LLM 提供商扩展（后端）

**models.py** 的 AIModelConfig.MODEL_CHOICES 扩展为 13 个提供商：
- openai, azure_openai, anthropic, google_gemini, ollama, deepseek, qwen, siliconflow, zhipu, baichuan, moonshot, doubao, other

**ai_models.py**: 同步更新 MODEL_CHOICES

### 3. 前端增强
**AIIntelligentModeConfig.vue** 更新：
- 新增 5 个选择框选项: qwen, ollama, baichuan, moonshot, doubao
- 新增 modelBaseUrlMap 默认 Base URL 映射（包括本地 Ollama: http://localhost:11434/v1）

### 4. i18n 国际化
**zh-cn/configuration.js** 和 **en/configuration.js** 同步更新新增提供商的翻译键

### 5. Prompt Engineering 改进
**models.py** 的 generate_test_cases_stream user_message:
- 增加 Chain-of-Thought 思考链指导（功能点提取→参与者识别→场景分类→用例规划）
- 增加质量自检清单（5项检查要点）
- 优化场景扩展库（增加安全测试）
- 优化输出格式

## 备份文件
- docs/tester_backup_20260514.md - 原 tester.md 备份
- docs/tester_pro_backup_20260514.md - 原 tester_pro.md 备份

## 修改的文件
1. apps/requirement_analysis/models.py - AIModelConfig.MODEL_CHOICES
2. apps/requirement_analysis/ai_models.py - 同步更新
3. frontend/src/views/configuration/AIIntelligentModeConfig.vue - 选项和BaseURL
4. frontend/src/locales/lang/zh-cn/configuration.js - i18n中文
5. frontend/src/locales/lang/en/configuration.js - i18n英文
6. docs/tester.md - v2 Prompt
7. docs/tester_pro.md - v2 Prompt