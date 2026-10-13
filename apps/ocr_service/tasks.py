# -*- coding: utf-8 -*-
"""
OCR 异步任务
支持超时控制和并发限制
"""
import os
import logging
import threading
import functools
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# PaddlePaddle 环境变量配置（必须在 import paddle 之前设置）
os.environ['FLAGS_use_mkldnn'] = '0'
os.environ['FLAGS_cinn_new_group_scheduler'] = '0'
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_check_cuda_version'] = '0'
os.environ['FLAGS_skip_allocator_mem_check'] = '1'
# 解决 kernel not registered 问题（reshape, full_int_array 等）
os.environ['FLAGS_new_executor_serial_run'] = '1'
os.environ['FLAGS_enable_new_ir'] = '0'
os.environ['FLAGS_enable_new_ir_in_executor'] = '0'
os.environ['FLAGS_use_cinn'] = '0'
os.environ['FLAGS_enable_new_executor'] = '0'
os.environ['FLAGS_enable_pir'] = '0'

from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

_ocr_semaphore = None
_semaphore_lock = threading.Lock()


def get_ocr_semaphore():
    """
    获取 OCR 并发信号量（单例模式）
    
    Returns:
        threading.Semaphore 实例
    """
    global _ocr_semaphore
    
    if _ocr_semaphore is None:
        with _semaphore_lock:
            if _ocr_semaphore is None:
                from django.conf import settings
                max_concurrent = getattr(settings, 'OCR_MAX_CONCURRENT_TASKS', 3)
                _ocr_semaphore = threading.Semaphore(max_concurrent)
                logger.info(f"OCR 并发信号量初始化: 最大并发数={max_concurrent}")
    
    return _ocr_semaphore


def with_timeout(timeout_seconds: int):
    """
    超时装饰器
    
    Args:
        timeout_seconds: 超时时间（秒）
        
    Returns:
        装饰器函数
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = [None]
            exception = [None]
            
            def worker():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e
            
            thread = threading.Thread(target=worker, daemon=True)
            thread.start()
            thread.join(timeout=timeout_seconds)
            
            if thread.is_alive():
                logger.warning(f"OCR 任务超时 ({timeout_seconds}秒)，已取消")
                raise TimeoutError(f"OCR 识别超时，超过 {timeout_seconds} 秒")
            
            if exception[0] is not None:
                raise exception[0]
            
            return result[0]
        
        return wrapper
    return decorator


def with_concurrency_limit(func):
    """
    并发限制装饰器
    
    Args:
        func: 被装饰的函数
        
    Returns:
        装饰后的函数
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        semaphore = get_ocr_semaphore()
        
        logger.debug(f"等待获取 OCR 并发信号量...")
        acquired = semaphore.acquire(timeout=300)
        
        if not acquired:
            logger.error("获取 OCR 并发信号量超时")
            raise RuntimeError("OCR 服务繁忙，请稍后重试")
        
        try:
            logger.debug("已获取 OCR 并发信号量，开始执行")
            return func(*args, **kwargs)
        finally:
            semaphore.release()
            logger.debug("已释放 OCR 并发信号量")
    
    return wrapper


def get_ocr_timeout():
    """
    获取 OCR 超时配置
    
    Returns:
        超时时间（秒）
    """
    from django.conf import settings
    return getattr(settings, 'OCR_TIMEOUT', 300)


