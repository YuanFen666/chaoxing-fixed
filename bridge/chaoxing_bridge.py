# -*- coding: utf-8 -*-
"""
应用后端（GUI 的数据与逻辑来源）
==============================
设计要点
--------
1. **只吐 JSON 字符串**。所有方法的返回值和事件都是 JSON，调用方（gui/）反序列化后
   使用，接口契约清晰稳定。
2. **回调而不是轮询**。长任务（刷课/考试）通过 on_event 回调把事件推给调用方。
3. **可取消**。`cancel()` 置位后，业务线程在下一个检查点（每个章节）退出；
   `cancel(force=True)` 立即中断视频/音频的等待循环。
4. **不碰原项目源码**。这里只是 import 它、调用它，逻辑仍在上游实现。

事件 JSON 形状：
    {"kind":"log",      "level":"INFO", "text":"...", "time":"12:34:56"}
    {"kind":"state",    "state":"running", "text":"..."}
    {"kind":"courses",  "courses":[...]}
    {"kind":"course",   "title":"...", "percent":100, "done":3, "total":10}
    {"kind":"progress", "done":3, "total":10, "text":"..."}
    {"kind":"exams",    "exams":[...], "ready":{...}}
    {"kind":"result",   "ok":true, "summary":"...", "detail":{...}}

手测（不经过 GUI）：
    python bridge/chaoxing_bridge.py --selfcheck
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# 路径：ROOT 必须是「项目根」，不能想当然地用 __file__ 往上推
#
# 【为什么】调用方的启动目录不固定（IDE 运行、快捷方式、打包后的 exe……），
# __file__ 或 cwd 推出来的"项目根"可能是错的 —— 于是 config.ini 找不到、
# cache.json 会写到错误的位置。实测踩过：describe() 报 source_ok=false。
#
# 解析顺序：
#   ① CHAOXING_ROOT 环境变量（调用方知道自己从哪加载的，直接告诉本模块，最可靠）
#   ② 从 __file__ 往上找含「源码/chaoxing-fixed/main.py」的目录
#   ③ 从当前工作目录往上找同样的标记
#   ④ 从 sys.executable 往上找
#   ⑤ 实在找不到就用 __file__ 往上两级（保持旧的兜底行为）
# ---------------------------------------------------------------------------
BRIDGE_DIR = Path(__file__).resolve().parent
SOURCE_DIR_NAME = "源码"
APP_DIR_NAME = "chaoxing-fixed"

#: 项目根的标志物：这些在真正的项目根一定有
_ROOT_MARKERS = (
    Path("start_chaoxing.bat"),
    Path(SOURCE_DIR_NAME) / APP_DIR_NAME / "main.py",
    Path("README.md"),
)


def _looks_like_root(p: Path) -> bool:
    """是不是项目根？用两个以上标志物命中来判定，避免把偶然同名的目录当成根。"""
    try:
        if not p.is_dir():
            return False
        # main.py 是最硬的证据：只有真正的项目根才有「源码/chaoxing-fixed/main.py」
        if (p / SOURCE_DIR_NAME / APP_DIR_NAME / "main.py").is_file():
            return True
        hits = sum(1 for m in _ROOT_MARKERS if (p / m).exists())
        return hits >= 2
    except OSError:
        return False


def _walk_up(start: Path) -> Optional[Path]:
    try:
        cur = start.resolve()
    except OSError:
        return None
    for _ in range(8):
        if _looks_like_root(cur):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _resolve_root() -> Path:
    env = (os.environ.get("CHAOXING_ROOT") or "").strip()
    if env:
        p = Path(env)
        if p.is_dir():
            return p.resolve()

    for start in (BRIDGE_DIR.parent, Path.cwd(), Path(sys.executable).resolve().parent,
                  BRIDGE_DIR):
        found = _walk_up(start)
        if found is not None:
            return found

    return BRIDGE_DIR.parent


ROOT = _resolve_root()

_DATA_FILES = {
    "cache": "cache.json",
    "answer_key": "answer_key.json",
    "exam_state": "exam_state.json",
    "cookies": "cookies.txt",
    "log": "chaoxing.log",
}


def _candidate_source_dirs() -> List[Path]:
    out = []
    env = (os.environ.get("CHAOXING_SRC") or "").strip()
    if env:
        out.append(Path(env))
    out.append(ROOT / SOURCE_DIR_NAME / APP_DIR_NAME)
    # 兼容打包/发布后「源码与 exe 同级」的布局
    out.append(ROOT / APP_DIR_NAME)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        out.append(exe_dir / SOURCE_DIR_NAME / APP_DIR_NAME)
        out.append(exe_dir)
    return out


def find_source_dir() -> Path:
    tried = []
    for c in _candidate_source_dirs():
        tried.append(str(c))
        if (c / "api" / "answer.py").is_file() and (c / "main.py").is_file():
            return c
    raise FileNotFoundError(
        "找不到原项目源码目录（需含 api/answer.py 与 main.py）。已尝试：\n  "
        + "\n  ".join(tried)
        + "\n可用环境变量 CHAOXING_SRC 指定。"
    )


SOURCE_DIR: Optional[Path] = None


def ensure_import_path() -> Path:
    """把源码目录插进 sys.path（幂等）。"""
    global SOURCE_DIR
    if SOURCE_DIR is None:
        SOURCE_DIR = find_source_dir()
    s = str(SOURCE_DIR)
    if s not in sys.path:
        sys.path.insert(0, s)
    return SOURCE_DIR


def set_runtime_cwd() -> Path:
    """
    把工作目录固定成项目根 —— 等价于 start_chaoxing.bat 的 `cd /d "%~dp0"`。
    这样 cache.json / answer_key.json / chaoxing.log 与命令行版是同一份。
    """
    target = ROOT
    try:
        cfg = ROOT / "config.ini"
        if cfg.is_file():
            target = cfg.parent
    except OSError:
        pass
    try:
        os.chdir(target)
    except OSError:
        pass
    return Path(os.getcwd())


def data_file(key: str) -> Path:
    return Path(os.getcwd()) / _DATA_FILES[key]


# ---------------------------------------------------------------------------
# 运行参数（与 config.ini 解耦：界面上的运行期开关走这里）
# ---------------------------------------------------------------------------
DEFAULT_TIKU_CONF = {
    "provider": "AI,TikuAnevol",
    "submit": "true",
    "cover_rate": "0.8",
    "true_list": "正确,对,√,是",
    "false_list": "错误,错,×,否,不对,不正确",
    "delay": "1.5",
}


class _Cancel:
    """全局取消标志。业务线程在每个章节检查一次。"""

    def __init__(self) -> None:
        self._ev = threading.Event()

    def set(self) -> None:
        self._ev.set()

    def clear(self) -> None:
        self._ev.clear()

    @property
    def set_(self) -> bool:
        return self._ev.is_set()


CANCEL = _Cancel()


class _LocalAbort(BaseException):
    """源码树不可用时的兜底（正常不会用到）。"""


_ABORT_CLS = None


def _abort_cls():
    """
    停止异常类：优先用源码树的 api.exceptions.StudyAborted，
    保证 worker 线程 / JobProcessor 能识别并走收操流程（而不是被转成章节重试）。
    异常类在源码目录挂载前可能拿不到，所以惰性解析。
    """
    global _ABORT_CLS
    if _ABORT_CLS is None:
        try:
            from api.exceptions import StudyAborted
            _ABORT_CLS = StudyAborted
        except Exception:  # noqa: BLE001
            _ABORT_CLS = _LocalAbort
    return _ABORT_CLS


def _check_cancel() -> None:
    if CANCEL.set_:
        raise _abort_cls()("用户已停止")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
class Backend:
    """
    应用后端主入口：GUI（gui/）持有一个实例，所有交互都走它。

    用法：
        backend = Backend(on_event=handler)   # handler 收 JSON 字符串事件
        result = json.loads(backend.list_courses())
        backend.start_run(options_json)       # 内部起线程，事件走 on_event
    """

    def __init__(self, on_event: Optional[Callable[[str], None]] = None) -> None:
        self._on_event = on_event
        self._lock = threading.RLock()
        self.config_path = ROOT / "config.ini"
        self.common: Dict[str, Any] = {}
        self.tiku_conf: Dict[str, Any] = dict(DEFAULT_TIKU_CONF)
        self.notify_conf: Dict[str, Any] = {}
        self.chaoxing = None
        self.src_dir: Optional[Path] = None
        self.courses: List[dict] = []
        self.exams: List[dict] = []
        self.last_result: Dict[str, Any] = {}
        self._running = False
        self._manual_logout = False  # logout() 置位；显式 login() 解除

    # ------------------------------------------------------------ 事件
    def emit(self, ev: Any) -> None:
        """
        发一条事件。**宽容处理入参**：接受 dict，也接受 JSON 字符串。

        为什么宽容：事件来源不止一处（本类内部、原项目的日志 sink、外部调用方），
        只认 dict 的话，传错类型会报
            'str' object has no attribute 'setdefault'
        这种既难懂又难查的错。所以入口统一做一次「是字符串就 json.loads」。
        """
        if isinstance(ev, (str, bytes, bytearray)):
            try:
                ev = json.loads(ev)
            except (ValueError, TypeError) as e:
                raise TypeError("emit() 收到无法解析为 JSON 的字符串：{}".format(e)) from e
        if not isinstance(ev, dict):
            raise TypeError("emit() 需要 dict 或 JSON 字符串，收到 {}".format(type(ev).__name__))
        ev.setdefault("ts", time.time())
        try:
            payload = json.dumps(ev, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            payload = json.dumps({"kind": "log", "level": "WARNING",
                                  "text": "事件序列化失败: {}".format(e)})
        cb = self._on_event
        if cb is None:
            print(payload, file=sys.stderr, flush=True)
            return
        try:
            cb(payload)
        except Exception:  # noqa: BLE001
            # 事件回调（界面侧）炸了不能把业务线程带走
            pass

    def emit_json(self, ev_json: str) -> str:
        """显式入口：调用方直接把自己序列化好的事件 JSON 发过来。"""
        self.emit(ev_json)
        return self._json({"ok": True})

    def log(self, level: str, text: str) -> None:
        self.emit({"kind": "log", "level": level, "text": text,
                   "time": time.strftime("%H:%M:%S")})

    def state(self, state: str, text: str = "") -> None:
        self.emit({"kind": "state", "state": state, "text": text})

    @staticmethod
    def _json(obj: Any) -> str:
        return json.dumps(obj, ensure_ascii=False)

    # ------------------------------------------------------------ 环境
    def describe(self) -> str:
        """一次性把所有路径/环境信息交给界面（首页用）。"""
        info = self._env_info()
        return self._json(info)

    def selfcheck(self) -> str:
        """同一个探针，放在实例上 —— 建完 Backend 就能自查，不必再取模块。"""
        return selfcheck()

    def version(self) -> str:
        return VERSION

    def emit_test(self) -> str:
        """
        发两条演示事件（**参数从本模块构造**）。

        存在的意义：把「后端 → 事件回调」这条链路单独测通。
        """
        self.emit({"kind": "log", "level": "INFO", "text": "来自后端的事件（回调测试）"})
        self.emit({"kind": "progress", "done": 2, "total": 5, "text": "测试进度"})
        return self._json({"ok": True, "msg": "已发送 2 条事件"})

    def echo(self, value_json: str = "null") -> str:
        """
        回显参数并报告它的类型 —— 用来验证调用链路的参数传递。
        传 '{"a":1}' 应该回 object；传 'abc' 应该回 str。
        """
        try:
            value = json.loads(value_json)
        except ValueError:
            value = value_json
        return self._json({"ok": True, "type": type(value).__name__,
                           "repr": repr(value)[:120]})

    @staticmethod
    def _env_info() -> Dict[str, Any]:
        try:
            src = str(find_source_dir())
            src_ok = True
        except FileNotFoundError as e:
            src, src_ok = str(e).splitlines()[0], False
        cfg = ROOT / "config.ini"
        return {
            "root": str(ROOT),
            "cwd": os.getcwd(),
            "source_dir": src,
            "source_ok": src_ok,
            "config_path": str(cfg),
            "config_exists": cfg.is_file(),
            "python": sys.version.split()[0],
            "python_exe": sys.executable,
            "version": VERSION,
            "data": {k: str(data_file(k)) for k in _DATA_FILES},
            "data_size": {k: (data_file(k).stat().st_size if data_file(k).is_file() else 0)
                          for k in ("cache", "answer_key")},
        }

    def attach_log_sink(self, level: str = "DEBUG") -> str:
        """
        把 loguru 的日志接到事件流（**不修改原项目的 api/logger.py**）。

        enqueue 必须为 False：enqueue=True 会建 multiprocessing 队列
        （Windows 命名管道），在受限环境里直接 PermissionError，而且对
        纯多线程程序本来就没必要。
        """
        try:
            from loguru import logger as _logger
        except Exception as e:  # noqa: BLE001
            self.log("WARNING", "loguru 不可用：{}".format(e))
            return ""
        sink_id = {}

        def _sink(message):
            r = message.record
            self.emit({"kind": "log", "level": r["level"].name, "text": r["message"],
                       "module": "{}:{}".format(r["name"], r["function"]),
                       "time": r["time"].strftime("%H:%M:%S")})

        try:
            sink_id["id"] = _logger.add(_sink, level=level, enqueue=False,
                                        format="{message}", colorize=False)
        except Exception as e:  # noqa: BLE001
            self.log("WARNING", "挂接日志失败：{}".format(e))
            return ""
        self._sink_id = sink_id.get("id")
        return str(self._sink_id or "")

    def detach_log_sink(self) -> None:
        sid = getattr(self, "_sink_id", None)
        if sid is None:
            return
        try:
            from loguru import logger as _logger
            _logger.remove(sid)
        except Exception:  # noqa: BLE001
            pass
        self._sink_id = None

    # ------------------------------------------------------------ 配置
    def load_config(self, path: str = "") -> str:
        if path:
            self.config_path = Path(path)
        try:
            ensure_import_path()
        except FileNotFoundError as e:
            self.log("ERROR", str(e))
            return self._json({"ok": False, "msg": str(e)})

        if not self.config_path.is_file():
            self.log("WARNING", "没找到 {}，使用默认配置".format(self.config_path))
            self.common = {"use_cookies": False, "username": "", "password": "",
                           "course_list": None, "speed": 1.0, "jobs": 4,
                           "notopen_action": "retry", "exam_watch": True}
            self.tiku_conf = dict(DEFAULT_TIKU_CONF)
            self.notify_conf = {}
            return self._json({"ok": True, "created": False, "msg": "配置文件不存在，已用默认值"})

        try:
            from main import load_config_from_file
            self.common, self.tiku_conf, self.notify_conf = load_config_from_file(
                str(self.config_path))
            self.tiku_conf.setdefault("delay", 0.0)
            self.tiku_conf.setdefault("cover_rate", 0.8)
            self.log("INFO", "已读取配置 {}".format(self.config_path))
            return self._json({"ok": True, "created": False, "msg": "配置已载入"})
        except Exception as e:  # noqa: BLE001
            self.log("ERROR", "读取配置失败：{}: {}".format(type(e).__name__, e))
            return self._json({"ok": False, "msg": "{}: {}".format(type(e).__name__, e)})

    def config_values(self) -> str:
        """把 config.ini 里的 GUI 可见项整理成扁平字典交给界面。"""
        import configparser
        cp = configparser.ConfigParser(interpolation=None)
        if self.config_path.is_file():
            cp.read(str(self.config_path), encoding="utf-8-sig")
        out: Dict[str, str] = {}
        for sec in cp.sections():
            for k, v in cp.items(sec):
                out["{}:{}".format(sec, k)] = v
        return self._json({"ok": True, "values": out, "path": str(self.config_path)})

    def read_config_text(self) -> str:
        try:
            if self.config_path.is_file():
                return self.config_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            self.log("ERROR", "读取配置原文失败：{}".format(e))
        return ""

    def write_config_text(self, text: str) -> str:
        """整份覆盖（配置页的「原文」模式用）。写成无 BOM 的 UTF-8。"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(text, encoding="utf-8", newline="\n")
            self.log("INFO", "配置原文已保存：{}".format(self.config_path))
            return self._json({"ok": True, "msg": "已保存"})
        except OSError as e:
            self.log("ERROR", "保存配置失败：{}".format(e))
            return self._json({"ok": False, "msg": str(e)})

    def save_config_values(self, pairs_json: str) -> str:
        """
        按「段:键 = 值」批量写回，**保留注释**（块级改写）。

        传入 JSON：{"tiku:provider":"AI,TikuAnevol", "common:jobs":"8"}
        只有被 `; >>> bridge:键` 标记过的会被改写，其余字节原样保留。
        """
        try:
            values = json.loads(pairs_json or "{}")
        except ValueError as e:
            return self._json({"ok": False, "msg": "参数不是合法 JSON：{}".format(e)})
        try:
            from config_store import apply_values
            n = apply_values(self.config_path, values)
            self.log("INFO", "已保存 {} 个配置项（注释保留）".format(n))
            return self._json({"ok": True, "msg": "已保存 {} 项".format(n), "count": n})
        except Exception as e:  # noqa: BLE001
            self.log("ERROR", "保存配置项失败：{}: {}".format(type(e).__name__, e))
            return self._json({"ok": False, "msg": "{}: {}".format(type(e).__name__, e)})

    # ------------------------------------------------------------ 登录
    def _build_chaoxing(self, username: str, password: str, account_index: int = 0):
        try:
            from api.answer import Tiku
            from api.base import Account, Chaoxing
        except ModuleNotFoundError as e:
            # 依赖缺失时把「内嵌解释器实际在用哪套路径」一起抛出来 ——
            # 界面上只有一句 No module named 'xxx' 完全没法定位是
            # 解释器找错了、还是 site-packages 没挂上。
            site = [p for p in sys.path if "site-packages" in p.replace("/", "\\").lower()]
            raise ModuleNotFoundError(
                "{} | 解释器={} prefix={} site-packages={}".format(
                    e, sys.executable, sys.prefix, "; ".join(site) or "（无）")
            ) from e

        cfg = dict(self.common)
        accounts = list(cfg.get("accounts") or [])
        if username or password:
            accounts = [(username, password)]
        elif not accounts and cfg.get("username") and cfg.get("password"):
            accounts = [(cfg.get("username"), cfg.get("password"))]
        if not accounts:
            raise ValueError("没有可用账号：请在「配置」里填手机号/密码")

        idx = int(account_index or 1)
        if not (1 <= idx <= len(accounts)):
            idx = 1
        user, pwd = accounts[idx - 1]

        tiku = Tiku()
        tiku.config_set(dict(self.tiku_conf))
        tiku = tiku.get_tiku_from_config()
        tiku.init_tiku()

        self.chaoxing = Chaoxing(account=Account(user, pwd), tiku=tiku,
                                 query_delay=float(self.tiku_conf.get("delay", 0) or 0))
        return self.chaoxing

    def login(self, username: str = "", password: str = "", account_index: int = 0) -> str:
        self._manual_logout = False  # 显式登录动作，解除手动登出封锁
        self.state("login", "正在登录…")
        if not self.common:
            self.load_config()
        try:
            chaoxing = self._build_chaoxing(username, password, account_index)
        except Exception as e:  # noqa: BLE001
            self.log("ERROR", "初始化失败：{}: {}".format(type(e).__name__, e))
            self.state("error", str(e))
            return self._json({"ok": False, "msg": str(e)})
        try:
            st = chaoxing.login(login_with_cookies=bool(self.common.get("use_cookies", False)))
        except Exception as e:  # noqa: BLE001
            self.log("ERROR", "登录异常：{}: {}".format(type(e).__name__, e))
            self.state("error", "登录异常")
            return self._json({"ok": False, "msg": "{}: {}".format(type(e).__name__, e)})
        if not st.get("status"):
            msg = st.get("msg", "未知原因")
            self.log("ERROR", "登录失败：{}".format(msg))
            self.state("error", "登录失败")
            # 登录失败要清掉会话：_build_chaoxing 一构建就赋了 self.chaoxing，
            # 不清的话下次 _ensure_login 看到「已有会话」直接放行，
            # 实际并未登录，后面拉课程全空，报成莫名其妙的「没有可处理的课程」。
            self.chaoxing = None
            return self._json({"ok": False, "msg": msg})
        self.log("INFO", "登录成功")
        self.state("login", "已登录")
        # 账号是界面显式输入的（不是 config 里读的）→ 写回 config.ini，
        # 否则下次启动/点开始又会报「没有可用账号」。config.ini 本就是本项目
        # 存账号的设计（且已被 .gitignore 排除），写回只是补上持久化这一环。
        if username and password:
            try:
                from config_store import apply_values, ensure_exists
                tpl = ROOT / "config.ini.example"
                ensure_exists(self.config_path, tpl if tpl.is_file() else None)
                apply_values(self.config_path,
                             {"common:username": username, "common:password": password})
                self.log("INFO", "账号已写回 config.ini，下次启动免输")
            except Exception as e:  # noqa: BLE001 写配置失败不影响登录本身
                self.log("WARNING", "账号写回 config.ini 失败：{}".format(e))
        return self._json({"ok": True, "msg": "登录成功"})

    def _ensure_login(self, username: str = "", password: str = "",
                      account_index: int = 0) -> bool:
        if self.chaoxing is not None:
            # 界面上换了账号：已登录会话和传入账号不一致时要重新登录，
            # 否则开始运行还在用旧账号刷课。
            cur = getattr(getattr(self.chaoxing, "account", None), "username", None)
            if username and cur and username != cur:
                self.log("INFO", "账号已切换（{} -> {}），重新登录".format(cur, username))
                self.chaoxing = None
            else:
                return True
        # 手动登出后：拒绝用 config.ini 的账号静默重登。
        # 只有调用方显式带来账号密码（= 用户明确的登录动作）才放行。
        if getattr(self, "_manual_logout", False) and not (username and password):
            self.log("WARNING", "已取消登录：请先重新登录（不会再用 config.ini 自动登录）")
            return False
        return bool(json.loads(self.login(username, password, account_index)).get("ok"))

    # ------------------------------------------------------------ 课程
    def list_courses(self, with_progress: bool = False) -> str:
        """
        取课程列表。with_progress=True 时顺带取完成度/分数 —— **每门课 3 个请求**
        （enc -> openc -> 进度页），课程多时明显更慢，所以默认关掉，由界面决定。
        """
        if not self._ensure_login():
            return self._json({"ok": False, "courses": [], "msg": "未登录"})
        self.state("courses", "正在读取课程列表…")
        try:
            courses = self.chaoxing.get_course_list() or []
        except Exception as e:  # noqa: BLE001
            self.log("ERROR", "读取课程列表失败：{}: {}".format(type(e).__name__, e))
            self.state("error", "读取课程列表失败")
            return self._json({"ok": False, "courses": [], "msg": str(e)})

        out = []
        for i, c in enumerate(courses, 1):
            _check_cancel()
            item = {
                "index": i,
                "title": str(c.get("title", "")),
                "courseId": str(c.get("courseId", "")),
                "clazzId": str(c.get("clazzId", "")),
                "cpi": str(c.get("cpi", "")),
                "teacher": str(c.get("teacher", "")),
                "progress": "",
                "percent": None,
                "score": None,
            }
            if with_progress:
                try:
                    from api.base import SessionManager
                    from api.progress import format_progress, get_course_progress
                    st = get_course_progress(SessionManager.get_session(), c)
                    item["progress"] = format_progress(st)
                    item["percent"] = st.get("percent")
                    item["score"] = st.get("score")
                except Exception as e:  # noqa: BLE001
                    self.log("DEBUG", "取进度失败 {} -> {}".format(item["title"], e))
                    item["progress"] = "?"
            out.append(item)
            self.emit({"kind": "course", "title": item["title"], "percent": item["percent"],
                       "score": item["score"], "done": i, "total": len(courses),
                       "text": item["progress"]})
        self.courses = out
        self.emit({"kind": "courses", "courses": out})
        self.log("INFO", "共读取到 {} 门课程".format(len(out)))
        return self._json({"ok": True, "courses": out, "msg": "共 {} 门".format(len(out))})

    # ------------------------------------------------------------ 考试
    def watch_exams(self, warn_hours: float = 48.0) -> str:
        if not self._ensure_login():
            return self._json({"ok": False, "exams": [], "ready": {}, "msg": "未登录"})
        courses = self.courses
        if not courses:
            data = json.loads(self.list_courses(with_progress=False))
            courses = data.get("courses") or []
        try:
            from api.exam import ExamWatch
            from api.notification import Notification

            notification = Notification()
            notification.config_set(dict(self.notify_conf))
            notification = notification.get_notification_from_config()
            notification.init_notification()

            watch = ExamWatch(notification, warn_hours=float(warn_hours or 48))
            self.state("exams", "正在读取考试情况…")
            exams = watch.run(list(courses)) or []
            ready = {k: _ready_dict(v) for k, v in (getattr(watch, "last_ready", {}) or {}).items()}
            payload = [_exam_dict(e) for e in exams]
            self.exams = exams
            self._watch_obj = watch          # 供 take_exams 复用（含 last_ready）
            self.emit({"kind": "exams", "exams": payload, "ready": ready})
            return self._json({"ok": True, "exams": payload, "ready": ready,
                               "msg": "共 {} 场".format(len(payload))})
        except Exception as e:  # noqa: BLE001
            self.log("WARNING", "考试看板失败（不影响刷课）：{}: {}".format(type(e).__name__, e))
            self.log("DEBUG", traceback.format_exc())
            return self._json({"ok": False, "exams": [], "ready": {},
                               "msg": "{}: {}".format(type(e).__name__, e)})

    # ------------------------------------------------------------ 运行
    def preflight(self, options_json: str = "{}") -> str:
        """
        启动前检查：把「肯定会白跑」的问题拦在开始之前。
        errors 阻断启动；warnings 只提示（比如没题库也能刷视频课）。
        """
        errors: List[str] = []
        warnings: List[str] = []
        try:
            ensure_import_path()
        except FileNotFoundError as e:
            errors.append("源码目录不可用：" + str(e).splitlines()[0])

        try:
            opt = json.loads(options_json or "{}")
        except ValueError:
            opt = {}
        if not self.common:
            self.load_config()

        # 1) 账号：界面传入 > config [accounts] > config [common]
        has_ui = bool(str(opt.get("username") or "") and str(opt.get("password") or ""))
        accs = self.common.get("accounts") or []
        has_cfg = bool(accs) or bool(self.common.get("username") and self.common.get("password"))
        if not has_ui and not has_cfg:
            errors.append("没有可用账号：请在「首页」登录一次（会自动存进 config.ini），"
                          "或在「配置」里填手机号/密码")

        # 2) 题库链：ANEVOL token 或 AI 三件套至少一路可用
        tokens = str(self.tiku_conf.get("tokens") or "").strip()
        endpoint = str(self.tiku_conf.get("endpoint") or "").strip()
        key = str(self.tiku_conf.get("key") or "").strip()
        model = str(self.tiku_conf.get("model") or "").strip()
        usable: List[str] = []
        if tokens and "你的" not in tokens:
            usable.append("TikuAnevol")
        if endpoint and key and model:
            usable.append("AI")
        if not usable:
            warnings.append("题库链不可用（ANEVOL token 与 AI 配置都缺）："
                            "视频课能刷，但章节测验/考试会答不了")

        # 3) 运行参数合法性（写 config 时填错的也拦一下）
        try:
            spd = float(opt.get("speed") or self.common.get("speed") or 1.0)
            if not (0.5 <= spd <= 2.0):
                warnings.append("倍速 {:.2f} 超出合理范围（0.5~2.0），已按边界值运行".format(spd))
        except (TypeError, ValueError):
            warnings.append("倍速配置不是数字，已按 1.0 运行")

        return self._json({"ok": not errors, "errors": errors, "warnings": warnings,
                           "usable_tiku": usable})

    def start_run(self, options_json: str) -> str:
        """
        跑一次（**可重入**：内部起线程，立刻返回，事件走回调）。
        返回 {"ok":true,"msg":"已启动"}；重复启动会被拒绝。
        启动前先做 preflight 检查，有致命问题直接拒绝并逐条列出。
        """
        pf = json.loads(self.preflight(options_json))
        for w in pf["warnings"]:
            self.log("WARNING", "启动检查：" + w)
        if not pf["ok"]:
            for e in pf["errors"]:
                self.log("ERROR", "启动检查：" + e)
            return self._json({"ok": False,
                               "msg": "启动检查未通过：" + "；".join(pf["errors"])})
        self.log("INFO", "启动检查通过：账号 ✓，题库可用：{}".format(
            "/".join(pf.get("usable_tiku") or []) or "无（仅刷视频）"))

        with self._lock:
            if self._running:
                return self._json({"ok": False, "msg": "已有任务在运行"})
            self._running = True
        try:
            opt = json.loads(options_json or "{}")
        except ValueError as e:
            self._running = False
            return self._json({"ok": False, "msg": "参数不是合法 JSON：{}".format(e)})

        t = threading.Thread(target=self._run_worker, args=(opt,), name="chaoxing-run",
                             daemon=True)
        t.start()
        return self._json({"ok": True, "msg": "已启动"})

    def is_running(self) -> bool:
        return bool(self._running)

    def logout(self) -> str:
        """
        取消登录：丢弃会话与已拉取的课程/考试缓存（config.ini 里的账号保留）。

        同时置「手动登出」标记：之后 _ensure_login 不再用 config.ini 里的账号
        静默重登 —— 用户明确退出后，任何需要登录的操作都必须重新显式登录。
        """
        self.chaoxing = None
        self.courses = []
        self.exams = []
        self._manual_logout = True
        self.log("INFO", "已取消登录")
        self.state("logout", "已取消登录")
        return self._json({"ok": True, "msg": "已取消登录"})

    def cancel(self, force: bool = False) -> str:
        """
        两级停止：第一次 = 优雅（当前任务点跑完退出）；
        再点一次（force=True）= 强制，立即中断视频/音频的等待循环（1 秒内生效）。
        """
        CANCEL.set()
        if force:
            try:
                ensure_import_path()
                from api.abort import request_force
                request_force()
            except Exception as e:  # noqa: BLE001
                self.log("WARNING", "强制停止标记设置失败（{}），已退化为优雅停止".format(e))
                return self._json({"ok": True, "msg": "已请求停止"})
            self.log("WARNING", "已强制停止：立即中断当前任务点")
            return self._json({"ok": True, "msg": "已强制停止"})
        self.log("WARNING", "已请求停止：当前任务点跑完就会退出（再点一次「停止」立即中断）")
        return self._json({"ok": True, "msg": "已请求停止"})

    def _run_worker(self, opt: Dict[str, Any]) -> None:
        CANCEL.clear()
        try:
            ensure_import_path()
            from api.abort import clear as clear_abort
            clear_abort()  # 复位上一轮的停止标志
        except Exception:  # noqa: BLE001
            pass
        self.attach_log_sink()
        t0 = time.time()
        try:
            if not self.common:
                self.load_config()
            # 运行参数覆盖（只影响本次）
            speed = max(1.0, min(2.0, float(opt.get("speed") or 1.0)))
            self.common["speed"] = speed
            self.common["jobs"] = int(opt.get("jobs") or 4)
            ids = [str(x) for x in (opt.get("courseIds") or []) if str(x).strip()]
            if ids:
                self.common["course_list"] = ids

            if not self._ensure_login(str(opt.get("username") or ""),
                                      str(opt.get("password") or ""),
                                      int(opt.get("accountIndex") or 0)):
                self._finish(False, "登录失败", t0)
                return

            do_study = bool(opt.get("study", True))
            do_exam = bool(opt.get("exam", False))
            auto_submit = bool(opt.get("autoSubmit", False))
            exam_watch = bool(opt.get("examWatch", True))

            all_courses = self.chaoxing.get_course_list() or []
            course_task = _filter_courses(all_courses, ids)
            if not course_task:
                self._finish(False, "没有可处理的课程", t0)
                return

            exams, watch = ([], None)
            if exam_watch:
                # watch_exams 内部会把 ExamWatch 实例留在 self._watch_obj 上
                self.watch_exams()
                exams = self.exams

            # 全局总进度 = 课程数 +（有考试再算一个阶段），保证进度条单调前进
            steps = len(course_task) + (1 if do_exam else 0)

            if do_exam and not do_study:
                self.emit({"kind": "progress", "done": 0, "total": steps,
                           "text": "开始考试作答"})
                exams, watch = self._run_exams(course_task, auto_submit,
                                               int(opt.get("maxExams") or 1))
                self.emit({"kind": "progress", "done": steps, "total": steps,
                           "text": "考试作答结束"})
                self._finish(True, "考试作答流程结束", t0)
                return

            if do_study:
                self.state("running", "开始刷课…")
                for i, course in enumerate(course_task):
                    _check_cancel()
                    self.emit({"kind": "progress", "done": i, "total": steps,
                               "text": "第 {}/{} 门：《{}》".format(
                                   i + 1, len(course_task), course.get("title", ""))})
                    self._study_course(course)
                self.log("INFO", "所有课程学习任务已完成")

            if do_exam and do_study:
                self.state("running", "刷课完成，接着处理考试…")
                self.emit({"kind": "progress", "done": len(course_task), "total": steps,
                           "text": "开始考试作答"})
                self._run_exams(course_task, auto_submit, 0)

            self._finish(True, "全部完成", t0)
        except _abort_cls():
            self.log("WARNING", "已被用户停止")
            self._finish(False, "已停止", t0)
        except BaseException as e:  # noqa: BLE001
            self.log("ERROR", "运行出错：{}: {}".format(type(e).__name__, e))
            self.log("DEBUG", traceback.format_exc())
            self._finish(False, "出错：{}: {}".format(type(e).__name__, e), t0)
        finally:
            self.detach_log_sink()
            with self._lock:
                self._running = False

    def _study_course(self, course: dict) -> None:
        from main import process_course

        title = str(course.get("title", ""))
        counter = {"chapter": 0, "total": 0}
        try:
            pl = self.chaoxing.get_course_point(course["courseId"], course["clazzId"],
                                                course["cpi"])
            pts = pl.get("points", []) if isinstance(pl, dict) else []
            counter["total"] = len(pts)
        except Exception as e:  # noqa: BLE001
            self.log("WARNING", "取章节失败 {}：{}".format(title, e))

        # 任务级状态：界面「任务」页直接吃这个，不用去解析日志文本
        self.emit({"kind": "task", "state": "running", "course": title,
                   "text": "正在刷课", "done": 0, "total": counter["total"]})

        # 用一个「每章必经」的钩子实现：取消检查 + 进度推送
        rl = self.chaoxing.rate_limiter
        original = rl.limit_rate

        def hooked(*a, **kw):
            _check_cancel()
            counter["chapter"] += 1
            # scope=chapter：这是「当前课程内」的章节进度，只更新任务行；
            # 全局总进度条由 _run_worker 按课程推，否则多门课时总进度会来回跳
            self.emit({"kind": "progress", "scope": "chapter", "done": counter["chapter"],
                       "total": counter["total"],
                       "text": "《{}》第 {} 章".format(title, counter["chapter"])})
            self.emit({"kind": "task", "state": "running", "course": title,
                       "text": "第 {} / {} 章".format(counter["chapter"], counter["total"]),
                       "done": counter["chapter"], "total": counter["total"]})
            return original(*a, **kw)

        rl.limit_rate = hooked
        self.emit({"kind": "course", "title": title, "percent": 0, "score": None,
                   "done": 0, "total": counter["total"], "text": "开始学习"})
        try:
            process_course(self.chaoxing, course, self.common)
        except _abort_cls():
            self.emit({"kind": "task", "state": "cancelled", "course": title,
                       "text": "已停止",
                       "done": counter["chapter"], "total": counter["total"]})
            raise
        except BaseException as e:  # noqa: BLE001
            self.emit({"kind": "task", "state": "error", "course": title,
                       "text": "{}: {}".format(type(e).__name__, e),
                       "done": counter["chapter"], "total": counter["total"]})
            raise
        finally:
            rl.limit_rate = original
        self.emit({"kind": "course", "title": title, "percent": 100, "score": None,
                   "done": counter["chapter"], "total": counter["total"], "text": "已完成"})
        self.emit({"kind": "task", "state": "done", "course": title, "text": "已完成",
                   "done": counter["chapter"], "total": counter["total"]})

    def _run_exams(self, courses: List[dict], auto_submit: bool, max_exams: int):
        from main import take_exams

        if not self.exams:
            self.watch_exams()
        watch = getattr(self, "_watch_obj", None)
        if watch is None:
            from api.exam import ExamWatch
            watch = ExamWatch(None, warn_hours=48)
            watch.last_ready = {}
        # 任务页反馈：考试阶段也要推 task 事件，否则前端预建的「考试作答」行
        # 永远停在「等待中」（course 名与前端预建行一致，才能就地更新同一行）
        self.emit({"kind": "task", "state": "running", "course": "考试作答",
                   "text": "正在作答", "done": 0, "total": 0})
        try:
            take_exams(watch, self.exams, courses, self.chaoxing.tiku,
                       auto_submit=auto_submit,
                       openc=str(self.common.get("exam_openc") or ""),
                       max_exams=int(max_exams or 0),
                       gate_wait=float(self.common.get("exam_gate_wait", 1800) or 1800),
                       gate_poll=float(self.common.get("exam_gate_poll", 120) or 120))
        except _abort_cls():
            self.emit({"kind": "task", "state": "cancelled", "course": "考试作答",
                       "text": "已停止", "done": 0, "total": 0})
            raise
        except BaseException as e:  # noqa: BLE001
            self.emit({"kind": "task", "state": "error", "course": "考试作答",
                       "text": "{}: {}".format(type(e).__name__, e), "done": 0, "total": 0})
            raise
        self.emit({"kind": "task", "state": "done", "course": "考试作答",
                   "text": "作答结束", "done": 0, "total": 0})
        return self.exams, watch

    def _finish(self, ok: bool, summary: str, t0: float) -> None:
        dur = int(time.time() - t0)
        text = "{}（耗时 {} 分 {} 秒）".format(summary, dur // 60, dur % 60)
        self.last_result = {"ok": ok, "summary": text}
        self.emit({"kind": "result", "ok": ok, "summary": text})
        self.state("done" if ok else "cancelled", text)

    # ------------------------------------------------------------ 答案库
    def bank_stats(self) -> str:
        out = {}
        for key in ("answer_key", "cache"):
            p = data_file(key)
            data = _read_json(p)
            out[key] = {"path": str(p), "count": len(data), "size": p.stat().st_size
                        if p.is_file() else 0}
        return self._json({"ok": True, "stats": out})

    def bank_search(self, keyword: str = "", limit: int = 500) -> str:
        kw = (keyword or "").strip().lower()
        rows = []
        for key in ("answer_key", "cache"):
            for q, a in _read_json(data_file(key)).items():
                if kw and kw not in str(q).lower() and kw not in str(a).lower():
                    continue
                rows.append({"source": "答案库" if key == "answer_key" else "缓存",
                             "question": str(q), "answer": str(a)})
                if len(rows) >= int(limit or 500):
                    break
            if len(rows) >= int(limit or 500):
                break
        return self._json({"ok": True, "rows": rows, "total": len(rows)})

    def bank_add(self, question: str, answer: str) -> str:
        """
        写入**已核验答案库**（answer_key.json）。
        会走 api.answer.normalize_title 归一化，保证与查询时的键一致。
        """
        if not (question or "").strip() or not (answer or "").strip():
            return self._json({"ok": False, "msg": "题干和答案都要填"})
        try:
            ensure_import_path()
            from api.answer import answer_key, normalize_title
            dao = answer_key()
            dao.add_cache(normalize_title(question), answer, source="GUI 手动")
            self.log("INFO", "答案库写入：{} -> {}".format(question[:40], answer[:40]))
            return self._json({"ok": True, "msg": "已写入答案库"})
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "msg": "{}: {}".format(type(e).__name__, e)})

    def bank_export(self, which: str, path: str) -> str:
        key = "answer_key" if which == "answer_key" else "cache"
        data = _read_json(data_file(key))
        if not data:
            return self._json({"ok": False, "msg": "该库是空的"})
        try:
            with open(path, "w", encoding="utf8") as fp:
                for q, a in sorted(data.items()):
                    fp.write("{}\t{}\n".format(q, str(a).replace("\n", " ")))
            return self._json({"ok": True, "msg": "已导出 {} 条".format(len(data))})
        except OSError as e:
            return self._json({"ok": False, "msg": str(e)})


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
VERSION = "1.0.0"


