# -*- coding: utf-8 -*-
"""
OCR 服务 API 视图
"""
import base64
import logging
import uuid
import time
import httpx
from io import BytesIO

from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import IsAuthenticated
from django.core.files.storage import default_storage

from .models import OCRConfig, OCRTask
from .serializers import (
    OCRConfigSerializer,
    OCRConfigListSerializer,
    OCRTaskSerializer,
    OCRRecognizeSerializer,
    OCRRecognizeResultSerializer
)
from .adapters import (
    get_ocr_service,
    OCREngineType,
    OCRLanguage,
    OCRConfig as OCRConfigData,
    TesseractAdapter,
    OnlineOCRAdapter,
    OnlineOCRProvider,
)

logger = logging.getLogger(__name__)


class OCRConfigViewSet(viewsets.ModelViewSet):
    """OCR 配置管理"""
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        return OCRConfig.objects.all()
    
    def get_serializer_class(self):
        if self.action == 'list':
            return OCRConfigListSerializer
        return OCRConfigSerializer
    
    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """获取所有启用的 OCR 配置"""
        configs = OCRConfig.objects.filter(is_active=True)
        serializer = OCRConfigListSerializer(configs, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """设置为默认配置"""
        config = self.get_object()
        
        OCRConfig.objects.filter(is_default=True).update(is_default=False)
        
        config.is_default = True
        config.save()
        
        return Response({'message': f'已将 {config.name} 设置为默认配置'})
    
    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """测试 OCR 配置
        
        支持两种测试模式：
        1. 上传图片时：执行完整的 OCR 识别测试
        2. 未上传图片时：仅测试 API 连接是否正常
        """
        config = self.get_object()
        
        image = request.FILES.get('image')
        
        if image:
            # 完整 OCR 识别测试
            try:
                from PIL import Image
                img = Image.open(image)
                
                ocr_config = OCRConfigData(
                    engine_type=self._get_engine_type(config.provider),
                    language=OCRLanguage.CHINESE_ENGLISH,
                    min_confidence=config.min_confidence,
                    online_provider=config.provider,
                    online_api_key=config.api_key,
                    online_base_url=config.base_url,
                    online_model=config.model_name,
                )
                
                service = get_ocr_service()
                result = service.recognize(img, config=ocr_config)
                
                return Response({
                    'success': result.success,
                    'text': result.text,
                    'confidence': result.confidence,
                    'engine': result.engine.value,
                    'error_message': result.error_message
                })
                
            except Exception as e:
                logger.error(f"OCR test failed: {e}")
                return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        else:
            # 仅测试 API 连接
            return self._test_connection(config)
    
    def _test_connection(self, config):
        """测试 OCR 服务连接是否正常"""
        try:
            if config.provider == 'tesseract':
                # Tesseract 离线引擎：检查是否安装
                from .adapters import TesseractAdapter
                installed = TesseractAdapter.check_installation()
                if installed.get('tesseract_available'):
                    return Response({
                        'success': True,
                        'message': 'Tesseract OCR 引擎已安装，连接测试成功',
                        'installation': installed,
                    })
                else:
                    return Response({
                        'success': False,
                        'message': installed.get('error') or 'Tesseract OCR 引擎未安装，请先安装 Tesseract',
                        'installation': installed,
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            
            # 在线 OCR 服务：发送简单请求验证 API 连接
            engine_type = self._get_engine_type(config.provider)
            ocr_config = OCRConfigData(
                engine_type=engine_type,
                language=OCRLanguage.CHINESE_ENGLISH,
                min_confidence=config.min_confidence,
                online_provider=config.provider,
                online_api_key=config.api_key,
                online_base_url=config.base_url,
                online_model=config.model_name,
                extra_params=config.extra_config or {},
            )
            
            provider_str = config.provider or 'openai'
            try:
                provider = OnlineOCRProvider(provider_str.lower())
            except ValueError:
                provider = OnlineOCRProvider.CUSTOM
            
            # 对于 OpenAI 兼容 API（OpenAI/Zhipu/SiliconFlow），发送简单的文本请求验证连接
            if provider in [OnlineOCRProvider.OPENAI, OnlineOCRProvider.ZHIPU, OnlineOCRProvider.SILICONFLOW]:
                base_url = config.base_url or 'https://api.openai.com/v1'
                if provider == OnlineOCRProvider.ZHIPU:
                    base_url = config.base_url or 'https://open.bigmodel.cn/api/paas/v4'
                elif provider == OnlineOCRProvider.SILICONFLOW:
                    base_url = config.base_url or 'https://api.siliconflow.cn/v1'
                
                url = f"{base_url.rstrip('/')}/chat/completions"
                model = config.model_name or 'gpt-4o'
                
                try:
                    with httpx.Client(timeout=30.0) as client:
                        response = client.post(
                            url,
                            json={
                                "model": model,
                                "messages": [
                                    {"role": "user", "content": "请回复'连接成功'"}
                                ],
                                "max_tokens": 50
                            },
                            headers={
                                "Content-Type": "application/json",
                                "Authorization": f"Bearer {config.api_key}"
                            }
                        )
                        response.raise_for_status()
                        result = response.json()
                        reply = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                        return Response({
                            'success': True,
                            'message': f'连接测试成功',
                            'response': reply
                        })
                except httpx.HTTPStatusError as e:
                    error_detail = ''
                    try:
                        error_body = e.response.json()
                        error_detail = error_body.get('error', {}).get('message', str(e))
                    except Exception:
                        error_detail = str(e)
                    return Response({
                        'success': False,
                        'message': f'连接测试失败: {error_detail}'
                    }, status=status.HTTP_400_BAD_REQUEST)
                except httpx.ConnectError:
                    return Response({
                        'success': False,
                        'message': '连接测试失败: 无法连接到服务器，请检查网络或API地址'
                    }, status=status.HTTP_400_BAD_REQUEST)
                except httpx.TimeoutException:
                    return Response({
                        'success': False,
                        'message': '连接测试失败: 请求超时，请检查网络或API地址'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # 对于百度 OCR：测试获取 access token
            elif provider == OnlineOCRProvider.BAIDU:
                try:
                    adapter = OnlineOCRAdapter(ocr_config)
                    adapter.initialize()
                    access_token = adapter._get_baidu_access_token()
                    if access_token:
                        return Response({
                            'success': True,
                            'message': '百度 OCR 连接测试成功'
                        })
                    else:
                        return Response({
                            'success': False,
                            'message': '百度 OCR 连接测试失败: 无法获取 Access Token'
                        }, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    return Response({
                        'success': False,
                        'message': f'百度 OCR 连接测试失败: {str(e)}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            
            # 对于腾讯/阿里云/自定义：检查配置是否完整
            elif provider == OnlineOCRProvider.TENCENT:
                extra = config.extra_config or {}
                if config.api_key and extra.get('secret_id') and extra.get('secret_key'):
                    return Response({
                        'success': True,
                        'message': '腾讯 OCR 配置检查通过'
                    })
                else:
                    return Response({
                        'success': False,
                        'message': '腾讯 OCR 配置不完整，需要 secret_id 和 secret_key'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            elif provider == OnlineOCRProvider.ALIYUN:
                extra = config.extra_config or {}
                if extra.get('access_key_id') and extra.get('access_key_secret'):
                    return Response({
                        'success': True,
                        'message': '阿里云 OCR 配置检查通过'
                    })
                else:
                    return Response({
                        'success': False,
                        'message': '阿里云 OCR 配置不完整，需要 access_key_id 和 access_key_secret'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            
            elif provider == OnlineOCRProvider.CUSTOM:
                if config.base_url:
                    return Response({
                        'success': True,
                        'message': '自定义 OCR 配置检查通过'
                    })
                else:
                    return Response({
                        'success': False,
                        'message': '自定义 OCR 需要配置 base_url'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            else:
                return Response({
                    'success': False,
                    'message': f'不支持的提供商: {config.provider}'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.error(f"OCR connection test failed: {e}")
            return Response({
                'success': False,
                'message': f'连接测试失败: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_engine_type(self, provider: str) -> OCREngineType:
        """根据提供商获取引擎类型"""
        if provider == 'tesseract':
            return OCREngineType.TESSERACT
        else:
            return OCREngineType.ONLINE


class OCRTaskViewSet(viewsets.ReadOnlyModelViewSet):
    """OCR 任务查询"""
    permission_classes = [IsAuthenticated]
    serializer_class = OCRTaskSerializer
    
    def get_queryset(self):
        return OCRTask.objects.all()


class OCRRecognizeView(APIView):
    """OCR 识别接口"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        serializer = OCRRecognizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        image = serializer.validated_data['image']
        config_id = serializer.validated_data.get('config_id')
        language = serializer.validated_data.get('language', 'chi_sim+eng')
        return_details = serializer.validated_data.get('return_details', False)
        
        try:
            from PIL import Image
            img = Image.open(image)
            
            ocr_config = None
            engine_type = OCREngineType.TESSERACT
            
            if config_id:
                try:
                    config = OCRConfig.objects.get(id=config_id, is_active=True)
                    ocr_config = OCRConfigData(
                        engine_type=self._get_engine_type(config.provider),
                        language=self._get_language(language),
                        min_confidence=config.min_confidence,
                        online_provider=config.provider,
                        online_api_key=config.api_key,
                        online_base_url=config.base_url,
                        online_model=config.model_name,
                        extra_params=config.extra_config or {},
                    )
                    engine_type = ocr_config.engine_type
                except OCRConfig.DoesNotExist:
                    pass
            
            if not ocr_config:
                ocr_config = OCRConfigData(
                    engine_type=OCREngineType.TESSERACT,
                    language=self._get_language(language),
                )
            
            service = get_ocr_service()
            start_time = time.time()
            result = service.recognize(img, engine_type=engine_type, config=ocr_config)
            processing_time = time.time() - start_time
            
            response_data = {
                'success': result.success,
                'text': result.text,
                'confidence': result.confidence,
                'engine': result.engine.value,
                'processing_time': round(processing_time, 3),
            }
            
            if return_details:
                response_data['texts'] = [item.to_dict() for item in result.texts]
            
            if not result.success:
                response_data['error_message'] = result.error_message
            
            return Response(response_data)
            
        except Exception as e:
            logger.error(f"OCR recognition failed: {e}")
            return Response({
                'success': False,
                'error_message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_engine_type(self, provider: str) -> OCREngineType:
        if provider == 'tesseract':
            return OCREngineType.TESSERACT
        else:
            return OCREngineType.ONLINE
    
    def _get_language(self, lang_str: str) -> OCRLanguage:
        lang_map = {
            'chi_sim': OCRLanguage.CHINESE,
            'eng': OCRLanguage.ENGLISH,
            'chi_sim+eng': OCRLanguage.CHINESE_ENGLISH,
            'japan': OCRLanguage.JAPANESE,
            'korean': OCRLanguage.KOREAN,
        }
        return lang_map.get(lang_str, OCRLanguage.CHINESE_ENGLISH)


class OCRRecognizeBase64View(APIView):
    """OCR 识别接口（Base64 图片）"""
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]
    
    def post(self, request):
        image_base64 = request.data.get('image')
        if not image_base64:
            return Response({'error': '请提供 base64 编码的图片'}, status=status.HTTP_400_BAD_REQUEST)
        
        config_id = request.data.get('config_id')
        language = request.data.get('language', 'chi_sim+eng')
        
        try:
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]
            
            image_data = base64.b64decode(image_base64)
            
            from PIL import Image
            img = Image.open(BytesIO(image_data))
            
            ocr_config = None
            engine_type = OCREngineType.TESSERACT
            
            if config_id:
                try:
                    config = OCRConfig.objects.get(id=config_id, is_active=True)
                    ocr_config = OCRConfigData(
                        engine_type=self._get_engine_type(config.provider),
                        language=self._get_language(language),
                        min_confidence=config.min_confidence,
                        online_provider=config.provider,
                        online_api_key=config.api_key,
                        online_base_url=config.base_url,
                        online_model=config.model_name,
                    )
                    engine_type = ocr_config.engine_type
                except OCRConfig.DoesNotExist:
                    pass
            
            if not ocr_config:
                ocr_config = OCRConfigData(
                    engine_type=OCREngineType.TESSERACT,
                    language=self._get_language(language),
                )
            
            service = get_ocr_service()
            result = service.recognize(img, engine_type=engine_type, config=ocr_config)
            
            return Response({
                'success': result.success,
                'text': result.text,
                'confidence': result.confidence,
                'engine': result.engine.value,
                'error_message': result.error_message if not result.success else None
            })
            
        except Exception as e:
            logger.error(f"OCR recognition failed: {e}")
            return Response({
                'success': False,
                'error_message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_engine_type(self, provider: str) -> OCREngineType:
        if provider == 'tesseract':
            return OCREngineType.TESSERACT
        else:
            return OCREngineType.ONLINE
    
    def _get_language(self, lang_str: str) -> OCRLanguage:
        lang_map = {
            'chi_sim': OCRLanguage.CHINESE,
            'eng': OCRLanguage.ENGLISH,
            'chi_sim+eng': OCRLanguage.CHINESE_ENGLISH,
        }
        return lang_map.get(lang_str, OCRLanguage.CHINESE_ENGLISH)


@api_view(['GET'])
def ocr_engines(request):
    """获取可用的 OCR 引擎列表"""
    service = get_ocr_service()
    available_engines = service.get_available_engines()
    
    engines = []
    for engine_type in OCREngineType:
        engines.append({
            'type': engine_type.value,
            'name': engine_type.name,
            'available': engine_type in available_engines
        })
    
    return Response({'engines': engines})


@api_view(['GET'])
def ocr_check_installation(request):
    """检查 OCR 引擎安装状态"""
    results = {}
    
    results['tesseract'] = TesseractAdapter.check_installation()
    
    return Response(results)


class OCRBatchRecognizeView(APIView):
    """批量 OCR 识别接口"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        from .serializers import OCRBatchRecognizeSerializer
        
        images = request.FILES.getlist('images')
        if not images:
            return Response({'error': '请上传图片文件'}, status=status.HTTP_400_BAD_REQUEST)
        
        config_id = request.data.get('config_id')
        language = request.data.get('language', 'chi_sim+eng')
        
        try:
            from PIL import Image
            
            ocr_config = None
            engine_type = OCREngineType.TESSERACT
            
            if config_id:
                try:
                    config = OCRConfig.objects.get(id=config_id, is_active=True)
                    ocr_config = OCRConfigData(
                        engine_type=self._get_engine_type(config.provider),
                        language=self._get_language(language),
                        min_confidence=config.min_confidence,
                        online_provider=config.provider,
                        online_api_key=config.api_key,
                        online_base_url=config.base_url,
                        online_model=config.model_name,
                    )
                    engine_type = ocr_config.engine_type
                except OCRConfig.DoesNotExist:
                    pass
            
            if not ocr_config:
                ocr_config = OCRConfigData(
                    engine_type=OCREngineType.TESSERACT,
                    language=self._get_language(language),
                )
            
            service = get_ocr_service()
            results = []
            all_texts = []
            total_confidence = 0
            success_count = 0
            
            for idx, image_file in enumerate(images):
                try:
                    img = Image.open(image_file)
                    start_time = time.time()
                    result = service.recognize(img, engine_type=engine_type, config=ocr_config)
                    processing_time = time.time() - start_time
                    
                    text = self._clean_text(result.text) if result.success else ''
                    
                    results.append({
                        'index': idx,
                        'filename': image_file.name,
                        'success': result.success,
                        'text': text,
                        'confidence': result.confidence,
                        'processing_time': round(processing_time, 3),
                        'error_message': result.error_message if not result.success else None
                    })
                    
                    if result.success and text:
                        all_texts.append(text)
                        total_confidence += result.confidence
                        success_count += 1
                        
                except Exception as e:
                    logger.error(f"Failed to process image {idx}: {e}")
                    results.append({
                        'index': idx,
                        'filename': image_file.name,
                        'success': False,
                        'text': '',
                        'error_message': str(e)
                    })
            
            combined_text = self._clean_combined_text('\n\n'.join(all_texts))
            avg_confidence = total_confidence / success_count if success_count > 0 else 0
            
            return Response({
                'success': success_count > 0,
                'total': len(images),
                'processed': success_count,
                'results': results,
                'combined_text': combined_text,
                'confidence': round(avg_confidence, 3),
            })
            
        except Exception as e:
            logger.error(f"Batch OCR recognition failed: {e}")
            return Response({
                'success': False,
                'error_message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_engine_type(self, provider: str) -> OCREngineType:
        if provider == 'tesseract':
            return OCREngineType.TESSERACT
        else:
            return OCREngineType.ONLINE
    
    def _get_language(self, lang_str: str) -> OCRLanguage:
        lang_map = {
            'chi_sim': OCRLanguage.CHINESE,
            'eng': OCRLanguage.ENGLISH,
            'chi_sim+eng': OCRLanguage.CHINESE_ENGLISH,
            'japan': OCRLanguage.JAPANESE,
            'korean': OCRLanguage.KOREAN,
        }
        return lang_map.get(lang_str, OCRLanguage.CHINESE_ENGLISH)
    
    def _clean_text(self, text: str) -> str:
        """清理单个 OCR 识别结果"""
        if not text:
            return ''
        
        import re
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n\s*\n+', '\n\n', text)
        text = re.sub(r' +', ' ', text)
        text = text.strip()
        
        return text
    
    def _clean_combined_text(self, text: str) -> str:
        """清理合并后的文本，确保格式整洁"""
        if not text:
            return ''
        
        import re
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r' +', ' ', text)
        text = text.strip()
        
        return text
