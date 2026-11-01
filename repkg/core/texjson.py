"""生成 .tex-json 元数据。

对应 RePKG.Application/Texture/TexJsonInfoGenerator.cs —— Wallpaper Engine
导入贴图时使用的 sidecar 文件。
"""
from __future__ import annotations

import json

from .enums import TexFlags
from .tex import Tex


def _is_power_of_two(n: int) -> bool:
    if n == 0:
        return False
    while n != 1:
        if n % 2 != 0:
            return False
        n //= 2
    return True


def generate_info(tex: Tex) -> str:
    """生成 .tex-json 文本。"""
    first_image = tex.first_image
    mipmap_count = len(first_image.mipmaps) if first_image else 0

    info = {
        "bleedtransparentcolors": True,
        "clampuvs": tex.has_flag(TexFlags.CLAMP_UVS),
        "format": tex.header.format.name.lower(),
        "nomip": str(mipmap_count == 1).lower(),
        "nointerpolation": tex.has_flag(TexFlags.NO_INTERPOLATION),
        "nonpoweroftwo": str(
            not _is_power_of_two(tex.header.image_width)
            or not _is_power_of_two(tex.header.image_height)
        ).lower(),
    }

    if tex.is_gif:
        container = tex.frame_info_container
        if container is None:
            raise ValueError("TEX 是动画贴图但缺少帧信息容器")
        info["spritesheetsequences"] = [
            {
                "duration": 1,
                "frames": len(container.frames),
                "width": container.gif_width,
                "height": container.gif_height,
            }
        ]

    return json.dumps(info, indent=2, ensure_ascii=False)
