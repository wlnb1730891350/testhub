"""
智能元素定位算法模块

基于自然语言描述 + Playwright 页面上下文，构建多层定位策略：
1. 语义匹配：根据自然语言描述匹配页面文本/aria-label/placeholder
2. 结构匹配：基于 CSS 选择器、XPath 等稳定定位
3. 视觉匹配：基于元素位置、大小的视觉特征
4. 容错兜底：多候选策略 + 重试机制
"""
import re
import logging
import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LocatorCandidate:
    """定位候选结果"""
    selector: str
    strategy: str  # css/xpath/playwright/text/js
    confidence: float
    reason: str = ''
    element_info: Dict = field(default_factory=dict)


class NaturalLanguageElementLocator:
    """
    基于自然语言描述的元素定位器
    
    核心能力：
    - 从自然语言中提取元素类型、文本内容、位置信息
    - 在页面中搜索最匹配的元素
    - 返回带置信度的定位策略
    """
    
    def __init__(self):
        # 元素类型 -> 标签名映射
        self.tag_map = {
            '按钮': 'button',
            '输入框': 'input',
            '文本框': 'input',
            '输入栏': 'input',
            '搜索框': 'input',
            '下拉框': 'select',
            '菜单': 'div',
            '链接': 'a',
            '图片': 'img',
            '图标': 'i',
            '标签页': 'div',
            '弹窗': 'div',
            '对话框': 'div',
            '表格': 'table',
            '行': 'tr',
            '列表': 'ul',
            '项目': 'li',
        }
        
        # 文本匹配属性优先级
        self.text_attrs = [
            'aria-label',
            'placeholder',
            'title',
            'alt',
            'data-testid',
            'data-cy',
            'data-qa',
        ]
    
    def parse_description(self, description: str) -> Dict:
        """
        解析自然语言描述，提取结构化信息
        
        Returns:
            {
                'element_type': 'button/input/...',
                'text_content': '匹配的文本',
                'attributes': {'aria-label': '...', ...},
                'position': 'top/middle/bottom/left/right',
                'context': 'modal/header/nav/sidebar',
                'raw': '原始描述'
            }
        """
        desc = description.strip()
        if not desc:
            return {}
        
        result = {
            'element_type': None,
            'text_content': None,
            'attributes': {},
            'position': None,
            'context': None,
            'raw': desc,
        }
        
        # 识别元素类型
        for keyword, tag in self.tag_map.items():
            if keyword in desc:
                result['element_type'] = tag
                break
        
        # 识别位置信息
        position_keywords = {
            '顶部': 'top',
            '上方': 'top',
            '顶部区域': 'top',
            '中部': 'middle',
            '中间': 'middle',
            '底部': 'bottom',
            '下方': 'bottom',
            '左侧': 'left',
            '左边': 'left',
            '右侧': 'right',
            '右边': 'right',
        }
        for keyword, position in position_keywords.items():
            if keyword in desc:
                result['position'] = position
                break
        
        # 识别上下文
        context_keywords = {
            '弹窗': 'modal',
            '对话框': 'modal',
            '下拉': 'dropdown',
            '菜单': 'menu',
            '导航': 'nav',
            '侧边栏': 'sidebar',
            '顶部导航': 'header',
            '底部': 'footer',
        }
        for keyword, context in context_keywords.items():
            if keyword in desc:
                result['context'] = context
                break
        
        # 提取引号内的文本作为精确匹配内容
        quoted = re.findall(r'["\u201c\u201d](.+?)["\u201c\u201d]', desc)
        if quoted:
            result['text_content'] = quoted[0]
        
        # 提取"点击xxx"、"输入xxx"等动作后的内容
        if not result['text_content']:
            action_pattern = re.compile(
                r'(?:点击|点|按|选择|打开|进入|输入|填写|搜索|查找|查询)\s*'
                r'[的]?\s*(.+)'
            )
            match = action_pattern.search(desc)
            if match:
                content = match.group(1).strip()
                # 去掉常见修饰词
                content = re.sub(r'按钮$|图标$|链接$|入口$', '', content).strip()
                result['text_content'] = content if content else None
        
        return result

    async def locate(
        self,
        page,
        description: str,
        action_type: str = 'click',
        execution_record = None,
        timeout_ms: int = 10000,
    ) -> Optional[LocatorCandidate]:
        """
        根据自然语言描述在页面中定位元素
        
        Args:
            page: Playwright page 对象
            description: 自然语言描述
            action_type: 动作类型 (click/type/search/assert)
            execution_record: 执行记录（用于日志）
            timeout_ms: 超时时间（毫秒）
            
        Returns:
            LocatorCandidate 或 None
        """
        parsed = self.parse_description(description)
        if not parsed:
            return None
        
        log = lambda msg: self._log(execution_record, msg)
        
        # 构建多策略候选列表
        candidates: List[LocatorCandidate] = []
        
        # 策略1: 精确文本匹配
        if parsed.get('text_content'):
            candidates.extend(self._text_match_candidates(parsed, action_type))
        
        # 策略2: 语义属性匹配
        candidates.extend(self._semantic_attr_candidates(parsed))
        
        # 策略3: 结构位置匹配
        candidates.extend(self._structural_candidates(page, parsed))
        
        # 策略4: 通用兜底匹配
        candidates.extend(self._fallback_candidates(parsed, action_type))
        
        # 按置信度排序
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        
        log(f"[NL Locator] 描述={description}, 候选数={len(candidates)}")
        
        # 验证候选元素
        for candidate in candidates:
            try:
                locator = page.locator(candidate.selector).first
                count = await locator.count()
                if count == 0:
                    continue
                
                visible = await locator.is_visible(timeout=timeout_ms)
                if visible:
                    candidate.confidence = min(candidate.confidence + 0.1, 0.99)
                    log(f"[NL Locator] 命中: {candidate.selector} (confidence={candidate.confidence:.2f})")
                    return candidate
                
            except Exception:
                continue
        
        return None

    def _text_match_candidates(self, parsed: Dict, action_type: str) -> List[LocatorCandidate]:
        """精确文本匹配候选"""
        candidates = []
        text = parsed.get('text_content', '')
        if not text:
            return candidates
        
        escaped = self._escape_css(text)
        
        # 按钮/链接文本匹配
        if action_type in ('click', 'select'):
            candidates.append(LocatorCandidate(
                selector=f'button:has-text("{escaped}")',
                strategy='css',
                confidence=0.95,
                reason=f'按钮文本匹配: {text}'
            ))
            candidates.append(LocatorCandidate(
                selector=f'a:has-text("{escaped}")',
                strategy='css',
                confidence=0.90,
                reason=f'链接文本匹配: {text}'
            ))
        
        # 输入框 placeholder 匹配
        if action_type in ('type', 'search'):
            candidates.append(LocatorCandidate(
                selector=f'input[placeholder="{escaped}"], input[placeholder*="{escaped}"], textarea[placeholder*="{escaped}"]',
                strategy='css',
                confidence=0.85,
                reason=f'placeholder匹配: {text}'
            ))
        
        # 通用文本匹配
        candidates.append(LocatorCandidate(
            selector=f'*:has-text("{escaped}")',
            strategy='css',
            confidence=0.60,
            reason=f'通用文本匹配: {text}'
        ))
        
        return candidates

    def _semantic_attr_candidates(self, parsed: Dict) -> List[LocatorCandidate]:
        """语义属性匹配候选"""
        candidates = []
        text = parsed.get('text_content', '') or ''
        escaped = self._escape_css(text)
        element_type = parsed.get('element_type')
        
        # aria-label 匹配
        if text:
            candidates.append(LocatorCandidate(
                selector=f'[aria-label="{escaped}"], [aria-label*="{escaped}"]',
                strategy='css',
                confidence=0.85,
                reason=f'aria-label匹配: {text}'
            ))
        
        # data-testid 匹配
        if text:
            candidates.append(LocatorCandidate(
                selector=f'[data-testid="{escaped}"], [data-testid*="{escaped}"]',
                strategy='css',
                confidence=0.80,
                reason=f'data-testid匹配: {text}'
            ))
        
        # 标题/alt 匹配
        if text:
            candidates.append(LocatorCandidate(
                selector=f'[title="{escaped}"], [title*="{escaped}"], img[alt*="{escaped}"]',
                strategy='css',
                confidence=0.75,
                reason=f'title/alt匹配: {text}'
            ))
        
        # 类型限定匹配
        if element_type and text:
            candidates.append(LocatorCandidate(
                selector=f'{element_type}[aria-label*="{escaped}"], {element_type}[placeholder*="{escaped}"]',
                strategy='css',
                confidence=0.80,
                reason=f'限定类型+属性匹配: {element_type}[...]={text}'
            ))
        
        return candidates

    def _structural_candidates(self, page, parsed: Dict) -> List[LocatorCandidate]:
        """结构位置匹配候选"""
        candidates = []
        position = parsed.get('position')
        context = parsed.get('context')
        element_type = parsed.get('element_type')
        
        # 上下文限定
        context_selectors = []
        if context == 'modal':
            context_selectors = [
                '[role="dialog"]', '[role="alertdialog"]',
                '.el-dialog', '.el-message-box', '.modal', '.dialog', '.popup'
            ]
        elif context == 'nav':
            context_selectors = ['nav', 'header', '[class*="header" i]', '[class*="nav" i]']
        elif context == 'sidebar':
            context_selectors = ['aside', '[class*="sidebar" i]', '[class*="side" i]']
        
        # 位置限定
        position_selectors = []
        if position == 'top':
            position_selectors = ['header', '[class*="header" i]', '[class*="top" i]']
        elif position == 'left':
            position_selectors = ['aside', '[class*="left" i]', '[class*="sidebar" i]']
        elif position == 'right':
            position_selectors = ['[class*="right" i]']
        
        # 组合上下文和位置
        for ctx in context_selectors + position_selectors:
            base = ctx
            if element_type:
                base += f' {element_type}'
            
            candidates.append(LocatorCandidate(
                selector=f'{base} >> visible=true',
                strategy='playwright',
                confidence=0.65,
                reason=f'结构限定: {base}'
            ))
        
        return candidates

    def _fallback_candidates(self, parsed: Dict, action_type: str) -> List[LocatorCandidate]:
        """通用兜底候选"""
        candidates = []
        element_type = parsed.get('element_type')
        text = parsed.get('text_content', '')
        escaped = self._escape_css(text) if text else ''
        
        # 类型限定
        if element_type:
            if action_type == 'click':
                candidates.append(LocatorCandidate(
                    selector=f'{element_type}:visible >> nth=0',
                    strategy='playwright',
                    confidence=0.40,
                    reason=f'类型兜底: {element_type}'
                ))
            elif action_type == 'type':
                candidates.append(LocatorCandidate(
                    selector=f'{element_type}[type="text"], {element_type}[type="search"], {element_type}[contenteditable="true"]:visible >> nth=0',
                    strategy='playwright',
                    confidence=0.40,
                    reason=f'输入类型兜底: {element_type}'
                ))
        
        # 文本内容限定（模糊）
        if text and len(text) >= 2:
            candidates.append(LocatorCandidate(
                selector=f'[aria-label*="{escaped}"], [placeholder*="{escaped}"], [title*="{escaped}"]',
                strategy='css',
                confidence=0.50,
                reason=f'模糊属性匹配: {text[:20]}'
            ))
        
        return candidates

    def _escape_css(self, text: str) -> str:
        """转义 CSS 选择器中的特殊字符"""
        text = str(text).replace('\\', '\\\\').replace('"', '\\"')
        return text
    
    def _log(self, execution_record, message: str):
        try:
            if execution_record and hasattr(execution_record, 'logs'):
                execution_record.logs += f"\n{message}"
        except Exception:
            pass


