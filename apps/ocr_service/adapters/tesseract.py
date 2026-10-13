# -*- coding: utf-8 -*-
"""
Tesseract OCR 适配器
"""
import os
import logging
from typing import List, Optional, Union, Any

from PIL import Image
import numpy as np

from .base import BaseOCRAdapter, OCRResult, OCRTextItem, OCRLanguage, OCRConfig, OCREngineType

logger = logging.getLogger(__name__)

TESSERACT_AVAILABLE = False

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    logger.warning("pytesseract not installed. Tesseract OCR will not be available.")


class TesseractAdapter(BaseOCRAdapter):
    """Tesseract OCR 适配器"""
    
    _tesseract_path = None
    _tesseract_data_path = None
    
    def __init__(self, config: Optional[OCRConfig] = None):
        super().__init__(config)
        
        if not TESSERACT_AVAILABLE:
            logger.warning("Tesseract OCR not available. Please install: pip install pytesseract")
            return
        
        if self.config.tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = self.config.tesseract_path
        
        if self.config.tesseract_data_path:
            os.environ['TESSDATA_PREFIX'] = self.config.tesseract_data_path
    
    @property
    def engine_type(self) -> OCREngineType:
        return OCREngineType.TESSERACT
    
    def initialize(self) -> bool:
        """
        初始化 Tesseract OCR 引擎
        
        Returns:
            是否初始化成功
        """
        if not TESSERACT_AVAILABLE:
            logger.warning("Tesseract OCR not available. Please install: pip install pytesseract")
            self._initialized = False
            return False
        
        try:
            version = pytesseract.get_tesseract_version()
            logger.info(f"Tesseract OCR initialized successfully, version: {version}")
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Tesseract OCR: {e}")
            self._initialized = False
            return False
    
    def is_available(self) -> bool:
        """检查 Tesseract 是否可用"""
        if not TESSERACT_AVAILABLE:
            return False
        
        try:
            version = pytesseract.get_tesseract_version()
            logger.debug(f"Tesseract version: {version}")
            return True
        except Exception as e:
            logger.warning(f"Tesseract not available: {e}")
            return False
    
    def _get_tesseract_lang(self, language: Optional[OCRLanguage] = None) -> str:
        """获取 Tesseract 语言代码"""
        lang = language or self.config.language
        
        lang_map = {
            OCRLanguage.CHINESE: 'chi_sim',
            OCRLanguage.ENGLISH: 'eng',
            OCRLanguage.CHINESE_ENGLISH: 'chi_sim+eng',
        }
        
        return lang_map.get(lang, 'chi_sim+eng')
    
    def recognize(
        self,
        image: Union[Image.Image, np.ndarray, str],
        language: Optional[OCRLanguage] = None,
        **kwargs
    ) -> OCRResult:
        """
        使用 Tesseract 识别图像中的文字
        
        Args:
            image: PIL Image、numpy array 或图像路径
            language: 识别语言
            **kwargs: 额外参数
                - psm: Page segmentation mode (0-13)
                - oem: OCR Engine Mode (0-3)
                - config: Custom config string
                
        Returns:
            OCRResult 识别结果
        """
        if not TESSERACT_AVAILABLE:
            return OCRResult(
                texts=[],
                success=False,
                engine=self.engine_type,
                error_message="Tesseract OCR not available. Please install: pip install pytesseract"
            )
        
        try:
            img = self.load_image(image)
            
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            width, height = img.size
            if width < 1000 or height < 200:
                scale_factor = 2
                img = img.resize(
                    (width * scale_factor, height * scale_factor),
                    Image.LANCZOS
                )
                logger.debug(f"Image scaled {scale_factor}x for better recognition")
            
            lang = self._get_tesseract_lang(language)
            
            psm = kwargs.get('psm', 6)
            oem = kwargs.get('oem', 3)
            custom_config = kwargs.get('config', f'--oem {oem} --psm {psm}')
            
            data = pytesseract.image_to_data(img, lang=lang, config=custom_config, output_type=pytesseract.Output.DICT)
            
            texts = []
            n_boxes = len(data['text'])
            
            for i in range(n_boxes):
                text = data['text'][i].strip()
                conf = float(data['conf'][i]) / 100.0
                
                if text and conf >= self.config.min_confidence:
                    x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                    
                    texts.append(OCRTextItem(
                        text=text,
                        confidence=conf,
                        bbox=(x, y, x + w, y + h)
                    ))
            
            texts.sort(key=lambda x: (x.bbox[1], x.bbox[0]))
            
            logger.info(f"Tesseract OCR recognized {len(texts)} text items")
            
            return OCRResult(
                texts=texts,
                success=True,
                engine=self.engine_type
            )
            
        except Exception as e:
            logger.error(f"Tesseract OCR failed: {e}")
            return OCRResult(
                texts=[],
                success=False,
                engine=self.engine_type,
                error_message=str(e)
            )
    
    def recognize_batch(
        self,
        images: List[Union[Image.Image, np.ndarray, str]],
        language: Optional[OCRLanguage] = None,
        **kwargs
    ) -> List[OCRResult]:
        """批量识别"""
        return [self.recognize(img, language, **kwargs) for img in images]
    
    @classmethod
    def check_installation(cls) -> dict:
        """
        检查 Tesseract 安装状态
        
        Returns:
            包含安装信息的字典
        """
        result = {
            'pytesseract_installed': TESSERACT_AVAILABLE,
            'tesseract_available': False,
            'version': None,
            'languages': [],
            'path': None,
            'error': None
        }
        
        if not TESSERACT_AVAILABLE:
            result['error'] = 'pytesseract not installed'
            return result
        
        try:
            result['version'] = str(pytesseract.get_tesseract_version())
            result['tesseract_available'] = True
            result['path'] = pytesseract.pytesseract.tesseract_cmd
            
            langs = pytesseract.get_languages()
            result['languages'] = langs
            
            result['chinese_available'] = 'chi_sim' in langs
            
        except Exception as e:
            result['error'] = str(e)
        
        return result
