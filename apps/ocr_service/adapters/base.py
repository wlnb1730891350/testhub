# -*- coding: utf-8 -*-
"""
OCR 基类和统一接口定义
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Union, Any
from PIL import Image
import numpy as np


class OCREngineType(Enum):
    """OCR 引擎类型"""
    TESSERACT = 'tesseract'
    ONLINE = 'online'


class OCRLanguage(Enum):
    """OCR 语言"""
    CHINESE = 'chi_sim'
    ENGLISH = 'eng'
    CHINESE_ENGLISH = 'chi_sim+eng'
    JAPANESE = 'japan'
    KOREAN = 'korean'


@dataclass
class OCRTextItem:
    """OCR 单个文本项"""
    text: str
    confidence: float = 1.0
    bbox: Optional[Tuple[int, int, int, int]] = None
    
    def to_dict(self) -> dict:
        return {
            'text': self.text,
            'confidence': self.confidence,
            'bbox': self.bbox,
        }


@dataclass
class OCRResult:
    """OCR 识别结果"""
    texts: List[OCRTextItem] = field(default_factory=list)
    success: bool = True
    engine: OCREngineType = OCREngineType.TESSERACT
    error_message: str = ''
    raw_result: Any = None
    
    @property
    def text(self) -> str:
        """获取合并后的文本"""
        return ' '.join([item.text for item in self.texts])
    
    @property
    def confidence(self) -> float:
        """获取平均置信度"""
        if not self.texts:
            return 0.0
        return sum(item.confidence for item in self.texts) / len(self.texts)
    
    def to_dict(self) -> dict:
        return {
            'texts': [item.to_dict() for item in self.texts],
            'text': self.text,
            'success': self.success,
            'engine': self.engine.value,
            'error_message': self.error_message,
        }


@dataclass
class OCRConfig:
    """OCR 配置"""
    engine_type: OCREngineType = OCREngineType.TESSERACT
    language: OCRLanguage = OCRLanguage.CHINESE_ENGLISH
    
    min_confidence: float = 0.3
    
    tesseract_path: Optional[str] = None
    tesseract_data_path: Optional[str] = None
    
    online_provider: str = 'openai'
    online_api_key: Optional[str] = None
    online_base_url: Optional[str] = None
    online_model: str = 'gpt-4o'
    
    extra_params: dict = field(default_factory=dict)


class BaseOCRAdapter(ABC):
    """OCR 适配器基类"""
    
    ENGINE_NAME = 'base'
    
    def __init__(self, config: Optional[OCRConfig] = None):
        self.config = config or OCRConfig()
        self._initialized = False
    
    @abstractmethod
    def initialize(self) -> bool:
        """
        初始化 OCR 引擎
        
        Returns:
            是否初始化成功
        """
        pass
    
    @abstractmethod
    def recognize(
        self,
        image: Union[Image.Image, np.ndarray, str],
        language: Optional[OCRLanguage] = None,
        **kwargs
    ) -> OCRResult:
        """
        识别图像中的文字
        
        Args:
            image: PIL Image、numpy array 或图像路径
            language: 识别语言
            **kwargs: 额外参数
            
        Returns:
            OCRResult 识别结果
        """
        pass
    
    @abstractmethod
    def recognize_batch(
        self,
        images: List[Union[Image.Image, np.ndarray, str]],
        language: Optional[OCRLanguage] = None,
        **kwargs
    ) -> List[OCRResult]:
        """
        批量识别图像中的文字
        
        Args:
            images: 图像列表
            language: 识别语言
            **kwargs: 额外参数
            
        Returns:
            OCRResult 列表
        """
        pass
    
    def is_available(self) -> bool:
        """
        检查 OCR 引擎是否可用
        
        Returns:
            是否可用
        """
        return self._initialized
    
    @staticmethod
    def load_image(image: Union[Image.Image, np.ndarray, str]) -> Image.Image:
        """
        加载图像为 PIL Image
        
        Args:
            image: PIL Image、numpy array 或图像路径
            
        Returns:
            PIL Image 对象
        """
        if isinstance(image, Image.Image):
            return image
        elif isinstance(image, np.ndarray):
            if image.ndim == 2:
                return Image.fromarray(image, mode='L')
            elif image.ndim == 3:
                if image.shape[2] == 4:
                    return Image.fromarray(image, mode='RGBA')
                elif image.shape[2] == 3:
                    return Image.fromarray(image, mode='RGB')
            raise ValueError(f"Unsupported numpy array shape: {image.shape}")
        elif isinstance(image, str):
            return Image.open(image)
        else:
            raise TypeError(f"Unsupported image type: {type(image)}")
    
    @staticmethod
    def image_to_numpy(image: Union[Image.Image, np.ndarray, str]) -> np.ndarray:
        """
        将图像转换为 numpy array
        
        Args:
            image: PIL Image、numpy array 或图像路径
            
        Returns:
            numpy array (RGB)
        """
        img = BaseOCRAdapter.load_image(image)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return np.array(img)
    
    def preprocess_image(
        self,
        image: Union[Image.Image, np.ndarray, str],
        enhance_contrast: bool = True,
        resize_factor: float = 1.0,
        denoise: bool = False
    ) -> Image.Image:
        """
        图像预处理
        
        Args:
            image: 输入图像
            enhance_contrast: 是否增强对比度
            resize_factor: 缩放因子
            denoise: 是否降噪
            
        Returns:
            预处理后的 PIL Image
        """
        from PIL import ImageEnhance, ImageFilter
        
        img = self.load_image(image)
        
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        if resize_factor != 1.0:
            new_size = (int(img.width * resize_factor), int(img.height * resize_factor))
            img = img.resize(new_size, Image.LANCZOS)
        
        if enhance_contrast:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.5)
        
        if denoise:
            img = img.filter(ImageFilter.MedianFilter())
        
        return img
    
    @staticmethod
    def resize_for_ocr(
        image: Union[Image.Image, np.ndarray, str],
        max_width: int = 1920,
        max_height: int = 1920,
        min_width: int = 640,
        min_height: int = 640
    ) -> Tuple[Image.Image, float]:
        """
        智能缩放图片以优化 OCR 识别速度
        
        Args:
            image: 输入图像
            max_width: 最大宽度
            max_height: 最大高度
            min_width: 最小宽度
            min_height: 最小高度
            
        Returns:
            (缩放后的图像, 缩放比例)
        """
        img = BaseOCRAdapter.load_image(image)
        
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        width, height = img.size
        scale = 1.0
        
        if width > max_width or height > max_height:
            scale_w = max_width / width
            scale_h = max_height / height
            scale = min(scale_w, scale_h)
            new_size = (int(width * scale), int(height * scale))
            img = img.resize(new_size, Image.LANCZOS)
        elif width < min_width and height < min_height:
            scale_w = min_width / width
            scale_h = min_height / height
            scale = max(scale_w, scale_h)
            new_size = (int(width * scale), int(height * scale))
            img = img.resize(new_size, Image.LANCZOS)
        
        return img, scale
