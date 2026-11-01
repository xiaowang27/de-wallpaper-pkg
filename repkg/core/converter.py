"""TEX -> 图片转换（PNG / GIF / MP4）。

对应 RePKG.Application/Texture/TexToImageConverter.cs。
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

from .dxt import decompress_dxt1, decompress_dxt3, decompress_dxt5
from .enums import (
    MipmapFormat,
    TexFlags,
    get_file_extension,
    is_compressed_format,
    is_image_format,
    is_raw_format,
)
from .tex import Tex, TexMipmap


class ConversionError(Exception):
    """贴图转换失败。"""


@dataclass
class ImageResult:
    """转换结果。"""

    data: bytes
    format: MipmapFormat

    @property
    def extension(self) -> str:
        return get_file_extension(self.format)


def _open_pillow():
    from PIL import Image

    return Image


def _mipmap_to_image(mipmap: TexMipmap):
    """把原始像素格式的 mipmap 转成 PIL Image。"""
    Image = _open_pillow()

    if mipmap.format == MipmapFormat.RGBA8888:
        return Image.frombytes("RGBA", (mipmap.width, mipmap.height), mipmap.data)
    if mipmap.format == MipmapFormat.R8:
        return Image.frombytes("L", (mipmap.width, mipmap.height), mipmap.data)
    if mipmap.format == MipmapFormat.RG88:
        # RG88 的语义：R = alpha, G = 灰度值（见原项目 Helpers/RG88.cs）
        # 原实现有两条不一致的转换路径，此处统一按 R=alpha / G=gray 处理。
        return _rg88_to_image(mipmap)
    raise ConversionError(f"不支持的原始像素格式: {mipmap.format}")


def _rg88_to_image(mipmap: TexMipmap):
    """RG88 -> RGBA Image（R 当 alpha，G 当灰度）。"""
    Image = _open_pillow()

    raw = mipmap.data
    count = mipmap.width * mipmap.height
    pixels = bytearray(count * 4)
    for i in range(count):
        r = raw[i * 2]
        g = raw[i * 2 + 1]
        pixels[i * 4] = g
        pixels[i * 4 + 1] = g
        pixels[i * 4 + 2] = g
        pixels[i * 4 + 3] = r
    return Image.frombytes("RGBA", (mipmap.width, mipmap.height), bytes(pixels))


def _decompress_mipmap(mipmap: TexMipmap) -> TexMipmap:
    """DXT 解压成 RGBA8888，返回新的 mipmap（不修改入参）。"""
    fmt = mipmap.format
    if fmt == MipmapFormat.COMPRESSED_DXT5:
        data = decompress_dxt5(mipmap.width, mipmap.height, mipmap.data)
    elif fmt == MipmapFormat.COMPRESSED_DXT3:
        data = decompress_dxt3(mipmap.width, mipmap.height, mipmap.data)
    elif fmt == MipmapFormat.COMPRESSED_DXT1:
        data = decompress_dxt1(mipmap.width, mipmap.height, mipmap.data)
    else:
        return mipmap

    return TexMipmap(
        width=mipmap.width,
        height=mipmap.height,
        data=data,
        decompressed_bytes_count=mipmap.decompressed_bytes_count,
        is_lz4_compressed=False,
        format=MipmapFormat.RGBA8888,
    )


class TexToImageConverter:
    """TEX 转换成图片。"""

    def get_converted_format(self, tex: Tex) -> MipmapFormat:
        """预判最终输出格式（不实际转换）。"""
        if tex.is_video_texture:
            return MipmapFormat.VIDEO_MP4

        mipmap = tex.first_mipmap
        if mipmap is None:
            raise ConversionError("TEX 中没有 mipmap")

        fmt = mipmap.format
        if is_compressed_format(fmt):
            raise ConversionError("原始 mipmap 格式不能是压缩格式")
        return MipmapFormat.IMAGE_PNG if is_raw_format(fmt) else fmt

    def convert_to_image(self, tex: Tex) -> ImageResult:
        """转换 TEX 为图片字节。"""
        if tex.is_gif:
            return self._convert_to_gif(tex)

        mipmap = tex.first_mipmap
        if mipmap is None:
            raise ConversionError("TEX 中没有 mipmap")

        if tex.is_video_texture:
            return self._convert_video(mipmap)

        fmt = mipmap.format

        if is_compressed_format(fmt):
            # 压缩格式先解压成 RGBA8888 再走 raw 分支
            mipmap = _decompress_mipmap(mipmap)
            fmt = mipmap.format

        if is_raw_format(fmt):
            image = _mipmap_to_image(mipmap)

            # mipmap 尺寸可能大于实际显示尺寸，需要裁剪
            if mipmap.width != tex.header.image_width or mipmap.height != tex.header.image_height:
                image = image.crop(
                    (0, 0, tex.header.image_width, tex.header.image_height)
                )

            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return ImageResult(data=buffer.getvalue(), format=MipmapFormat.IMAGE_PNG)

        # 整图格式（PNG/JPEG/...）：原样透传
        return ImageResult(data=mipmap.data, format=fmt)

    def _convert_video(self, mipmap: TexMipmap) -> ImageResult:
        """视频纹理：校验 mp4 magic 后原样透传。"""
        if len(mipmap.data) < 12:
            raise ConversionError("mp4 数据过短，缺少 magic header")

        magic = mipmap.data[4:12].decode("ascii", errors="replace")
        valid = ("ftypisom", "ftypmsnv", "ftypmp42")
        if magic.lower() not in valid:
            raise ConversionError(f"不是预期的 mp4 magic header: {magic!r}")

        return ImageResult(data=mipmap.data, format=MipmapFormat.VIDEO_MP4)

    def _convert_to_gif(self, tex: Tex) -> ImageResult:
        """按帧表重建动画 GIF。"""
        Image = _open_pillow()

        if tex.frame_info_container is None:
            raise ConversionError("GIF 贴图缺少帧信息容器")

        container = tex.frame_info_container
        frames = container.frames
        if not frames:
            raise ConversionError("GIF 贴图没有帧")

        frame_format = tex.first_mipmap.format if tex.first_mipmap else MipmapFormat.RGBA8888
        if not is_raw_format(frame_format):
            raise ConversionError("GIF 转换目前只支持原始像素格式")

        gif_width = container.gif_width
        gif_height = container.gif_height
        if gif_width <= 0 or gif_height <= 0:
            raise ConversionError("GIF 尺寸无效")

        # 每个 image 的第一张 mipmap 作为一帧的来源
        sequence_images = []
        for image in tex.images_container.images:
            mipmap = image.first_mipmap
            if mipmap is None:
                raise ConversionError("GIF 的某个 image 没有 mipmap")
            sequence_images.append(_mipmap_to_image(mipmap))

        output_frames = []
        durations = []

        for frame_info in frames:
            if frame_info.image_id >= len(sequence_images):
                raise ConversionError(f"帧引用了不存在的 image: {frame_info.image_id}")

            # 旋转矩形：Width/Height 为 0 时回退用 HeightX/WidthY
            width = frame_info.width if frame_info.width != 0 else frame_info.height_x
            height = frame_info.height if frame_info.height != 0 else frame_info.width_y

            x = min(frame_info.x, frame_info.x + width)
            y = min(frame_info.y, frame_info.y + height)

            # 由矩形边推旋转角
            rotation_angle = -(
                math.atan2(_sign(height), _sign(width)) - math.pi / 4
            )

            source = sequence_images[frame_info.image_id]
            crop_box = (
                int(x),
                int(y),
                int(x) + int(abs(width)),
                int(y) + int(abs(height)),
            )
            frame = source.crop(crop_box)

            degrees = round(rotation_angle * 180 / math.pi)
            if degrees != 0:
                frame = frame.rotate(degrees, expand=True)

            output_frames.append(frame.convert("RGBA"))
            durations.append(int(round(frame_info.frametime * 100)))

        buffer = io.BytesIO()
        first = output_frames[0]
        first.save(
            buffer,
            format="GIF",
            save_all=True,
            append_images=output_frames[1:],
            duration=durations,
            loop=0,
            disposal=2,
        )

        return ImageResult(data=buffer.getvalue(), format=MipmapFormat.IMAGE_GIF)


def _sign(value: float) -> float:
    """符号函数，与 C# Math.Sign 行为一致（0 返回 0）。"""
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0
