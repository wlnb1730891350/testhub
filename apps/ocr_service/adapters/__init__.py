# -*- coding: utf-8 -*-
"""
统一 OCR 服务层

支持的 OCR 引擎：
- Tesseract: 传统 OCR，轻量级，适合简单文字识别
- Online OCR: 在线大模型 OCR（GLM-4V、GPT-4V 等）
"""
from .base import BaseOCRAdapter, OCRResult, OCRTextItem, OCREngineType, OCRLanguage, OCRConfig
from .service import OCRService, get_ocr_service
from .tesseract import TesseractAdapter
from .online import OnlineOCRAdapter, OnlineOCRProvider

__all__ = [
    'BaseOCRAdapter',
    'OCRResult',
    'OCRTextItem',
    'OCREngineType',
    'OCRLanguage',
    'OCRConfig',
    'OCRService',
    'get_ocr_service',
    'TesseractAdapter',
    'OnlineOCRAdapter',
    'OnlineOCRProvider',
]
