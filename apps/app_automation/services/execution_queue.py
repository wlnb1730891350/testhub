# -*- coding: utf-8 -*-
"""APP 自动化执行队列健康检查。"""
import logging

from celery import current_app

logger = logging.getLogger(__name__)


def check_execution_queue():
    """确认 Redis broker 和至少一个 Celery worker 均可用。"""
    try:
        connection = current_app.connection_for_write()
        connection.ensure_connection(max_retries=0, timeout=2)
        connection.release()
    except Exception as exc:
        logger.warning('APP 自动化 Redis broker 不可用: %s', exc)
        return False, '执行队列不可用，请启动 Redis 服务后重试'

    try:
        workers = current_app.control.ping(timeout=1.5)
    except Exception as exc:
        logger.warning('APP 自动化 Celery worker 探测失败: %s', exc)
        return False, '执行服务不可用，请启动 Celery worker 后重试'

    if not workers:
        return False, '执行服务未启动，请启动 Celery worker 后重试'
    return True, ''
