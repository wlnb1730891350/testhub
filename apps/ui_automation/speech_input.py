"""
语音输入处理模块 - 将自然语音转换为文本指令

支持：
1. 浏览器端 Web Speech API 采集（前端）
2. 后端 OpenAI Whisper API 转写
3. 智能语义解析，将自然语音转为结构化步骤
"""
import io
import json
import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class SpeechProcessor:
    """
    语音处理器 - 将语音音频转为文本指令
    
    支持两种模式：
    1. API模式：使用 OpenAI Whisper API 进行语音转文字
    2. 本地模式：使用本地 whisper 模型
    """
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY', '')
        self.base_url = base_url or os.getenv('WHISPER_BASE_URL', 'https://api.openai.com/v1')
        self._instruction_cache: Dict[str, List[Dict]] = {}
    
    def transcribe_audio(
        self,
        audio_data: bytes,
        language: str = 'zh',
        model: str = 'whisper-1'
    ) -> Tuple[str, Optional[str]]:
        """
        将音频数据转换为文本
        
        Args:
            audio_data: 音频二进制数据
            language: 语言代码 ('zh'=中文, 'en'=英文, 'auto'=自动)
            model: Whisper 模型名称
            
        Returns:
            (transcribed_text, error_message)
        """
        try:
            url = f"{self.base_url}/audio/transcriptions"
            
            files = {
                'file': ('audio.webm', io.BytesIO(audio_data), 'audio/webm'),
            }
            data = {
                'model': model,
                'response_format': 'json',
            }
            if language != 'auto':
                data['language'] = language
            
            headers = {
                'Authorization': f'Bearer {self.api_key}',
            }
            
            response = requests.post(
                url,
                files=files,
                data=data,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            text = result.get('text', '').strip()
            
            if not text:
                return '', '未识别到语音内容'
            
            logger.info(f"语音转文字成功: {text[:100]}")
            return text, None
            
        except requests.exceptions.Timeout:
            return '', '语音识别请求超时'
        except requests.exceptions.RequestException as e:
            logger.error(f"语音转文字请求失败: {e}")
            return '', f'语音识别服务不可用: {str(e)[:100]}'
        except Exception as e:
            logger.error(f"语音转文字异常: {e}", exc_info=True)
            return '', f'语音识别失败: {str(e)[:100]}'

    def normalize_speech_text(self, text: str) -> str:
        """
        语音识别后的文本规范化处理
        
        常见修正：
        - 去除语气词、重复词
        - 修正同音字错误
        - 统一指令格式
        """
        if not text:
            return ''
        
        # 去除首尾空白
        text = text.strip()
        
        # 去除语气词
        filler_words = ['嗯', '啊', '哦', '哈', '呀', '哇', '呐', '哎', '诶']
        for word in filler_words:
            text = text.replace(word, '')
        
        # 修正常见同音字/识别错误
        corrections = {
            '登入': '登录',
            '登陆': '登录',
            '登陆': '登录',
            '搜锁': '搜索',
            '搜所': '搜索',
            '查寻': '查询',
            '查找': '查找',
            '提现': '提交',
            '提信': '提交',
            '确任': '确认',
            '确证': '确认',
            '验让': '验证',
            '验正': '验证',
        }
        
        for wrong, correct in corrections.items():
            text = text.replace(wrong, correct)
        
        # 去除多余空格
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text


class NaturalLanguageParser:
    """
    自然语言解析器 - 将语音文本解析为结构化步骤
    """
    
    # 动作关键词映射
    ACTION_KEYWORDS = {
        '点击': 'click',
        '点按': 'click',
        '点一下': 'click',
        '选择': 'click',
        '打开': 'click',
        '进入': 'click',
        '输入': 'type',
        '填写': 'type',
        '录入': 'type',
        '搜索': 'search',
        '查找': 'search',
        '检索': 'search',
        '查询': 'search',
        '滚动': 'scroll',
        '滑动': 'scroll',
        '等待': 'wait',
        '暂停': 'wait',
        '验证': 'assert',
        '检查': 'assert',
        '确认': 'assert',
    }
    
    # 元素类型关键词
    ELEMENT_KEYWORDS = {
        '按钮': 'button',
        '输入框': 'input',
        '文本框': 'input',
        '输入栏': 'input',
        '搜索框': 'search',
        '搜索栏': 'search',
        '下拉框': 'select',
        '下拉菜单': 'select',
        '选项': 'option',
        '链接': 'link',
        '图片': 'image',
        '图标': 'icon',
        '标签': 'tab',
        '页面': 'page',
        '弹窗': 'modal',
        '对话框': 'dialog',
    }
    
    def parse(self, text: str) -> List[Dict]:
        """
        解析自然语言文本为步骤列表
        
        Returns:
            [
                {
                    'action_type': 'click/type/search/...',
                    'description': '步骤描述',
                    'element_hint': '元素名称提示',
                    'input_value': '输入值（如有）',
                    'confidence': 0.95
                }
            ]
        """
        if not text:
            return []
        
        # 按句号、感叹号、问号、换行分割
        sentences = re.split(r'[。！？\n]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        steps = []
        for sentence in sentences:
            step = self._parse_sentence(sentence)
            if step:
                steps.append(step)
        
        return steps
    
    def _parse_sentence(self, sentence: str) -> Optional[Dict]:
        """解析单句自然语言"""
        sentence = sentence.strip()
        if not sentence:
            return None
        
        # 识别动作类型
        action_type = None
        action_keyword = None
        for keyword, action in self.ACTION_KEYWORDS.items():
            if keyword in sentence:
                action_type = action
                action_keyword = keyword
                break
        
        if not action_type:
            # 默认当作点击处理
            action_type = 'click'
            action_keyword = '点击'
        
        # 提取元素描述
        element_hint = self._extract_element_hint(sentence, action_keyword)
        
        # 提取输入值
        input_value = self._extract_input_value(sentence, action_type)
        
        # 计算置信度
        confidence = self._calculate_confidence(sentence, action_type, element_hint)
        
        return {
            'action_type': action_type,
            'description': sentence,
            'element_hint': element_hint,
            'input_value': input_value,
            'confidence': confidence,
        }
    
    def _extract_element_hint(self, sentence: str, action_keyword: str) -> str:
        """提取元素描述"""
        # 去掉动作词后的内容
        pattern = rf'^{action_keyword}\s*[的]?\s*'
        text = re.sub(pattern, '', sentence).strip()
        
        # 去掉常见修饰词
        modifiers = ['一下', '一个', '那个', '这个', '该', '此', '当前', '页面上的']
        for modifier in modifiers:
            text = text.replace(modifier, '')
        
        # 去掉输入值
        text = re.sub(r'[“\"\'](.+?)[”\"\']', '', text).strip()
        
        # 去掉末尾标点
        text = re.sub(r'[。！？,，.。]$', '', text).strip()
        
        return text
    
    def _extract_input_value(self, sentence: str, action_type: str) -> str:
        """提取输入值"""
        if action_type not in ('type', 'search'):
            return ''
        
        # 匹配引号内的内容
        match = re.search(r'[“\"\'](.+?)[”\"\']', sentence)
        if match:
            return match.group(1)
        
        # 匹配"输入xxx"或"搜索xxx"
        match = re.search(r'(?:输入|填写|搜索|查找)\s*(.+)', sentence)
        if match:
            return match.group(1).strip()
        
        return ''
    
    def _calculate_confidence(self, sentence: str, action_type: str, element_hint: str) -> float:
        """计算解析置信度"""
        confidence = 0.5
        
        # 动作关键词识别到则加分
        if action_type != 'click' or any(kw in sentence for kw in self.ACTION_KEYWORDS):
            confidence += 0.2
        
        # 元素描述不为空加分
        if element_hint:
            confidence += 0.2
        
        # 输入值明确加分
        if action_type in ('type', 'search') and self._extract_input_value(sentence, action_type):
            confidence += 0.1
        
        return min(confidence, 0.99)
