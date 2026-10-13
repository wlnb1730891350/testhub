# -*- coding: utf-8 -*-
import subprocess
import logging
import platform
import re

logger = logging.getLogger(__name__)


class DeviceManager:
    """设备管理器 - Android ADB 设备管理"""
    
    def __init__(self, adb_path='adb'):
        self.adb_path = adb_path
        # Don't verify ADB in __init__ to avoid blocking initialization
        # Verification will happen when methods are called
        
        # 设置跨平台的subprocess参数
        self.subprocess_kwargs = {}
        if platform.system() == 'Windows':
            self.subprocess_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    
    def _verify_adb(self):
        """验证ADB是否可用"""
        try:
            result = subprocess.run(
                [self.adb_path, 'version'],
                capture_output=True,
                text=True,
                timeout=5,
                **self.subprocess_kwargs
            )
            if result.returncode != 0:
                logger.warning(f"ADB验证失败: {result.stderr}")
                return False
            logger.info(f"ADB验证成功: {result.stdout.strip()}")
            return True
        except FileNotFoundError:
            logger.error(f"找不到ADB命令: {self.adb_path}")
            raise Exception(f"找不到ADB命令: {self.adb_path}，请检查ADB路径配置")
        except subprocess.TimeoutExpired:
            logger.error("ADB验证超时")
            raise Exception("ADB验证超时，请检查ADB是否正常工作")
        except Exception as e:
            logger.error(f"ADB验证异常: {str(e)}")
            raise

    def _run_adb(self, args, timeout=10, binary_output=False):
        """执行一条 ADB 命令，并保留可展示的错误信息。"""
        try:
            result = subprocess.run(
                [self.adb_path, *args],
                capture_output=True,
                text=not binary_output,
                timeout=timeout,
                **self.subprocess_kwargs
            )
        except FileNotFoundError:
            return None, '找不到 ADB，请在 APP 自动化配置中检查 ADB 路径'
        except subprocess.TimeoutExpired:
            return None, 'ADB 命令超时，请检查设备连接'
        except Exception as exc:
            logger.exception('执行 ADB 命令失败: %s', args)
            return None, f'ADB 调用失败: {exc}'

        if result.returncode != 0:
            stderr = result.stderr.decode(errors='replace') if binary_output and result.stderr else result.stderr
            return result, (stderr or result.stdout or 'ADB 命令执行失败').strip()
        return result, ''

    def _recover_execution_surface(self, device_id):
        """Wake a device and close lock-screen or notification overlays before a cold start."""
        actions = [
            ('唤醒屏幕', ['-s', device_id, 'shell', 'input', 'keyevent', '224']),
            ('尝试解锁', ['-s', device_id, 'shell', 'input', 'swipe', '608', '2110', '608', '520', '200']),
            ('关闭系统遮罩', ['-s', device_id, 'shell', 'input', 'keyevent', '4']),
            ('回到桌面', ['-s', device_id, 'shell', 'input', 'keyevent', '3']),
        ]
        recovered = []
        for name, args in actions:
            result, error = self._run_adb(args, timeout=5)
            if result is None or result.returncode != 0:
                logger.warning('执行环境恢复动作失败: %s, %s', name, error)
                continue
            recovered.append(name)
        return recovered

    def preflight(self, device_id, package_name='', recover_environment=True):
        """执行 APP 自动化前的设备健康检查，返回稳定的结构化结果。"""
        checks = []
        device_info = {'device_id': device_id}

        version_result, version_error = self._run_adb(['version'], timeout=5)
        adb_ready = version_result is not None and version_result.returncode == 0
        checks.append({
            'key': 'adb',
            'name': 'ADB 可用性',
            'passed': adb_ready,
            'message': 'ADB 可用' if adb_ready else version_error,
        })
        if not adb_ready:
            return {'ready': False, 'checks': checks, 'device': device_info}

        state_result, state_error = self._run_adb(['-s', device_id, 'get-state'], timeout=8)
        state = state_result.stdout.strip() if state_result and state_result.returncode == 0 else ''
        state_messages = {
            'offline': '设备离线，请检查数据线、模拟器或网络连接',
            'unauthorized': '设备未授权，请在设备上确认 USB 调试授权',
        }
        device_ready = state == 'device'
        checks.append({
            'key': 'device',
            'name': '设备连接与授权',
            'passed': device_ready,
            'message': '设备已连接并授权' if device_ready else state_messages.get(state, state_error or f'设备状态异常: {state or "未知"}'),
        })
        if not device_ready:
            return {'ready': False, 'checks': checks, 'device': device_info}

        recovered_actions = []
        if recover_environment:
            recovered_actions = self._recover_execution_surface(device_id)

        window_result, _ = self._run_adb(
            ['-s', device_id, 'shell', 'dumpsys', 'window'], timeout=8
        )
        window_state = window_result.stdout if window_result else ''
        is_locked = bool(re.search(
            r'(?:isKeyguardShowing|mDreamingLockscreen)\s*=\s*true', window_state, re.IGNORECASE
        ))
        checks.append({
            'key': 'execution_surface',
            'name': '执行界面就绪',
            'passed': not is_locked,
            'message': (
                '已恢复设备执行界面' if recovered_actions else '设备执行界面已就绪'
            ) if not is_locked else '设备仍处于锁屏状态，请先解除密码或生物识别锁屏后再执行',
            'recovered_actions': recovered_actions,
        })
        if is_locked:
            return {'ready': False, 'checks': checks, 'device': device_info}

        model_result, _ = self._run_adb(['-s', device_id, 'shell', 'getprop', 'ro.product.model'], timeout=5)
        version_result, _ = self._run_adb(['-s', device_id, 'shell', 'getprop', 'ro.build.version.release'], timeout=5)
        size_result, _ = self._run_adb(['-s', device_id, 'shell', 'wm', 'size'], timeout=5)
        model = model_result.stdout.strip() if model_result else ''
        android_version = version_result.stdout.strip() if version_result else ''
        screen_size = ''
        if size_result:
            for line in size_result.stdout.splitlines():
                if 'x' in line:
                    screen_size = line.split(':', 1)[-1].strip()
                    break
        device_info.update({
            'name': model,
            'android_version': android_version,
            'screen_size': screen_size,
        })
        checks.append({
            'key': 'device_info',
            'name': '设备信息读取',
            'passed': bool(model or android_version or screen_size),
            'message': '已读取设备信息' if (model or android_version or screen_size) else '设备信息读取失败，但不影响执行',
            'required': False,
        })

        package_name = (package_name or '').strip()
        if package_name:
            package_result, package_error = self._run_adb(
                ['-s', device_id, 'shell', 'pm', 'path', package_name], timeout=8
            )
            installed = bool(package_result and package_result.stdout.strip().startswith('package:'))
            checks.append({
                'key': 'package',
                'name': '应用安装状态',
                'passed': installed,
                'message': f'已安装: {package_name}' if installed else (package_error or f'未在设备上找到应用: {package_name}'),
            })

        required_checks = [item for item in checks if item.get('required', True)]
        return {
            'ready': all(item['passed'] for item in required_checks),
            'checks': checks,
            'device': device_info,
        }
    
    def list_devices(self):
        """
        获取设备列表
        返回: [{'device_id': 'xxx', 'status': 'online', ...}, ...]
        """
        try:
            # Verify ADB is available before running commands
            self._verify_adb()
            
            logger.info(f"执行ADB命令: {self.adb_path} devices -l")
            result = subprocess.run(
                [self.adb_path, 'devices', '-l'],
                capture_output=True,
                text=True,
                timeout=10,
                **self.subprocess_kwargs
            )
            
            if result.returncode != 0:
                logger.error(f"ADB命令执行失败: {result.stderr}")
                raise Exception(f"ADB命令执行失败: {result.stderr}")
            
            logger.info(f"ADB输出: {result.stdout}")
            devices = []
            lines = result.stdout.strip().split('\n')[1:]  # 跳过第一行标题
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('*'):
                    continue
                
                parts = line.split()
                if len(parts) >= 2:
                    device_id = parts[0]
                    status = 'online' if parts[1] == 'device' else 'offline'
                    
                    # 解析设备信息
                    device_info = {
                        'device_id': device_id,
                        'status': status,
                        'name': None,
                        'android_version': None,
                        'ip_address': None,
                        'port': 5555
                    }
                    
                    # 如果是远程设备，解析IP和端口
                    if ':' in device_id:
                        ip_port = device_id.split(':')
                        device_info['ip_address'] = ip_port[0]
                        device_info['port'] = int(ip_port[1]) if len(ip_port) > 1 else 5555
                    
                    # 获取设备详细信息
                    if status == 'online':
                        try:
                            device_info.update(self.get_device_info(device_id))
                        except Exception:
                            pass
                    
                    devices.append(device_info)
            
            logger.info(f"找到 {len(devices)} 个设备")
            return devices
            
        except subprocess.TimeoutExpired:
            logger.error("ADB命令执行超时")
            raise Exception("ADB命令执行超时")
        except Exception as e:
            logger.error(f"获取设备列表失败: {str(e)}")
            raise Exception(f"获取设备列表失败: {str(e)}")
    
    def get_device_info(self, device_id):
        """
        获取设备详细信息
        """
        info = {}
        
        try:
            # 获取设备名称
            result = subprocess.run(
                [self.adb_path, '-s', device_id, 'shell', 'getprop', 'ro.product.model'],
                capture_output=True,
                text=True,
                timeout=5,
                **self.subprocess_kwargs
            )
            if result.returncode == 0:
                info['name'] = result.stdout.strip()
            
            # 获取Android版本
            result = subprocess.run(
                [self.adb_path, '-s', device_id, 'shell', 'getprop', 'ro.build.version.release'],
                capture_output=True,
                text=True,
                timeout=5,
                **self.subprocess_kwargs
            )
            if result.returncode == 0:
                info['android_version'] = result.stdout.strip()
                
        except Exception as e:
            logger.warning(f"获取设备 {device_id} 详细信息失败: {str(e)}")
        
        return info
    
    def connect_device(self, ip_address, port=5555):
        """
        连接远程设备
        返回: {'device_id': 'xxx', 'status': 'online', ...} 或 None
        """
        try:
            device_address = f"{ip_address}:{port}"
            logger.info(f"连接设备: {device_address}")
            
            # 执行连接命令
            result = subprocess.run(
                [self.adb_path, 'connect', device_address],
                capture_output=True,
                text=True,
                timeout=30,
                **self.subprocess_kwargs
            )
            
            if result.returncode != 0:
                logger.error(f"连接失败: {result.stderr}")
                raise Exception(f"连接失败: {result.stderr}")
            
            # 检查连接结果
            output = result.stdout.strip()
            logger.info(f"连接结果: {output}")
            if 'connected' in output.lower() or 'already connected' in output.lower():
                # 获取设备信息
                device_info = {
                    'device_id': device_address,
                    'status': 'online',
                    'ip_address': ip_address,
                    'port': port,
                    'name': None,
                    'android_version': None
                }
                
                # 获取详细信息
                try:
                    device_info.update(self.get_device_info(device_address))
                except Exception as e:
                    logger.warning(f"获取设备详细信息失败: {str(e)}")
                
                logger.info(f"设备连接成功: {device_info}")
                return device_info
            else:
                logger.error(f"连接失败: {output}")
                raise Exception(f"连接失败: {output}")
                
        except subprocess.TimeoutExpired:
            logger.error("连接超时")
            raise Exception("连接超时，请检查设备网络")
        except Exception as e:
            logger.error(f"连接设备失败: {str(e)}")
            raise Exception(f"连接设备失败: {str(e)}")
    
    def disconnect_device(self, device_id: str) -> bool:
        """
        断开设备连接
        """
        try:
            logger.info(f"断开设备: {device_id}")
            result = subprocess.run(
                [self.adb_path, 'disconnect', device_id],
                capture_output=True,
                text=True,
                timeout=10,
                **self.subprocess_kwargs
            )
            
            success = result.returncode == 0
            if success:
                logger.info(f"设备断开成功: {device_id}")
            else:
                logger.error(f"设备断开失败: {result.stderr}")
            return success
            
        except Exception as e:
            logger.error(f"断开设备失败: {str(e)}")
            return False
