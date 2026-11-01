"""核心层的单元测试。

不依赖外部样本文件，全部用构造出来的二进制数据做往返验证。
"""
from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest

from repkg.core.enums import (
    FreeImageFormat,
    MipmapFormat,
    TexFlags,
    TexFormat,
    TexImageContainerVersion,
    get_mipmap_format,
    is_compressed_format,
    is_image_format,
    is_raw_format,
)
from repkg.core.package import Package, PackageEntry, PackageReader, PackageWriter
from repkg.core.tex import TexReader, TexWriter


# --------------------------------------------------------------------------
# PKG
# --------------------------------------------------------------------------


def test_pkg_roundtrip_ascii():
    """PKG 读写往返（含偏移回填）。"""
    package = Package(magic="PKGV0005")
    package.entries.append(
        PackageEntry(full_path="hello_world.txt", data=b"Hello world!")
    )
    package.entries.append(PackageEntry(full_path="test.txt", data=b"Test"))

    buf = io.BytesIO()
    PackageWriter().write_to(buf, package)

    buf.seek(0)
    read = PackageReader().read_from(buf)

    assert read.magic == "PKGV0005"
    assert len(read.entries) == 2
    assert read.entries[0].full_path == "hello_world.txt"
    assert read.entries[0].data == b"Hello world!"
    assert read.entries[1].data == b"Test"


def test_pkg_offset_is_relative_to_body():
    """entry.offset 必须相对 body 起点，而非文件头。"""
    package = Package(magic="PKGV0005")
    package.entries.append(PackageEntry(full_path="a.txt", data=b"AAAA"))
    package.entries.append(PackageEntry(full_path="b.txt", data=b"BBBBBB"))

    buf = io.BytesIO()
    PackageWriter().write_to(buf, package)

    raw = buf.getvalue()
    buf.seek(0)
    read = PackageReader().read_from(buf)

    # 第二个 entry 的 offset 应为 4（第一个 entry 的长度）
    assert read.entries[1].offset == 4
    assert read.entries[1].data == b"BBBBBB"

    # body 起点 = header 结束位置
    body_start = read.header_size
    assert raw[body_start : body_start + 4] == b"AAAA"
    assert raw[body_start + 4 : body_start + 10] == b"BBBBBB"


def test_pkg_unicode_path_uses_byte_length():
    """非 ASCII 路径必须用字节数做长度前缀（C# 原版此处是 bug）。"""
    package = Package(magic="PKGV0005")
    package.entries.append(PackageEntry(full_path="场景/壁纸.tex", data=b"x" * 10))

    buf = io.BytesIO()
    PackageWriter().write_to(buf, package)

    buf.seek(0)
    read = PackageReader().read_from(buf)

    assert read.entries[0].full_path == "场景/壁纸.tex"
    assert read.entries[0].data == b"x" * 10


def test_pkg_entry_properties():
    entry = PackageEntry(full_path="dir/sub/file.tex", data=b"")
    assert entry.name == "file"
    assert entry.extension == ".tex"
    assert entry.directory_path == "dir/sub"


# --------------------------------------------------------------------------
# TEX
# --------------------------------------------------------------------------


def _build_tex_v2_rgba(
    width: int = 4,
    height: int = 4,
    mipmaps: list[tuple[int, int, bytes]] | None = None,
    lz4: bool = False,
) -> bytes:
    """构造一个 V2 容器 + RGBA8888 贴图的 TEX。"""
    if mipmaps is None:
        mipmaps = [(width, height, bytes(width * height * 4))]

    out = io.BytesIO()
    out.write(b"TEXV0005\x00")
    out.write(b"TEXI0001\x00")
    out.write(
        struct.pack(
            "<iiiiiiI",
            int(TexFormat.RGBA8888),
            int(TexFlags.NONE),
            width,
            height,
            width,
            height,
            0,
        )
    )
    # TEXB0002
    out.write(b"TEXB0002\x00")
    out.write(struct.pack("<i", 1))  # imageCount
    out.write(struct.pack("<i", len(mipmaps)))
    for mw, mh, data in mipmaps:
        out.write(struct.pack("<ii", mw, mh))
        out.write(struct.pack("<i", 1 if lz4 else 0))
        out.write(struct.pack("<i", len(data)))
        out.write(struct.pack("<i", len(data)))
        out.write(data)
    return out.getvalue()


