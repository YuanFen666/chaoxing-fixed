# -*- coding: utf-8 -*-
"""
后端连通性自检
==============
命令行「一次跑通」用：python bridge/bootstrap.py -> 打印 selfcheck + describe。
不联网、不登录。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def bootstrap() -> str:
    """返回 selfcheck 的 JSON 字符串。"""
    import chaoxing_bridge as cb
    return cb.selfcheck()


def describe(*_args) -> str:
    import chaoxing_bridge as cb
    return cb.Backend().describe()


def _main() -> int:
    print(bootstrap())
    print(describe())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