def _filter_courses(all_courses: List[dict], ids: List[str]) -> List[dict]:
    if not ids:
        return list(all_courses or [])
    want = {str(x).strip() for x in ids if str(x).strip()}
    picked = [c for c in (all_courses or []) if str(c.get("courseId")) in want]
    return picked or list(all_courses or [])


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        if path.is_file():
            with path.open("r", encoding="utf-8-sig") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def _exam_dict(e) -> dict:
    return {
        "course_title": getattr(e, "course_title", ""),
        "course_id": getattr(e, "course_id", ""),
        "name": getattr(e, "name", ""),
        "status": getattr(e, "status", ""),
        "exam_id": getattr(e, "exam_id", ""),
        "remain_human": getattr(e, "remain_human", ""),
        "remain_hours": getattr(e, "remain_hours", None),
        "todo": bool(getattr(e, "todo", False)),
        "done": bool(getattr(e, "done", False)),
    }


def _ready_dict(r) -> Optional[dict]:
    if r is None:
        return None
    return {
        "can_start": bool(getattr(r, "can_start", False)),
        "reason": getattr(r, "reason", ""),
        "need_face": bool(getattr(r, "need_face", False)),
        "need_captcha": bool(getattr(r, "need_captcha", False)),
        "need_code": bool(getattr(r, "need_code", False)),
        "monitor": bool(getattr(r, "monitor", False)),
        "duration": getattr(r, "duration", ""),
    }