def test_tex_read_v2_rgba():
    data = _build_tex_v2_rgba(4, 4, [(4, 4, bytes(range(16)) * 4)])
    tex = TexReader().read_bytes(data)

    assert tex.magic1 == "TEXV0005"
    assert tex.magic2 == "TEXI0001"
    assert tex.header.format == TexFormat.RGBA8888
    assert tex.header.image_width == 4
    assert tex.images_container.magic == "TEXB0002"
    assert tex.images_container.version == TexImageContainerVersion.V2
    assert len(tex.images_container.images) == 1

    mipmap = tex.first_mipmap
    assert mipmap is not None
    assert mipmap.width == 4
    assert mipmap.height == 4
    assert mipmap.format == MipmapFormat.RGBA8888
    assert mipmap.data == bytes(range(16)) * 4


def test_tex_roundtrip_byte_exact():
    """TEX 读写必须 byte-exact（对齐原项目 TexWriterTests 的做法）。"""
    original = _build_tex_v2_rgba(8, 8, [(8, 8, bytes(range(64)) * 4)])
    tex = TexReader().read_bytes(original)
    written = TexWriter().write_bytes(tex)
    assert written == original


def test_tex_roundtrip_multiple_mipmaps():
    original = _build_tex_v2_rgba(
        8, 8, [(8, 8, bytes(8 * 8 * 4)), (4, 4, bytes(4 * 4 * 4)), (2, 2, bytes(2 * 2 * 4))]
    )
    tex = TexReader().read_bytes(original)
    written = TexWriter().write_bytes(tex)
    assert written == original


def test_tex_v1_container():
    """V1 容器没有 lz4 标记和解压长度字段。"""
    out = io.BytesIO()
    out.write(b"TEXV0005\x00")
    out.write(b"TEXI0001\x00")
    out.write(
        struct.pack(
            "<iiiiiiI",
            int(TexFormat.RGBA8888),
            int(TexFlags.NONE),
            2,
            2,
            2,
            2,
            0,
        )
    )
    out.write(b"TEXB0001\x00")
    out.write(struct.pack("<i", 1))
    out.write(struct.pack("<i", 1))  # mipmapCount
    out.write(struct.pack("<ii", 2, 2))
    out.write(struct.pack("<i", 16))
    out.write(bytes(16))

    tex = TexReader().read_bytes(out.getvalue())
    assert tex.images_container.version == TexImageContainerVersion.V1
    assert tex.first_mipmap.width == 2
    assert len(tex.first_mipmap.data) == 16


def test_tex_v4_container_falls_back_to_v3():
    """非 mp4 的 V4 容器应按 V3 处理。"""
    out = io.BytesIO()
    out.write(b"TEXV0005\x00")
    out.write(b"TEXI0001\x00")
    out.write(
        struct.pack(
            "<iiiiiiI",
            int(TexFormat.RGBA8888),
            int(TexFlags.NONE),
            2,
            2,
            2,
            2,
            0,
        )
    )
    # TEXB0004: imageCount, imageFormat, isVideoMp4
    # （顺序与 C# 原版一致：magic -> imageCount -> imageFormat -> isVideoMp4）
    out.write(b"TEXB0004\x00")
    out.write(struct.pack("<i", 1))  # imageCount
    out.write(struct.pack("<i", int(FreeImageFormat.PNG)))
    out.write(struct.pack("<i", 0))  # isVideoMp4
    out.write(struct.pack("<i", 1))  # mipmapCount
    out.write(struct.pack("<ii", 2, 2))
    out.write(struct.pack("<i", 0))  # not lz4
    out.write(struct.pack("<i", 0))  # decompressed count
    out.write(struct.pack("<i", 4))
    out.write(bytes(4))

    tex = TexReader().read_bytes(out.getvalue())
    assert tex.images_container.version == TexImageContainerVersion.V3
    assert tex.images_container.image_format == FreeImageFormat.PNG


