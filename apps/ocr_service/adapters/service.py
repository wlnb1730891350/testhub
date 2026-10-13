# -*- coding: utf-8 -*-
"""
OCR 服务类 - 统一 OCR 调用入口
"""
import logging
from typing import Dict, List, Optional, Union, Any
from PIL import Image
import numpy as np

from django.conf import settings

from .base import BaseOCRAdapter, OCRResult, OCREngineType, OCRLanguage, OCRConfig

logger = logging.getLogger(__name__)


class OCRService:
    """OCR 服务类 - 统一管理多种 OCR 引擎"""
    
    _adapters: Dict[OCREngineType, BaseOCRAdapter] = {}
    _initialized = False
    
    def __init__(self):
        self._config_cache = {}
    
    @classmethod
    def _lazy_init(cls):
        """延迟初始化适配器"""
        if cls._initialized:
            return
        
        cls._initialized = True
    
    def get_adapter(
        self,
        engine_type: OCREngineType = OCREngineType.TESSERACT,
        config: Optional[OCRConfig] = None
    ) -> BaseOCRAdapter:
        """
        获取 OCR 适配器
        
        Args:
            engine_type: OCR 引擎类型
            config: OCR 配置
            
        Returns:
            OCR 适配器实例
        """
        self._lazy_init()
        
        cache_key = (engine_type, id(config))
        if cache_key in self._config_cache:
            return self._config_cache[cache_key]
        
        adapter = self._create_adapter(engine_type, config)
        self._config_cache[cache_key] = adapter
        return adapter
    
    def _create_adapter(
        self,
        engine_type: OCREngineType,
        config: Optional[OCRConfig] = None
    ) -> BaseOCRAdapter:
        """创建 OCR 适配器"""
        if engine_type == OCREngineType.TESSERACT:
            from .tesseract import TesseractAdapter
            return TesseractAdapter(config)
        
        elif engine_type == OCREngineType.ONLINE:
            from .online import OnlineOCRAdapter
            return OnlineOCRAdapter(config)
        
        else:
            raise ValueError(f"Unsupported OCR engine type: {engine_type}")
    
    def recognize(
        self,
        image: Union[Image.Image, np.ndarray, str],
        engine_type: OCREngineType = OCREngineType.TESSERACT,
        language: Optional[OCRLanguage] = None,
        config: Optional[OCRConfig] = None,
        **kwargs
    ) -> OCRResult:
        """
        识别图像中的文字
        
        Args:
            image: PIL Image、numpy array 或图像路径
            engine_type: OCR 引擎类型
            language: 识别语言
            config: OCR 配置
            **kwargs: 额外参数
            
        Returns:
            OCRResult 识别结果
        """
        adapter = self.get_adapter(engine_type, config)
        return adapter.recognize(image, language, **kwargs)
    
    def recognize_text(
        self,
        image: Union[Image.Image, np.ndarray, str],
        engine_type: OCREngineType = OCREngineType.TESSERACT,
        language: Optional[OCRLanguage] = None,
        config: Optional[OCRConfig] = None,
        min_confidence: float = 0.3,
        **kwargs
    ) -> str:
        """
        识别图像中的文字并返回纯文本
        
        Args:
            image: PIL Image、numpy array 或图像路径
            engine_type: OCR 引擎类型
            language: 识别语言
            config: OCR 配置
            min_confidence: 最小置信度
            **kwargs: 额外参数
            
        Returns:
            识别出的文本字符串
        """
        result = self.recognize(image, engine_type, language, config, **kwargs)
        
        if not result.success:
            return ""
        
        texts = []
        for item in result.texts:
            if item.confidence >= min_confidence:
                texts.append(item.text)
        
        return ' '.join(texts)
    
    def recognize_number(
        self,
        image: Union[Image.Image, np.ndarray, str],
        engine_type: OCREngineType = OCREngineType.TESSERACT,
        allow_comma: bool = True,
        **kwargs
    ) -> int:
        """
        识别图像中的数字
        
        Args:
            image: PIL Image、numpy array 或图像路径
            engine_type: OCR 引擎类型
            allow_comma: 是否允许逗号分隔符
            **kwargs: 额外参数
            
        Returns:
            识别出的数字
        """
        text = self.recognize_text(image, engine_type, **kwargs)
        
        text = text.replace('o', '0').replace('O', '0')
        text = text.replace('l', '1').replace('I', '1')
        text = text.replace('?', '1')
        
        if allow_comma:
            digits = ''.join(filter(lambda x: x.isdigit() or x == ',', text))
            digits = digits.replace(',', '')
        else:
            digits = ''.join(filter(str.isdigit, text))
        
        try:
            return int(digits) if digits else 0
        except ValueError:
            logger.error(f"Cannot convert text to number: {text}")
            return 0
    
    def recognize_region(
        self,
        image: Union[Image.Image, np.ndarray, str],
        region: tuple,
        engine_type: OCREngineType = OCREngineType.TESSERACT,
        **kwargs
    ) -> OCRResult:
        """
        识别图像指定区域的文字
        
        Args:
            image: PIL Image、numpy array 或图像路径
            region: 区域坐标 (x1, y1, x2, y2)
            engine_type: OCR 引擎类型
            **kwargs: 额外参数
            
        Returns:
            OCRResult 识别结果
        """
        img = BaseOCRAdapter.load_image(image)
        
        x1, y1, x2, y2 = region
        cropped = img.crop((x1, y1, x2, y2))
        
        return self.recognize(cropped, engine_type, **kwargs)
    
    def recognize_region_text(
        self,
        image: Union[Image.Image, np.ndarray, str],
        region: tuple,
        engine_type: OCREngineType = OCREngineType.TESSERACT,
        **kwargs
    ) -> str:
        """
        识别图像指定区域的文字并返回纯文本
        
        Args:
            image: PIL Image、numpy array 或图像路径
            region: 区域坐标 (x1, y1, x2, y2)
            engine_type: OCR 引擎类型
            **kwargs: 额外参数
            
        Returns:
            识别出的文本字符串
        """
        result = self.recognize_region(image, region, engine_type, **kwargs)
        
        if not result.success:
            return ""
        
        texts = [item.text for item in result.texts]
        return ' '.join(texts)
    
    def is_engine_available(self, engine_type: OCREngineType) -> bool:
        """
        检查 OCR 引擎是否可用
        
        Args:
            engine_type: OCR 引擎类型
            
        Returns:
            是否可用
        """
        try:
            adapter = self.get_adapter(engine_type)
            return adapter.is_available()
        except Exception as e:
            logger.warning(f"OCR engine {engine_type} not available: {e}")
            return False
    
    def get_available_engines(self) -> List[OCREngineType]:
        """
        获取所有可用的 OCR 引擎
        
        Returns:
            可用的 OCR 引擎列表
        """
        available = []
        for engine_type in OCREngineType:
            if self.is_engine_available(engine_type):
                available.append(engine_type)
        return available


_ocr_service_instance: Optional[OCRService] = None


def get_ocr_service() -> OCRService:
    """
    获取 OCR 服务单例实例
    
    Returns:
        OCRService 实例
    """
    global _ocr_service_instance
    if _ocr_service_instance is None:
        _ocr_service_instance = OCRService()
    return _ocr_service_instance
