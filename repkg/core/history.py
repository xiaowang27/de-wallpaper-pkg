"""扫描目录历史。

记录用户扫描过的目录，方便下次直接点选，不用重新输入路径。
持久化到 <项目根>/data/scan_history.json。

设计要点：
- 历史是「用户输入过的目录」，去重、按最近使用排序
- 只存路径与时间，不存任何工程数据
- 读写失败都��该影响主流程（历史是便利功能，不是必需品）
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .paths import PROJECT_ROOT

#: 历史文件路径
HISTORY_FILE = PROJECT_ROOT / "data" / "scan_history.json"

#: 最多保留多少条
MAX_ENTRIES = 30


def _is_same_path(a: str, b: str) -> bool:
    """判断两个路径是否指向同一目录。

    先规范化再比较，否则 "E:/a" 与 "E:\\a" 会被当成两条。
    Windows 下不区分大小写。
    """
    def norm(p: str) -> str:
        try:
            return str(Path(p).expanduser()).lower()
        except (OSError, ValueError):
            return str(p).lower()

    return norm(a) == norm(b)


def _load() -> list[dict]:
    """读取历史，失败返回空列表。"""
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict) and e.get("path")]


def _save(entries: list[dict]) -> bool:
    """写入历史，失败返回 False。"""
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def add_directory(path: str | Path, count: int = 0) -> list[dict]:
    """把目录加入历史（去重、最新在前）。

    Args:
        path: 目录路径。
        count: 该次扫描找到的工程数（仅作展示）。

    Returns:
        更新后的历史列表。
    """
    target = str(Path(path).expanduser())
    entries = _load()

    # 去掉同路径的旧记录（Windows 路径不区分大小写）
    entries = [e for e in entries if not _is_same_path(e.get("path", ""), target)]

    entries.insert(0, {"path": target, "count": count, "used_at": time.time()})
    entries = entries[:MAX_ENTRIES]
    _save(entries)
    return entries


def list_directories() -> list[dict]:
    """读取历史（按最近使用排序）。"""
    entries = _load()
    entries.sort(key=lambda e: e.get("used_at", 0), reverse=True)
    return entries


def remove_directory(path: str) -> list[dict]:
    """从历史中移除一条。

    比较前先做同样的规范化，否则 "E:/a" 与 "E:\\a" 会被当成两条。
    """
    entries = [e for e in _load() if not _is_same_path(e.get("path", ""), path)]
    _save(entries)
    return entries


def clear() -> None:
    """清空历史。"""
    _save([])
