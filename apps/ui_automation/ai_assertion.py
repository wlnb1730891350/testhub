"""
AI智能断言服务
用户只需用自然语言描述期望的页面状态，AI自动截图+分析DOM来判断通过/失败
"""
import base64
import json
import logging
import httpx
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)


class AIAssertionService:
    """AI智能断言服务"""

    @staticmethod
    async def get_ai_config():
        """获取AI模型配置"""
        from asgiref.sync import sync_to_async
        from apps.requirement_analysis.models import AIModelConfig
        # Prefer writer model (more likely to be available), fallback to any active
        config = await sync_to_async(
            lambda: AIModelConfig.objects.filter(is_active=True, role='writer').first()
            or AIModelConfig.objects.filter(is_active=True).first()
        )()
        if not config:
            raise ValueError("未配置AI模型，请在需求分析模块中配置AI模型")
        return config

    @staticmethod
    async def ai_assert(
        page,
        assertion_text: str,
        screenshot_base64: Optional[str] = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        AI智能断言

        Args:
            page: Playwright page对象
            assertion_text: 自然语言断言描述，如"页面显示登录成功"
            screenshot_base64: 可选的截图base64，如果不提供会自动截图

        Returns:
            (是否通过, 日志信息, 截图base64)
        """
        try:
            config = await AIAssertionService.get_ai_config()

            # 1. 截图
            if not screenshot_base64:
                screenshot_bytes = await page.screenshot()
                screenshot_base64 = f"data:image/png;base64,{base64.b64encode(screenshot_bytes).decode()}"

            # 2. 获取页面关键信息
            page_info = await page.evaluate("""() => {
                const getTextContent = (selector) => {
                    try {
                        const el = document.querySelector(selector);
                        return el ? el.innerText.trim().substring(0, 500) : '';
                    } catch { return ''; }
                };

                const body = document.body;
                const visibleText = body ? body.innerText.trim().substring(0, 3000) : '';

                // 获取所有可见的文本元素
                const textElements = Array.from(document.querySelectorAll(
                    'h1, h2, h3, h4, h5, h6, p, span, a, button, label, td, th, li, div > text'
                )).filter(el => {
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' && style.visibility !== 'hidden' && el.innerText.trim();
                }).slice(0, 100).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    text: el.innerText.trim().substring(0, 200),
                    id: el.id || '',
                    className: el.className ? el.className.substring(0, 100) : ''
                }));

                // 获取表单元素
                const formElements = Array.from(document.querySelectorAll(
                    'input, select, textarea'
                )).filter(el => {
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none';
                }).slice(0, 30).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    value: el.value || '',
                    placeholder: el.placeholder || '',
                    id: el.id || '',
                    name: el.name || ''
                }));

                // 检查是否有错误信息
                const errorElements = Array.from(document.querySelectorAll(
                    '.error, .alert-danger, .alert-error, [class*=error], [class*=danger], .el-message--error'
                )).map(el => el.innerText.trim()).filter(Boolean);

                return {
                    url: window.location.href,
                    title: document.title,
                    visibleText: visibleText,
                    textElements: textElements,
                    formElements: formElements,
                    errorElements: errorElements,
                    bodyClasses: body ? body.className : ''
                };
            }""")

            # 3. 构建AI prompt
            screenshot_data = screenshot_base64.split(",")[1] if "," in screenshot_base64 else screenshot_base64

            prompt = f"""你是一个UI自动化测试断言专家。请根据以下信息判断断言是否通过。

## 断言描述
{assertion_text}

## 当前页面信息
- URL: {page_info.get("url", "")}
- 标题: {page_info.get("title", "")}

## 页面可见文本（前3000字符）
{page_info.get("visibleText", "")[:3000]}

## 页面文本元素
{json.dumps(page_info.get("textElements", [])[:50], ensure_ascii=False, indent=2)}

## 表单元素
{json.dumps(page_info.get("formElements", [])[:20], ensure_ascii=False, indent=2)}

## 错误信息
{json.dumps(page_info.get("errorElements", []), ensure_ascii=False)}

请严格按照以下JSON格式返回：
{{
    "passed": true或false,
    "reason": "判断原因的简要说明",
    "evidence": "找到的具体证据（页面上的实际文本或状态）"
}}

注意：
1. 只返回JSON，不要有其他内容
2. passed为true表示断言通过，false表示断言失败
3. reason要简洁说明为什么通过或失败
4. evidence要引用页面上实际存在的文本或状态"""

            # 4. 调用AI
            messages = [
                {
                    "role": "user",
                    "content": prompt
                }
            ]

            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{config.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {config.api_key}"},
                    json={
                        "model": config.model_name,
                        "messages": messages,
                        "temperature": 0.1,
                        "max_tokens": 1000,
                        "stream": False
                    }
                )
                response.raise_for_status()
                result = response.json()
                ai_response = result["choices"][0]["message"]["content"].strip()

            # 5. 解析AI响应
            # 尝试提取JSON
            json_str = ai_response
            if "```json" in ai_response:
                json_str = ai_response.split("```json")[1].split("```")[0].strip()
            elif "```" in ai_response:
                json_str = ai_response.split("```")[1].split("```")[0].strip()

            try:
                parsed = json.loads(json_str)
                passed = parsed.get("passed", False)
                reason = parsed.get("reason", "")
                evidence = parsed.get("evidence", "")
            except json.JSONDecodeError:
                # 如果AI返回的不是JSON，尝试从文本中判断
                passed = "通过" in ai_response or "true" in ai_response.lower()
                reason = ai_response[:200]
                evidence = ""

            # 6. 构建日志
            if passed:
                log = f"✓ AI断言通过: {assertion_text}\n"
                log += f"  - 判断原因: {reason}\n"
                if evidence:
                    log += f"  - 页面证据: {evidence}"
            else:
                log = f"✗ AI断言失败: {assertion_text}\n"
                log += f"  - 判断原因: {reason}\n"
                if evidence:
                    log += f"  - 页面证据: {evidence}"

            return passed, log, screenshot_base64

        except Exception as e:
            logger.error(f"AI断言执行失败: {e}")
            return False, f"AI断言执行异常: {str(e)}", screenshot_base64
