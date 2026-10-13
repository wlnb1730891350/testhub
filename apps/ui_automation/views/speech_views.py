"""
语音输入 API 视图
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


class SpeechTranscribeView(APIView):
    """
    语音转文字 API
    
    POST /api/ui-automation/speech/transcribe/
    Content-Type: multipart/form-data
    
    Parameters:
        audio: 音频文件 (webm/mp3/wav)
        language: 语言代码 (zh/en/auto)，默认 zh
    
    Returns:
        {
            'code': 0,
            'text': '转写后的文本',
            'normalized_text': '规范化后的文本',
            'confidence': 0.95
        }
    """
    permission_classes = [IsAuthenticated]
    parser_classes = []  # 手动处理 multipart
    
    def post(self, request):
        try:
            audio_file = request.FILES.get('audio')
            language = request.data.get('language', 'zh')
            
            if not audio_file:
                return Response({
                    'code': 400,
                    'msg': '未提供音频文件',
                    'success': False
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 读取音频数据
            audio_data = audio_file.read()
            
            if len(audio_data) == 0:
                return Response({
                    'code': 400,
                    'msg': '音频文件为空',
                    'success': False
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 语音转文字
            from ..speech_input import SpeechProcessor
            processor = SpeechProcessor()
            
            transcribed_text, error = processor.transcribe_audio(
                audio_data=audio_data,
                language=language
            )
            
            if error:
                return Response({
                    'code': 500,
                    'msg': error,
                    'success': False
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # 文本规范化
            normalized_text = processor.normalize_speech_text(transcribed_text)
            
            return Response({
                'code': 0,
                'msg': '转写成功',
                'success': True,
                'data': {
                    'text': transcribed_text,
                    'normalized_text': normalized_text,
                    'language': language,
                    'confidence': 0.95  # Whisper 默认置信度
                }
            })
            
        except Exception as e:
            logger.error(f"语音转文字失败: {e}", exc_info=True)
            return Response({
                'code': 500,
                'msg': f'转写失败: {str(e)[:100]}',
                'success': False
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SpeechParseView(APIView):
    """
    自然语言解析 API
    
    POST /api/ui-automation/speech/parse/
    
    Parameters:
        text: 自然语言文本
    
    Returns:
        {
            'code': 0,
            'steps': [
                {
                    'action_type': 'click',
                    'description': '点击搜索按钮',
                    'element_hint': '搜索按钮',
                    'input_value': '',
                    'confidence': 0.95
                }
            ]
        }
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            text = request.data.get('text', '')
            
            if not text:
                return Response({
                    'code': 400,
                    'msg': '未提供文本',
                    'success': False
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 自然语言解析
            from ..speech_input import NaturalLanguageParser
            parser = NaturalLanguageParser()
            steps = parser.parse(text)
            
            return Response({
                'code': 0,
                'msg': '解析成功',
                'success': True,
                'data': {
                    'steps': steps,
                    'original_text': text
                }
            })
            
        except Exception as e:
            logger.error(f"自然语言解析失败: {e}", exc_info=True)
            return Response({
                'code': 500,
                'msg': f'解析失败: {str(e)[:100]}',
                'success': False
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SpeechElementLocateView(APIView):
    """
    语音驱动的元素定位 API
    
    POST /api/ui-automation/speech/locate/
    
    Parameters:
        project_id: 项目ID（用于获取最近执行页面）
        description: 自然语言描述
        action_type: 动作类型 (click/type/search)
    
    Returns:
        {
            'code': 0,
            'locator': {
                'selector': 'button[type="submit"]',
                'strategy': 'css',
                'confidence': 0.95,
                'reason': '按钮文本匹配'
            },
            'element_info': {
                'tag': 'button',
                'text': '搜索',
                'position': {...}
            }
        }
    """
    permission_classes = [IsAuthenticated]
    
    async def post(self, request):
        try:
            project_id = request.data.get('project_id')
            description = request.data.get('description', '')
            action_type = request.data.get('action_type', 'click')
            
            if not project_id or not description:
                return Response({
                    'code': 400,
                    'msg': '缺少必要参数',
                    'success': False
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 获取最近的 Playwright 页面上下文
            # TODO: 实现页面上下文管理
            page = None
            
            if not page:
                return Response({
                    'code': 400,
                    'msg': '无可用的浏览器页面，请先启动执行环境',
                    'success': False
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # 元素定位
            from ..element_locator import NaturalLanguageElementLocator
            locator = NaturalLanguageElementLocator()
            
            candidate = await locator.locate(
                page=page,
                description=description,
                action_type=action_type
            )
            
            if not candidate:
                return Response({
                    'code': 404,
                    'msg': '未找到匹配的元素',
                    'success': False,
                    'data': {
                        'description': description,
                        'action_type': action_type
                    }
                }, status=status.HTTP_404_NOT_FOUND)
            
            # 捕捉元素信息
            from ..element_locator import ElementCapture
            page_locator = page.locator(candidate.selector).first
            capture_result = await ElementCapture.capture(page_locator, include_screenshot=True)
            
            return Response({
                'code': 0,
                'msg': '定位成功',
                'success': True,
                'data': {
                    'locator': {
                        'selector': candidate.selector,
                        'strategy': candidate.strategy,
                        'confidence': candidate.confidence,
                        'reason': candidate.reason
                    },
                    'element_info': capture_result
                }
            })
            
        except Exception as e:
            logger.error(f"元素定位失败: {e}", exc_info=True)
            return Response({
                'code': 500,
                'msg': f'定位失败: {str(e)[:100]}',
                'success': False
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
