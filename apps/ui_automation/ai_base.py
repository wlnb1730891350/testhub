import logging

logger = logging.getLogger('django')

import os

# 禁用 browser-use 遥测
os.environ['ANONYMIZED_TELEMETRY'] = 'false'

import asyncio
import functools
import json
import re
import time
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from .business_actions import _find_best_login_dialog, _find_login_field, evaluate_login_success

# 加载环境变量
load_dotenv()

TASK_STATUS_ACTIONS = {'mark_task_complete', 'mark_task_failed', 'mark_task_skipped'}


def _normalize_action_params(action_name, action_params):
    """Normalize common LLM-generated action parameter variants to browser-use schema."""
    if isinstance(action_params, int):
        if action_name in TASK_STATUS_ACTIONS:
            return {'task_id': action_params}
        return {'index': action_params}

    if action_name == 'switch_tab' and isinstance(action_params, str) and not isinstance(action_params, dict):
        return {'tab_id': action_params}

    if not isinstance(action_params, dict):
        return action_params

    normalized_params = {}
    for key, value in action_params.items():
        normalized_key = key
        if key in {'element_index', 'element_id', 'node_id', 'id'} and action_name not in TASK_STATUS_ACTIONS:
            normalized_key = 'index'
        elif key in {'tab', 'target', 'target_id'} and action_name in {'switch_tab', 'switch'}:
            normalized_key = 'tab_id'
        elif key in {'content', 'value'} and action_name in {'input', 'input_text'}:
            normalized_key = 'text'
        normalized_params[normalized_key] = value
    return normalized_params


def _is_terminal_status_action(action_name, action_params):
    if action_name in TASK_STATUS_ACTIONS:
        return True
    if action_name != 'update_task_status' or not isinstance(action_params, dict):
        return False
    return str(action_params.get('status', '')).strip().lower() in {'completed', 'failed', 'skipped'}


def _enforce_single_task_step(actions):
    """
    Enforce single-task-per-step:
    once a terminal task status action appears, discard any later business actions.
    """
    if not isinstance(actions, list):
        return actions

    trimmed_actions = []
    terminal_seen = False
    dropped_count = 0

    for action in actions:
        if not isinstance(action, dict):
            trimmed_actions.append(action)
            continue

        if terminal_seen:
            dropped_count += 1
            continue

        trimmed_actions.append(action)
        for action_name, action_params in action.items():
            if _is_terminal_status_action(action_name, action_params):
                terminal_seen = True
                break
            if action_name == 'done':
                terminal_seen = True
                break

    if dropped_count:
        logger.warning(
            f"⚠️ Enforced single-task step boundary: dropped {dropped_count} action(s) after terminal status update"
        )

    return trimmed_actions


def _get_task_status_action_task_id(action):
    if not isinstance(action, dict):
        return None

    for action_name, action_params in action.items():
        if action_name in TASK_STATUS_ACTIONS and isinstance(action_params, dict):
            return action_params.get('task_id')
        if action_name == 'update_task_status' and isinstance(action_params, dict):
            status = str(action_params.get('status', '')).strip().lower()
            if status in {'completed', 'failed', 'skipped'}:
                return action_params.get('task_id')
    return None


def _has_real_business_action(action):
    if not isinstance(action, dict):
        return False
    return any(
        action_name not in {'mark_task_complete', 'mark_task_failed', 'mark_task_skipped', 'update_task_status', 'done'}
        for action_name in action.keys()
    )