class ElementCapture:
    """
    元素捕捉机制
    
    在定位到元素后，完整捕获其信息：
    - DOM 属性（id, name, class, placeholder, aria-label...）
    - 位置信息（bounding box: x, y, width, height）
    - 截图（元素级截图）
    - 父子关系（ancestor chain）
    - 生成稳定定位器
    """
    
    @staticmethod
    async def capture(page, locator, include_screenshot: bool = True) -> Dict:
        """
        完整捕获元素信息
        
        Returns:
            {
                'dom_info': {tag, id, name, className, ...},
                'position': {x, y, width, height},
                'screenshot': 'base64...',  # 可选
                'ancestor_chain': [{tag, id, class}, ...],
                'generated_locator': {
                    'strategy': 'css/xpath',
                    'value': '...',
                    'confidence': 0.95
                }
            }
        """
        result = {
            'dom_info': {},
            'position': {},
            'screenshot': None,
            'ancestor_chain': [],
            'generated_locator': {'strategy': 'css', 'value': '', 'confidence': 0.0},
        }
        
        try:
            element_handle = await locator.element_handle()
            if not element_handle:
                return result
            
            # 1. DOM 信息
            result['dom_info'] = await ElementCapture._get_dom_info(element_handle)
            
            # 2. 位置信息
            result['position'] = await ElementCapture._get_position(page, locator)
            
            # 3. 元素截图
            if include_screenshot:
                result['screenshot'] = await ElementCapture._capture_screenshot(page, locator)
            
            # 4. 祖先链
            result['ancestor_chain'] = await ElementCapture._get_ancestor_chain(element_handle)
            
            # 5. 生成稳定定位器
            result['generated_locator'] = ElementCapture._generate_locator(result)
            
        except Exception as e:
            logger.warning(f"元素捕捉失败: {e}")
        
        return result
    
    @staticmethod
    async def _get_dom_info(element_handle) -> Dict:
        """获取 DOM 属性信息"""
        try:
            js = """
            (el) => {
                const attrs = {};
                const keep = ['id', 'name', 'type', 'className', 'placeholder', 'title', 'alt',
                    'role', 'aria-label', 'aria-labelledby', 'data-testid', 'data-cy', 'data-qa',
                    'href', 'src', 'value', 'disabled', 'readonly'];
                for (const key of keep) {
                    const val = el.getAttribute(key);
                    if (val !== null) attrs[key] = val;
                }
                attrs.tag = el.tagName ? el.tagName.toLowerCase() : '';
                attrs.innerText = (el.innerText || '').substring(0, 100);
                return attrs;
            }
            """
            return await element_handle.evaluate(js) or {}
        except Exception:
            return {}
    
    @staticmethod
    async def _get_position(page, locator) -> Dict:
        """获取元素位置和尺寸"""
        try:
            js = """
            (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    visible: rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden',
                    zIndex: parseInt(style.zIndex) || 0,
                    position: style.position
                };
            }
            """
            box = await locator.evaluate(js)
            return box or {}
        except Exception:
            return {}
    
    @staticmethod
    async def _capture_screenshot(page, locator) -> Optional[str]:
        """捕获元素截图"""
        try:
            screenshot_bytes = await locator.screenshot(timeout=5000)
            import base64
            return base64.b64encode(screenshot_bytes).decode('utf-8')
        except Exception:
            return None
    
    @staticmethod
    async def _get_ancestor_chain(element_handle, max_depth: int = 5) -> List[Dict]:
        """获取祖先元素链（用于生成相对定位器）"""
        chain = []
        try:
            current = element_handle
            for _ in range(max_depth):
                if not current:
                    break
                
                js = """
                (el) => {
                    const info = { tag: '', id: '', className: '' };
                    if (!el) return info;
                    info.tag = el.tagName ? el.tagName.toLowerCase() : '';
                    info.id = el.id || '';
                    info.className = (el.className || '').toString().trim().split(' ').slice(0, 3).join('.');
                    return info;
                }
                """
                info = await current.evaluate(js)
                if info and info.get('tag'):
                    chain.append(info)
                
                current = await current.evaluate_handle('el => el.parentElement')
        except Exception:
            pass
        
        return chain
    
    @staticmethod
    def _generate_locator(capture_result: Dict) -> Dict:
        """根据捕捉信息生成最优定位器"""
        dom = capture_result.get('dom_info', {})
        chain = capture_result.get('ancestor_chain', [])
        
        # 优先：ID
        el_id = dom.get('id', '')
        if el_id and re.match(r'^[a-zA-Z][\w-]*$', el_id):
            return {
                'strategy': 'css',
                'value': f'#{el_id}',
                'confidence': 0.99,
                'reason': '元素ID唯一且稳定'
            }
        
        # 次优：name + type（表单元素）
        name = dom.get('name', '')
        input_type = dom.get('type', '')
        if name and input_type:
            return {
                'strategy': 'css',
                'value': f'[name="{name}"][type="{input_type}"]',
                'confidence': 0.90,
                'reason': 'name+type组合稳定'
            }
        
        # 第三优：placeholder
        placeholder = dom.get('placeholder', '')
        if placeholder:
            return {
                'strategy': 'css',
                'value': f'[placeholder="{placeholder}"]',
                'confidence': 0.85,
                'reason': 'placeholder文本匹配'
            }
        
        # 第四优：aria-label
        aria_label = dom.get('aria-label', '')
        if aria_label:
            return {
                'strategy': 'css',
                'value': f'[aria-label="{aria_label}"]',
                'confidence': 0.80,
                'reason': 'aria-label语义匹配'
            }
        
        # 兜底：tag + class
        tag = dom.get('tag', '')
        class_name = dom.get('className', '').split()[0] if dom.get('className') else ''
        if tag and class_name:
            return {
                'strategy': 'css',
                'value': f'{tag}.{class_name}',
                'confidence': 0.50,
                'reason': '标签+类名兜底'
            }
        
        return {
            'strategy': 'css',
            'value': tag or '*',
            'confidence': 0.30,
            'reason': '极弱兜底'
        }