@with_concurrency_limit
def _do_ocr_recognition(
    file_path: str,
    ocr_config_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    执行 OCR 识别（带并发限制）
    
    Args:
        file_path: 文件路径
        ocr_config_id: OCR 配置 ID
        
    Returns:
        识别结果
    """
    from apps.ocr_service.models import OCRConfig
    from apps.ocr_service.adapters import (
        get_ocr_service, OCREngineType, OCRLanguage, OCRConfig as OCRConfigData
    )
    
    if not ocr_config_id:
        from apps.requirement_analysis.document_processor import document_processor
        return {
            'text': document_processor([file_path]),
            'warning': None
        }
    
    try:
        ocr_config = OCRConfig.objects.get(id=ocr_config_id, is_active=True)
        
        engine_type_map = {
            'tesseract': OCREngineType.TESSERACT,
            'openai': OCREngineType.ONLINE,
            'zhipu': OCREngineType.ONLINE,
            'baidu': OCREngineType.ONLINE,
            'tencent': OCREngineType.ONLINE,
            'aliyun': OCREngineType.ONLINE,
            'custom': OCREngineType.ONLINE,
        }
        
        lang_map = {
            'chi_sim': OCRLanguage.CHINESE,
            'eng': OCRLanguage.ENGLISH,
            'chi_sim+eng': OCRLanguage.CHINESE_ENGLISH,
            'japan': OCRLanguage.JAPANESE,
            'korean': OCRLanguage.KOREAN,
        }
        
        config_data = OCRConfigData(
            engine_type=engine_type_map.get(ocr_config.provider, OCREngineType.TESSERACT),
            language=lang_map.get(ocr_config.language, OCRLanguage.CHINESE_ENGLISH),
            min_confidence=ocr_config.min_confidence,
            online_provider=ocr_config.provider,
            online_api_key=ocr_config.api_key,
            online_base_url=ocr_config.base_url,
            online_model=ocr_config.model_name,
        )
        
        from PIL import Image
        img = Image.open(file_path)
        
        ocr_service = get_ocr_service()
        result = ocr_service.recognize(img, engine_type=config_data.engine_type, config=config_data)
        
        if result.success:
            text = _clean_ocr_text(result.text)
            logger.info(f"使用 {ocr_config.provider} OCR 识别成功: {len(text)} 字符")
            return {
                'text': text,
                'warning': None
            }
        else:
            warning = f"OCR 识别失败: {result.error_message}，已回退到 Tika 解析"
            logger.warning(f"OCR 识别失败，回退到 Tika: {result.error_message}")
            from apps.requirement_analysis.document_processor import document_processor
            return {
                'text': document_processor([file_path]),
                'warning': warning
            }
            
    except OCRConfig.DoesNotExist:
        warning = "OCR 配置不存在，已使用默认 Tika 解析"
        logger.warning(f"OCR 配置不存在: {ocr_config_id}，使用默认 Tika")
        from apps.requirement_analysis.document_processor import document_processor
        return {
            'text': document_processor([file_path]),
            'warning': warning
        }
    except Exception as e:
        warning = f"OCR 识别出错: {str(e)}，已回退到 Tika 解析"
        logger.error(f"OCR 识别出错: {e}，回退到 Tika")
        from apps.requirement_analysis.document_processor import document_processor
        return {
            'text': document_processor([file_path]),
            'warning': warning
        }


def extract_text_async(
    document_id: int,
    ocr_config_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    异步提取文档文本（带超时控制和并发限制）
    
    Args:
        document_id: 文档ID
        ocr_config_id: OCR配置ID（可选）
        
    Returns:
        提取结果字典
    """
    from apps.requirement_analysis.models import RequirementDocument
    from apps.requirement_analysis.document_processor import document_processor
    
    try:
        document = RequirementDocument.objects.get(id=document_id)
        
        if document.extracted_text:
            return {
                'success': True,
                'document_id': document_id,
                'extracted_text': document.extracted_text,
                'text_length': len(document.extracted_text),
                'warning': document.extraction_warning if document.extraction_warning else None,
                'message': '文本已存在'
            }
        
        file_path = document.file.path
        file_ext = os.path.splitext(file_path)[1].lower()
        
        image_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp']
        
        text = ''
        warning_message = None
        timeout_seconds = get_ocr_timeout()
        
        if file_ext in image_extensions:
            logger.info(f"开始 OCR 识别: document_id={document_id}, timeout={timeout_seconds}s")
            
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        _do_ocr_recognition,
                        file_path,
                        ocr_config_id
                    )
                    
                    try:
                        result = future.result(timeout=timeout_seconds)
                        text = result['text']
                        warning_message = result.get('warning')
                        logger.info(f"OCR 识别成功: document_id={document_id}, text_length={len(text)}")
                    except FuturesTimeoutError:
                        warning_message = f"OCR 识别超时（{timeout_seconds}秒），已回退到 Tika 解析"
                        logger.warning(f"OCR 识别超时: document_id={document_id}, 回退到 Tika 解析")
                        try:
                            text = document_processor([file_path])
                            logger.info(f"Tika 回退解析成功: document_id={document_id}")
                        except Exception as tika_error:
                            logger.error(f"Tika 回退解析失败: document_id={document_id}, error={tika_error}")
                            raise Exception(f"OCR 和 Tika 解析均失败: OCR超时, Tika错误: {tika_error}")
                        
            except Exception as e:
                warning_message = f"OCR 处理异常: {str(e)}，已回退到 Tika 解析"
                logger.error(f"OCR 处理异常: document_id={document_id}, error={e}", exc_info=True)
                try:
                    text = document_processor([file_path])
                    logger.info(f"Tika 回退解析成功: document_id={document_id}")
                except Exception as tika_error:
                    logger.error(f"Tika 回退解析失败: document_id={document_id}, error={tika_error}")
                    raise Exception(f"OCR 和 Tika 解析均失败: OCR错误: {e}, Tika错误: {tika_error}")
        else:
            logger.info(f"非图片文件，使用 Tika 解析: document_id={document_id}, file_ext={file_ext}")
            text = document_processor([file_path])
        
        document.extracted_text = text
        if warning_message:
            document.extraction_warning = warning_message
        document.status = 'analyzed'
        document.save()
        
        logger.info(f"文本提取完成: document_id={document_id}, status=analyzed, text_length={len(text)}")
        
        return {
            'success': True,
            'document_id': document_id,
            'extracted_text': text,
            'text_length': len(text),
            'warning': warning_message
        }
        
    except RequirementDocument.DoesNotExist:
        logger.error(f"文档不存在: document_id={document_id}")
        return {
            'success': False,
            'document_id': document_id,
            'error': '文档不存在'
        }
    except Exception as e:
        logger.error(f"提取文本失败: document_id={document_id}, error={e}", exc_info=True)
        try:
            document = RequirementDocument.objects.get(id=document_id)
            document.status = 'failed'
            document.extraction_error = str(e)
            document.save()
            logger.info(f"已更新文档状态为失败: document_id={document_id}")
        except Exception as update_error:
            logger.error(f"更新文档失败状态时出错: document_id={document_id}, error={update_error}")
        return {
            'success': False,
            'document_id': document_id,
            'error': str(e)
        }


def _clean_ocr_text(text: str) -> str:
    """清理 OCR 识别结果，去除多余空格和格式问题"""
    if not text:
        return ''
    
    import re
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n +', '\n', text)
    text = re.sub(r' +\n', '\n', text)
    text = text.strip()
    
    return text


def get_ocr_status() -> Dict[str, Any]:
    """
    获取 OCR 服务状态
    
    Returns:
        状态信息字典
    """
    from django.conf import settings
    
    max_concurrent = getattr(settings, 'OCR_MAX_CONCURRENT_TASKS', 3)
    timeout = getattr(settings, 'OCR_TIMEOUT', 300)
    
    semaphore = get_ocr_semaphore()
    
    return {
        'max_concurrent_tasks': max_concurrent,
        'timeout_seconds': timeout,
        'semaphore_value': semaphore._value if hasattr(semaphore, '_value') else 'N/A',
    }
