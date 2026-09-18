# -*- coding: utf-8 -*-
"""
全局停止信号（两级）
===================

为什么需要它：worker 线程对 process_chapter 的异常一律转重试、watchdog 还会
给死掉的 worker 补位 —— 单纯往 worker 里抛异常是停不下来的。所以停止必须
走「共享标志位 + 各处主动检查」：

- 优雅停止（abort）：worker 在章节边界退出，当前任务点跑完；
- 强制停止（force）：连视频/文档的等待循环也立即中断（最长 1 秒内生效）。

bridge 层的「取消」最终都会汇聚到这里。
"""
import threading

from api.exceptions import StudyAborted

_abort = threading.Event()
_force = threading.Event()


def request_abort() -> None:
    """请求优雅停止：worker 在章节边界收工。"""
    _abort.set()


def request_force() -> None:
    """请求强制停止：等待循环（视频/音频播放中）也立即中断。"""
    _force.set()
    _abort.set()  # 强制包含优雅


def clear() -> None:
    """新一轮运行前复位。"""
    _abort.clear()
    _force.clear()


def abort_requested() -> bool:
    return _abort.is_set()


def force_requested() -> bool:
    return _force.is_set()


def check_abort() -> None:
    """章节边界检查：收到停止请求就抛 StudyAborted。"""
    if _abort.is_set():
        raise StudyAborted("用户已停止")


def check_force_abort() -> None:
    """高频等待循环检查：只有「强制停止」才中断，避免误伤优雅停止。"""
    if _force.is_set():
        raise StudyAborted("用户强制停止")