# ---------------------------------------------------------------------------
# 模块级便捷函数（不实例化也能用）
# ---------------------------------------------------------------------------
def version() -> str:
    return VERSION


def selfcheck() -> str:
    """连通性探针：不联网，只检查路径与依赖是否就位。"""
    out = {"ok": True, "version": VERSION, "python": sys.version.split()[0],
           "cwd": os.getcwd(), "errors": [], "warnings": []}
    try:
        set_runtime_cwd()
        src = ensure_import_path()
        out["source_dir"] = str(src)
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["errors"].append("{}: {}".format(type(e).__name__, e))
        return json.dumps(out, ensure_ascii=False)

    for mod in ("loguru", "tqdm", "requests", "bs4", "lxml", "openai", "httpx", "pyaes"):
        try:
            __import__(mod)
        except Exception as e:  # noqa: BLE001
            out["warnings"].append("缺少依赖 {}（{}）".format(mod, type(e).__name__))
    try:
        import api.answer  # noqa: F401
        import api.exam  # noqa: F401
        import api.progress  # noqa: F401
        import main  # noqa: F401
        out["imports_ok"] = True
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["imports_ok"] = False
        out["errors"].append("导入原项目失败 {}: {}".format(type(e).__name__, e))
    out["config_exists"] = (ROOT / "config.ini").is_file()
    return json.dumps(out, ensure_ascii=False)


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="chaoxing 应用后端")
    ap.add_argument("--selfcheck", action="store_true", help="离线自检并打印 JSON")
    ap.add_argument("--describe", action="store_true", help="打印环境信息 JSON")
    ap.add_argument("--demo", action="store_true", help="跑一遍事件流（不联网）")
    args = ap.parse_args()

    if args.selfcheck:
        print(selfcheck())
        return 0
    if args.describe:
        print(Backend().describe())
        return 0
    if args.demo:
        b = Backend(on_event=lambda s: print("EVENT:", s))
        b.load_config()
        print(b.describe())
        b.emit({"kind": "progress", "done": 1, "total": 3, "text": "演示"})
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
