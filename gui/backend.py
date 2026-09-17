# -*- coding: utf-8 -*-
"""
Qt 信号封装：把 bridge.Backend 接到 Qt 事件循环上。

为什么要这一层
--------------
bridge.Backend 的所有事件（log / task / progress / state / result）都从它的
工作线程发出；而阻塞式调用（login / list_courses）不能在 GUI 线程里跑。
Qt 的 Signal 天生跨线程安全（自动排队到接收者所在线程），所以这里只做两件
很薄的事：

1. ``event``   —— Backend 的事件回调原样转成 Signal（JSON 字符串）；
2. ``result``  —— 阻塞调用丢进 daemon 线程，完成后以 (tag, JSON) 形式回来。

页面只跟 QtBackend 打交道，永远不需要碰线程。
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

# bridge 在仓库根，先把根目录放进 import 路径
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bridge.chaoxing_bridge import Backend  # noqa: E402


class QtBackend(QObject):
    """Backend 的 Qt 外衣。构造一次，全局共享（见 gui.app.AppContext）。"""

    #: Backend 的每条事件（log / state / courses / course / task / progress / result）
    event = Signal(str)

    #: 阻塞调用的返回：result(tag, payload_json)。tag 用于区分是哪次调用。
    result = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.backend = Backend(on_event=self.event.emit)

    # ------------------------------------------------------------------ 阻塞调用 → 后台线程
    def _async(self, tag: str, fn) -> None:
        """把返回 JSON 字符串的阻塞调用放进线程跑完再 emit result。"""

        def _run():
            try:
                payload = fn()
            except Exception as e:  # noqa: BLE001 —— 任何意外都以结果形式回给界面
                payload = json.dumps({"ok": False, "msg": f"{type(e).__name__}: {e}"},
                                     ensure_ascii=False)
            self.result.emit(tag, payload)

        threading.Thread(target=_run, name=f"gui-{tag}", daemon=True).start()

    def load_config(self) -> None:
        self._async("config", self.backend.load_config)

    def config_values(self) -> None:
        self._async("config_values", self.backend.config_values)

    def login(self, username: str, password: str) -> None:
        self._async("login", lambda: self.backend.login(username, password))

    def refresh_courses(self, with_progress: bool = False) -> None:
        self._async("courses", lambda: self.backend.list_courses(with_progress))

    def watch_exams(self, warn_hours: float = 48.0) -> None:
        self._async("exams", lambda: self.backend.watch_exams(warn_hours))

    # ------------------------------------------------------------------ 答案库
    def bank_stats(self) -> None:
        self._async("bank_stats", self.backend.bank_stats)

    def bank_search(self, keyword: str, limit: int = 500) -> None:
        self._async("bank_search", lambda: self.backend.bank_search(keyword, limit))

    def bank_add(self, question: str, answer: str) -> None:
        self._async("bank_add", lambda: self.backend.bank_add(question, answer))

    def bank_export(self, which: str, path: str) -> None:
        self._async("bank_export", lambda: self.backend.bank_export(which, path))

    # ------------------------------------------------------------------ 配置
    def read_config_text(self) -> None:
        # read_config_text 返回的是原文而非 JSON，这里统一包成 JSON 再走 result 通道
        self._async("config_text", lambda: json.dumps(
            {"ok": True, "text": self.backend.read_config_text()}, ensure_ascii=False))

    def write_config_text(self, text: str) -> None:
        self._async("config_text_save", lambda: self.backend.write_config_text(text))

    def save_config_values(self, pairs: dict) -> None:
        self._async("config_save",
                    lambda: self.backend.save_config_values(json.dumps(pairs, ensure_ascii=False)))

    # ------------------------------------------------------------------ 立即返回的调用
    def start(self, options: dict) -> dict:
        """启动刷课（Backend 内部起线程，立刻返回）。已含 preflight 检查。"""
        return json.loads(self.backend.start_run(json.dumps(options, ensure_ascii=False)))

    def cancel(self, force: bool = False) -> dict:
        """两级停止：第一次优雅，force=True 强制（1 秒内中断）。"""
        return json.loads(self.backend.cancel(force))

    @property
    def running(self) -> bool:
        return self.backend.is_running()
