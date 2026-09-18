# -*- coding: utf-8 -*-
"""
config.ini 的「块级改写」编辑（后端用）
======================================
**为什么不让调用方直接改 config.ini**：这个文件里全是中文注释，是用户的说明书。
configparser 一回写就把注释和空行全抹了，代价太大。

做法：只有被下面这两行包裹的区块才会被改写

    ; >>> bridge:tiku:provider
    provider = AI,TikuAnevol
    ; <<< bridge:tiku:provider

其余字节**原样保留**。所以：
  · 用户手写的注释永远不丢
  · 用户没让 GUI 管的键永远不会被覆盖
  · 重复保存不会堆叠区块（原地替换）

另外两个必须处理的坑（原项目踩过）：
  · **BOM**：记事本「另存为 UTF-8」会加 BOM，configparser 用 "utf8" 读会直接
    抛 MissingSectionHeaderError（第一段变成 "\\ufeff[common]"），程序一启动就崩。
    所以读取用 `utf-8-sig`，写出用**无 BOM** 的 UTF-8。
  · **值里带 %**：configparser 开了插值会把 `%` 当语法；桥接层解析时显式关掉。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BEGIN = "; >>> bridge:{}:{}"
END = "; <<< bridge:{}:{}"

_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
_OPTION_RE = re.compile(r"^\s*(?P<key>[^=;#\s][^=]*?)\s*=\s*(?P<val>.*?)\s*$")
_BEGIN_RE = re.compile(r"^\s*; >>> bridge:(?P<sec>[^:\s]+):(?P<key>\S+)\s*$")
_END_RE = re.compile(r"^\s*; <<< bridge:(?P<sec>[^:\s]+):(?P<key>\S+)\s*$")


def read_text(path: Path) -> str:
    if Path(path).is_file():
        return Path(path).read_text(encoding="utf-8-sig", errors="replace")
    return ""


def write_text(path: Path, text: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    # 无 BOM —— 避免把用户文件改出 BOM（会让 configparser 崩）
    p.write_text(text, encoding="utf-8", newline="\n")


def ensure_exists(path: Path, template: Optional[Path] = None) -> bool:
    """没有 config.ini 就从模板复制一份（去掉 BOM）。返回是否新建。"""
    p = Path(path)
    if p.is_file():
        return False
    text = ""
    if template and Path(template).is_file():
        text = Path(template).read_text(encoding="utf-8-sig", errors="replace")
    if not text:
        text = "[common]\n\n[tiku]\nprovider = AI,TikuAnevol\n\n[notification]\nprovider = ServerChan\n"
    write_text(p, text)
    return True


def _section_bounds(lines: List[str], section: str) -> Optional[Tuple[int, int]]:
    start = None
    for i, ln in enumerate(lines):
        m = _SECTION_RE.match(ln)
        if not m:
            continue
        if start is None:
            if m.group("name").strip().lower() == section.strip().lower():
                start = i
                continue
        else:
            return start, i
    return (start, len(lines)) if start is not None else None


def apply_values(path: Path, values: Dict[str, object]) -> int:
    """
    把 {"段:键": 值} 写进 config.ini（块级改写）。返回改动的项数。

    键里的段名大小写不敏感；值里的换行会被压成空格（ini 单行值）。
    """
    p = Path(path)
    ensure_exists(p)
    lines = read_text(p).splitlines()

    by_section: Dict[str, Dict[str, str]] = {}
    for full_key, raw in (values or {}).items():
        if ":" not in str(full_key):
            continue
        sec, key = str(full_key).split(":", 1)
        sec, key = sec.strip(), key.strip()
        if not sec or not key:
            continue
        val = "" if raw is None else str(raw).replace("\r", " ").replace("\n", " ").strip()
        by_section.setdefault(sec, {})[key] = val

    n = 0
    for sec, kv in by_section.items():
        lines, changed = _rewrite_section(lines, sec, kv)
        n += changed
    write_text(p, "\n".join(lines))
    return n


def _rewrite_section(lines: List[str], section: str, kv: Dict[str, str]) -> Tuple[List[str], int]:
    bounds = _section_bounds(lines, section)
    if bounds is None:
        out = list(lines)
        if out and out[-1].strip():
            out.append("")
        out.append("[{}]".format(section))
        for k, v in kv.items():
            out.extend([BEGIN.format(section, k), "{} = {}".format(k, v), END.format(section, k)])
        return out, len(kv)

    s, e = bounds
    head, body, tail = lines[: s + 1], lines[s + 1: e], lines[e:]

    handled = set()
    changed = 0
    new_body: List[str] = []
    i = 0
    while i < len(body):
        m = _BEGIN_RE.match(body[i])
        if m and m.group("sec").lower() == section.lower() and m.group("key") in kv:
            key = m.group("key")
            # 吃掉旧区块
            j = i + 1
            while j < len(body):
                em = _END_RE.match(body[j])
                if em and em.group("sec").lower() == section.lower() and em.group("key") == key:
                    break
                j += 1
            new_body.extend([BEGIN.format(section, key),
                             "{} = {}".format(key, kv[key]),
                             END.format(section, key)])
            handled.add(key)
            changed += 1
            i = j + 1
            continue
        new_body.append(body[i])
        i += 1

    for k, v in kv.items():
        if k in handled:
            continue
        replaced = False
        for idx, ln in enumerate(new_body):
            if ln.strip().startswith(";"):
                continue
            om = _OPTION_RE.match(ln)
            if om and om.group("key").strip().lower() == k.lower():
                # 用户原来写过这个键 —— 就地替换（不会出现两个同名键）
                new_body[idx: idx + 1] = [BEGIN.format(section, k),
                                          "{} = {}".format(k, v),
                                          END.format(section, k)]
                replaced = True
                changed += 1
                break
        if not replaced:
            if new_body and new_body[-1].strip():
                new_body.append("")
            new_body.extend([BEGIN.format(section, k),
                             "{} = {}".format(k, v),
                             END.format(section, k)])
            changed += 1

    return head + new_body + tail, changed


def read_values(path: Path) -> Dict[str, str]:
    """把整份配置读成 {"段:键": 值}（关闭插值，避免密码里的 % 报错）。"""
    import configparser
    cp = configparser.ConfigParser(interpolation=None)
    p = Path(path)
    if p.is_file():
        cp.read(str(p), encoding="utf-8-sig")
    out: Dict[str, str] = {}
    for sec in cp.sections():
        for k, v in cp.items(sec):
            out["{}:{}".format(sec, k)] = v
    return out