def _extract_task_literals(task_description):
    if not task_description:
        return []

    text = str(task_description)
    literals = []
    literals.extend(re.findall(r'「([^」]+)」', text))
    literals.extend(re.findall(r'"([^"\n]+)"', text))
    literals.extend(re.findall(r"'([^'\n]+)'", text))
    literals.extend(re.findall(r'https?://[^\s]+', text))
    literals.extend(re.findall(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', text))

    deduped = []
    for item in literals:
        cleaned = str(item).strip()
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
    return deduped


def _action_matches_pending_task(action, pending_task_description):
    if not isinstance(action, dict):
        return False

    literals = _extract_task_literals(pending_task_description)
    if not literals:
        return False

    action_payload = json.dumps(action, ensure_ascii=False)
    return any(literal in action_payload for literal in literals)


def _enforce_pending_status_settlement(actions, pending_task_id, pending_task_description=None):
    """
    If the previous step executed a task but forgot to mark it, the next step must settle
    that pending task status first and must not start the following business task in the same step.
    """
    if not pending_task_id or not isinstance(actions, list):
        return actions

    marked_pending_task = any(
        str(_get_task_status_action_task_id(action)) == str(pending_task_id)
        for action in actions
    )
    has_real_action = any(_has_real_business_action(action) for action in actions)

    if not (marked_pending_task and has_real_action):
        return actions

    real_actions = [action for action in actions if _has_real_business_action(action)]
    if pending_task_description and any(
        _action_matches_pending_task(action, pending_task_description)
        for action in real_actions
    ):
        return actions

    settled_actions = [
        action for action in actions
        if str(_get_task_status_action_task_id(action)) == str(pending_task_id)
    ]

    if settled_actions:
        logger.warning(
            f"⚠️ Settling pending task {pending_task_id} first: dropped business actions from the same step"
        )
        return settled_actions

    return actions


def _contains_auth_failure_signal(text):
    if not text:
        return False

    normalized = str(text).lower()
    keywords = [
        '登录失败', 'login failed', 'invalid credentials', 'incorrect password',
        '用户名或密码', '账号或密码', 'authentication failed', 'auth failed',
        'bad credentials', 'unauthorized', '401', '403'
    ]
    return any(keyword in normalized for keyword in keywords)

# ============================================================================

# ============================================================================

# PART 1: Common Patches (Pydantic, ActionModel, TokenCost, Basic Connection)
# ============================================================================

# Patch ChatOpenAI to allow setting attributes (required for browser-use token counting)
try:
    from pydantic import ConfigDict

    if hasattr(ChatOpenAI, 'model_config'):
        if isinstance(ChatOpenAI.model_config, dict):
            ChatOpenAI.model_config['extra'] = 'allow'
        else:
            ChatOpenAI.model_config = ConfigDict(extra='allow', arbitrary_types_allowed=True)
    else:
        ChatOpenAI.model_config = ConfigDict(extra='allow', arbitrary_types_allowed=True)
except ImportError:
    if hasattr(ChatOpenAI, 'model_config'):
        ChatOpenAI.model_config['extra'] = 'allow'

# 修改 ActionModel 配置以允许额外字段
try:
    from browser_use.tools.registry.views import ActionModel
    from pydantic import ConfigDict

    ActionModel.model_config = ConfigDict(arbitrary_types_allowed=True, extra='allow')
    logger.info("✅ Modified ActionModel.model_config to allow extra fields")
except Exception as e:
    logger.warning(f"⚠️ Failed to modify ActionModel config: {e}")

# Patch Agent.get_model_output 方法
try:
    from browser_use.agent.service import Agent
    from browser_use.agent.message_manager.service import AgentOutput
    import json as json_module

    _original_get_model_output = Agent.get_model_output


    async def _patched_get_model_output(self, input_messages):
        """修补后的 get_model_output，直接从 response.content 解析 JSON"""
        # logger.info("🔧 _patched_get_model_output called")

        if hasattr(self, '_task_was_done') and self._task_was_done:
            logger.info("🔧 Task was marked as done, stopping LLM interaction")
            raise KeyboardInterrupt("Task finished")

        kwargs = {'output_format': self.AgentOutput}

        # Add retry logic for LLM invocation with timeout
        max_retries = 2  # 重试次数为2次
        last_exception = None
        response = None
        for attempt in range(max_retries):
            try:
                # 添加超时控制，设置为60秒（支持硅基流动等大模型API的响应时间）
                response = await asyncio.wait_for(
                    self.llm.ainvoke(input_messages, **kwargs),
                    timeout=60.0  # 超时时间60秒
                )
                break
            except asyncio.TimeoutError as te:
                last_exception = te
                logger.warning(f"⚠️ LLM invocation timed out (attempt {attempt + 1}/{max_retries}): {te}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)  # 重试间隔0.5秒
            except Exception as e:
                last_exception = e
                logger.warning(f"⚠️ LLM invocation failed (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.5)  # 重试间隔0.5秒
        else:
            logger.error(f"❌ LLM invocation failed after {max_retries} attempts.")
            raise last_exception

        # 检查响应是否为空或无效
        if not response or not hasattr(response, 'content'):
            error_msg = "LLM returned invalid response (no content attribute)"
            logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)

        # 检查content是否为空字符串
        content = response.content
        if not content or not isinstance(content, str) or not content.strip():
            error_msg = "LLM returned empty content - possible API error or timeout"
            logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)

        try:
            if hasattr(response, 'content') and isinstance(response.content, str):
                # 处理带有 <thinking> 标签的响应
                content_text = response.content.strip()
                # 移除开头的 <thinking>...</thinking> 标签块
                import re
                thinking_pattern = r'^<thinking>.*?</thinking>\s*'
                if re.match(thinking_pattern, content_text, re.DOTALL):
                    content_text = re.sub(thinking_pattern, '', content_text, count=1, flags=re.DOTALL)
                    logger.info("🔧 Fixed: removed leading <thinking> block from response")

                content_dict = json_module.loads(content_text)

                # 规范化 action 字典
                if 'action' in content_dict:
                    import re
                    normalized_actions = []
                    for action_dict in content_dict['action']:
                        # 处理字符串格式的 action（如 "mark_task_complete(task_id=8)"）
                        if isinstance(action_dict, str):
                            match = re.match(r'(\w+)\(([^)]*)\)', action_dict.strip())
                            if match:
                                action_name = match.group(1)
                                params_str = match.group(2)
                                # 解析参数
                                if action_name in TASK_STATUS_ACTIONS:
                                    task_id_match = re.search(r'task_id=(\d+)', params_str)
                                    if task_id_match:
                                        normalized_actions.append({action_name: {'task_id': int(task_id_match.group(1))}})
                                        logger.info(f"🔧 Fixed: parsed string action '{action_dict}'")
                                elif action_name == 'update_task_status':
                                    task_id_match = re.search(r'task_id=(\d+)', params_str)
                                    status_match = re.search(r"status=['\"]?(\w+)['\"]?", params_str)
                                    if task_id_match and status_match:
                                        normalized_actions.append({
                                            action_name: {
                                                'task_id': int(task_id_match.group(1)),
                                                'status': status_match.group(1)
                                            }
                                        })
                                        logger.info(f"🔧 Fixed: parsed string action '{action_dict}'")
                                elif action_name == 'done':
                                    normalized_actions.append({'done': {}})
                            continue

                        normalized_action = {}
                        for action_name, action_params in action_dict.items():
                            normalized_value = _normalize_action_params(action_name, action_params)
                            # 忽略无效的字符串参数（如 {"click": "保存"}）
                            if isinstance(normalized_value, str) and action_name not in ['done', 'switch_tab']:
                                logger.warning(f"⚠️ Invalid action format: {action_name}: {normalized_value}, skipping")
                                continue
                            normalized_action[action_name] = normalized_value
                        if normalized_action:  # 只添加非空的 action
                            normalized_actions.append(normalized_action)
                    normalized_actions = _enforce_single_task_step(normalized_actions)
                    pending_task_id = getattr(self, '_pending_status_task_id', None)
                    pending_task_description = getattr(self, '_pending_status_task_description', None)
                    content_dict['action'] = _enforce_pending_status_settlement(
                        normalized_actions,
                        pending_task_id,
                        pending_task_description
                    )

                # 检查 action 数组外部的 mark_task_complete（错误格式）
                # 如果存在，将其添加到 action 数组中
                for action_name in [*TASK_STATUS_ACTIONS, 'update_task_status']:
                    if action_name not in content_dict:
                        continue
                    if 'action' not in content_dict:
                        content_dict['action'] = []
                    if isinstance(content_dict[action_name], dict):
                        content_dict['action'].append({action_name: content_dict[action_name]})
                        logger.info(f"🔧 Fixed: moved {action_name} into action array")
                    elif isinstance(content_dict[action_name], int) and action_name in TASK_STATUS_ACTIONS:
                        task_id = content_dict[action_name]
                        content_dict['action'].append({action_name: {'task_id': task_id}})
                        logger.info(f"🔧 Fixed: converted {action_name}({task_id}) to proper format and added to action array")

                parsed = AgentOutput.model_construct(
                    thinking=content_dict.get('thinking'),
                    evaluation_previous_goal=content_dict.get('evaluation_previous_goal'),
                    memory=content_dict.get('memory'),
                    next_goal=content_dict.get('next_goal'),
                    action=[]
                )

                class _ActionWrapper:
                    def __init__(self, action_dict):
                        self._action_dict = action_dict

                    def model_dump(self, **kwargs):
                        return self._action_dict

                    def get_index(self):
                        for action_params in self._action_dict.values():
                            if isinstance(action_params, dict) and 'index' in action_params:
                                return action_params['index']
                        return None

                action_list = []
                for action_dict in content_dict.get('action', []):
                    action_list.append(_ActionWrapper(action_dict))

                object.__setattr__(parsed, 'action', action_list)

                if len(parsed.action) > self.settings.max_actions_per_step:
                    parsed.action = parsed.action[:self.settings.max_actions_per_step]

                return parsed
        except Exception as e:
            # If our complex normalization fails, fall back to the original method
            logger.warning(f"⚠️ Custom output normalization failed, falling back: {e}")
            return await _original_get_model_output(self, input_messages)


    Agent.get_model_output = _patched_get_model_output
    logger.info("✅ Successfully patched Agent.get_model_output")
except Exception as e:
    logger.error(f"❌ Failed to patch Agent.get_model_output: {e}")

# Patch TokenCost
try:
    from browser_use.tokens.service import TokenCost
    from langchain_core.messages import HumanMessage, SystemMessage as LangChainSystemMessage, AIMessage


    def _patched_register_llm(self, llm):
        """修补后的 register_llm，修复 langchain 兼容性"""
        instance_id = str(id(llm))
        if instance_id in self.registered_llms:
            return llm

        self.registered_llms[instance_id] = llm
        _original_ainvoke = llm.ainvoke
        _token_service = self

        async def _fixed_tracked_ainvoke(messages, output_format=None, **kwargs):
            # Sanitize message contents
            def _content_to_str(content):
                if isinstance(content, str): return content
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, str):
                            parts.append(item)
                        elif isinstance(item, dict):
                            if 'text' in item:
                                parts.append(str(item['text']))
                            elif 'image' in item or 'image_url' in item:
                                parts.append("[image]")
                        else:
                            parts.append(str(item))
                    return "\n".join(parts)
                if isinstance(content, dict):
                    if 'text' in content: return str(content['text'])
                    if 'content' in content: return str(content['content'])
                    if 'image' in content or 'image_url' in content: return "[image]"
                return str(content)

            def _sanitize_message(msg):
                msg_type_name = type(msg).__name__
                content = getattr(msg, 'content', msg)
                content_str = _content_to_str(content)
                if msg_type_name == 'SystemMessage': return LangChainSystemMessage(content=content_str)
                if msg_type_name in ('HumanMessage', 'UserMessage'): return HumanMessage(content=content_str)
                if msg_type_name == 'AIMessage': return AIMessage(content=content_str)
                if isinstance(msg, (HumanMessage, LangChainSystemMessage, AIMessage)): return type(msg)(
                    content=content_str)
                return HumanMessage(content=str(content_str))

            sanitized_messages = [_sanitize_message(m) for m in messages]

            output_format = kwargs.pop('output_format', None)
            if output_format:
                kwargs['response_format'] = {"type": "json_object"}

            # Add retry logic for LLM invocation
            max_retries = 2  # 重试次数为2次
            last_exception = None
            for attempt in range(max_retries):
                try:
                    result = await _original_ainvoke(sanitized_messages, **kwargs)
                    break
                except Exception as e:
                    last_exception = e
                    if "response_format" in str(e):
                        kwargs.pop('response_format', None)
                        # retry immediately without response_format
                        continue

                    logger.warning(f"⚠️ LLM ainvoke failed (attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.5)  # 等待0.5秒
            else:
                logger.error(f"❌ LLM ainvoke failed after {max_retries} attempts.")
                raise last_exception

            # Enhance response parsing
            import json as json_module
            clean_content = result.content.strip() if hasattr(result, 'content') else str(result).strip()

            # 处理带有 <thinking> 标签的响应
            thinking_pattern = r'^<thinking>.*?</thinking>\s*'
            if re.match(thinking_pattern, clean_content, re.DOTALL):
                clean_content = re.sub(thinking_pattern, '', clean_content, count=1, flags=re.DOTALL)
                logger.info("🔧 Fixed in TokenCost: removed leading <thinking> block from response")

            # Remove Markdown
            if '```' in clean_content:
                match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', clean_content, re.DOTALL)
                if match:
                    clean_content = match.group(1).strip()
                else:
                    clean_content = re.sub(r'```[a-z]*', '', clean_content).replace('```', '').strip()

            parsed_data = None
            try:
                parsed_data = json_module.loads(clean_content)
            except Exception:
                try:
                    match = re.search(r'(\{.*\})', clean_content, re.DOTALL)
                    if match: parsed_data = json_module.loads(match.group(1))
                except Exception:
                    pass

            # Wrapper classes
            class _ActionWrapper:
                def __init__(self, action_dict):
                    self._dict = {}
                    for k, v in action_dict.items():
                        if isinstance(v, dict):
                            self._dict[k] = _normalize_action_params(k, v)
                        else:
                            self._dict[k] = v
                    for k, v in self._dict.items(): setattr(self, k, v)

                def model_dump(self, **kwargs):
                    return self._dict

                def get_index(self):
                    for v in self._dict.values():
                        if isinstance(v, dict) and 'index' in v: return v['index']
                    return None

            # Construct AgentOutput manually
            agent_output = None
            if parsed_data and 'action' in parsed_data:
                # Normalize actions
                normalized_actions = []
                for action_dict in parsed_data['action']:
                    # 处理字符串格式的 action（如 "mark_task_complete(task_id=8)"）
                    if isinstance(action_dict, str):
                        match = re.match(r'(\w+)\(([^)]*)\)', action_dict.strip())
                        if match:
                            action_name = match.group(1)
                            params_str = match.group(2)
                            # 解析参数
                            if action_name in TASK_STATUS_ACTIONS:
                                task_id_match = re.search(r'task_id=(\d+)', params_str)
                                if task_id_match:
                                    normalized_actions.append({action_name: {'task_id': int(task_id_match.group(1))}})
                                    logger.info(f"🔧 Fixed in TokenCost: parsed string action '{action_dict}'")
                            elif action_name == 'update_task_status':
                                task_id_match = re.search(r'task_id=(\d+)', params_str)
                                status_match = re.search(r"status=['\"]?(\w+)['\"]?", params_str)
                                if task_id_match and status_match:
                                    normalized_actions.append({
                                        action_name: {
                                            'task_id': int(task_id_match.group(1)),
                                            'status': status_match.group(1)
                                        }
                                    })
                                    logger.info(f"🔧 Fixed in TokenCost: parsed string action '{action_dict}'")
                            elif action_name == 'done':
                                normalized_actions.append({'done': {}})
                        continue

                    normalized_action = {}
                    for action_name, action_params in action_dict.items():
                        normalized_value = _normalize_action_params(action_name, action_params)
                        # 忽略无效的字符串参数（如 {"click": "保存"}）
                        if isinstance(normalized_value, str) and action_name not in ['done', 'switch_tab']:
                            logger.warning(f"⚠️ Invalid action format in TokenCost: {action_name}: {normalized_value}, skipping")
                            continue
                        normalized_action[action_name] = normalized_value
                    if normalized_action:  # 只添加非空的 action
                        normalized_actions.append(normalized_action)
                normalized_actions = _enforce_single_task_step(normalized_actions)
                pending_task_id = getattr(llm, '_pending_status_task_id', None)
                pending_task_description = getattr(llm, '_pending_status_task_description', None)
                parsed_data['action'] = _enforce_pending_status_settlement(
                    normalized_actions,
                    pending_task_id,
                    pending_task_description
                )

                # 检查 action 数组外部的 mark_task_complete（错误格式）
                for action_name in [*TASK_STATUS_ACTIONS, 'update_task_status']:
                    if action_name not in parsed_data:
                        continue
                    if isinstance(parsed_data[action_name], dict):
                        parsed_data['action'].append({action_name: parsed_data[action_name]})
                        logger.info(f"🔧 Fixed in TokenCost: moved {action_name} into action array")
                    elif isinstance(parsed_data[action_name], int) and action_name in TASK_STATUS_ACTIONS:
                        task_id = parsed_data[action_name]
                        parsed_data['action'].append({action_name: {'task_id': task_id}})
                        logger.info(f"🔧 Fixed in TokenCost: moved {action_name}(task_id={task_id}) into action array")

                try:
                    from browser_use.agent.message_manager.service import AgentOutput
                    agent_output = AgentOutput.model_construct(
                        thinking=parsed_data.get('thinking'),
                        evaluation_previous_goal=parsed_data.get('evaluation_previous_goal'),
                        memory=parsed_data.get('memory'),
                        next_goal=parsed_data.get('next_goal'),
                        action=[]
                    )
                    action_list = []
                    for action_dict in parsed_data.get('action', []):
                        action_list.append(_ActionWrapper(action_dict))
                    object.__setattr__(agent_output, 'action', action_list)
                except Exception as e:
                    logger.error(f"🔧 Failed to create AgentOutput: {e}")

            class _ResponseWrapper:
                def __init__(self, orig, completion_obj):
                    self._orig = orig
                    self.content = getattr(orig, 'content', '')
                    self.response_metadata = getattr(orig, 'response_metadata', {})
                    self.completion = completion_obj
                    usage = getattr(orig, 'usage', None) or (
                        orig.response_metadata.get('token_usage') if hasattr(orig, 'response_metadata') else None)
                    if not usage: usage = {}
                    # Fix usage
                    usage = dict(usage) if hasattr(usage, '__dict__') else usage
                    usage.setdefault('prompt_tokens', 0)
                    usage.setdefault('completion_tokens', 0)
                    usage.setdefault('total_tokens', 0)
                    self.usage = usage

                def __getattr__(self, name): return getattr(self._orig, name)

            wrapped = _ResponseWrapper(result, agent_output)
            if hasattr(wrapped, 'usage') and wrapped.usage:
                try:
                    _token_service.add_usage(llm.model, wrapped.usage)
                except Exception:
                    pass

            return wrapped

        setattr(llm, 'ainvoke', _fixed_tracked_ainvoke)
        return llm


    TokenCost.register_llm = _patched_register_llm
    logger.info("✅ Successfully patched TokenCost.register_llm")
except Exception as e:
    logger.error(f"❌ Failed to patch TokenCost: {e}")

# Patch BrowserSession.connect (Windows CDP fix)
try:
    from browser_use.browser.session import BrowserSession
    import httpx

    _original_connect = BrowserSession.connect


    async def _patched_connect(self, cdp_url=None):
        if cdp_url: return await _original_connect(self, cdp_url=cdp_url)

        browser_profile = getattr(self, 'browser_profile', None)
        if hasattr(browser_profile, 'cdp_url') and browser_profile.cdp_url:
            return await _original_connect(self, cdp_url=browser_profile.cdp_url)

        port = 9222
        if hasattr(browser_profile, 'extra_chromium_args'):
            for arg in browser_profile.extra_chromium_args:
                if '--remote-debugging-port=' in str(arg):
                    try:
                        port = int(arg.split('=')[1]); break
                    except Exception:
                        pass
        if hasattr(browser_profile, 'remote_debugging_port'):
            port = browser_profile.remote_debugging_port

        cdp_endpoint = f"http://localhost:{port}/json/version"

        for attempt in range(10): # 增加重试次数
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(cdp_endpoint)
                    if response.status_code == 200 and response.text:
                        version_info = response.json()
                        browser_profile.cdp_url = version_info['webSocketDebuggerUrl']
                        return await _original_connect(self, cdp_url=browser_profile.cdp_url)
            except Exception:
                if attempt < 4: await asyncio.sleep(1.0)

        return await _original_connect(self, cdp_url=cdp_url)


    BrowserSession.connect = _patched_connect
    logger.info("✅ Successfully patched BrowserSession.connect")
except Exception as e:
    logger.error(f"❌ Failed to patch BrowserSession.connect: {e}")

# Patch ClickElementAction parameters
try:
    from browser_use.tools.views import ClickElementAction

    _original_click_init = ClickElementAction.__init__


    def _patched_click_init(self, **kwargs):
        fixed_kwargs = {}
        for key, value in kwargs.items():
            if isinstance(value, int) and key not in ['index']:
                fixed_kwargs['index'] = value
            else:
                fixed_kwargs[key] = value
        if len(kwargs) == 1:
            key, value = list(kwargs.items())[0]
            if isinstance(value, int) and key != 'index':
                fixed_kwargs = {'index': value}
        try:
            return _original_click_init(self, **fixed_kwargs)
        except TypeError:
            if fixed_kwargs and isinstance(list(fixed_kwargs.values())[0], int):
                return _original_click_init(self, **{'index': list(fixed_kwargs.values())[0]})
            raise


    ClickElementAction.__init__ = _patched_click_init
except Exception:
    pass

# Patch ToolRegistry
try:
    from browser_use.tools.registry.service import Registry as ToolRegistry

    # Force patch Registry class
    _original_execute_action = ToolRegistry.execute_action


    async def _patched_execute_action(self, action_name: str, params: dict, **kwargs):
        # 自动映射 switch_tab -> switch (强制映射)
        if action_name == 'switch_tab':
            logger.info(f"🔧 Force aliasing: switch_tab -> switch")
            action_name = 'switch'

        if isinstance(params, int):
            params = {'index': params}
        elif not isinstance(params, dict) and params is not None:
            # 针对 switch_tab 可能是纯字符串的情况
            if action_name in ['switch_tab', 'switch']:
                params = {'tab_id': params}
            else:
                params = {'value': params} if params else {}

        if isinstance(params, dict):
            normalized_params = _normalize_action_params(action_name, params)
            if normalized_params != params:
                logger.info(f"🔧 Normalized action params for {action_name}: {params} -> {normalized_params}")
            params = normalized_params

        # 针对点击增加延迟，确保 UI 更新 (如弹窗弹出、下拉框展开)
        if action_name in ['click_element', 'click']:
            result = await _original_execute_action(self, action_name, params, **kwargs)
            # 增加延迟到 1.5s，并强制在点击后等待浏览器渲染
            # 尤其是对于 element-plus 等 UI 框架，下拉列表渲染需要时间
            await asyncio.sleep(1.5)
            return result

        return await _original_execute_action(self, action_name, params, **kwargs)


    ToolRegistry.execute_action = _patched_execute_action
    logger.info("✅ Successfully patched ToolRegistry.execute_action with alias support")
except Exception as e:
    logger.error(f"❌ Failed to patch ToolRegistry: {e}")

# Patch ScreenshotWatchdog GLOBALLY to fix timeouts
try:
    from browser_use.browser.watchdogs.screenshot_watchdog import ScreenshotWatchdog

    _original_on_screenshot_event = ScreenshotWatchdog.on_ScreenshotEvent

    # Check if already patched to avoid double patching
    if not getattr(_original_on_screenshot_event, '_is_patched_global', False):
        async def on_ScreenshotEvent(self, event):
            """
            Patched screenshot event handler with increased timeout and optimized parameters.
            """
            try:
                # Try original method first with strict timeout
                result = await asyncio.wait_for(
                    _original_on_screenshot_event(self, event),
                    timeout=3.0  # Reduced for fail-fast
                )
                return result
            except asyncio.TimeoutError:
                logger.warning(f"DEBUG: Watchdog timeout (3s), trying optimized approach...")
                try:
                    # Get CDP session
                    cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=None)
                    if not cdp_session: raise Exception("Failed to get CDP session")

                    params = {'format': 'png', 'quality': 50, 'from_surface': True, 'capture_beyond_viewport': False}

                    # One quick retry
                    result = await asyncio.wait_for(
                        cdp_session.cdp_client.send.Page.captureScreenshot(params=params,
                                                                           session_id=cdp_session.session_id),
                        timeout=3.0
                    )
                    return result

                except Exception as ex:
                    # In Text Mode especially, we don't want to die on screenshot
                    logger.warning(f"DEBUG: Screenshot failed optimized, returning placeholder: {ex}")
                    import base64
                    # 1x1 transparent pixel
                    placeholder = base64.b64decode(
                        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
                    return {'data': placeholder}
            except Exception as e:
                logger.error(f"DEBUG: Screenshot unexpected error: {e}")
                import base64
                placeholder = base64.b64decode(
                    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
                return {'data': placeholder}


        on_ScreenshotEvent._is_patched_global = True
        ScreenshotWatchdog.on_ScreenshotEvent = on_ScreenshotEvent
        logger.info("✅ Applied Global ScreenshotWatchdog Patch")

    # Patch DOMWatchdog
    from browser_use.browser.watchdogs.dom_watchdog import DOMWatchdog

    _original_capture_clean_screenshot = DOMWatchdog._capture_clean_screenshot

    if not getattr(_original_capture_clean_screenshot, '_is_patched_global', False):
        async def _capture_clean_screenshot(self):
            try:
                # Very short timeout for DOM clean screenshot checks
                return await asyncio.wait_for(_original_capture_clean_screenshot(self), timeout=3.0)
            except Exception as e:
                logger.warning(f"DEBUG: Clean screenshot failed/timed out: {e}, continuing...")
                return None


        _capture_clean_screenshot._is_patched_global = True
        DOMWatchdog._capture_clean_screenshot = _capture_clean_screenshot
        logger.info("✅ Applied Global DOMWatchdog Patch")

except Exception as e:
    logger.error(f"❌ Failed to apply Global Watchdog patches: {e}")

# Patch Agent verdict
try:
    from browser_use.agent.service import Agent
    from browser_use.agent.message_manager.service import AgentOutput

    _original_judge_and_log = Agent._judge_and_log


    def _agent_output_getattr(self, name):
        if name == 'verdict':
            if hasattr(self, 'next_goal') and self.next_goal:
                if any(
                    w in str(self.next_goal).lower() for w in ['complete', 'done', 'finished', 'success']): return True
            if hasattr(self, 'evaluation_previous_goal') and self.evaluation_previous_goal:
                if any(w in str(self.evaluation_previous_goal).lower() for w in ['success', 'complete']): return True
            return False
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")


    if not hasattr(AgentOutput, '__getattr__'):
        AgentOutput.__getattr__ = _agent_output_getattr


    async def _patched_judge_and_log(self):
        try:
            return await _original_judge_and_log(self)
        except AttributeError as e:
            if 'verdict' in str(e):
                return None
            raise


    Agent._judge_and_log = _patched_judge_and_log
except Exception:
    pass

# Patch LocalBrowserWatchdog._find_free_port to force port 9222 on Linux
try:
    from browser_use.browser.watchdogs.local_browser_watchdog import LocalBrowserWatchdog
    import platform

    _original_find_free_port = LocalBrowserWatchdog._find_free_port

    # 创建补丁函数 - 始终作为实例方法（接受 self）
    def _patched_find_free_port(self):
        if platform.system() == 'Linux':
            logger.info("🔧 Force using port 9222 for Linux environment")
            return 9222
        # 尝试调用原始方法，兼容不同签名
        try:
            return _original_find_free_port(self)
        except TypeError:
            # 如果原始方法不接受 self，尝试不带参数调用
            return _original_find_free_port()

    LocalBrowserWatchdog._find_free_port = _patched_find_free_port
    logger.info("✅ Successfully patched LocalBrowserWatchdog._find_free_port")
except Exception as e:
    logger.error(f"❌ Failed to patch LocalBrowserWatchdog._find_free_port: {e}")

# ============================================================================
# PART 2: Helper Classes
# ============================================================================

from langchain_core.callbacks import BaseCallbackHandler
from typing import Any


class RawResponseLogger(BaseCallbackHandler):
    def on_llm_new_token(self, token: str, **kwargs: Any) -> Any:
        pass

    def on_llm_end(self, response: Any, **kwargs: Any) -> Any:
        try:
            generation = response.generations[0][0]
            logger.info(f"DEBUG: Raw LLM Response: {generation.text}")
        except Exception:
            pass


# ============================================================================
# PART 3: Base Browser Agent
# ============================================================================

from browser_use import Agent, Controller
from browser_use.browser.events import CloseTabEvent, SwitchTabEvent
from browser_use.browser.profile import BrowserProfile


class BaseBrowserAgent:
    def __init__(self, execution_mode='text', enable_gif=True, case_name=None):
        self.execution_mode = 'text'
        self.enable_gif = enable_gif  # GIF录制开关
        self.case_name = case_name or "Adhoc Task"  # 用例名称

        # Load Config from DB
        from apps.requirement_analysis.models import AIModelConfig

        # Select Config (always use text mode config)
        role_name = 'browser_use_text'
        config_obj = AIModelConfig.objects.filter(role=role_name, is_active=True).first()

        model_config = {}
        if config_obj:
            model_config = {
                'api_key': config_obj.api_key,
                'base_url': config_obj.base_url,
                'model_name': config_obj.model_name,
                'provider': config_obj.model_type,
                'temperature': config_obj.temperature  # 读取配置的temperature
            }

        self.api_key = model_config.get('api_key') or os.getenv('AUTH_TOKEN')
        self.base_url = model_config.get('base_url') or os.getenv('BASE_URL')
        self.model_name = model_config.get('model_name') or os.getenv('MODEL_NAME')
        self.provider = model_config.get('provider', 'openai')

        if not self.api_key:
            raise ValueError(f"No API Key found for mode: {execution_mode}")

        # 智能temperature处理：特殊模型强制使用特定temperature值
        # 格式: {'模型名称关键字': temperature值}
        special_model_temperature_map = {
            'kimi-2.5': 1.0,  # Moonshot AI Kimi 2.5 只支持 temperature=1
            'kimi-k2.5': 1.0,  # Moonshot AI Kimi K2.5 只支持 temperature=1
            'kimi': 1.0,  # 通用Kimi模型匹配（兜底）
            # 未来可以在这里添加其他特殊模型，例如：
            # 'claude-3.5-sonnet': 0.7,
            # 'gpt-4-turbo': 0.0,
        }

        # 确定最终使用的temperature值
        final_temperature = 0.0  # 默认值
        model_name_lower = self.model_name.lower()

        # 1. 优先检查是否是特殊模型
        for model_keyword, temp in special_model_temperature_map.items():
            if model_keyword in model_name_lower:
                final_temperature = temp
                logger.info(f"✅ 检测到特殊模型 '{self.model_name}'，使用强制 temperature={temp}")
                break
        else:
            # 2. 如果不是特殊模型，使用配置中的值
            if 'temperature' in model_config:
                final_temperature = model_config['temperature']
                logger.info(f"📋 使用配置的 temperature={final_temperature}")
            else:
                # 3. 如果配置中没有，使用默认值
                final_temperature = 0.0
                logger.info(f"⚙️ 使用默认 temperature={final_temperature}")

        self.llm = ChatOpenAI(
            model=self.model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            temperature=final_temperature,
            callbacks=[RawResponseLogger()]
        )

        # browser-use requirement
        try:
            object.__setattr__(self.llm, 'provider', self.provider)
            object.__setattr__(self.llm, 'model', self.model_name)
        except Exception:
            if not hasattr(self.llm, '__pydantic_extra__') or self.llm.__pydantic_extra__ is None:
                self.llm.__pydantic_extra__ = {}
            self.llm.__pydantic_extra__['provider'] = self.provider
            self.llm.__pydantic_extra__['model'] = self.model_name

    def _format_action(self, action):
        try:
            action_dict = {}
            if hasattr(action, 'model_dump'):
                action_dict = action.model_dump()
            elif hasattr(action, '_action_dict'):
                action_dict = action._action_dict
            elif hasattr(action, '_dict'):
                action_dict = action._dict
            elif isinstance(action, dict):
                action_dict = action
            else:
                return str(action)

            if not action_dict: return "待机"

            descriptions = []
            for name, params in action_dict.items():
                if not params and name not in ['scroll_down', 'scroll_up', 'done']: continue

                if name in ['go_to_url', 'navigate']:
                    url = params.get('url') if isinstance(params, dict) else params
                    descriptions.append(f"访问: {url}")
                elif name in ['click_element', 'click']:
                    index = params.get('index') if isinstance(params, dict) else params
                    descriptions.append(f"点击[{index}]")
                elif name in ['input_text', 'input']:
                    text = params.get('text') if isinstance(params, dict) else None
                    descriptions.append(f"输入: '{text}'")
                elif name == 'switch_tab':
                    index = params.get('index', params)
                    descriptions.append(f"切换标签 {index}")
                elif name == 'open_new_tab':
                    url = params.get('url', params)
                    descriptions.append(f"新标签打开: {url}")
                elif name == 'close_tab':
                    descriptions.append("关闭当前标签页")
                elif name == 'done':
                    descriptions.append("任务完成")
                else:
                    descriptions.append(f"{name}")
            return " | ".join(descriptions)
        except Exception:
            return "执行操作"

    async def _verify_execution_llm(self):
        """在真正启动执行前做一次轻量连通性检查，避免浏览器启动后反复空转失败。"""
        try:
            await asyncio.wait_for(
                self.llm.ainvoke("Reply with OK."),
                timeout=20.0
            )
        except Exception as e:
            raise RuntimeError(f"Execution LLM unavailable: {e}") from e

    def _parse_nn_login_task(self, task_description: str):
        """识别 NN Web 手机验证码登录任务，返回 url/phone/code；不匹配返回 None。"""
        text = str(task_description or '')
        if 'test6-web.nn.com' not in text and 'test-web.nn.com' not in text and 'nn.com' not in text:
            return None
        if not any(keyword in text for keyword in ['手机号', '手机', '验证码', '登录']):
            return None
        url_match = re.search(r'https?://[^\s，。；、]+', text)
        phone_match = re.search(r'(?:手机号|手机号码|手机|账号)\D*(1\d{10})', text)
        code_match = re.search(r'(?:验证码|校验码)\D*(\d{4,8})', text)
        if not url_match or not phone_match or not code_match:
            return None
        return {
            'url': url_match.group(0).rstrip('/'),
            'phone': phone_match.group(1),
            'code': code_match.group(1),
        }

    async def _run_nn_login_deterministic(self, task_description: str, planned_tasks=None, callback=None, should_stop=None):
        """NN Web 登录确定性执行器：直接使用 Playwright，绕开通用 AI 乱点和 browser-use Page 包装差异。"""
        task = self._parse_nn_login_task(task_description)
        if not task:
            return None

        async def emit(payload):
            if not callback:
                return
            if asyncio.iscoroutinefunction(callback):
                await callback(payload)
            else:
                callback(payload)

        async def mark(task_id, status):
            if task_id:
                await emit({'task_id': int(task_id), 'status': status})

        def ensure_object(value):
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except Exception:
                    return {'raw': value}
            return value or {}

        def task_id_by_keywords(*keywords):
            if not planned_tasks:
                return None
            # 优先匹配 pending/in_progress 状态的任务，避免误匹配已完成的任务
            pending_match = None
            for item in planned_tasks:
                desc = str(item.get('description', ''))
                if any(keyword in desc for keyword in keywords):
                    if item.get('status', 'pending') in ('pending', 'in_progress'):
                        return item.get('id')
                    if pending_match is None:
                        pending_match = item.get('id')
            return pending_match

        async def log_step(title):
            await emit({'type': 'log', 'content': f'\n[Deterministic]\n{title}\n'})

        gif_frames = []

        async def capture_gif_frame(page, label):
            """确定性 Playwright 路径的轻量 GIF 录制：关键节点截图，结束后合成 GIF。"""
            if not self.enable_gif:
                return
            try:
                frame = await page.screenshot(type='png', full_page=False)
                gif_frames.append({'label': label, 'data': frame})
                await emit({'type': 'log', 'content': f'\n[System] GIF录制帧: {label}\n'})
            except Exception as frame_exc:
                logger.warning(f"⚠️ Deterministic GIF frame capture failed ({label}): {frame_exc}")

        def save_deterministic_gif():
            if not self.enable_gif or not gif_frames:
                return
            try:
                from io import BytesIO
                from PIL import Image, ImageDraw
                from .gif_utils import save_compact_gif
                output_path = os.path.join(os.getcwd(), 'agent_history.gif')
                frames = []
                for idx, item in enumerate(gif_frames, 1):
                    image = Image.open(BytesIO(item['data'])).convert('RGB')
                    # 给画面加一个很轻的步骤标签，便于报告回看。
                    draw = ImageDraw.Draw(image)
                    label = f"{idx}. {item.get('label', '')}"
                    draw.rectangle((8, 8, min(620, 18 + len(label) * 9), 36), fill=(0, 0, 0))
                    draw.text((14, 14), label, fill=(255, 255, 255))
                    frames.append(image)
                if frames:
                    save_compact_gif(frames, output_path, duration=900)
                    logger.info(f"✅ Deterministic GIF generated: {output_path}, frames={len(frames)}")
            except Exception as gif_exc:
                logger.warning(f"⚠️ Failed to generate deterministic GIF: {gif_exc}")

        await emit({'type': 'log', 'content': '\n[System] 检测到 NN 手机验证码登录任务，切换为确定性 Playwright 执行器。\n'})
        if self.enable_gif:
            await emit({'type': 'log', 'content': '\n[System] 已开启GIF录制，确定性执行器将按关键步骤截图合成GIF。\n'})

        login_final_status_recorded = False
        from playwright.async_api import async_playwright
        playwright = None
        browser = None
        context = None
        try:
            playwright = await async_playwright().start()
            headless = os.name != 'nt'
            browser = await playwright.chromium.launch(
                headless=headless,
                args=['--disable-blink-features=AutomationControlled', '--disable-infobars', '--disable-notifications']
            )
            context = await browser.new_context(viewport={'width': 1280, 'height': 720})
            page = await context.new_page()

            await log_step(f"访问: {task['url']}")
            await page.goto(task['url'], wait_until='domcontentloaded', timeout=45000)
            try:
                await page.wait_for_load_state('networkidle', timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(1500)
            await capture_gif_frame(page, '访问页面')
            await mark(task_id_by_keywords('访问'), 'completed')

            async def record_real_action(action_type, description, input_value='', assert_value='', element=None, source='deterministic_recorder'):
                """记录确定性执行器真实发生的浏览器动作，供 AI录制沉淀普通 UI 用例使用。"""
                payload = {
                    'type': 'record_action',
                    'action': {
                        'action_type': action_type,
                        'description': description,
                        'input_value': input_value or '',
                        'assert_value': assert_value or '',
                        'element_text': '',
                        'element_tag': '',
                        'locator_strategy': '',
                        'locator_value': '',
                        'locator_description': description,
                        'page_url': '',
                        'source': source,
                        'timestamp': time.time(),
                    }
                }
                try:
                    payload['action']['page_url'] = page.url
                except Exception:
                    pass
                if isinstance(element, dict):
                    payload['action'].update({k: v for k, v in element.items() if v is not None})
                await emit(payload)

            await record_real_action(
                'goto',
                f"访问: {task['url']}",
                input_value=task['url'],
                element={'locator_description': f"访问: {task['url']}"},
            )

            close_result = await page.evaluate("""
            () => {
              const closeSelectors = [
                'button[class*=close]', 'button[class*=Close]', '[aria-label*=关闭]', '[aria-label*=close]',
                '.el-dialog__headerbtn', '.ant-modal-close', '.popup-close', '.ad-close',
                'i[class*=close]', 'span[class*=close]', 'svg[class*=close]'
              ];
              for (const selector of closeSelectors) {
                for (const el of document.querySelectorAll(selector)) {
                  const r = el.getBoundingClientRect();
                  if (r.width > 0 && r.height > 0) { el.click(); return 'clicked ' + selector; }
                }
              }
              return 'no popup';
            }
            """)
            await log_step(f'关闭弹窗: {close_result}')
            await capture_gif_frame(page, '关闭弹窗')
            if isinstance(close_result, str) and close_result != 'no popup':
                await record_real_action(
                    'click',
                    f'关闭弹窗: {close_result}',
                    element={
                        'element_text': '关闭',
                        'element_tag': 'button',
                        'locator_strategy': 'xpath',
                        'locator_value': "(//*[contains(@class,'close') or contains(@class,'Close') or contains(@aria-label,'关闭') or contains(@aria-label,'close')])[1]",
                        'locator_description': '弹窗关闭按钮',
                    },
                )
            await mark(task_id_by_keywords('弹窗', '关闭'), 'completed')

            login_opened = await page.evaluate("""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
              const hasLoginInput = () => Array.from(document.querySelectorAll('input')).some(i => {
                const s = [i.placeholder, i.name, i.id, i.type].join(' ').toLowerCase();
                return /手机|手机号|验证码|phone|mobile|code|tel/.test(s);
              });
              if (hasLoginInput()) return {opened: true, via: 'already'};
              const candidates = [];
              const push = el => { if (el && visible(el) && !candidates.includes(el)) candidates.push(el); };
              push(document.querySelector('#aside-header-avatar'));
              document.querySelectorAll('img[alt*=默认头像], [class*=avatar], [id*=avatar], [class*=login], [id*=login], button, a, div, span').forEach(el => {
                const txt = (el.innerText || el.alt || el.getAttribute('aria-label') || '').trim();
                const cls = String(el.className || '');
                const id = String(el.id || '');
                if (/登录|默认头像|login|avatar|user|我的/.test(txt + ' ' + cls + ' ' + id)) push(el);
              });
              candidates.sort((a,b) => {
                const ar=a.getBoundingClientRect(), br=b.getBoundingClientRect();
                return (br.top < 140 ? 1 : 0) - (ar.top < 140 ? 1 : 0) || br.right - ar.right;
              });
              for (const el of candidates.slice(0, 30)) {
                const r = el.getBoundingClientRect();
                el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:r.left+r.width/2, clientY:r.top+r.height/2}));
                el.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:r.left+r.width/2, clientY:r.top+r.height/2}));
                el.click();
                await sleep(800);
                if (hasLoginInput()) return {opened: true, via: (el.innerText || el.alt || el.id || el.className || el.tagName).slice(0,80)};
              }
              return {opened: false, tried: candidates.length, text: document.body.innerText.slice(0,800), html: document.body.innerHTML.slice(0,800)};
            }
            """)
            login_opened = ensure_object(login_opened)
            dialog_info = await _find_best_login_dialog(page)
            if dialog_info:
                login_opened['dialog'] = dialog_info

            await capture_gif_frame(page, '打开登录入口')
            if not login_opened.get('opened'):
                raise RuntimeError(f'未能打开登录弹窗: {login_opened}')
            await record_real_action(
                'click',
                '打开登录入口/点击默认头像',
                element={
                    'element_text': str(login_opened.get('via', '登录入口'))[:80],
                    'element_tag': 'button',
                    'locator_strategy': 'css',
                    'locator_value': '#aside-header-avatar, img[alt*="默认头像"], [class*="avatar"], [id*="login"], [class*="login"]',
                    'locator_description': '登录入口/默认头像',
                },
            )
            await mark(task_id_by_keywords('登录入口'), 'completed')

            fill_result = await page.evaluate("""
            async ({phone, code, dialogSelector}) => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
              const root = dialogSelector ? document.querySelector(dialogSelector) : document;
              const inputs = Array.from((root || document).querySelectorAll('input')).filter(visible);
              const scorePhone = i => /手机|手机号|phone|mobile|tel/.test([i.placeholder,i.name,i.id,i.type].join(' ').toLowerCase()) ? 10 : (i.maxLength === 11 ? 6 : 0);
              const scoreCode = i => /验证码|校验码|code|captcha/.test([i.placeholder,i.name,i.id].join(' ').toLowerCase()) ? 10 : ((i.maxLength >= 4 && i.maxLength <= 8) ? 5 : 0);
              const phoneInput = inputs.slice().sort((a,b)=>scorePhone(b)-scorePhone(a))[0];
              if (!phoneInput || scorePhone(phoneInput) <= 0) return {ok:false, reason:'phone input not found', inputs: inputs.map(i=>({ph:i.placeholder,name:i.name,id:i.id,type:i.type,max:i.maxLength}))};
              phoneInput.focus(); phoneInput.value = phone;
              phoneInput.dispatchEvent(new Event('input', {bubbles:true}));
              phoneInput.dispatchEvent(new Event('change', {bubbles:true}));
              await sleep(200);
              const codeInputs = Array.from((root || document).querySelectorAll('input')).filter(visible).filter(i => i !== phoneInput);
              const codeInput = codeInputs.slice().sort((a,b)=>scoreCode(b)-scoreCode(a))[0];
              if (!codeInput || scoreCode(codeInput) <= 0) return {ok:false, reason:'code input not found', inputs: codeInputs.map(i=>({ph:i.placeholder,name:i.name,id:i.id,type:i.type,max:i.maxLength}))};
              codeInput.focus(); codeInput.value = code;
              codeInput.dispatchEvent(new Event('input', {bubbles:true}));
              codeInput.dispatchEvent(new Event('change', {bubbles:true}));
              await sleep(200);
              return {ok:true, phonePlaceholder: phoneInput.placeholder, codePlaceholder: codeInput.placeholder, scopedToDialog: !!dialogSelector};
            }
            """, {**task, 'dialogSelector': (dialog_info or {}).get('selector')})
            fill_result = ensure_object(fill_result)

            await log_step(f'输入手机号/验证码: {fill_result}')
            await capture_gif_frame(page, '输入手机号和验证码')
            if not fill_result.get('ok'):
                raise RuntimeError(f'输入失败: {fill_result}')

            await record_real_action(
                'fill',
                f"输入手机号 {task['phone']}",
                input_value=task['phone'],
                element={
                    'element_text': str(fill_result.get('phonePlaceholder', '手机号'))[:80],

                    'locator_strategy': 'css',
                    'locator_value': 'input[placeholder*="手机"], input[name*="phone"], input[name*="mobile"], input[type="tel"]',
                    'locator_description': '手机号输入框',
                },
            )
            await record_real_action(
                'fill',
                f"输入验证码 {task['code']}",
                input_value=task['code'],
                element={
                    'element_text': str(fill_result.get('codePlaceholder', '验证码'))[:80],
                    'element_tag': 'input',
                    'locator_strategy': 'css',
                    'locator_value': 'input[placeholder*="验证码"], input[name*="code"], input[id*="code"], input[autocomplete="one-time-code"]',
                    'locator_description': '验证码输入框',
                },
            )
            await mark(task_id_by_keywords('手机号', '手机'), 'completed')
            await mark(task_id_by_keywords('验证码'), 'completed')

            agree_result = await page.evaluate("""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
              // 1) 原生 checkbox
              const inputs = Array.from(document.querySelectorAll('input[type=checkbox]')).filter(visible);
              if (inputs.length) {
                const cb = inputs[0];
                if (!cb.checked) { cb.click(); cb.dispatchEvent(new Event('change', {bubbles:true})); }
                return {ok:true, via:'checkbox', checked:cb.checked};
              }
              // 2) 自定义 checkbox 组件（nn-checkbox, el-checkbox 等）
              const customCbs = Array.from(document.querySelectorAll('[class*=checkbox],[class*=check-box],[role=checkbox],[aria-checked]')).filter(visible);
              for (const el of customCbs) {
                const cls = String(el.className || '');
                const ariaChecked = el.getAttribute('aria-checked');
                if (ariaChecked === 'true' || el.classList.contains('is-checked') || el.classList.contains('checked')) {
                  return {ok:true, via:'custom-checkbox-already-checked', cls:cls.slice(0,80)};
                }
                el.click(); await sleep(300);
                return {ok:true, via:'custom-checkbox', cls:cls.slice(0,80)};
              }
              // 3) 文本匹配兜底：找"我已阅读并同意"附近的可点击元素
              const els = Array.from(document.querySelectorAll('label,span,div,i,svg,p')).filter(visible);
              for (const el of els) {
                const txt = (el.innerText || el.getAttribute('aria-label') || '').trim();
                const cls = String(el.className || '');
                if (/同意|阅读|协议|隐私|checkbox|check/.test(txt + ' ' + cls)) {
                  el.click(); await sleep(300); return {ok:true, via:(txt || cls).slice(0,80)};
                }
              }
              return {ok:false, reason:'agree control not found'};
            }
            """)
            agree_result = ensure_object(agree_result)
            await log_step(f'勾选协议: {agree_result}')
            await capture_gif_frame(page, '勾选协议')
            if not agree_result.get('ok'):
                raise RuntimeError(f'勾选协议失败: {agree_result}')
            await record_real_action(
                'click',
                '勾选同意协议',
                element={
                    'element_text': str(agree_result.get('via', '同意协议'))[:80],
                    'element_tag': 'checkbox',
                    'locator_strategy': 'css',
                    'locator_value': 'input[type="checkbox"], .nn-checkbox, .nn-checkbox__input, .nn-checkbox__inner',
                    'locator_description': '协议勾选框',
                },
            )
            await mark(task_id_by_keywords('勾选', '同意', '用户手册', '协议'), 'completed')

            submit_result = await page.evaluate("""
            async () => {
              const sleep = ms => new Promise(r => setTimeout(r, ms));
              const visible = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
              // 优先找 button 元素（最精确），再找 a/div/span
              const btns = Array.from(document.querySelectorAll('button')).filter(visible);
              const btnCandidates = btns.filter(el => {
                const txt = (el.innerText || el.value || '').trim();
                return /^登录|^立即登录|^登录\s*\/\s*注册$|^确定$|^确认$/.test(txt);
              });
              if (btnCandidates.length) {
                btnCandidates.sort((a,b) => a.getBoundingClientRect().width*a.getBoundingClientRect().height - b.getBoundingClientRect().width*b.getBoundingClientRect().height);
                const el = btnCandidates[0];
                const txt = (el.innerText || el.value || '').trim();
                el.click();
                await sleep(1800);
                return {ok:true, clicked:txt.slice(0,80)};
              }
              // 兜底：搜索所有元素，按面积升序（优先点击最精确的元素）
              const els = Array.from(document.querySelectorAll('button,a,div,span')).filter(visible);
              const candidates = els.filter(el => /登录|立即登录|确定|确认/.test((el.innerText || el.value || '').trim()));
              candidates.sort((a,b) => a.getBoundingClientRect().width*a.getBoundingClientRect().height - b.getBoundingClientRect().width*b.getBoundingClientRect().height);
              for (const el of candidates) {
                const txt = (el.innerText || el.value || '').trim();
                // 跳过文本过长的容器元素（>20字符通常不是按钮）
                if (txt.length > 20) continue;
                el.click();
                await sleep(1800);
                return {ok:true, clicked:txt.slice(0,80)};
              }
              return {ok:false, reason:'login button not found', candidates:candidates.length, texts: els.map(e=>(e.innerText||'').trim()).filter(Boolean).filter(t=>t.length<50).slice(0,20)};
            }
            """)
            submit_result = ensure_object(submit_result)
            await log_step(f'点击登录: {submit_result}')
            await capture_gif_frame(page, '点击登录')
            if not submit_result.get('ok'):
                raise RuntimeError(f'点击登录失败: {submit_result}')

            await record_real_action(
                'click',
                '点击登录按钮',
                element={
                    'element_text': str(submit_result.get('clicked', '登录'))[:80],
                    'element_tag': 'button',
                    'locator_strategy': 'xpath',
                    'locator_value': "(//button[contains(normalize-space(),'登录') or contains(normalize-space(),'注册')])[last()]",
                    'locator_description': '登录按钮',
                },
            )
            await mark(task_id_by_keywords('登录按钮', '登录 / 注册', '执行登录'), 'completed')

            await page.wait_for_timeout(3000)
            assertion_state = await evaluate_login_success(page)
            assertion = {
                'success': bool(assertion_state.get('passed')),
                'reason': assertion_state.get('reason', ''),
                'evidence': assertion_state.get('evidence', {}),
            }

            await log_step(f'登录断言: {assertion}')
            await capture_gif_frame(page, '登录断言')
            await record_real_action(
                'aiAssert',
                '断言登录成功',
                input_value='断言登录成功',
                assert_value='断言登录成功',
                element={
                    'element_text': '页面正文',
                    'element_tag': 'body',
                    'locator_strategy': 'css',
                    'locator_value': 'body',
                    'locator_description': '页面正文',
                },
            )
            final_task_id = task_id_by_keywords('完成登录') or task_id_by_keywords('断言是否成功登录', '断言登录', '断言是否', '提交登录', '提交登录操作')
            if assertion.get('success'):
                await mark(final_task_id, 'completed')
                login_final_status_recorded = True
                await emit({'type': 'log', 'content': '\n[System] NN 登录确定性执行完成。\n'})
                return True
            else:
                await mark(final_task_id, 'failed')
                login_final_status_recorded = True
                raise RuntimeError(f"登录断言失败: {assertion}")


        except Exception as exc:
            await emit({'type': 'log', 'content': f'\n[System] NN 登录确定性执行失败：{exc}\n'})
            current = None
            if planned_tasks:
                for item in planned_tasks:
                    if item.get('status', 'pending') in {'pending', 'in_progress'}:
                        current = item.get('id')
                        break
            if current and not login_final_status_recorded:
                await mark(current, 'failed')
            raise
        finally:
            save_deterministic_gif()
            try:
                if context:
                    await context.close()
            except Exception:
                pass
            try:
                if browser:
                    await browser.close()
            except Exception:
                pass
            try:
                if playwright:
                    await playwright.stop()
            except Exception:
                pass

    def _extract_structured_steps(self, text: str):
        """从原始任务文本中稳定提取步骤，作为 LLM 拆分失败时的兜底。"""
        if not text:
            return []

        normalized_text = str(text).replace('\r\n', '\n').replace('\r', '\n').strip()
        if not normalized_text:
            return []

        # 优先按行解析显式编号步骤
        numbered_line_pattern = re.compile(r'^\s*(\d+(?:\.\d+)*)[\.\s、:：-]+(.*)$')
        extracted_steps = []
        plain_lines = []

        for raw_line in normalized_text.split('\n'):
            line = raw_line.strip()
            if not line:
                continue
            match = numbered_line_pattern.match(line)
            if match:
                desc = match.group(2).strip()
                if desc:
                    extracted_steps.append(desc)
            else:
                plain_lines.append(line)

        if extracted_steps:
            if len(extracted_steps) == 1 and '\n' not in normalized_text:
                split_inline_text = re.sub(
                    r'\s+(?=\d+(?:\.\d+)*[\.\s、:：-]+)',
                    '\n',
                    normalized_text
                )
                if split_inline_text != normalized_text:
                    inline_steps = self._extract_structured_steps(split_inline_text)
                    if len(inline_steps) > 1:
                        return inline_steps
            return extracted_steps

        # 其次解析单行内多个编号步骤，例如：
        # "1.访问xx 2.搜索xx 3.点击xx"
        split_inline_text = re.sub(
            r'\s+(?=\d+(?:\.\d+)*[\.\s、:：-]+)',
            '\n',
            normalized_text
        )
        if split_inline_text != normalized_text:
            inline_steps = self._extract_structured_steps(split_inline_text)
            if inline_steps:
                return inline_steps

        # 最后退化为逐行文本
        return plain_lines or [normalized_text]

    def _normalize_steps(self, raw_steps, fallback_text: str):
        """清洗并展开步骤列表，避免多步被合并成一条。"""
        steps = raw_steps if isinstance(raw_steps, list) else []
        normalized_steps = []

        for step in steps:
            if step is None:
                continue
            desc = str(step).strip()
            if not desc:
                continue

            # 如果单个 step 里仍然包含多行/多编号步骤，继续拆开
            nested_steps = self._extract_structured_steps(desc)
            if nested_steps and not (len(nested_steps) == 1 and nested_steps[0] == desc):
                normalized_steps.extend(nested_steps)
            else:
                normalized_steps.append(desc)

        if not normalized_steps:
            normalized_steps = self._extract_structured_steps(fallback_text)

        cleaned_steps = []
        for desc in normalized_steps:
            current = str(desc).strip()
            while True:
                match = re.match(r'^\s*\d+(?:\.\d+)*[\.\s、:：-]+(.*)', current, re.S)
                if not match:
                    break
                current = match.group(1).strip()
            if current:
                cleaned_steps.append(current)

        return cleaned_steps or [fallback_text.strip()]

    def _compact_steps(self, steps):
        """合并过细的动作级步骤，收敛为核心业务子任务。"""
        if not steps:
            return []

        compacted = []
        i = 0
        total = len(steps)

        while i < total:
            current = str(steps[i]).strip()
            current_lower = current.lower()

            # 合并“打开浏览器 / 输入URL / 回车访问”这一类导航碎步
            if (
                ('浏览器' in current or 'browser' in current_lower or '地址栏' in current)
                and i + 1 < total
            ):
                window = " ".join(str(s).strip() for s in steps[i:i + 3])
                url_match = re.search(r'https?://[^\s]+', window)
                if url_match:
                    compacted.append(f"访问{url_match.group(0)}")
                    i += min(3, total - i)
                    continue

            # 合并“点击搜索框 / 输入关键词 / 点击搜索 / 等待结果”
            search_window = " ".join(str(s).strip() for s in steps[i:i + 4])
            if any(keyword in search_window for keyword in ['搜索框', '关键词', '百度一下', '搜索结果', 'search']):
                query_match = re.search(r"(?:输入搜索关键词[:：]?\s*|搜索)\s*['\"]?([^'\"\n]+?)['\"]?(?:\s|$)", search_window)
                if query_match:
                    query = query_match.group(1).strip()
                    query = re.sub(r'(并执行搜索|按钮或按下回车键|结果列表加载完成)$', '', query).strip()
                    compacted.append(f"搜索{query}")
                    i += min(4, total - i)
                    continue

            # 合并“点击第N条结果 + 新标签查看详情”
            if any(keyword in current for keyword in ['搜索结果', '结果', '标题链接', '查看详情']):
                if any(keyword in current for keyword in ['第二条', '第2条', '详情', '链接']):
                    compacted.append("点击第2条搜索结果查看详情")
                    i += 1
                    continue

            # 合并关闭标签页相关步骤
            if any(keyword in current for keyword in ['关闭', '标签页', '新标签页', 'close tab']):
                compacted.append("关闭该标签页")
                i += 1
                continue

            compacted.append(current)
            i += 1

        # 去重并保持顺序
        deduped = []
        for step in compacted:
            if not deduped or deduped[-1] != step:
                deduped.append(step)
        return deduped

    def _step_complexity_score(self, step: str) -> int:
        """粗略评估单个步骤是否包含多个动作。"""
        text = str(step).strip()
        if not text:
            return 0

        score = 0
        if len(text) >= 24:
            score += 1
        if len(text) >= 48:
            score += 1
        if any(token in text for token in ['并', '然后', '之后', '再', '并且', '同时', '且']):
            score += 1
        if any(token in text for token in ['点击', '输入', '搜索', '选择', '打开', '关闭', '提交', '保存', '查看', '切换']):
            action_hits = sum(text.count(token) for token in ['点击', '输入', '搜索', '选择', '打开', '关闭', '提交', '保存', '查看', '切换'])
            if action_hits >= 2:
                score += 1
        return score

    def _step_has_specific_requirements(self, step: str) -> bool:
        """判断步骤是否包含必须保留的字面值、断言或字段约束。"""
        text = str(step).strip()
        if not text:
            return False

        signals = 0
        if re.search(r'https?://', text):
            signals += 1
        if any(token in text for token in ['「', '」', '"', "'"]):
            signals += 1
        if re.search(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b', text):
            signals += 1
        if re.search(r'\([^)]{2,}\)', text):
            signals += 1
        if any(token in text for token in ['标题为', '返回', '确认页面', '确认', '验证', '校验']):
            signals += 1
        if any(token in text for token in ['输入框', '按钮', '下拉', '单选', '日期', 'Password', 'Text input', 'Dropdown']):
            signals += 1
        return signals >= 2

    def _should_redecompose_explicit_steps(self, steps):
        """判断已编号任务是否复杂到需要模型二次整合。"""
        if not steps:
            return False

        detail_rich_count = sum(1 for step in steps if self._step_has_specific_requirements(step))
        if detail_rich_count >= max(2, len(steps) // 2):
            return False

        if len(steps) >= 10:
            return True

        complex_count = sum(1 for step in steps if self._step_complexity_score(step) >= 2)
        if complex_count >= max(2, len(steps) // 2):
            return True

        very_long_count = sum(1 for step in steps if len(str(step).strip()) >= 40)
        if very_long_count >= max(2, len(steps) // 2):
            return True

        return False

    async def _model_break_down_task(self, task_description: str, mode: str = 'break_down'):
        """调用模型拆分或重整任务步骤。"""
        if mode == 'recompose':
            prompt = (
                "You are given a task that already has numbered steps, but some steps may be too granular or redundant. "
                "Rewrite them into core business steps only. "
                "Rules: keep the original intent and order, merge mechanical browser operations into the surrounding business step, "
                "do not invent new goals, do not split into micro-actions like clicking an input box or waiting for page load. "
                "Preserve every concrete literal requirement from the original steps, including URLs, field labels, option values, dates, expected titles, "
                "expected result text, and quoted content. Do not replace them with vague phrases like '输入文本信息' or '验证成功'. "
                "Return JSON list of concise Chinese strings only.\n\n"
                f"Task:\n{task_description}"
            )
        else:
            prompt = (
                "Break down this task into core business steps only. "
                "Avoid micro-actions like opening the browser, clicking into an input box, or waiting for results unless they are the user's explicit goal. "
                "Preserve every concrete literal requirement from the original task, including URLs, field labels, option values, dates, expected titles, "
                "expected result text, and quoted content. Do not replace them with vague summaries like '输入文本信息' or '验证成功'. "
                "Keep the order and return JSON list of concise Chinese strings only.\n\n"
                f"Task:\n{task_description}"
            )

        response = await self.llm.ainvoke(prompt)
        content = response.content.strip() if hasattr(response, 'content') else str(response)

        steps = []
        try:
            import json
            match = re.search(r'(\[.*\])', content, re.DOTALL)
            if match:
                steps = json.loads(match.group(1))
        except Exception:
            pass

        return steps

    def _finalize_steps(self, steps, fallback_text: str):
        """统一收口步骤列表，保证输出可执行且尽量精简。"""
        return self._compact_steps(self._normalize_steps(steps, fallback_text))

    async def analyze_task(self, task_description: str):
        try:
            explicit_steps = self._extract_structured_steps(task_description)
            if len(explicit_steps) >= 2:
                if self._should_redecompose_explicit_steps(explicit_steps):
                    steps = await self._model_break_down_task(task_description, mode='recompose')
                    cleaned_steps = self._finalize_steps(steps, task_description)
                else:
                    cleaned_steps = self._normalize_steps(explicit_steps, task_description)
                return [{'id': i + 1, 'description': s, 'status': 'pending'} for i, s in enumerate(cleaned_steps)]

            steps = await self._model_break_down_task(task_description, mode='break_down')
            cleaned_steps = self._finalize_steps(steps, task_description)

            return [{'id': i + 1, 'description': s, 'status': 'pending'} for i, s in enumerate(cleaned_steps)]
        except Exception as e:
            logger.warning(f"⚠️ analyze_task fallback triggered: {e}")
            cleaned_steps = self._finalize_steps([], task_description)
            return [{'id': i + 1, 'description': s, 'status': 'pending'} for i, s in enumerate(cleaned_steps)]

    def _cleanup_zombie_chrome(self):
        """Clean up any existing Chrome processes on port 9222 (Linux only)"""
        import platform
        import psutil

        if platform.system() != 'Linux':
            return

        logger.info("🧹 Cleaning up zombie Chrome processes...")
        cleaned_count = 0
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    # Check for chrome/chromium
                    if proc.info['name'] and ('chrome' in proc.info['name'] or 'chromium' in proc.info['name']):
                        # Check command line for port 9222
                        cmdline = proc.info.get('cmdline', [])
                        if cmdline and any('9222' in str(arg) for arg in cmdline):
                            logger.info(f"Killing zombie chrome pid={proc.pid}")
                            proc.kill()
                            cleaned_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception as e:
            logger.warning(f"⚠️ Failed to cleanup zombie chrome: {e}")

        if cleaned_count > 0:
            logger.info(f"✅ Cleaned up {cleaned_count} zombie Chrome processes")

    def _create_browser_profile(self):
        # Default implementation, can be overridden
        chrome_path = None
        import platform

        system = platform.system()
        if system == 'Windows':
            paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe")
            ]
            for p in paths:
                if os.path.exists(p):
                    chrome_path = p
                    break
        elif system == 'Linux':
            # Linux 系统常见的 Chrome 路径 - 优先使用我们预装的浏览器
            paths = [
                # 优先使用Docker容器中预装的Chromium
                '/usr/bin/chromium-browser',
                '/usr/bin/chromium',
                '/usr/bin/google-chrome',
                # 检查Playwright安装的浏览器
                '/ms-playwright/chromium-*/chromium-linux/chromium',
                '/root/.cache/ms-playwright/chromium-*/chromium-linux/chromium',
                # 备用路径
                '/usr/bin/google-chrome-stable',
                '/opt/google/chrome/chrome',
                '/snap/bin/chromium',
            ]
            for p in paths:
                # 支持通配符路径
                if '*' in p:
                    import glob
                    matches = glob.glob(p)
                    if matches:
                        for match in matches:
                            if os.path.exists(match) and os.access(match, os.X_OK):
                                chrome_path = match
                                logger.info(f"找到浏览器: {chrome_path}")
                                break
                        if chrome_path:
                            break
                elif os.path.exists(p) and os.access(p, os.X_OK):
                    chrome_path = p
                    logger.info(f"找到浏览器: {chrome_path}")
                    break

            # 如果还是没找到，尝试查找Playwright的默认路径或让browser-use自行安装
            if not chrome_path:
                import glob
                playwright_paths = glob.glob('/ms-playwright/**/chromium', recursive=True)
                playwright_paths.extend(glob.glob('/root/.cache/ms-playwright/**/chromium', recursive=True))
                playwright_paths.extend(glob.glob('/ms-playwright/**/chromium-linux/chromium', recursive=True))
                playwright_paths.extend(glob.glob('/root/.cache/ms-playwright/**/chromium-linux/chromium', recursive=True))
                for p in playwright_paths:
                    if os.path.exists(p) and os.access(p, os.X_OK):
                        chrome_path = p
                        logger.info(f"通过Playwright找到浏览器: {chrome_path}")
                        break

                # 最后的备用方案：让browser-use自行处理浏览器安装
                if not chrome_path:
                    logger.info("未找到预装浏览器，将让browser-use自动安装")
                    chrome_path = None  # 让browser-use处理

        # 基础性能优化参数
        extra_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars', '--disable-notifications',
            '--disable-background-networking',
            '--disable-background-timer-throttling',
            '--disable-renderer-backgrounding',
            '--disable-backgrounding-occluded-windows',
            '--disable-extensions',
            '--disable-web-security',  # 允许跨域请求
        ]

        # 根据操作系统添加特定参数
        if system == 'Linux':
            # Linux 服务器环境（特别是无头环境）必需的参数
            extra_args.extend([
                '--no-sandbox',  # Linux 必需：禁用沙箱
                '--disable-setuid-sandbox',  # Linux 必需：禁用 setuid 沙箱
                '--disable-dev-shm-usage',  # Linux 必需：使用 /tmp 而不是 /dev/shm
                '--disable-gpu',  # 禁用 GPU 加速（服务器通常无 GPU）
                '--headless=new',  # Linux 服务器使用无头模式
                '--disable-software-rasterizer',  # 禁用软件光栅化器
                '--remote-debugging-port=9222',  # 使用固定端口，避免随机端口导致连接失败
                '--remote-debugging-address=0.0.0.0', # 允许远程连接，而不仅仅是 127.0.0.1
                '--no-zygote',  # 减少进程数
                '--single-process',  # 单进程模式，虽然不稳定但能解决某些 Docker 环境下的 PID 问题
            ])
        else:
            # macOS 和 Windows 使用显示模式
            extra_args.extend([
                '--no-sandbox',  # 兼容性
                '--disable-gpu',
                '--remote-debugging-port=9222',
            ])

        return BrowserProfile(
            headless=(system == 'Linux'),  # Linux 使用无头模式，其他系统使用显示模式
            disable_security=True,
            executable_path=chrome_path,
            args=extra_args,
            wait_for_network_idle_page_load_time=0.2,
            minimum_wait_page_load_time=0.05,
            wait_between_actions=0.1,
            enable_default_extensions=False
        )

    async def run_task(self, task_description: str, planned_tasks=None, callback=None, should_stop=None):
        # 固定高频流程（如 NN 手机验证码登录）必须先尝试确定性执行，
        # 不能依赖 LLM 连通性；否则模型临时不可用时，Playwright 兜底永远跑不到。
        deterministic_history = await self._run_nn_login_deterministic(
            task_description,
            planned_tasks=planned_tasks,
            callback=callback,
            should_stop=should_stop
        )
        if deterministic_history is not None:
            return deterministic_history

        await self._verify_execution_llm()

        # Cleanup potential zombie processes before starting
        self._cleanup_zombie_chrome()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        controller = Controller()
        _task_was_done = False
        active_task_statuses = {'pending', 'in_progress'}
        max_execution_seconds = int(os.getenv('AI_AGENT_MAX_EXECUTION_SECONDS', '180'))
        max_agent_steps = int(os.getenv('AI_AGENT_MAX_STEPS', '30'))
        no_progress_limit = int(os.getenv('AI_AGENT_NO_PROGRESS_LIMIT', '4'))
        execution_started_at = time.monotonic()

        async def emit_callback(payload):
            if not callback:
                return

            if asyncio.iscoroutinefunction(callback):
                await callback(payload)
            else:
                callback(payload)

        def is_placeholder_url(url: str) -> bool:
            normalized = (url or '').strip().lower()
            return (
                not normalized
                or normalized == 'about:blank'
                or normalized.startswith('chrome://newtab')
                or normalized.startswith('edge://newtab')
            )

        def is_close_step(description: str) -> bool:
            text = str(description or '').strip()
            return any(keyword in text for keyword in ['关闭', '关闭该标签页', '关闭标签页'])

        def get_next_active_task():
            if not planned_tasks:
                return None

            for task in planned_tasks:
                if task.get('status', 'pending') in active_task_statuses:
                    return task
            return None

        async def find_preferred_fallback_tab(browser_session, exclude_target_id=None):
            tabs = await browser_session.get_tabs()
            candidate_tabs = [tab for tab in tabs if tab.target_id != exclude_target_id]
            if not candidate_tabs:
                return None

            non_placeholder_tabs = [tab for tab in candidate_tabs if not is_placeholder_url(getattr(tab, 'url', ''))]
            return (non_placeholder_tabs or candidate_tabs)[-1]

        @controller.action('Done')
        async def done(success: bool = True, text: str = ""):
            nonlocal _task_was_done
            _task_was_done = True
            return f"Finished: {text}"

        async def close_popup_in_session(browser_session=None):
            """Close any active popup/dialog/modal on the current page, return diagnostic text."""
            if not browser_session:
                return "No browser session available"
            try:
                page = None
                if hasattr(browser_session, 'get_current_page'):
                    page = await browser_session.get_current_page()
                if page is None and hasattr(browser_session, 'must_get_current_page'):
                    page = await browser_session.must_get_current_page()
                if page is None:
                    return "No active page available"

                await page.keyboard.press('Escape')
                await asyncio.sleep(0.5)

                close_popup_js = """
                () => {
                    const selector = [
                        'button[class*="close"]', 'button[class*="Close"]',
                        'button[aria-label*="关闭"]', 'button[aria-label*="close"]',
                        'a[class*="close"]', 'i[class*="close"]',
                        '[class*="close"][class*="btn"]',
                        '.modal-header button', '.dialog-header button',
                        '.el-dialog__headerbtn', '.ant-modal-close',
                        '.popup-close', '.ad-close',
                        '.layui-layer-close', '.layui-layer-btn0',
                        'img[alt*="close"]', 'img[alt*="关闭"]',
                        'svg[class*="close"]', 'span[class*="close"]'
                    ].join(',');
                    const btns = document.querySelectorAll(selector);
                    for (const btn of btns) {
                        const rect = btn.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            btn.click();
                            return 'clicked close btn: ' + btn.outerHTML.slice(0, 80);
                        }
                    }

                    const overlays = document.querySelectorAll(
                        '[class*="modal"],[class*="dialog"],[class*="overlay"],[class*="popup"],[id*="modal"],[id*="dialog"]'
                    );
                    for (const el of overlays) {
                        const style = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        const z = parseInt(style.zIndex) || 0;
                        if (rect.width > 80 && rect.height > 80 && (z >= 100 || style.position === 'fixed')) {
                            el.style.display = 'none';
                            return 'hid overlay z=' + z;
                        }
                    }

                    const all = Array.from(document.querySelectorAll('body *'));
                    let highest = null;
                    let highestZ = 0;
                    for (const el of all) {
                        const style = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        const z = parseInt(style.zIndex) || 0;
                        if ((style.position === 'fixed' || style.position === 'absolute') && z >= highestZ && z >= 100 && rect.width > 80 && rect.height > 80) {
                            highest = el;
                            highestZ = z;
                        }
                    }
                    if (highest) {
                        highest.style.display = 'none';
                        return 'hid fixed layer z=' + highestZ;
                    }
                    return 'no popup detected';
                }
                """
                return await page.evaluate(close_popup_js)
            except Exception as e:
                logger.warning(f"⚠️ close_popup action failed: {e}")
                return f"close_popup attempt failed: {e}"

        @controller.action('close_popup')
        async def close_popup(browser_session=None):
            """Close any active popup/dialog/modal on the current page."""
            logger.info("🧹 Executing close_popup: trying Escape key, JS, and element strategies")
            js_result = await close_popup_in_session(browser_session)
            logger.info(f"🧹 close_popup result: {js_result}")
            return f"Closed popup: {js_result}"

        @controller.action('search_page')
        async def search_page(pattern: str = None, text: str = None, browser_session=None):
            """Permissive page text search. Accepts both browser-use native `pattern` and common LLM mistake `text`."""
            keyword = pattern or text or ""
            logger.info(f"🔎 Executing compatible search_page: {keyword}")
            if not keyword:
                return "search_page skipped: empty pattern"
            try:
                page = None
                if browser_session and hasattr(browser_session, 'get_current_page'):
                    page = await browser_session.get_current_page()
                if page is None:
                    return f"search_page received pattern={keyword}, but no active page available"
                result = await page.evaluate(
                    """(kw) => {
                        const bodyText = document.body ? document.body.innerText : '';
                        const found = bodyText.includes(kw);
                        try { window.find(kw); } catch(e) {}
                        return {found, sample: bodyText.slice(0, 300)};
                    }""",
                    keyword
                )
                return f"search_page pattern={keyword}, found={result.get('found')}, sample={result.get('sample')}"
            except Exception as e:
                logger.warning(f"⚠️ compatible search_page failed: {e}")
                return f"search_page failed but ignored: {e}"

        @controller.action('close_tab')
        async def close_tab(browser_session=None):
            if browser_session is None or browser_session.agent_focus_target_id is None:
                raise ValueError("No active tab to close")
            target_id = browser_session.agent_focus_target_id
            fallback_tab = None
            try:
                fallback_tab = await find_preferred_fallback_tab(browser_session, exclude_target_id=target_id)
            except Exception as e:
                logger.warning(f"Failed to determine fallback tab before closing {target_id[-4:]}: {e}")

            event = browser_session.event_bus.dispatch(CloseTabEvent(target_id=target_id))
            await event

            if fallback_tab is not None:
                try:
                    await asyncio.sleep(0.15)
                    if browser_session.agent_focus_target_id != fallback_tab.target_id:
                        await browser_session.event_bus.dispatch(
                            SwitchTabEvent(target_id=fallback_tab.target_id)
                        )
                        logger.info(
                            f"↩️ Switched back to existing tab {fallback_tab.target_id[-4:]} "
                            f"({fallback_tab.url}) after closing {target_id[-4:]}"
                        )
                        await emit_callback({
                            'type': 'log',
                            'content': (
                                f"\n[System]\n关闭标签页后，已切回来源页 {fallback_tab.target_id[-4:]}\n"
                            )
                        })
                except Exception as e:
                    logger.warning(f"Failed to switch back to preferred tab after closing {target_id[-4:]}: {e}")

            next_active_task = get_next_active_task()
            if next_active_task and is_close_step(next_active_task.get('description')):
                logger.info(f"✅ Auto-marking close step task {next_active_task['id']} as completed after close_tab")
                await emit_callback({'task_id': int(next_active_task['id']), 'status': 'completed'})

            return f"Closed tab {target_id[-4:]}"

        @controller.action('mark_task_complete')
        async def mark_task_complete(task_id: int):
            logger.info(f"✅ Explicitly marking task {task_id} as completed")
            try:
                await emit_callback({'task_id': int(task_id), 'status': 'completed'})
            except Exception as e:
                logger.warning(f"Failed to execute mark_task_complete callback: {e}")
            return f"Task {task_id} marked completed"

        @controller.action('mark_task_failed')
        async def mark_task_failed(task_id: int):
            logger.info(f"❌ Explicitly marking task {task_id} as failed")
            try:
                await emit_callback({'task_id': int(task_id), 'status': 'failed'})
            except Exception as e:
                logger.warning(f"Failed to execute mark_task_failed callback: {e}")
            return f"Task {task_id} marked failed"

        @controller.action('mark_task_skipped')
        async def mark_task_skipped(task_id: int):
            logger.info(f"⏭️ Explicitly marking task {task_id} as skipped")
            try:
                await emit_callback({'task_id': int(task_id), 'status': 'skipped'})
            except Exception as e:
                logger.warning(f"Failed to execute mark_task_skipped callback: {e}")
            return f"Task {task_id} marked skipped"

        @controller.action('update_task_status')
        async def update_task_status(task_id: int, status: str):
            normalized_status = str(status).strip().lower()
            if normalized_status not in {'completed', 'failed', 'skipped', 'in_progress'}:
                raise ValueError(f"Unsupported task status: {status}")
            logger.info(f"🔄 Explicitly updating task {task_id} to {normalized_status}")
            try:
                await emit_callback({'task_id': int(task_id), 'status': normalized_status})
            except Exception as e:
                logger.warning(f"Failed to execute update_task_status callback: {e}")
            return f"Task {task_id} marked {normalized_status}"

        # 构建强化版 Prompt
        final_task = task_description
        if planned_tasks:
            final_task += "\n\nIMPORTANT INSTRUCTION:\n"
            final_task += "You have a list of sub-tasks. Execute strictly in order.\n"
            final_task += "CRITICAL: MUST call one of 'mark_task_complete', 'mark_task_failed', 'mark_task_skipped', or 'update_task_status(task_id=..., status=...)' IMMEDIATELY after determining each sub-task result. NEVER skip this step.\n"
            final_task += "IMPORTANT: If a sub-task (like opening a URL) is already fulfilled by the initial state, YOU MUST mark it complete in your VERY FIRST STEP.\n"
            final_task += "Sub-tasks (Execute in order):\n"
            cleaned_tasks = []
            for t in planned_tasks:
                desc = t['description']
                # 递归去除所有层级的重复序号，例如 "1. 1. xxx" -> "xxx"
                while True:
                    match = re.match(r'^\s*\d+[\.\s、:]+(.*)', desc)
                    if not match: break
                    desc = match.group(1).strip()
                cleaned_tasks.append(f"{t['id']}. {desc}")
            final_task += "\n".join(cleaned_tasks)

        # 极限效率版标记指令
        from datetime import datetime
        final_task += f"\n\nCURRENT TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        final_task += "\nCRITICAL PERFORMANCE & SYNC RULES:\n"
        final_task += "1. TASK COMPLETION MARKING RULES:\n"
        final_task += "   a) MARK AFTER COMPLETION: Call 'mark_task_complete(task_id=N)' ONLY AFTER you have SUCCESSFULLY COMPLETED task N.\n"
        final_task += "   b) MARK CURRENT TASK: Always mark the task you just completed, NOT the next task or previous tasks.\n"
        final_task += "   c) CHECK TASK ID: Before marking, verify: 'I just completed task N' - if N is already marked, check which task you actually completed.\n"
        final_task += "   d) DO NOT SKIP: Every sub-task must end with an explicit terminal status update: completed, failed, or skipped.\n"
        final_task += "   e) EXAMPLE SUCCESS: [{click: {...}}, {mark_task_complete: {task_id: 4}}]\n"
        final_task += "   f) EXAMPLE FAILURE: if task 4 cannot be completed after verification, call {mark_task_failed: {task_id: 4}}.\n"
        final_task += "   g) EXAMPLE SKIP: if task 4 is intentionally unnecessary, call {mark_task_skipped: {task_id: 4}}.\n"
        final_task += "   h) NO PRE-MARKING: Never mark a task before completing it. Never mark a task twice.\n"
        final_task += "   i) SINGLE-TASK STEP: If you mark task N in the current step, STOP there. Do NOT start task N+1 in the same step.\n"
        final_task += "   j) FORM EXAMPLE: Good: [{input: {...}}, {mark_task_complete: {task_id: 2}}] then next step handles task 3. Bad: [{mark_task_complete: {task_id: 1}}, {input: {...task 2...}}].\n"
        final_task += "2. NO JAVASCRIPT IN INPUT: When a task asks for a timestamp, YOU MUST compute the final string yourself (e.g., 'V8.01734892400').\n"
        final_task += "   - DO NOT output 'Date.now()' or '{{...}}' strings. Use the CURRENT TIME provided above to estimate a timestamp.\n"
        final_task += "3. DROPDOWN & MODAL ISOLATION: If an action (clicking a button/dropdown) triggers a UI change (modal opens/dropdown expands), YOU MUST STOP and WAIT for the next step to see the new elements. DO NOT attempt to interact with newly appeared elements (like dropdown options) in the same step as the click that opened them.\n"
        final_task += "4. TAB HANDLING: If clicking a link/result opens a new tab, DO NOT click the same result again. Immediately switch to the newest tab, verify the detail page there, then mark the current sub-task complete.\n"
        final_task += "5. ULTRALIGHT THINKING: Keep 'thinking' under 10 words. Just list next actions. Merge multiple INPUTS if they are on the same form, but NEVER merge a UI-opening click with its subsequent interaction. SPEED IS CRITICAL - respond as quickly as possible.\n"
        final_task += "6. FORM VALIDATION & ERROR DETECTION: When filling forms, you MUST:\n"
        final_task += "   a) Check for RED TEXT messages (validation errors) before clicking save/submit\n"
        final_task += "   b) If validation errors exist, COMPLETE ALL MISSING FIELDS first, then retry save\n"
        final_task += "   c) NEVER close a dialog/modal if there are validation errors - complete the form instead\n"
        final_task += "   d) Verify all required fields are filled before attempting to save\n"
        final_task += "   e) Common validation errors: missing required fields (red asterisk or red text), invalid format, etc.\n"
        final_task += "7. RETRY LOGIC: If a previous 'save' or 'submit' failed (e.g., error toast or validation error):\n"
        final_task += "   a) STOP and examine the page for validation errors (red text, error messages)\n"
        final_task += "   b) RE-VERIFY all fields - check dropdowns are actually selected, not just clicked\n"
        final_task += "   c) Re-select dropdowns and re-input text to ensure the form is complete\n"
        final_task += "   d) DO NOT close the dialog - stay and complete all missing fields\n"
        final_task += "   e) Often errors are caused by: missing project selection, unfilled required fields, incorrect format\n"
        final_task += "8. DO NOT REPEAT: If a task is complete, mark it and MOVE ON. Never click the same search result or link twice unless you verified the first click failed.\n"
        final_task += "9. VERIFICATION: Task 15/16 usually require checking the list. Ensure you are on the correct page and the new data is visible before marking complete.\n"
        final_task += "10. ELEMENT IDENTIFICATION: Carefully identify elements before clicking. AVOID clicking 'close' or 'cancel' buttons when filling forms. Check button labels, aria-labels, and icons to ensure you're clicking the correct element.\n"
        final_task += "11. ACTION PARAM FORMAT: For browser actions, always use browser-use native parameter names. Use 'index' for click/input/select actions, use 'text' for typed input content, use 'pattern' for search_page (NEVER use search_page text=...). Never use aliases like 'element_id'.\n"
        final_task += "12. CREDENTIALS RULE: NEVER invent, replace, or guess credentials. Only use the username/password explicitly provided in the task. If login keeps failing with an explicit error like '登录失败' or '用户名或密码错误', stop retrying after a small number of attempts and mark the current login task as failed.\n"
        final_task += "13. POPUP/DISMISS: When you need to close a popup/ad/modal but cannot find its close button (X) in the interactive elements list, call 'close_popup()' action. It tries Escape key, JS-based close button detection, and overlay removal. If the popup still persists, close_popup again — do NOT get stuck.\n"
        final_task += "14. AGGRESSIVE CLOSE: If test environment has distracting ads, popups, or overlays that block interaction, call close_popup() multiple times early in the process to clear the page.\n"

        if 'qwen' in self.model_name.lower() or 'deepseek' in self.model_name.lower():
            final_task += "13. EXTREMELY MINIMIZE output tokens for speed. Keep responses as short as possible while maintaining accuracy.\n"

        # 核心修复: 清理 task 长文本中的 URL，防止中文标点紧贴 URL 导致 browser-use 解析错误
        # 例如 "http://localhost:3000，" -> "http://localhost:3000 "
        try:
            # 在中文标点前加空格，避免它们成为 URL 的一部分
            final_task = re.sub(r'(https?://[^\s\u4e00-\u9fa5]+?)(?=[，；。、！])', r'\1 ', final_task)
            logger.info(f"🔧 Optimized task description for URL extraction")
        except Exception:
            pass

        browser_profile = self._create_browser_profile()

        # 检测模型是否支持视觉
        # 不支持视觉的模型关键字
        no_vision_models = ['deepseek', 'qwen', 'glm', 'chatglm', 'baichuan', 'moonshot', 'kimi', 'doubao', 'mimo']
        model_name_lower = self.model_name.lower()
        model_supports_vision = not any(keyword in model_name_lower for keyword in no_vision_models)
        
        # 根据环境变量和模型能力决定是否使用视觉
        env_use_vision = str(os.getenv('AI_AGENT_USE_VISION', 'true')).lower() not in ('0', 'false', 'no')
        use_vision = env_use_vision and model_supports_vision
        
        if env_use_vision and not model_supports_vision:
            logger.warning(f"模型 {self.model_name} 不支持视觉，已自动禁用视觉模式")

        agent = Agent(
            task=final_task,
            llm=self.llm,
            controller=controller,
            browser_profile=browser_profile,
            use_vision=use_vision,
            max_actions_per_step=10,  # 增加步进密度，减少总步骤数，降低超时风险
            max_retries=1,  # 减少重试次数以提高速度 (从2改为1)
            max_failures=4,  # 给弹窗/截图等偶发失败留出恢复空间，避免过早终止
            llm_timeout=45,  # 降低LLM单次等待，避免整体任务长时间卡住
            step_timeout=45,  # 降低单步超时，配合整单超时熔断
            generate_gif=self.enable_gif,  # 根据开关决定是否生成GIF
        )
        agent._task_was_done = False
        agent._pending_status_task_id = None
        agent._pending_status_task_description = None
        agent._auth_failure_task_id = None
        agent._auth_failure_count = 0

        # Callback helper - 添加任务标记跟踪
        last_processed_step = 0
        last_marked_task_id = 0  # 跟踪上一次标记的任务ID
        known_tab_ids = set()
        consecutive_no_progress_steps = 0
        visited_url_counts = {}
        repeated_navigation_limit = int(os.getenv('AI_AGENT_REPEAT_NAVIGATION_LIMIT', '1'))

        def normalize_url_for_guard(url):
            normalized = str(url or '').strip()
            if not normalized:
                return ''
            normalized = normalized.rstrip('/')
            return normalized.lower()

        def extract_navigation_urls(actions):
            urls = []
            for action in actions:
                action_dict = action.model_dump() if hasattr(action, 'model_dump') else getattr(action, '_action_dict', {})
                if isinstance(action_dict, dict):
                    for key in ['go_to_url', 'navigate', 'open_new_tab']:
                        if key in action_dict:
                            params = action_dict.get(key)
                            url = params.get('url') if isinstance(params, dict) else params
                            normalized = normalize_url_for_guard(url)
                            if normalized and not is_placeholder_url(normalized):
                                urls.append(normalized)
            return urls

        def normalize_recorded_action(action_dict, page_url='', active_task_desc=''):
            """把 browser-use 模型动作转换为可沉淀的真实动作草稿。"""
            if not isinstance(action_dict, dict):
                return None
            skip_actions = {
                'mark_task_complete', 'mark_task_failed', 'mark_task_skipped',
                'update_task_status', 'done', 'Done', 'search_page'
            }
            for name, params in action_dict.items():
                if name in skip_actions:
                    continue
                params = params if isinstance(params, dict) else {'value': params}
                desc_suffix = f"（{active_task_desc}）" if active_task_desc else ''
                if name in ['go_to_url', 'navigate', 'open_new_tab']:
                    url = params.get('url') or params.get('value') or ''
                    return {
                        'action_type': 'goto',
                        'description': f'访问: {url}',
                        'input_value': url,
                        'assert_value': '',
                        'element_text': '',
                        'element_tag': '',
                        'locator_strategy': '',
                        'locator_value': '',
                        'locator_description': f'访问: {url}',
                        'page_url': url or page_url,
                        'source': 'browser_use_real_action',
                        'timestamp': time.time(),
                    }
                if name in ['click_element', 'click']:
                    index = params.get('index') or params.get('value') or ''
                    return {
                        'action_type': 'click',
                        'description': f'点击页面元素[{index}]{desc_suffix}',
                        'input_value': '',
                        'assert_value': '',
                        'element_text': str(params.get('text') or params.get('label') or active_task_desc or '')[:80],
                        'element_tag': '',
                        'locator_strategy': 'ai_index',
                        'locator_value': str(index),
                        'locator_description': active_task_desc or f'页面元素[{index}]',
                        'page_url': page_url,
                        'source': 'browser_use_real_action',
                        'timestamp': time.time(),
                    }
                if name in ['input_text', 'input']:
                    value = params.get('text') or params.get('value') or ''
                    index = params.get('index') or ''
                    return {
                        'action_type': 'fill',
                        'description': f'输入 {value}{desc_suffix}',
                        'input_value': value,
                        'assert_value': '',
                        'element_text': str(params.get('label') or active_task_desc or '')[:80],
                        'element_tag': 'input',
                        'locator_strategy': 'ai_index',
                        'locator_value': str(index),
                        'locator_description': active_task_desc or f'输入框[{index}]',
                        'page_url': page_url,
                        'source': 'browser_use_real_action',
                        'timestamp': time.time(),
                    }
                if name in ['select_dropdown_option', 'select_option']:
                    value = params.get('text') or params.get('option') or params.get('value') or ''
                    index = params.get('index') or ''
                    return {
                        'action_type': 'select',
                        'description': f'选择 {value}{desc_suffix}',
                        'input_value': value,
                        'assert_value': '',
                        'element_text': str(params.get('label') or active_task_desc or '')[:80],
                        'element_tag': 'select',
                        'locator_strategy': 'ai_index',
                        'locator_value': str(index),
                        'locator_description': active_task_desc or f'下拉元素[{index}]',
                        'page_url': page_url,
                        'source': 'browser_use_real_action',
                        'timestamp': time.time(),
                    }
                if name in ['scroll_down', 'scroll_up']:
                    return None
                return {
                    'action_type': 'click',
                    'description': f'{name}{desc_suffix}',
                    'input_value': str(params.get('text') or params.get('value') or ''),
                    'assert_value': '',
                    'element_text': str(active_task_desc or name)[:80],
                    'element_tag': '',
                    'locator_strategy': '',
                    'locator_value': '',
                    'locator_description': active_task_desc or name,
                    'page_url': page_url,
                    'source': 'browser_use_real_action',
                    'timestamp': time.time(),
                }
            return None

        async def current_page_url(agent_instance):
            try:
                browser_session = getattr(agent_instance, 'browser_session', None)
                if browser_session and hasattr(browser_session, 'get_current_page'):
                    page = await browser_session.get_current_page()
                    return getattr(page, 'url', '') or ''
            except Exception:
                pass
            return ''

        async def on_step_end(agent_instance):
            nonlocal last_processed_step, last_marked_task_id, known_tab_ids, consecutive_no_progress_steps, visited_url_counts

            elapsed_seconds = time.monotonic() - execution_started_at
            if elapsed_seconds > max_execution_seconds:
                current_active_task = get_next_active_task()
                current_active_task_id = current_active_task.get('id') if current_active_task else None
                await emit_callback({
                    'type': 'log',
                    'content': f"\n[System] AI执行超过最大时长 {max_execution_seconds} 秒，已自动停止，避免长时间卡住。\n"
                })
                if current_active_task_id:
                    await emit_callback({'task_id': int(current_active_task_id), 'status': 'failed'})
                raise KeyboardInterrupt("AI execution timeout")

            if should_stop:
                do_stop = await should_stop() if asyncio.iscoroutinefunction(should_stop) else should_stop()
                if do_stop: raise KeyboardInterrupt("User requested stop")

            if _task_was_done:
                raise KeyboardInterrupt("Done")

            history = getattr(agent_instance, 'history', [])
            if hasattr(history, 'history'): history = history.history

            if len(history) > last_processed_step:
                for i in range(last_processed_step, len(history)):
                    step = history[i]
                    # Log logic here
                    try:
                        actions = []
                        if hasattr(step, 'model_output') and hasattr(step.model_output, 'action'):
                            raw = step.model_output.action
                            actions = raw if isinstance(raw, list) else [raw]

                        current_active_task = get_next_active_task()
                        current_active_task_id = current_active_task.get('id') if current_active_task else None
                        current_active_task_desc = str(current_active_task.get('description', '')) if current_active_task else ''
                        if current_active_task_id and any(keyword in current_active_task_desc.lower() for keyword in ['登录', 'login']):
                            signal_text_parts = []
                            model_output = getattr(step, 'model_output', None)
                            for field_name in ['thinking', 'evaluation_previous_goal', 'memory', 'next_goal']:
                                value = getattr(model_output, field_name, None)
                                if value:
                                    signal_text_parts.append(str(value))

                            if _contains_auth_failure_signal(" ".join(signal_text_parts)):
                                if getattr(agent_instance, '_auth_failure_task_id', None) == current_active_task_id:
                                    agent_instance._auth_failure_count += 1
                                else:
                                    agent_instance._auth_failure_task_id = current_active_task_id
                                    agent_instance._auth_failure_count = 1

                                if agent_instance._auth_failure_count >= 3:
                                    logger.warning(
                                        f"⚠️ Login/auth failure threshold reached for task {current_active_task_id}; marking task failed"
                                    )
                                    await emit_callback({
                                        'type': 'log',
                                        'content': (
                                            f"\n[System]\n检测到登录连续失败 3 次，已自动将子任务 {current_active_task_id} 标记为失败并停止执行。\n"
                                        )
                                    })
                                    await emit_callback({
                                        'task_id': int(current_active_task_id),
                                        'status': 'failed'
                                    })
                                    raise KeyboardInterrupt("Repeated authentication failure")
                            elif getattr(agent_instance, '_auth_failure_task_id', None) == current_active_task_id:
                                agent_instance._auth_failure_count = 0

                        # 检查这一步是否调用了任务状态更新动作
                        step_has_task_complete = False
                        step_marked_task_id = None
                        for action in actions:
                            action_dict = action.model_dump() if hasattr(action, 'model_dump') else getattr(action,
                                                                                                            '_action_dict',
                                                                                                            {})
                            if 'mark_task_complete' in action_dict:
                                step_has_task_complete = True
                                step_marked_task_id = action_dict['mark_task_complete'].get('task_id')
                            elif 'mark_task_failed' in action_dict:
                                step_has_task_complete = True
                                step_marked_task_id = action_dict['mark_task_failed'].get('task_id')
                            elif 'mark_task_skipped' in action_dict:
                                step_has_task_complete = True
                                step_marked_task_id = action_dict['mark_task_skipped'].get('task_id')
                            elif 'update_task_status' in action_dict:
                                step_has_task_complete = True
                                payload = action_dict['update_task_status']
                                step_marked_task_id = payload.get('task_id')

                            if step_has_task_complete:
                                # 检查是否重复标记已完成的任务 - 提示但不自动修复
                                if planned_tasks:
                                    for task in planned_tasks:
                                        if task['id'] == step_marked_task_id and task.get('status') in ['completed', 'failed', 'skipped']:
                                            next_expected = last_marked_task_id + 1
                                            logger.warning(
                                                f"⚠️ Task {step_marked_task_id} is already terminal ({task.get('status')})! "
                                                f"You should mark task {next_expected} instead.")
                                            break
                                last_marked_task_id = step_marked_task_id
                                if getattr(agent_instance, '_pending_status_task_id', None) == step_marked_task_id:
                                    agent_instance._pending_status_task_id = None
                                    agent_instance._pending_status_task_description = None
                                break

                        # 检查这一步是否有实际操作（非mark_task_complete的操作）
                        has_real_action = False
                        has_link_open_action = False
                        for action in actions:
                            action_dict = action.model_dump() if hasattr(action, 'model_dump') else getattr(action,
                                                                                                            '_action_dict',
                                                                                                            {})
                            for key in action_dict.keys():
                                if key not in ['mark_task_complete', 'mark_task_failed', 'mark_task_skipped', 'update_task_status', 'done']:
                                    has_real_action = True
                                if key in ['click', 'open_new_tab', 'navigate', 'go_to_url']:
                                    has_link_open_action = True
                                    break
                            if has_real_action:
                                break

                        action_str = " | ".join([self._format_action(a) for a in actions])
                        log_content = f"\n[Step {i + 1}]\n执行: {action_str}\n"

                        navigation_urls = extract_navigation_urls(actions)
                        repeated_url = None
                        for navigation_url in navigation_urls:
                            visited_url_counts[navigation_url] = visited_url_counts.get(navigation_url, 0) + 1
                            if visited_url_counts[navigation_url] > repeated_navigation_limit:
                                repeated_url = navigation_url
                                break

                        if repeated_url:
                            current_active_task = get_next_active_task()
                            current_active_task_id = current_active_task.get('id') if current_active_task else None
                            await emit_callback({
                                'type': 'log',
                                'content': (
                                    f"\n[System] 检测到 AI 重复访问同一页面：{repeated_url}，"
                                    "已自动停止，避免反复刷新网页。\n"
                                )
                            })
                            if current_active_task_id:
                                await emit_callback({'task_id': int(current_active_task_id), 'status': 'failed'})
                            raise KeyboardInterrupt("AI repeated navigation guard")

                        browser_session = getattr(agent_instance, 'browser_session', None)
                        # 重复导航不是业务进展；单纯反复访问 URL 不能重置“无进展”计数。
                        made_progress = bool((has_real_action and not navigation_urls) or step_has_task_complete or str(action_str).strip())
                        if (not made_progress) and current_active_task_id and is_close_step(current_active_task_desc):
                            close_result = await close_popup_in_session(browser_session)
                            logger.info(f"🧹 Auto popup close for task {current_active_task_id}: {close_result}")
                            await emit_callback({
                                'type': 'log',
                                'content': f"\n[System] 检测到当前子任务是关闭弹窗，已自动执行 close_popup：{close_result}\n"
                            })
                            await emit_callback({'task_id': int(current_active_task_id), 'status': 'completed'})
                            if current_active_task:
                                current_active_task['status'] = 'completed'
                            made_progress = True
                            step_has_task_complete = True

                        if made_progress:
                            consecutive_no_progress_steps = 0
                        else:
                            consecutive_no_progress_steps += 1
                            if consecutive_no_progress_steps >= no_progress_limit:
                                current_active_task = get_next_active_task()
                                current_active_task_id = current_active_task.get('id') if current_active_task else None
                                await emit_callback({
                                    'type': 'log',
                                    'content': (
                                        f"\n[System] 连续 {no_progress_limit} 步未产生有效操作，已自动停止，"
                                        "请检查任务描述、页面状态或模型输出。\n"
                                    )
                                })
                                if current_active_task_id:
                                    await emit_callback({'task_id': int(current_active_task_id), 'status': 'failed'})
                                raise KeyboardInterrupt("AI no-progress guard")

                        if callback:
                            if asyncio.iscoroutinefunction(callback):
                                await callback({'type': 'log', 'content': log_content})
                            else:
                                callback({'type': 'log', 'content': log_content})

                        page_url_for_record = await current_page_url(agent_instance)
                        for action in actions:
                            action_dict = action.model_dump() if hasattr(action, 'model_dump') else getattr(action, '_action_dict', {})
                            recorded_action = normalize_recorded_action(
                                action_dict,
                                page_url=page_url_for_record,
                                active_task_desc=current_active_task_desc,
                            )
                            if recorded_action:
                                await emit_callback({'type': 'record_action', 'action': recorded_action})

                        if planned_tasks and all(
                            task.get('status') in ['completed', 'failed', 'skipped']
                            for task in planned_tasks
                        ):
                            await emit_callback({
                                'type': 'log',
                                'content': "\n[System] 所有子任务均已进入终态，自动结束AI执行。\n"
                            })
                            raise KeyboardInterrupt("All planned tasks finished")

                        browser_session = getattr(agent_instance, 'browser_session', None)
                        if browser_session is not None:
                            try:
                                tabs = await browser_session.get_tabs()
                                current_tab_ids = {tab.target_id for tab in tabs}
                                if not known_tab_ids:
                                    known_tab_ids = current_tab_ids
                                else:
                                    new_tabs = [tab for tab in tabs if tab.target_id not in known_tab_ids]
                                    if new_tabs and has_link_open_action:
                                        newest_tab = new_tabs[-1]
                                        if browser_session.agent_focus_target_id != newest_tab.target_id:
                                            await browser_session.event_bus.dispatch(
                                                SwitchTabEvent(target_id=newest_tab.target_id)
                                            )
                                            logger.info(
                                                f"🔀 Auto-switched to newly opened tab {newest_tab.target_id[-4:]} after link click"
                                            )
                                            if callback:
                                                auto_switch_log = (
                                                    f"\n[System]\n检测到新标签页，已自动切换到 {newest_tab.target_id[-4:]}\n"
                                                )
                                                if asyncio.iscoroutinefunction(callback):
                                                    await callback({'type': 'log', 'content': auto_switch_log})
                                                else:
                                                    callback({'type': 'log', 'content': auto_switch_log})
                                    known_tab_ids = current_tab_ids
                            except Exception as tab_error:
                                logger.warning(f"⚠️ Failed to inspect/switch tabs after step {i + 1}: {tab_error}")

                        # 记录未标记任务的步骤（不自动修复，仅警告）
                        if has_real_action and not step_has_task_complete and planned_tasks:
                            next_expected_task_id = last_marked_task_id + 1
                            if next_expected_task_id <= len(planned_tasks):
                                # 检查这个任务是否还没有被标记
                                task_already_marked = False
                                for task in planned_tasks:
                                    if task['id'] == next_expected_task_id and task.get('status') in ['completed', 'failed', 'skipped']:
                                        task_already_marked = True
                                        last_marked_task_id = next_expected_task_id
                                        break

                                if not task_already_marked:
                                    # 记录警告，提示 AI 标记当前任务
                                    agent_instance._pending_status_task_id = next_expected_task_id
                                    pending_task_description = None
                                    if planned_tasks:
                                        for task in planned_tasks:
                                            if task.get('id') == next_expected_task_id:
                                                pending_task_description = task.get('description')
                                                break
                                    agent_instance._pending_status_task_description = pending_task_description
                                    logger.warning(
                                        f"⚠️ Step {i + 1} had actions but no task status update. "
                                        f"Please mark task {next_expected_task_id} as completed, failed, or skipped.")

                    except Exception as e:
                        logger.warning(f"⚠️ Error in on_step_end processing: {e}")
                last_processed_step = len(history)

        try:
            # Try to pass callback
            import inspect
            sig = inspect.signature(agent.run)
            if 'on_step_end' in sig.parameters:
                await asyncio.wait_for(
                    agent.run(max_steps=max_agent_steps, on_step_end=on_step_end),
                    timeout=max_execution_seconds + 15
                )
            else:
                await asyncio.wait_for(
                    agent.run(max_steps=max_agent_steps),
                    timeout=max_execution_seconds + 15
                )
        except asyncio.TimeoutError:
            await emit_callback({
                'type': 'log',
                'content': f"\n[System] AI执行达到硬超时 {max_execution_seconds + 15} 秒，已强制结束。\n"
            })
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Agent execution error: {e}")
            raise

        # 避免在 browser-use history 对象上做深度反射：部分版本的 history.steps/截图字段可能阻塞，
        # 导致 Agent 已结束但执行记录一直 running。最终状态收敛统一交给 ViewSet 的 planned_tasks 检查。
        history = getattr(agent, 'history', [])
        logger.info("🔍 Skipping deep final history scan; returning agent history for ViewSet finalization")
        return history

    def _find_executed_tasks(self, history):
        """
        通过分析执行历史找出已执行但未标记完成的任务
        """
        if not history or not hasattr(history, 'steps'):
            return []

        executed_actions = {}  # 已执行的操作类型和索引，以及对应的步骤
        marked_tasks = set()  # 已标记完成的任务ID

        # 分析执行历史
        for step_idx, step in enumerate(getattr(history, 'steps', [])):
            # 检查每一步中的actions
            actions = getattr(step, 'actions', [])
            for action in actions:
                # 记录已执行的操作
                if hasattr(action, 'input'):
                    action_key = f"input_{action.input.index}"
                    executed_actions[action_key] = {
                        'step': step_idx,
                        'action': 'input',
                        'index': action.input.index
                    }
                elif hasattr(action, 'click'):
                    action_key = f"click_{action.click.index}"
                    executed_actions[action_key] = {
                        'step': step_idx,
                        'action': 'click',
                        'index': action.click.index
                    }
                elif hasattr(action, 'switch_tab'):
                    action_key = f"switch_tab_{action.switch_tab.tab_id}"
                    executed_actions[action_key] = {
                        'step': step_idx,
                        'action': 'switch_tab',
                        'tab_id': action.switch_tab.tab_id
                    }

                # 记录已标记完成的任务
                if hasattr(action, 'mark_task_complete'):
                    marked_tasks.add(action.mark_task_complete.task_id)

        # 理想情况下应该有一个映射机制来关联操作和任务，但由于我们没有这个映射，
        # 我们只能记录未标记完成的执行操作作为调试信息
        unmarked_actions = []
        for action_key, action_info in executed_actions.items():
            unmarked_actions.append({
                'action': action_info['action'],
                'step': action_info['step'],
                'details': action_key
            })

        return {
            'marked_tasks': list(marked_tasks),
            'executed_actions': len(executed_actions),
            'unmarked_actions': unmarked_actions
        }

    async def run_full_process(self, task_description: str, analysis_callback=None, step_callback=None,
                               should_stop=None):
        planned_tasks = await self.analyze_task(task_description)
        if analysis_callback:
            if asyncio.iscoroutinefunction(analysis_callback):
                await analysis_callback(planned_tasks)
            else:
                analysis_callback(planned_tasks)

        return await self.run_task(task_description, planned_tasks, step_callback, should_stop)
