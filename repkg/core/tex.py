"""TEX 贴图容器的读取与写入。

整体布局：

    nstring  "TEXV0005"
    nstring  "TEXI0001"
    Header (28 字节):
        int32 format / int32 flags / int32 textureWidth / int32 textureHeight
        int32 imageWidth / int32 imageHeight / uint32 unkInt0
    ImageContainer:
        nstring magic ("TEXB0001" ~ "TEXB0004")
        int32  imageCount
        [int32 imageFormat]    仅 TEXB0003 / TEXB0004
        [int32 isVideoMp4]     仅 TEXB0004
        image[0..imageCount-1]
    FrameInfoContainer:        仅当 flags 含 IS_GIF
        nstring magic ("TEXS0001" / "TEXS0002" / "TEXS0003")
        int32  frameCount
        [int32 gifWidth, gifHeight]   仅 TEXS0003
        frame[0..frameCount-1]

字符串有两种编码：
    nstring        : UTF-8 字节 + \\0 结尾（TEX magic）
    string_i32     : int32 长度前缀 + UTF-8 字节
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Iterator

from .enums import (
    FreeImageFormat,
    MipmapFormat,
    TexFlags,
    TexFormat,
    TexImageContainerVersion,
    get_mipmap_format,
)


class TexError(Exception):
    """TEX 解析错误基类。"""


class UnknownMagicError(TexError):
    """遇到未知的 magic 标识。"""


class UnsafeTexError(TexError):
    """文件结构超出安全限制（防畸形文件 OOM）。"""


class EnumNotValidError(TexError):
    """枚举值非法。"""


# 安全上限，对齐 RePKG.Application/Constants.cs
MAX_FRAME_COUNT = 100_000
MAX_IMAGE_COUNT = 100
MAX_MIPMAP_COUNT = 32
MAX_MIPMAP_BYTE_COUNT = 250_000_000


@dataclass
class TexMipmap:
    """一张 mipmap（同一贴图的不同分辨率层级）。"""

    width: int = 0
    height: int = 0
    data: bytes = b""
    decompressed_bytes_count: int = 0
    is_lz4_compressed: bool = False
    format: MipmapFormat = MipmapFormat.INVALID


@dataclass
class TexImage:
    """一个 image，含若干 mipmap。"""

    mipmaps: list[TexMipmap] = field(default_factory=list)

    @property
    def first_mipmap(self) -> TexMipmap | None:
        return self.mipmaps[0] if self.mipmaps else None


@dataclass
class TexHeader:
    """TEX 头部。"""

    format: TexFormat = TexFormat.RGBA8888
    flags: TexFlags = TexFlags.NONE
    texture_width: int = 0
    texture_height: int = 0
    image_width: int = 0
    image_height: int = 0
    unk_int0: int = 0


@dataclass
class TexImageContainer:
    """贴图容器，含多个 image。"""

    magic: str = ""
    image_format: FreeImageFormat = FreeImageFormat.UNKNOWN
    version: TexImageContainerVersion = TexImageContainerVersion.V1
    images: list[TexImage] = field(default_factory=list)


@dataclass
class TexFrameInfo:
    """GIF 帧信息。"""

    image_id: int = 0
    frametime: float = 0.0
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    width_y: float = 0.0
    height_x: float = 0.0
    height: float = 0.0


@dataclass
class TexFrameInfoContainer:
    """GIF 帧表。"""

    magic: str = ""
    gif_width: int = 0
    gif_height: int = 0
    frames: list[TexFrameInfo] = field(default_factory=list)


@dataclass
class Tex:
    """一个完整的 TEX 文件。"""

    magic1: str = ""
    magic2: str = ""
    header: TexHeader = field(default_factory=TexHeader)
    images_container: TexImageContainer = field(default_factory=TexImageContainer)
    frame_info_container: TexFrameInfoContainer | None = None

    @property
    def is_gif(self) -> bool:
        return bool(self.header.flags & TexFlags.IS_GIF)

    @property
    def is_video_texture(self) -> bool:
        return bool(self.header.flags & TexFlags.IS_VIDEO_TEXTURE)

    @property
    def first_image(self) -> TexImage | None:
        return self.images_container.images[0] if self.images_container.images else None

    @property
    def first_mipmap(self) -> TexMipmap | None:
        image = self.first_image
        return image.first_mipmap if image else None

    def has_flag(self, flag: TexFlags) -> bool:
        return bool(self.header.flags & flag)


# --------------------------------------------------------------------------
# 底层读写
# --------------------------------------------------------------------------


def read_nstring(stream: BinaryIO, max_length: int = -1) -> str:
    """读取以 \\0 结尾的字符串。"""
    chars = bytearray()
    while True:
        byte = stream.read(1)
        if not byte:
            raise TexError("读取 NString 时流意外结束")
        if byte == b"\x00":
            break
        chars += byte
        if 0 < max_length <= len(chars):
            break
    return chars.decode("utf-8", errors="replace")


def write_nstring(stream: BinaryIO, text: str) -> None:
    """写入以 \\0 结尾的字符串。"""
    stream.write(text.encode("utf-8"))
    stream.write(b"\x00")


def read_string_i32(stream: BinaryIO, max_length: int = -1) -> str:
    """读取 int32 长度前缀 + UTF-8 字节的字符串。"""
    size = struct.unpack("<i", stream.read(4))[0]
    if max_length > -1:
        size = min(size, max_length)
    if size < 0:
        raise TexError("字符串长度不能为负数")
    return stream.read(size).decode("utf-8", errors="replace")


def write_string_i32(stream: BinaryIO, text: str) -> None:
    """写入 int32 长度前缀 + UTF-8 字节（长度必须是字节数）。"""
    raw = text.encode("utf-8")
    stream.write(struct.pack("<i", len(raw)))
    stream.write(raw)


# --------------------------------------------------------------------------
# Reader
# --------------------------------------------------------------------------


class TexReader:
    """TEX 读取器。"""

    def read_from(
        self,
        stream: BinaryIO,
        read_mipmap_bytes: bool = True,
        decompress_mipmap_bytes: bool = True,
    ) -> Tex:
        """解析一个 TEX。"""
        tex = Tex()
        tex.magic1 = read_nstring(stream, 16)
        if tex.magic1 != "TEXV0005":
            raise UnknownMagicError(f"未知的 TEX magic1: {tex.magic1!r}")

        tex.magic2 = read_nstring(stream, 16)
        if tex.magic2 != "TEXI0001":
            raise UnknownMagicError(f"未知的 TEX magic2: {tex.magic2!r}")

        tex.header = self._read_header(stream)
        tex.images_container = self._read_image_container(stream, tex.header.format)

        if tex.is_gif:
            tex.frame_info_container = self._read_frame_info_container(stream)

        return tex

    def read_bytes(
        self,
        data: bytes,
        read_mipmap_bytes: bool = True,
        decompress_mipmap_bytes: bool = True,
    ) -> Tex:
        """从字节序列解析一个 TEX。"""
        import io

        with io.BytesIO(data) as stream:
            return self.read_from(stream, read_mipmap_bytes, decompress_mipmap_bytes)

    def _read_header(self, stream: BinaryIO) -> TexHeader:
        # 7 个字段共 28 字节：format / flags / textureWidth / textureHeight
        #                   / imageWidth / imageHeight / unkInt0
        values = struct.unpack("<iiiiiiI", stream.read(28))
        header = TexHeader(
            format=TexFormat(values[0]),
            flags=TexFlags(values[1]),
            texture_width=values[2],
            texture_height=values[3],
            image_width=values[4],
            image_height=values[5],
            unk_int0=values[6],
        )
        if header.format not in list(TexFormat):
            raise EnumNotValidError(f"非法的 TexFormat: {values[0]}")
        return header

    def _read_image_container(self, stream: BinaryIO, tex_format: TexFormat) -> TexImageContainer:
        container = TexImageContainer()
        container.magic = read_nstring(stream, 16)

        image_count = struct.unpack("<i", stream.read(4))[0]
        if image_count < 0:
            raise UnsafeTexError(f"image 数量为负数: {image_count}")
        if image_count > MAX_IMAGE_COUNT:
            raise UnsafeTexError(f"image 数量超出上限: {image_count}/{MAX_IMAGE_COUNT}")

        if container.magic in ("TEXB0001", "TEXB0002"):
            pass
        elif container.magic == "TEXB0003":
            container.image_format = FreeImageFormat(struct.unpack("<i", stream.read(4))[0])
        elif container.magic == "TEXB0004":
            image_format = FreeImageFormat(struct.unpack("<i", stream.read(4))[0])
            is_video_mp4 = struct.unpack("<i", stream.read(4))[0] == 1
            if image_format == FreeImageFormat.UNKNOWN and is_video_mp4:
                image_format = FreeImageFormat.MP4
            container.image_format = image_format
        else:
            raise UnknownMagicError(f"未知的 TEX 容器 magic: {container.magic!r}")

        container.version = TexImageContainerVersion(int(container.magic[4:]))

        # 非 mp4 的 V4 按 V3 处理（只有 mp4 才走 V4 的 mipmap 布局）
        if container.version == TexImageContainerVersion.V4 and container.image_format != FreeImageFormat.MP4:
            container.version = TexImageContainerVersion.V3

        for _ in range(image_count):
            container.images.append(self._read_image(stream, container, tex_format))

        return container

    def _read_image(self, stream: BinaryIO, container: TexImageContainer, tex_format: TexFormat) -> TexImage:
        mipmap_count = struct.unpack("<i", stream.read(4))[0]
        if mipmap_count < 0:
            raise UnsafeTexError(f"mipmap 数量为负数: {mipmap_count}")
        if mipmap_count > MAX_MIPMAP_COUNT:
            raise UnsafeTexError(f"mipmap 数量超出上限: {mipmap_count}/{MAX_MIPMAP_COUNT}")

        mipmap_format = get_mipmap_format(container.image_format, tex_format)
        image = TexImage()

        for _ in range(mipmap_count):
            mipmap = self._read_mipmap(stream, container.version)
            mipmap.format = mipmap_format
            if mipmap.is_lz4_compressed:
                mipmap.data = decompress_lz4(mipmap.data, mipmap.decompressed_bytes_count)
                mipmap.is_lz4_compressed = False
            image.mipmaps.append(mipmap)

        return image

    def _read_mipmap(self, stream: BinaryIO, version: TexImageContainerVersion) -> TexMipmap:
        mipmap = TexMipmap()

        if version == TexImageContainerVersion.V1:
            mipmap.width, mipmap.height = struct.unpack("<ii", stream.read(8))
        elif version in (TexImageContainerVersion.V2, TexImageContainerVersion.V3):
            mipmap.width, mipmap.height = struct.unpack("<ii", stream.read(8))
            mipmap.is_lz4_compressed = struct.unpack("<i", stream.read(4))[0] == 1
            mipmap.decompressed_bytes_count = struct.unpack("<i", stream.read(4))[0]
        elif version == TexImageContainerVersion.V4:
            # FIXME 原始实现中这三个参数语义未确认，读取时校验其固定值。
            param1 = struct.unpack("<i", stream.read(4))[0]
            if param1 != 1:
                raise UnsafeTexError(f"V4 mipmap 未知参数 param1: {param1}")
            param2 = struct.unpack("<i", stream.read(4))[0]
            if param2 != 2:
                raise UnsafeTexError(f"V4 mipmap 未知参数 param2: {param2}")
            read_nstring(stream)  # conditionJson，语义未确认
            param3 = struct.unpack("<i", stream.read(4))[0]
            if param3 != 1:
                raise UnsafeTexError(f"V4 mipmap 未知参数 param3: {param3}")
            mipmap.width, mipmap.height = struct.unpack("<ii", stream.read(8))
            mipmap.is_lz4_compressed = struct.unpack("<i", stream.read(4))[0] == 1
            mipmap.decompressed_bytes_count = struct.unpack("<i", stream.read(4))[0]
        else:
            raise TexError(f"不支持的容器版本: {version}")

        byte_count = struct.unpack("<i", stream.read(4))[0]
        if byte_count < 0:
            raise UnsafeTexError(f"mipmap 字节数为负数: {byte_count}")
        if byte_count > MAX_MIPMAP_BYTE_COUNT:
            raise UnsafeTexError(f"mipmap 字节数超出上限: {byte_count}/{MAX_MIPMAP_BYTE_COUNT}")

        mipmap.data = stream.read(byte_count)
        if len(mipmap.data) != byte_count:
            raise TexError(f"mipmap 数据不完整: 期望 {byte_count} 字节, 实际 {len(mipmap.data)}")

        return mipmap

    def _read_frame_info_container(self, stream: BinaryIO) -> TexFrameInfoContainer:
        container = TexFrameInfoContainer()
        container.magic = read_nstring(stream, 16)

        frame_count = struct.unpack("<i", stream.read(4))[0]
        if frame_count < 0:
            raise UnsafeTexError(f"帧数量为负数: {frame_count}")
        if frame_count > MAX_FRAME_COUNT:
            raise UnsafeTexError(f"帧数量超出上限: {frame_count}/{MAX_FRAME_COUNT}")

        if container.magic == "TEXS0003":
            container.gif_width, container.gif_height = struct.unpack("<ii", stream.read(8))
        elif container.magic not in ("TEXS0001", "TEXS0002"):
            raise UnknownMagicError(f"未知的帧信息容器 magic: {container.magic!r}")

        for _ in range(frame_count):
            frame = TexFrameInfo()
            frame.image_id = struct.unpack("<i", stream.read(4))[0]
            frame.frametime = struct.unpack("<f", stream.read(4))[0]
            if container.magic == "TEXS0001":
                (
                    frame.x,
                    frame.y,
                    frame.width,
                    frame.width_y,
                    frame.height_x,
                    frame.height,
                ) = struct.unpack("<iiiiii", stream.read(24))
            else:
                (
                    frame.x,
                    frame.y,
                    frame.width,
                    frame.width_y,
                    frame.height_x,
                    frame.height,
                ) = struct.unpack("<ffffff", stream.read(24))
            container.frames.append(frame)

        # TEXS0001/0002 不存 gif 宽高，从首帧取（供 GIF 重建使用）
        if container.gif_width == 0 or container.gif_height == 0:
            if container.frames:
                container.gif_width = int(container.frames[0].width)
                container.gif_height = int(container.frames[0].height)
            else:
                container.gif_width = 0
                container.gif_height = 0

        return container


def decompress_lz4(data: bytes, known_length: int) -> bytes:
    """LZ4 block 格式解压（无 4 字节长度前缀，非 frame 格式）。"""
    import lz4.block

    result = lz4.block.decompress(data, uncompressed_size=known_length)
    return result


# --------------------------------------------------------------------------
# Writer
# --------------------------------------------------------------------------


class TexWriter:
    """TEX 写入器。

    注意：目前只支持写入 V1 / V2 / V3 容器（与原项目一致）。
    V4 的三个未知参数语义未确认，无法正确写回。
    """

    def write_to(self, stream: BinaryIO, tex: Tex) -> None:
        if tex.magic1 != "TEXV0005":
            raise UnknownMagicError(f"未知的 TEX magic1: {tex.magic1!r}")
        if tex.magic2 != "TEXI0001":
            raise UnknownMagicError(f"未知的 TEX magic2: {tex.magic2!r}")

        write_nstring(stream, tex.magic1)
        write_nstring(stream, tex.magic2)

        self._write_header(stream, tex.header)
        self._write_image_container(stream, tex.images_container)

        if tex.is_gif and tex.frame_info_container is not None:
            self._write_frame_info_container(stream, tex.frame_info_container)

    def write_bytes(self, tex: Tex) -> bytes:
        import io

        buffer = io.BytesIO()
        self.write_to(buffer, tex)
        return buffer.getvalue()

    def _write_header(self, stream: BinaryIO, header: TexHeader) -> None:
        stream.write(
            struct.pack(
                "<iiiiiiI",
                int(header.format),
                int(header.flags),
                header.texture_width,
                header.texture_height,
                header.image_width,
                header.image_height,
                header.unk_int0,
            )
        )

    def _write_image_container(self, stream: BinaryIO, container: TexImageContainer) -> None:
        write_nstring(stream, container.magic)
        stream.write(struct.pack("<i", len(container.images)))

        if container.version in (TexImageContainerVersion.V3, TexImageContainerVersion.V4):
            stream.write(struct.pack("<i", int(container.image_format)))

        for image in container.images:
            self._write_image(stream, container.version, image)

    def _write_image(self, stream: BinaryIO, version: TexImageContainerVersion, image: TexImage) -> None:
        stream.write(struct.pack("<i", len(image.mipmaps)))

        for mipmap in image.mipmaps:
            if version == TexImageContainerVersion.V1:
                stream.write(struct.pack("<ii", mipmap.width, mipmap.height))
            else:
                stream.write(struct.pack("<ii", mipmap.width, mipmap.height))
                stream.write(struct.pack("<i", 1 if mipmap.is_lz4_compressed else 0))
                stream.write(struct.pack("<i", mipmap.decompressed_bytes_count))
            stream.write(struct.pack("<i", len(mipmap.data)))
            stream.write(mipmap.data)

    def _write_frame_info_container(self, stream: BinaryIO, container: TexFrameInfoContainer) -> None:
        write_nstring(stream, container.magic)
        stream.write(struct.pack("<i", len(container.frames)))

        if container.magic == "TEXS0003":
            stream.write(struct.pack("<ii", container.gif_width, container.gif_height))

        for frame in container.frames:
            stream.write(struct.pack("<i", frame.image_id))
            stream.write(struct.pack("<f", frame.frametime))
            if container.magic == "TEXS0001":
                stream.write(
                    struct.pack(
                        "<iiiiii",
                        int(frame.x),
                        int(frame.y),
                        int(frame.width),
                        int(frame.width_y),
                        int(frame.height_x),
                        int(frame.height),
                    )
                )
            else:
                stream.write(
                    struct.pack(
                        "<ffffff",
                        frame.x,
                        frame.y,
                        frame.width,
                        frame.width_y,
                        frame.height_x,
                        frame.height,
                    )
                )