def test_tex_rejects_bad_magic():
    from repkg.core.tex import UnknownMagicError

    with pytest.raises(UnknownMagicError):
        TexReader().read_bytes(b"BADMAGIC\x00TEXI0001\x00")


def test_tex_rejects_oversized_counts():
    """畸形文件（超大 count）必须被安全限制拦截。"""
    from repkg.core.tex import UnsafeTexError

    out = io.BytesIO()
    out.write(b"TEXV0005\x00")
    out.write(b"TEXI0001\x00")
    out.write(
        struct.pack(
            "<iiiiiiI",
            int(TexFormat.RGBA8888),
            int(TexFlags.NONE),
            2,
            2,
            2,
            2,
            0,
        )
    )
    out.write(b"TEXB0002\x00")
    out.write(struct.pack("<i", 999999))  # 远超 MAX_IMAGE_COUNT

    with pytest.raises(UnsafeTexError):
        TexReader().read_bytes(out.getvalue())


# --------------------------------------------------------------------------
# GIF 帧表
# --------------------------------------------------------------------------


def _build_gif_tex(frames: list[tuple[int, float, float, float, float, float, float, float]]) -> bytes:
    """构造一个带帧表的 GIF TEX（TEXS0003，float32 坐标）。"""
    out = io.BytesIO()
    out.write(b"TEXV0005\x00")
    out.write(b"TEXI0001\x00")
    out.write(
        struct.pack(
            "<iiiiiiI",
            int(TexFormat.RGBA8888),
            int(TexFlags.IS_GIF),
            4,
            4,
            4,
            4,
            0,
        )
    )
    out.write(b"TEXB0002\x00")
    out.write(struct.pack("<i", len(frames)))
    for _ in frames:
        out.write(struct.pack("<i", 1))  # mipmapCount
        out.write(struct.pack("<ii", 4, 4))
        out.write(struct.pack("<i", 0))
        out.write(struct.pack("<i", 0))
        out.write(struct.pack("<i", 64))
        out.write(bytes(64))

    out.write(b"TEXS0003\x00")
    out.write(struct.pack("<i", len(frames)))
    out.write(struct.pack("<ii", 4, 4))  # gifWidth, gifHeight
    for image_id, frametime, x, y, w, wy, hx, h in frames:
        out.write(struct.pack("<i", image_id))
        out.write(struct.pack("<f", frametime))
        out.write(struct.pack("<ffffff", x, y, w, wy, hx, h))
    return out.getvalue()


def test_tex_gif_frame_container():
    data = _build_gif_tex([(0, 0.1, 0.0, 0.0, 4.0, 0.0, 0.0, 4.0)])
    tex = TexReader().read_bytes(data)

    assert tex.is_gif
    assert tex.frame_info_container is not None
    assert tex.frame_info_container.magic == "TEXS0003"
    assert tex.frame_info_container.gif_width == 4
    assert len(tex.frame_info_container.frames) == 1
    assert tex.frame_info_container.frames[0].frametime == pytest.approx(0.1)


# --------------------------------------------------------------------------
# 枚举 / 格式判定
# --------------------------------------------------------------------------


