"""真实 Wallpaper Engine 素材的回归测试。

样本：tests/3276927533/ （真实 workshop 工程，含中文路径 + 4K 贴图）

这个样本的价值：它是唯一能证明格式实现正确的「标准答案」。
构造出来的样本只能证明代码自洽，真实素材才能证明实现与 Wallpaper Engine 兼容。

样本不存在时整个模块跳过（不阻塞其它测试）。
"""
from __future__ import annotations

import pathlib

import pytest

from repkg.core.package import PackageReader, PackageWriter
from repkg.core.tex import TexReader, TexWriter

#: 真实素材样本目录（相对项目根）
SAMPLE_DIR = pathlib.Path(__file__).resolve().parent.parent / "tests" / "3276927533"
SAMPLE_PKG = SAMPLE_DIR / "scene.pkg"

pytestmark = pytest.mark.skipif(
    not SAMPLE_PKG.exists(), reason="真实素材样本不存在"
)


@pytest.fixture(scope="module")
def package():
    return PackageReader().read_file(SAMPLE_PKG, read_entry_bytes=False)


@pytest.fixture(scope="module")
def package_with_data():
    return PackageReader().read_file(SAMPLE_PKG)


def test_real_pkg_header(package):
    """真实 PKG 的头部结构。"""
    assert package.magic == "PKGV0021"
    assert len(package.entries) == 10
    assert package.header_size > 0


def test_real_pkg_chinese_paths(package):
    """真实素材含中文路径，验证多字节 UTF-8 的读写。"""
    paths = [e.full_path for e in package.entries]
    chinese = [p for p in paths if any(ord(c) > 127 for c in p)]
    assert chinese, "样本应包含中文路径"
    assert "materials/310 - 电脑.tex" in paths


def test_real_pkg_byte_exact_roundtrip(package_with_data):
    """真实 PKG 读写必须逐字节一致（对齐原项目 TexWriterTests 的做法）。"""
    original = SAMPLE_PKG.read_bytes()

    import io

    buf = io.BytesIO()
    PackageWriter().write_to(buf, package_with_data)

    assert buf.getvalue() == original, "真实 PKG 往返出现字节差异"


def test_real_tex_structure(package_with_data):
    """真实 TEX 的结构：magic / 容器版本 / mipmap 数量。"""
    entry = next(e for e in package_with_data.entries if e.full_path.endswith(".tex"))
    tex = TexReader().read_bytes(entry.data)

    assert tex.magic1 == "TEXV0005"
    assert tex.magic2 == "TEXI0001"
    assert tex.images_container.magic == "TEXB0003"
    assert tex.header.image_width == 3840
    assert tex.header.image_height == 2160
    assert len(tex.images_container.images) == 1
    assert len(tex.images_container.images[0].mipmaps) == 5


def test_real_tex_byte_exact_roundtrip(package_with_data):
    """真实 TEX 读写必须逐字节一致。"""
    entry = next(e for e in package_with_data.entries if e.full_path.endswith(".tex"))

    tex = TexReader().read_bytes(entry.data)

    import io

    buf = io.BytesIO()
    TexWriter().write_to(buf, tex)

    assert buf.getvalue() == entry.data, "真实 TEX 往返出现字节差异"


def test_real_tex_first_mipmap_is_png(package_with_data):
    """首个 mipmap 是整图 PNG 格式，尺寸为 image 尺寸而非 texture 尺寸。"""
    entry = next(e for e in package_with_data.entries if e.full_path.endswith(".tex"))
    tex = TexReader().read_bytes(entry.data)

    mipmap = tex.first_mipmap
    assert mipmap is not None
    assert mipmap.width == 3840
    assert mipmap.height == 2160
    # PNG 魔数
    assert mipmap.data[:8] == b"\x89PNG\r\n\x1a\n"
