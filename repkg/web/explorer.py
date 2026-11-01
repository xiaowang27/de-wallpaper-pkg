"""系统文件管理器与剪贴板集成。

「在文件管理器中查看」：
    Windows  explorer /select,<路径>   定位并高亮文件
    macOS    open -R <路径>             访达中定位
    Linux    xdg-open <目录>            打开所在目录

「复制路径」：
    Windows  PowerShell Set-Clipboard
    macOS    pbcopy
    Linux    xclip / xsel
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if _IS_WINDOWS else 0


def _spawn(args: list[str]) -> bool:
    """启动外部命令，不阻塞当前进程。"""
    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        )
        return True
    except (OSError, ValueError):
        return False


def _run(args: list[str], stdin: bytes | None = None, timeout: int = 10) -> bool:
    """执行命令并等待结束。"""
    try:
        result = subprocess.run(
            args,
            input=stdin,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        return result.returncode == 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def reveal_in_file_manager(path: str | Path) -> tuple[bool, str]:
    """在系统文件管理器中定位/打开路径。

    Returns:
        (是否成功, 提示信息)
    """
    target = Path(path)

    if not target.exists():
        return False, f"路径不存在: {target}"

    if _IS_WINDOWS:
        # explorer 的 /select 参数必须整体作为单个字符串传入
        args = [shutil.which("explorer") or "explorer.exe"]
        args.append(str(target) if target.is_dir() else f"/select,{target}")
        ok = _spawn(args)
        return (True, f"已在资源管理器中定位: {target}") if ok else (False, "启动资源管理器失败")

    if sys.platform == "darwin":
        opener = shutil.which("open")
        if not opener:
            return False, "找不到 open 命令"
        args = [opener] + ([str(target)] if target.is_dir() else ["-R", str(target)])
        ok = _spawn(args)
        return (True, f"已在访达中定位: {target}") if ok else (False, "启动访达失败")

    opener = shutil.which("xdg-open")
    if not opener:
        return False, "找不到 xdg-open 命令"
    ok = _spawn([opener, str(target if target.is_dir() else target.parent)])
    return (True, f"已在文件管理器中打开: {target}") if ok else (False, "启动文件管理器失败")


def copy_to_clipboard(text: str) -> bool:
    """把文本复制到系统剪贴板。"""
    if not text:
        return False

    if _IS_WINDOWS:
        ps = shutil.which("powershell") or shutil.which("pwsh")
        if not ps:
            return False
        return _run([ps, "-NoProfile", "-NonInteractive", "-Command",
                     f"Set-Clipboard -Value '{_escape_ps(text)}'"])

    if sys.platform == "darwin":
        pbcopy = shutil.which("pbcopy")
        return bool(pbcopy) and _run([pbcopy], stdin=text.encode("utf-8"))

    clip = shutil.which("xclip") or shutil.which("xsel")
    if not clip:
        return False
    args = [clip, "-selection", "clipboard"] if "xclip" in clip else [clip, "-b"]
    return _run(args, stdin=text.encode("utf-8"))


def _escape_ps(text: str) -> str:
    """转义 PowerShell 单引号字符串内的单引号。"""
    return text.replace("'", "''")
