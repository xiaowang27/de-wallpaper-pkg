"""输出路径配置。

设计原则：**输出目录始终相对于项目根目录**，而不是临时目录或当前工作目录。
这样无论从 PyCharm、命令行还是 Web 启动，产物都落在同一个地方。

项目根的识别方式：从本文件向上查找带 pyproject.toml 的目录；
找不到时回退到当前工作目录（此时行为退化为相对当前目录输出）。
"""
from __future__ import annotations

import os
from pathlib import Path

#: 输出根目录名
OUT_DIR_NAME = "out"

#: 收集出来的图片/视频的子目录名（放在解包目录顶层）
MEDIA_DIR_NAME = "media"


def find_project_root() -> Path:
    """定位项目根目录（向上查找 pyproject.toml）。"""
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return Path.cwd()


#: 项目根目录
PROJECT_ROOT = find_project_root()

#: 输出根目录：<项目根>/out
OUT_DIR = Path(os.environ.get("REPKG_OUT_DIR") or (PROJECT_ROOT / OUT_DIR_NAME))


def resolve_out_dir(explicit: str | Path | None = None) -> Path:
    """解析最终使用的输出目录。

    优先级：显式参数 > 环境变量 REPKG_OUT_DIR > <项目根>/out
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    return OUT_DIR.resolve()