def test_mipmap_format_two_level_decision():
    """container 声明了 imageFormat 就用整图格式，否则按 header 像素格式。"""
    assert get_mipmap_format(FreeImageFormat.PNG, TexFormat.RGBA8888) == MipmapFormat.IMAGE_PNG
    assert get_mipmap_format(FreeImageFormat.UNKNOWN, TexFormat.RGBA8888) == MipmapFormat.RGBA8888
    assert get_mipmap_format(FreeImageFormat.UNKNOWN, TexFormat.DXT5) == MipmapFormat.COMPRESSED_DXT5
    assert get_mipmap_format(FreeImageFormat.UNKNOWN, TexFormat.DXT1) == MipmapFormat.COMPRESSED_DXT1
    assert get_mipmap_format(FreeImageFormat.UNKNOWN, TexFormat.R8) == MipmapFormat.R8
    assert get_mipmap_format(FreeImageFormat.UNKNOWN, TexFormat.RG88) == MipmapFormat.RG88


def test_format_predicates():
    assert is_image_format(MipmapFormat.IMAGE_PNG)
    assert not is_image_format(MipmapFormat.RGBA8888)
    assert is_raw_format(MipmapFormat.RGBA8888)
    assert is_raw_format(MipmapFormat.R8)
    assert is_raw_format(MipmapFormat.RG88)
    assert not is_raw_format(MipmapFormat.COMPRESSED_DXT5)
    assert is_compressed_format(MipmapFormat.COMPRESSED_DXT1)


# --------------------------------------------------------------------------
# DXT
# --------------------------------------------------------------------------


def test_dxt1_decompress_produces_rgba():
    """构造一个已知的 DXT1 块，验证解压结果。"""
    from repkg.core.dxt import decompress_dxt1

    # 红色端点 (0xF800) + 蓝色端点 (0x001F)，索引全 0 -> 应为红色
    block = struct.pack("<HH", 0xF800, 0x001F) + bytes([0, 0, 0, 0])
    out = decompress_dxt1(4, 4, block)

    assert len(out) == 4 * 4 * 4
    # 第一个像素应为红色 (255,0,0,255)
    assert out[0] == 255
    assert out[1] == 0
    assert out[2] == 0
    assert out[3] == 255


def test_dxt5_decompress_alpha():
    """DXT5 的 alpha 通道应被正确展开。"""
    from repkg.core.dxt import decompress_dxt5

    # alpha0=255, alpha1=0 -> 8bit 插值；索引字节全 0 -> alpha = alpha0 = 255
    block = bytes([255, 0]) + bytes(6) + struct.pack("<HH", 0xF800, 0x001F) + bytes(4)
    out = decompress_dxt5(4, 4, block)
    assert len(out) == 4 * 4 * 4
    assert out[3] == 255


# --------------------------------------------------------------------------
# 输出路径
# --------------------------------------------------------------------------


def test_out_dir_defaults_to_project_root():
    """默认输出目录必须是 <项目根>/out，而不是临时目录或 cwd。"""
    from repkg.core.paths import OUT_DIR, PROJECT_ROOT, resolve_out_dir

    assert OUT_DIR.name == "out"
    assert OUT_DIR.parent == PROJECT_ROOT
    # 显式参数优先
    assert resolve_out_dir("D:/somewhere") == Path("D:/somewhere").resolve()


def test_pkg_entry_paths_use_posix_separator():
    """PKG 内部路径用正斜杠，directory_path 不能返回反斜杠。"""
    entry = PackageEntry(full_path="a/b/c/file.tex", data=b"")
    assert entry.directory_path == "a/b/c"
    assert entry.name == "file"
    assert entry.extension == ".tex"

    # 混合分隔符也要正确处理
    entry2 = PackageEntry(full_path="a\\b\\c\\file.tex", data=b"")
    assert entry2.directory_path == "a/b/c"


def test_is_media_path():
    from repkg.core.extractor import is_media_path

    assert is_media_path("a/b/video.mp4")
    assert is_media_path("a/b/texture.PNG")
    assert is_media_path("x.gif")
    assert not is_media_path("scene.json")
    assert not is_media_path("materials/texture.tex")
