# bridge/ — 应用后端

GUI（`gui/`）的数据与逻辑来源。**业务逻辑仍然在原项目里**（`源码/chaoxing-fixed/`），
这一层只负责三件事：把原项目跑起来、把结果变成 JSON、把过程变成事件流。

```
bridge/
├── chaoxing_bridge.py    ★ 主入口：Backend 类 + 模块级函数
├── config_store.py       config.ini 的「块级改写」（保留注释）
├── bootstrap.py          命令行连通性自检
└── requirements.txt      必须 Python 3.13
```

## 设计契约

1. **所有方法返回 JSON 字符串**，事件也是 JSON 字符串。
   调用方（`gui/backend.py` 的 QtBackend）反序列化后使用，接口契约清晰稳定。
2. **长任务用回调推事件**，不用轮询。
   `start_run()` 立刻返回，之后通过 `on_event` 回调把事件一条条推给调用方。
3. **两级停止**：`cancel()` 优雅（当前任务点跑完退出）；
   `cancel(force=True)` 强制（1 秒内中断视频/音频的等待循环）。

## 事件契约

```json
{"kind":"log",      "level":"INFO", "text":"...", "time":"12:34:56"}
{"kind":"state",    "state":"running", "text":"..."}
{"kind":"courses",  "courses":[{"title":"...","courseId":"...","percent":100}]}
{"kind":"course",   "title":"...", "percent":100, "done":3, "total":10, "text":"..."}
{"kind":"task",     "state":"running", "course":"...", "done":3, "total":10, "text":"..."}
{"kind":"progress", "done":3, "total":10, "text":"..."}
{"kind":"exams",    "exams":[...], "ready":{"<examId>":{"can_start":true,"reason":"",...}}}
{"kind":"result",   "ok":true, "summary":"...", "detail":{}}
```

`kind` 之外，`ts` 是统一附加的时间戳。

## 主要方法

| 方法 | 作用 |
|---|---|
| `describe()` | 环境信息（路径 / 配置 / Python 版本 / 数据文件大小） |
| `selfcheck()` | 离线自检：路径 + 依赖 + 能否 import 原项目 |
| `load_config()` | 读 config.ini（用原项目的 `load_config_from_file`） |
| `config_values()` / `save_config_values(json)` | 读 / 写 GUI 可见配置项（**保留注释**） |
| `read_config_text()` / `write_config_text(text)` | 配置原文读写 |
| `login(user, pwd, idx)` | 登录 |
| `list_courses(with_progress)` | 课程列表（带完成度时要额外发请求，默认关） |
| `watch_exams(warn_hours)` | 考试看板 + 只读就绪体检 |
| `preflight(options_json)` | 启动前检查（errors 阻断 / warnings 提示） |
| `start_run(options_json)` | 启动任务（含 preflight；**线程内跑，立刻返回**） |
| `is_running()` / `cancel(force)` | 状态查询 / 两级停止 |
| `bank_stats()` / `bank_search(kw, limit)` / `bank_add(q, a)` | 答案库 |

## 自己测一下（不经过 GUI）

```bash
.venv-gui\Scripts\python.exe bridge\chaoxing_bridge.py --selfcheck
.venv-gui\Scripts\python.exe bridge\bootstrap.py
```

## 三个必须知道的坑（都踩过）

1. **必须 Python 3.13**。原项目 `main.py` 用了 `from queue import ShutDown`，
   那是 3.13 才有的；3.12 及以下直接 `ImportError`。
2. **`emit()` 接受 dict 也接受 JSON 字符串**。事件来源不止一处，
   只认 dict 的话会报 `'str' object has no attribute 'setdefault'` 这种难懂的错。
3. **`api/logger.py` 里的 `enqueue=True` 会建 multiprocessing 命名管道**。
   在受限环境（沙箱/部分安全软件）里会直接 `PermissionError`，而且对纯多线程程序
   本来就没必要。如果你的环境报这个错，把它改成 `enqueue=False` 即可 ——
   本后端自己的 sink 就是用 `enqueue=False` 挂的。
