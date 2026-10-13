import os
import platform
import shutil
import signal
import subprocess
from datetime import datetime
from pathlib import Path

import logging
import psutil
from django.conf import settings
from django.db import connection
from django.utils import timezone
logger = logging.getLogger(__name__)

from .jmx_builder import JMeterPlanBuilder, UploadedJMXPlanBuilder, normalize_config
from .models import PerformanceExecution
from .realtime_report import get_realtime_report_config
from .result_parser import parse_jtl


def run_performance_execution(execution_id):
    executor = PerformanceTestExecutor()
    return executor.execute(execution_id)


def stop_execution_process(pid):
    if not pid:
        return False
    try:
        process = psutil.Process(pid)
        for child in process.children(recursive=True):
            child.terminate()
        process.terminate()
        _, alive = psutil.wait_procs([process], timeout=getattr(settings, 'TIMEOUTS_PROCESS_WAIT', 5))
        for proc in alive:
            proc.kill()
        return True
    except psutil.NoSuchProcess:
        return True
    except Exception as exc:
        logger.error(f'停止JMeter进程失败: pid={pid}, error={exc}', exc_info=True)
        return False


class PerformanceTestExecutor:
    def execute(self, execution_id):
        try:
            execution = PerformanceExecution.objects.select_related('script', 'project', 'executed_by').get(id=execution_id)
            self._mark_running(execution)

            config = normalize_config(execution.script.config, base_url=execution.project.base_url)
            self._validate_load_limits(config)

            jmeter_cmd = self._find_jmeter_command()
            if not jmeter_cmd:
                raise RuntimeError('未找到 JMeter 可执行文件，请配置 JMETER_BIN_PATH 或 JMETER_HOME')

            paths = self._prepare_execution_paths(execution.id)
            jmx_content = self._build_jmx_content(execution, config)
            self._write_file(paths['jmx'], jmx_content)

            execution.jmx_path = paths['jmx']
            execution.jtl_path = paths['jtl']
            execution.log_path = paths['log']
            execution.report_url = self._get_report_url(execution.id)
            execution.report_status = 'GENERATING'
            execution.save(update_fields=['jmx_path', 'jtl_path', 'log_path', 'report_url', 'report_status'])

            exit_code = self._run_jmeter(execution, jmeter_cmd, paths)
            self._collect_results(execution, exit_code, paths)
            return {
                'success': execution.status == 'COMPLETED',
                'execution_id': execution.id,
                'exit_code': exit_code,
                'summary': execution.summary,
                'report_url': execution.report_url,
            }
        except Exception as exc:
            logger.error(f'性能测试执行失败: execution_id={execution_id}, error={exc}', exc_info=True)
            try:
                PerformanceExecution.objects.filter(id=execution_id).update(
                    status='FAILED',
                    finished_at=timezone.now(),
                    report_status='FAILED',
                    error_message=str(exc),
                )
            except Exception:
                pass
            return {'success': False, 'execution_id': execution_id, 'error': str(exc)}
        finally:
            connection.close()

    def _mark_running(self, execution):
        execution.status = 'RUNNING'
        execution.started_at = timezone.now()
        execution.error_message = ''
        execution.save(update_fields=['status', 'started_at', 'error_message'])

    def _run_jmeter_command(self, cmd, stdout_log_path, timeout, env=None):
        """执行 JMeter 命令并返回退出码"""
        env = env or os.environ.copy()
        with open(stdout_log_path, 'a', encoding='utf-8') as stdout_log:
            stdout_log.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {' '.join(cmd)}\n")
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='ignore',
                env=env,
            )
            try:
                if process.stdout:
                    for line in process.stdout:
                        stdout_log.write(line)
                        if 'summary' in line.lower() or 'error' in line.lower():
                            logger.info(f'[JMeter] {line.strip()}')
                return process.wait(timeout=timeout)
            finally:
                if process.poll() is None:
                    stop_execution_process(process.pid)

    def _run_jmeter_test(self, execution, jmeter_cmd, paths):
        """仅执行 JMeter 测试，不生成报告"""
        cmd = [
            jmeter_cmd,
            '-n',
            '-t', paths['jmx'],
            '-l', paths['jtl'],
            '-j', paths['log'],
        ]
        timeout = getattr(settings, 'PERFORMANCE_JMETER_TIMEOUT', 3600)
        env = os.environ.copy()
        heap = getattr(settings, 'PERFORMANCE_JMETER_HEAP', '')
        if heap:
            env['HEAP'] = heap

        logger.info(f"执行 JMeter 测试: {' '.join(cmd)}")
        execution.jmeter_pid = None
        execution.save(update_fields=['jmeter_pid'])
        return self._run_jmeter_command(cmd, paths['stdout_log'], timeout, env)

    def _generate_html_report(self, jmeter_cmd, paths):
        """单独生成 HTML 报告，处理 JMeter 5.4.3 无错误时生成失败的 bug"""
        cmd = [
            jmeter_cmd,
            '-g', paths['jtl'],
            '-o', paths['report_dir'],
        ]
        timeout = getattr(settings, 'PERFORMANCE_REPORT_TIMEOUT', 300)
        logger.info(f"生成 JMeter HTML 报告: {' '.join(cmd)}")
        try:
            exit_code = self._run_jmeter_command(cmd, paths['stdout_log'], timeout)
            if exit_code == 0 and os.path.exists(os.path.join(paths['report_dir'], 'index.html')):
                logger.info('JMeter HTML 报告生成成功')
                return True
            else:
                logger.warning(f'JMeter HTML 报告生成失败，退出码: {exit_code}，尝试生成简化报告')
                self._generate_simple_report(paths)
                return False
        except Exception as exc:
            logger.error(f'生成 JMeter HTML 报告异常: {exc}')
            self._generate_simple_report(paths)
            return False

    def _generate_simple_report(self, paths):
        """生成简化的 HTML 报告作为降级方案"""
        try:
            jtl_file = paths['jtl']
            report_dir = paths['report_dir']
            os.makedirs(report_dir, exist_ok=True)

            # 解析 JTL 数据
            import csv
            samples = []
            with open(jtl_file, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    samples.append(row)

            # 计算统计数据
            total = len(samples)
            success = sum(1 for s in samples if s.get('success') == 'true')
            failed = total - success
            elapsed_times = [int(s['elapsed']) for s in samples if s.get('elapsed')]

            stats = {
                'total': total,
                'success': success,
                'failed': failed,
                'success_rate': f'{(success/total*100):.2f}%' if total > 0 else 'N/A',
                'min_elapsed': min(elapsed_times) if elapsed_times else 0,
                'max_elapsed': max(elapsed_times) if elapsed_times else 0,
                'avg_elapsed': f'{sum(elapsed_times)/len(elapsed_times):.2f}' if elapsed_times else 0,
            }

            # 生成 HTML
            html_content = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>性能测试报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
        h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
        .warning {{ background: #fff3cd; border: 1px solid #ffc107; padding: 15px; border-radius: 4px; margin-bottom: 20px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
        .stat-card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #4CAF50; }}
        .stat-label {{ color: #666; margin-top: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background: #4CAF50; color: white; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>性能测试报告</h1>
        <div class="warning">
            <strong>说明：</strong>由于 JMeter 版本兼容性问题，此为简化版报告。完整版报告功能请升级 JMeter 到 5.5 或更高版本。
        </div>
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{stats['total']}</div>
                <div class="stat-label">总请求数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{stats['success']}</div>
                <div class="stat-label">成功数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: {'#f44336' if stats['failed'] > 0 else '#4CAF50'}">{stats['failed']}</div>
                <div class="stat-label">失败数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{stats['success_rate']}</div>
                <div class="stat-label">成功率</div>
            </div>
        </div>
        <div class="stats">
            <div class="stat-card">
                <div class="stat-value">{stats['min_elapsed']}ms</div>
                <div class="stat-label">最小响应时间</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{stats['max_elapsed']}ms</div>
                <div class="stat-label">最大响应时间</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{stats['avg_elapsed']}ms</div>
                <div class="stat-label">平均响应时间</div>
            </div>
        </div>
        <h2>请求详情</h2>
        <table>
            <thead>
                <tr>
                    <th>标签</th>
                    <th>响应时间(ms)</th>
                    <th>状态码</th>
                    <th>状态</th>
                </tr>
            </thead>
            <tbody>
                {''.join(f"<tr><td>{s['label']}</td><td>{s['elapsed']}</td><td>{s['responseCode']}</td><td style='color: {'green' if s['success'] == 'true' else 'red'}'>{'成功' if s['success'] == 'true' else '失败'}</td></tr>" for s in samples)}
            </tbody>
        </table>
    </div>
</body>
</html>'''

            with open(os.path.join(report_dir, 'index.html'), 'w', encoding='utf-8') as f:
                f.write(html_content)

            logger.info('简化版性能测试报告生成成功')
            return True
        except Exception as exc:
            logger.error(f'生成简化报告失败: {exc}', exc_info=True)
            return False

    def _run_jmeter(self, execution, jmeter_cmd, paths):
        """执行 JMeter 测试并生成报告"""
        # 第一步：执行测试
        exit_code = self._run_jmeter_test(execution, jmeter_cmd, paths)

        # 第二步：生成报告（测试成功才生成）
        if exit_code == 0:
            self._generate_html_report(jmeter_cmd, paths)

        return exit_code

    def _collect_results(self, execution, exit_code, paths):
        parsed = parse_jtl(paths['jtl'])
        summary = parsed.get('summary', {})
        report_success = os.path.exists(os.path.join(paths['report_dir'], 'index.html'))

        execution.finished_at = timezone.now()
        if execution.started_at:
            execution.duration = (execution.finished_at - execution.started_at).total_seconds()
        execution.summary = summary
        execution.metrics = {
            'labels': parsed.get('labels', {}),
            'timeline': parsed.get('timeline', []),
            'errors': parsed.get('errors', []),
        }
        execution.report_status = 'SUCCESS' if report_success else 'FAILED'

        if exit_code == 0 and summary.get('total_samples', 0) > 0:
            execution.status = 'COMPLETED'
        elif exit_code == 0 and summary.get('total_samples', 0) == 0:
            execution.status = 'FAILED'
            execution.error_message = 'JMeter 执行完成但未采集到样本'
        else:
            execution.status = 'FAILED'
            execution.error_message = f'JMeter 执行失败，退出码: {exit_code}'

        execution.save(update_fields=[
            'finished_at', 'duration', 'summary', 'metrics',
            'report_status', 'status', 'error_message',
        ])

    def _prepare_execution_paths(self, execution_id):
        base_dir = os.path.join(settings.MEDIA_ROOT, getattr(settings, 'PERFORMANCE_TESTING', 'performance_testing'))
        paths = {
            'jmx_dir': os.path.join(base_dir, 'jmx', f'execution_{execution_id}'),
            'jtl_dir': os.path.join(base_dir, 'jtl', f'execution_{execution_id}'),
            'log_dir': os.path.join(base_dir, 'logs', f'execution_{execution_id}'),
            'report_dir': os.path.join(base_dir, 'reports', f'execution_{execution_id}'),
        }
        for key in ('jmx_dir', 'jtl_dir', 'log_dir'):
            os.makedirs(paths[key], exist_ok=True)

        if os.path.exists(paths['report_dir']):
            shutil.rmtree(paths['report_dir'])
        os.makedirs(paths['report_dir'], exist_ok=True)

        paths.update({
            'jmx': os.path.join(paths['jmx_dir'], 'test_plan.jmx'),
            'jtl': os.path.join(paths['jtl_dir'], 'result.jtl'),
            'log': os.path.join(paths['log_dir'], 'jmeter.log'),
            'stdout_log': os.path.join(paths['log_dir'], 'stdout.log'),
        })
        for file_path in (paths['jtl'], paths['log'], paths['stdout_log']):
            if os.path.exists(file_path):
                os.remove(file_path)
        return paths

    def _write_file(self, path, content):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(content)

    def _build_jmx_content(self, execution, config):
        realtime_config = get_realtime_report_config(test_title=execution.script.name, execution=execution)
        if execution.script.script_type == 'JMX_UPLOAD' and execution.script.original_jmx:
            with execution.script.original_jmx.open('rb') as handle:
                content = handle.read()
            return UploadedJMXPlanBuilder(
                content,
                execution.script.config,
                testname=execution.script.name,
                realtime_config=realtime_config,
            ).build_string()

        return JMeterPlanBuilder(
            config,
            testname=execution.script.name,
            base_url=execution.project.base_url,
            realtime_config=realtime_config,
        ).build_string()

    def _find_jmeter_command(self):
        configured = getattr(settings, 'JMETER_BIN_PATH', '') or os.environ.get('JMETER_BIN_PATH', '')
        if configured and os.path.isfile(configured):
            return configured

        executable = 'jmeter.bat' if platform.system() == 'Windows' else 'jmeter'
        home = getattr(settings, 'JMETER_HOME', '') or os.environ.get('JMETER_HOME', '')
        if home:
            candidate = os.path.join(home, 'bin', executable)
            if os.path.isfile(candidate):
                return candidate

        project_root = Path(settings.BASE_DIR).parent
        builtin = project_root / 'expand' / 'jmeter' / 'bin' / executable
        if builtin.exists():
            return str(builtin)

        system = shutil.which(executable)
        if system:
            return system
        return None

    def _validate_load_limits(self, config):
        max_threads = getattr(settings, 'PERFORMANCE_MAX_THREADS', 1000)
        max_duration = getattr(settings, 'PERFORMANCE_MAX_DURATION', 7200)
        total_threads = sum(int(group.get('threads') or 0) for group in config.get('thread_groups', []))
        max_group_duration = max((int(group.get('duration') or 0) for group in config.get('thread_groups', [])), default=0)
        if total_threads > max_threads:
            raise ValueError(f'线程数超过平台限制: {total_threads} > {max_threads}')
        if max_group_duration > max_duration:
            raise ValueError(f'压测持续时间超过平台限制: {max_group_duration} > {max_duration} 秒')

    def _get_report_url(self, execution_id):
        return f'/api/performance-testing-reports/execution_{execution_id}/index.html'


def send_signal_to_pid(pid, sig=signal.SIGTERM):
    os.kill(pid, sig)
