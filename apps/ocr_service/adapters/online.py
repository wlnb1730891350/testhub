# -*- coding: utf-8 -*-
"""
在线 OCR 大模型适配器
支持 OpenAI GPT-4V、智谱 GLM-4V、百度 AI OCR、腾讯 OCR、阿里云 OCR、自定义 HTTP API
"""
import base64
import logging
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional, Union, Any, Dict
from io import BytesIO
from urllib.parse import urlencode, quote

from PIL import Image
import numpy as np
import httpx

from .base import BaseOCRAdapter, OCRResult, OCRTextItem, OCRLanguage, OCRConfig, OCREngineType

logger = logging.getLogger(__name__)


class OnlineOCRProvider(Enum):
    """在线 OCR 服务提供商"""
    OPENAI = 'openai'
    ZHIPU = 'zhipu'
    SILICONFLOW = 'siliconflow'
    BAIDU = 'baidu'
    TENCENT = 'tencent'
    ALIYUN = 'aliyun'
    CUSTOM = 'custom'


class OnlineOCRAdapter(BaseOCRAdapter):
    """在线 OCR 大模型适配器"""
    
    ENGINE_NAME = 'online'
    
    PROVIDER_CONFIGS = {
        OnlineOCRProvider.OPENAI: {
            'default_model': 'gpt-4o',
            'default_base_url': 'https://api.openai.com/v1',
            'auth_type': 'bearer',
        },
        OnlineOCRProvider.ZHIPU: {
            'default_model': 'glm-4v',
            'default_base_url': 'https://open.bigmodel.cn/api/paas/v4',
            'auth_type': 'bearer',
        },
        OnlineOCRProvider.SILICONFLOW: {
            'default_model': 'Qwen/Qwen2.5-VL-72B-Instruct',
            'default_base_url': 'https://api.siliconflow.cn/v1',
            'auth_type': 'bearer',
        },
        OnlineOCRProvider.BAIDU: {
            'default_base_url': 'https://aip.baidubce.com/rest/2.0/ocr/v1',
            'auth_type': 'access_token',
        },
        OnlineOCRProvider.TENCENT: {
            'default_base_url': 'https://ocr.tencentcloudapi.com',
            'auth_type': 'tencent_sign',
        },
        OnlineOCRProvider.ALIYUN: {
            'default_base_url': 'https://ocr-api.cn-hangzhou.aliyuncs.com',
            'auth_type': 'aliyun_sign',
        },
        OnlineOCRProvider.CUSTOM: {
            'auth_type': 'custom',
        },
    }
    
    def __init__(self, config: Optional[OCRConfig] = None):
        super().__init__(config)
        
        provider_str = self.config.online_provider or 'openai'
        try:
            self.provider = OnlineOCRProvider(provider_str.lower())
        except ValueError:
            self.provider = OnlineOCRProvider.CUSTOM
        
        self._load_extra_config()
    
    def _load_extra_config(self):
        """加载额外配置"""
        self.extra_config = self.config.extra_params or {}
        
        if self.provider == OnlineOCRProvider.BAIDU:
            self.baidu_secret_key = self.extra_config.get('secret_key', '')
        elif self.provider == OnlineOCRProvider.TENCENT:
            self.tencent_secret_id = self.extra_config.get('secret_id', '')
            self.tencent_secret_key = self.extra_config.get('secret_key', '')
            self.tencent_region = self.extra_config.get('region', 'ap-guangzhou')
        elif self.provider == OnlineOCRProvider.ALIYUN:
            self.aliyun_access_key_id = self.extra_config.get('access_key_id', '')
            self.aliyun_access_key_secret = self.extra_config.get('access_key_secret', '')
            self.aliyun_action = self.extra_config.get('action', 'RecognizeGeneral')
        elif self.provider == OnlineOCRProvider.CUSTOM:
            self.custom_request_method = self.extra_config.get('request_method', 'POST')
            self.custom_request_format = self.extra_config.get('request_format', 'openai')
            self.custom_response_format = self.extra_config.get('response_format', 'openai')
            self.custom_headers = self.extra_config.get('headers', {})
            self.custom_body_template = self.extra_config.get('body_template', {})
            self.custom_response_path = self.extra_config.get('response_path', 'choices[0].message.content')
    
    @property
    def engine_type(self) -> OCREngineType:
        return OCREngineType.ONLINE
    
    def initialize(self) -> bool:
        """初始化在线 OCR 引擎"""
        provider_config = self.PROVIDER_CONFIGS.get(self.provider, {})
        
        if self.provider == OnlineOCRProvider.BAIDU:
            if not self.config.online_api_key or not self.baidu_secret_key:
                logger.warning("Baidu OCR api_key or secret_key not configured")
                self._initialized = False
                return False
        elif self.provider == OnlineOCRProvider.TENCENT:
            if not self.tencent_secret_id or not self.tencent_secret_key:
                logger.warning("Tencent OCR secret_id or secret_key not configured")
                self._initialized = False
                return False
        elif self.provider == OnlineOCRProvider.ALIYUN:
            if not self.aliyun_access_key_id or not self.aliyun_access_key_secret:
                logger.warning("Aliyun OCR access_key_id or access_key_secret not configured")
                self._initialized = False
                return False
        elif self.provider == OnlineOCRProvider.CUSTOM:
            if not self.config.online_base_url:
                logger.warning("Custom OCR requires base_url")
                self._initialized = False
                return False
        elif not self.config.online_api_key:
            logger.warning("API key not configured for online OCR")
            self._initialized = False
            return False
        
        if not self.config.online_base_url:
            self.config.online_base_url = provider_config.get('default_base_url')
        
        logger.info(f"Online OCR initialized: provider={self.provider.value}")
        self._initialized = True
        return True
    
    def _image_to_base64(self, image: Union[Image.Image, np.ndarray, str]) -> str:
        """将图像转换为 base64 编码"""
        img = self.load_image(image)
        
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    def _get_baidu_access_token(self) -> str:
        """获取百度 OCR Access Token"""
        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.config.online_api_key,
            "client_secret": self.baidu_secret_key
        }
        
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, params=params)
            response.raise_for_status()
            result = response.json()
            return result.get('access_token', '')
    
    def _build_openai_request(self, image_base64: str, language: Optional[OCRLanguage] = None) -> Dict[str, Any]:
        """构建 OpenAI API 请求"""
        lang_hint = "中文" if language in [OCRLanguage.CHINESE, OCRLanguage.CHINESE_ENGLISH] else "English"
        
        return {
            "model": self.config.online_model or 'gpt-4o',
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"请识别这张图片中的所有{lang_hint}文字，直接输出识别结果，不要添加任何解释或格式化。如果图片中没有文字，请输出'无文字'。"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 4096
        }
    
    def _build_zhipu_request(self, image_base64: str, language: Optional[OCRLanguage] = None) -> Dict[str, Any]:
        """构建智谱 API 请求"""
        lang_hint = "中文" if language in [OCRLanguage.CHINESE, OCRLanguage.CHINESE_ENGLISH] else "English"
        
        return {
            "model": self.config.online_model or 'glm-4v',
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"请识别这张图片中的所有{lang_hint}文字，直接输出识别结果，不要添加任何解释或格式化。"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 4096
        }
    
    def _build_baidu_request(self, image_base64: str, language: Optional[OCRLanguage] = None) -> tuple:
        """构建百度 OCR API 请求"""
        url = f"{self.config.online_base_url.rstrip('/')}/general_basic"
        
        access_token = self._get_baidu_access_token()
        url = f"{url}?access_token={access_token}"
        
        body = {
            "image": image_base64,
            "language_type": "CHN_ENG" if language in [OCRLanguage.CHINESE, OCRLanguage.CHINESE_ENGLISH] else "ENG",
            "detect_direction": "true",
            "detect_language": "true",
            "probability": "true"
        }
        
        return url, body
    
    def _build_tencent_request(self, image_base64: str, language: Optional[OCRLanguage] = None) -> tuple:
        """构建腾讯 OCR API 请求"""
        action = "GeneralAccurateOCR"
        version = "2018-11-19"
        timestamp = int(time.time())
        date = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d')
        
        payload = {
            "ImageBase64": image_base64,
        }
        
        body = json.dumps(payload)
        
        service = "ocr"
        host = "ocr.tencentcloudapi.com"
        
        http_request_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        ct = "application/json; charset=utf-8"
        canonical_headers = f"content-type:{ct}\nhost:{host}\n"
        signed_headers = "content-type;host"
        hashed_request_payload = hashlib.sha256(body.encode('utf-8')).hexdigest()
        canonical_request = f"{http_request_method}\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{hashed_request_payload}"
        
        algorithm = "TC3-HMAC-SHA256"
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()
        string_to_sign = f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"
        
        secret_date = hmac.new(
            f"TC3{self.tencent_secret_key}".encode('utf-8'),
            date.encode('utf-8'),
            hashlib.sha256
        ).digest()
        secret_service = hmac.new(secret_date, service.encode('utf-8'), hashlib.sha256).digest()
        secret_signing = hmac.new(secret_service, "tc3_request".encode('utf-8'), hashlib.sha256).digest()
        signature = hmac.new(secret_signing, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
        
        authorization = f"{algorithm} Credential={self.tencent_secret_id}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
        
        headers = {
            "Authorization": authorization,
            "Content-Type": ct,
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": version,
            "X-TC-Region": self.tencent_region
        }
        
        url = f"https://{host}"
        return url, body, headers
    
    def _build_aliyun_request(self, image_base64: str, language: Optional[OCRLanguage] = None) -> tuple:
        """构建阿里云 OCR API 请求"""
        action = self.aliyun_action
        version = "2021-07-07"
        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        
        params = {
            "Action": action,
            "Version": version,
            "Format": "JSON",
            "AccessKeyId": self.aliyun_access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": str(uuid.uuid4()),
            "Timestamp": timestamp,
            "Image": image_base64,
        }
        
        sorted_params = sorted(params.items())
        canonicalized_query_string = urlencode(sorted_params, quote_via=quote)
        
        string_to_sign = f"POST&%2F&{quote(canonicalized_query_string, safe='')}"
        
        key = f"{self.aliyun_access_key_secret}&".encode('utf-8')
        signature = base64.b64encode(
            hmac.new(key, string_to_sign.encode('utf-8'), hashlib.sha1).digest()
        ).decode('utf-8')
        
        params["Signature"] = signature
        
        url = self.config.online_base_url or "https://ocr-api.cn-hangzhou.aliyuncs.com"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "x-acs-action": action,
        }
        
        return url, params, headers
    
    def _build_custom_request(self, image_base64: str, language: Optional[OCRLanguage] = None) -> tuple:
        """构建自定义 HTTP API 请求"""
        url = self.config.online_base_url
        method = self.custom_request_method.upper()
        
        headers = dict(self.custom_headers)
        
        if self.config.online_api_key:
            if 'Authorization' not in headers:
                headers['Authorization'] = f"Bearer {self.config.online_api_key}"
        
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'
        
        request_format = self.custom_request_format.lower()
        
        if request_format == 'openai':
            body = self._build_openai_request(image_base64, language)
        elif request_format == 'raw':
            body = dict(self.custom_body_template)
            body['image'] = image_base64
        elif request_format == 'custom':
            body = dict(self.custom_body_template)
            if not body:
                logger.warning("Custom body template is empty, using default format")
                body = {"image": image_base64}
            for key, value in list(body.items()):
                if isinstance(value, str):
                    if '{image}' in value:
                        body[key] = value.replace('{image}', image_base64)
                    if '{api_key}' in value:
                        body[key] = value.replace('{api_key}', self.config.online_api_key or '')
        else:
            body = {"image": image_base64}
        
        return url, method, headers, body
    
    def _parse_openai_response(self, response: Dict[str, Any]) -> str:
        """解析 OpenAI 格式响应"""
        if 'choices' in response and len(response['choices']) > 0:
            message = response['choices'][0].get('message', {})
            return message.get('content', '')
        return ''
    
    def _parse_baidu_response(self, response: Dict[str, Any]) -> str:
        """解析百度 OCR 响应"""
        words_result = response.get('words_result', [])
        texts = [item.get('words', '') for item in words_result]
        return '\n'.join(texts)
    
    def _parse_tencent_response(self, response: Dict[str, Any]) -> str:
        """解析腾讯 OCR 响应"""
        response_data = response.get('Response', {})
        text_detections = response_data.get('TextDetections', [])
        texts = [item.get('DetectedText', '') for item in text_detections]
        return '\n'.join(texts)
    
    def _parse_aliyun_response(self, response: Dict[str, Any]) -> str:
        """解析阿里云 OCR 响应"""
        data = response.get('Data', {})
        blocks = data.get('BlockList', [])
        texts = [block.get('Content', '') for block in blocks if block.get('Content')]
        return '\n'.join(texts)
    
    def _parse_custom_response(self, response: Dict[str, Any]) -> str:
        """解析自定义 API 响应"""
        response_format = self.custom_response_format.lower()
        
        if response_format == 'openai':
            return self._parse_openai_response(response)
        
        if response_format == 'text':
            if isinstance(response, str):
                return response
            if isinstance(response, dict):
                return response.get('text', response.get('content', str(response)))
            return str(response)
        
        path_parts = self.custom_response_path.split('.')
        result = response
        for i, part in enumerate(path_parts):
            if '[' in part and ']' in part:
                key = part.split('[')[0]
                index_str = part.split('[')[1].split(']')[0]
                try:
                    index = int(index_str)
                except ValueError:
                    logger.warning(f"Invalid index in path '{part}': {index_str}")
                    return ''
                
                if key:
                    result = result.get(key, [])
                if not isinstance(result, list):
                    logger.warning(f"Expected list at '{key}' but got {type(result).__name__}")
                    return ''
                if len(result) <= index:
                    logger.warning(f"Index {index} out of range for list of length {len(result)}")
                    return ''
                result = result[index]
            else:
                if not isinstance(result, dict):
                    logger.warning(f"Expected dict at path part '{part}' but got {type(result).__name__}")
                    return ''
                if part not in result:
                    logger.warning(f"Key '{part}' not found in response at path position {i}")
                    return ''
                result = result[part]
        
        if isinstance(result, str):
            return result
        elif isinstance(result, list):
            return '\n'.join(str(item) for item in result)
        elif isinstance(result, dict):
            return result.get('text', result.get('content', str(result)))
        return str(result)
    
    def _call_api_sync(self, image_base64: str, language: Optional[OCRLanguage] = None) -> Dict[str, Any]:
        """同步调用在线 OCR API"""
        if self.provider == OnlineOCRProvider.OPENAI:
            request_body = self._build_openai_request(image_base64, language)
            url = f"{self.config.online_base_url.rstrip('/')}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.online_api_key}"
            }
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, json=request_body, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_openai_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.ZHIPU:
            request_body = self._build_zhipu_request(image_base64, language)
            url = f"{self.config.online_base_url.rstrip('/')}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.online_api_key}"
            }
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, json=request_body, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_openai_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.BAIDU:
            url, body = self._build_baidu_request(image_base64, language)
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, data=body, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_baidu_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.TENCENT:
            url, body, headers = self._build_tencent_request(image_base64, language)
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, content=body, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_tencent_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.ALIYUN:
            url, params, headers = self._build_aliyun_request(image_base64, language)
            with httpx.Client(timeout=60.0) as client:
                response = client.post(url, data=params, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_aliyun_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.CUSTOM:
            url, method, headers, body = self._build_custom_request(image_base64, language)
            with httpx.Client(timeout=60.0) as client:
                if method == 'GET':
                    response = client.get(url, params=body, headers=headers)
                else:
                    response = client.post(url, json=body, headers=headers)
                response.raise_for_status()
                try:
                    result = response.json()
                    result['_text'] = self._parse_custom_response(result)
                except:
                    result = {'_text': response.text}
                return result
        
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    async def _call_api_async(self, image_base64: str, language: Optional[OCRLanguage] = None) -> Dict[str, Any]:
        """异步调用在线 OCR API"""
        if self.provider == OnlineOCRProvider.OPENAI:
            request_body = self._build_openai_request(image_base64, language)
            url = f"{self.config.online_base_url.rstrip('/')}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.online_api_key}"
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=request_body, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_openai_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.ZHIPU:
            request_body = self._build_zhipu_request(image_base64, language)
            url = f"{self.config.online_base_url.rstrip('/')}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.online_api_key}"
            }
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=request_body, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_openai_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.BAIDU:
            url, body = self._build_baidu_request(image_base64, language)
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, data=body, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_baidu_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.TENCENT:
            url, body, headers = self._build_tencent_request(image_base64, language)
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, content=body, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_tencent_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.ALIYUN:
            url, params, headers = self._build_aliyun_request(image_base64, language)
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, data=params, headers=headers)
                response.raise_for_status()
                result = response.json()
                result['_text'] = self._parse_aliyun_response(result)
                return result
        
        elif self.provider == OnlineOCRProvider.CUSTOM:
            url, method, headers, body = self._build_custom_request(image_base64, language)
            async with httpx.AsyncClient(timeout=60.0) as client:
                if method == 'GET':
                    response = await client.get(url, params=body, headers=headers)
                else:
                    response = await client.post(url, json=body, headers=headers)
                response.raise_for_status()
                try:
                    result = response.json()
                    result['_text'] = self._parse_custom_response(result)
                except:
                    result = {'_text': response.text}
                return result
        
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    def recognize(
        self,
        image: Union[Image.Image, np.ndarray, str],
        language: Optional[OCRLanguage] = None,
        **kwargs
    ) -> OCRResult:
        """使用在线 OCR 服务识别图像中的文字"""
        try:
            image_base64 = self._image_to_base64(image)
            
            async_mode = kwargs.get('async_mode', False)
            
            if async_mode:
                import asyncio
                response = asyncio.run(self._call_api_async(image_base64, language))
            else:
                response = self._call_api_sync(image_base64, language)
            
            text = response.get('_text', '')
            
            if text == '无文字' or not text:
                return OCRResult(
                    texts=[],
                    success=True,
                    engine=self.engine_type
                )
            
            texts = [OCRTextItem(
                text=text,
                confidence=1.0,
                bbox=None
            )]
            
            logger.info(f"Online OCR recognized text: {text[:100]}...")
            
            return OCRResult(
                texts=texts,
                success=True,
                engine=self.engine_type,
                raw_result=response
            )
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Online OCR API error: {e}")
            return OCRResult(
                texts=[],
                success=False,
                engine=self.engine_type,
                error_message=f"API error: {e.response.status_code}"
            )
        except Exception as e:
            logger.error(f"Online OCR recognition failed: {e}")
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
    
    def is_available(self) -> bool:
        """检查在线 OCR 服务是否可用"""
        if self.provider == OnlineOCRProvider.BAIDU:
            return bool(self.config.online_api_key and self.baidu_secret_key)
        elif self.provider == OnlineOCRProvider.TENCENT:
            return bool(self.tencent_secret_id and self.tencent_secret_key)
        elif self.provider == OnlineOCRProvider.ALIYUN:
            return bool(self.aliyun_access_key_id and self.aliyun_access_key_secret)
        elif self.provider == OnlineOCRProvider.CUSTOM:
            return bool(self.config.online_base_url)
        else:
            return bool(self.config.online_api_key)
    
    @classmethod
    def check_configuration(cls, config: OCRConfig) -> dict:
        """检查在线 OCR 配置"""
        result = {
            'provider': config.online_provider,
            'model': config.online_model,
            'base_url': config.online_base_url,
            'api_key_configured': bool(config.online_api_key),
            'available': False,
            'error': None
        }
        
        provider_str = config.online_provider or 'openai'
        try:
            provider = OnlineOCRProvider(provider_str.lower())
        except ValueError:
            provider = OnlineOCRProvider.CUSTOM
        
        if provider == OnlineOCRProvider.BAIDU:
            extra = config.extra_params or {}
            result['available'] = bool(config.online_api_key and extra.get('secret_key'))
            if not result['available']:
                result['error'] = 'Baidu OCR requires API key and secret key'
        elif provider == OnlineOCRProvider.TENCENT:
            extra = config.extra_params or {}
            result['available'] = bool(extra.get('secret_id') and extra.get('secret_key'))
            if not result['available']:
                result['error'] = 'Tencent OCR requires secret_id and secret_key'
        elif provider == OnlineOCRProvider.ALIYUN:
            extra = config.extra_params or {}
            result['available'] = bool(extra.get('access_key_id') and extra.get('access_key_secret'))
            if not result['available']:
                result['error'] = 'Aliyun OCR requires access_key_id and access_key_secret'
        elif provider == OnlineOCRProvider.CUSTOM:
            result['available'] = bool(config.online_base_url)
            if not result['available']:
                result['error'] = 'Custom OCR requires base_url'
        else:
            if not config.online_api_key:
                result['error'] = 'API key not configured'
            else:
                result['available'] = True
        
        return result
