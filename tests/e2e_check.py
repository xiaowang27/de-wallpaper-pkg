"""端到端验证：构造真实 PKG，跑通 解包 -> TEX -> PNG 全链路。

用真实的 PNG 字节（由 Pillow 生成）作为贴图内容，验证：
    PKG -> 读取 -> entry 落盘 -> TEX 解析 -> PNG 输出 -> tex-json 生成
"""
from __future__ import annotations

import io
import json
import shutil
import struct
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from repkg.core.extractor import ExtractOptions, Extractor
from repkg.core.package import Package, PackageEntry, PackageWriter
from repkg.core.tex import TexReader


def make_png_bytes(width: int = 64, height: int = 32, color=(200, 30, 30, 255)) -> bytes:
    """生成一张真实 PNG 的字节。"""
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


def make_tex_rgba8888(png_bytes: bytes, width: int = 64, height: int = 32) -> bytes:
    """构造一个 TEXB0003 (PNG 整图) 的 TEX 文件。

    TEXB0003 会声明 imageFormat=PNG，此时贴图数据就是 PNG 文件的原始字节。
    """
    out = io.BytesIO()
    out.write(b"TEXV0005\x00")
    out.write(b"TEXI0001\x00")
    # format=RGBA8888(0), flags=0, texW/H, imageW/H, unk
    out.write(struct.pack("<iiiiiiI", 0, 0, width, height, width, height, 0))
    # TEXB0003
    out.write(b"TEXB0003\x00")
    out.write(struct.pack("<i", 1))          # imageCount
    out.write(struct.pack("<i", 13))         # imageFormat = FIF_PNG
    out.write(struct.pack("<i", 1))          # mipmapCount
    out.write(struct.pack("<ii", width, height))
    out.write(struct.pack("<i", 0))          # isLZ4Compressed
    out.write(struct.pack("<i", 0))          # decompressedBytesCount
    out.write(struct.pack("<i", len(png_bytes)))
    out.write(png_bytes)
    return out.getvalue()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="repkg_e2e_"))
    print(f"工作目录: {tmp}\n")

    # ---- 构造 PKG ----
    png_bytes = make_png_bytes()
    tex_bytes = make_tex_rgba8888(png_bytes)
    print(f"生成 PNG {len(png_bytes)} 字节, TEX {len(tex_bytes)} 字节")

    package = Package(magic="PKGV0005")
    package.entries.append(
        PackageEntry(full_path="materials/textures/bg.tex", data=tex_bytes)
    )
    package.entries.append(
        PackageEntry(full_path="scene.json", data=b'{"type":"scene","version":2}')
    )
    package.entries.append(
        PackageEntry(full_path="scripts/main.txt", data=b"hello world")
    )

    pkg_path = tmp / "123456789" / "scene.pkg"
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    PackageWriter().write_file(pkg_path, package)
    print(f"生成 PKG: {pkg_path} ({pkg_path.stat().st_size} 字节)\n")

    # ---- 目录扫描 ----
    extractor = Extractor()
    found = extractor.scan_directory(tmp)
    print(f"目录扫描结果: {[str(p.relative_to(tmp)) for p in found]}")
    assert len(found) == 1, "扫描应找到 1 个 pkg"

    # ---- 解包 ----
    out_dir = tmp / "output"
    options = ExtractOptions(output_dir=out_dir, convert_tex=True, overwrite=True)
    result = extractor.extract_package(found[0], options, log=lambda m: print("   ", m))

    print(f"\n解出文件 {len(result.files_written)} · 图片 {len(result.images_written)} · 错误 {len(result.errors)}")
    for err in result.errors:
        print(f"  [错误] {err}")

    # ---- 校验产物 ----
    ok = True

    tex_out = out_dir / "materials" / "textures" / "bg.tex"
    if not tex_out.exists():
        print("✗ 未解出 bg.tex"); ok = False
    else:
        print(f"✓ 解出 {tex_out.relative_to(out_dir)} ({tex_out.stat().st_size} 字节)")

    json_out = out_dir / "scene.json"
    if not json_out.exists():
        print("✗ 未解出 scene.json"); ok = False
    else:
        content = json_out.read_text()
        assert json.loads(content)["type"] == "scene"
        print(f"✓ 解出 {json_out.relative_to(out_dir)}")

    txt_out = out_dir / "scripts" / "main.txt"
    if not txt_out.exists():
        print("✗ 未解出 main.txt"); ok = False
    else:
        assert txt_out.read_text() == "hello world"
        print(f"✓ 解出 {txt_out.relative_to(out_dir)}")

    # PNG 输出：TEXB0003 声明 PNG 整图 -> 应当原样透传
    png_out = out_dir / "materials" / "textures" / "bg.png"
    if not png_out.exists():
        print("✗ 未生成 bg.png"); ok = False
    else:
        img = Image.open(png_out)
        print(f"✓ 生成 {png_out.relative_to(out_dir)} ({img.size[0]}x{img.size[1]} {img.format})")
        assert img.size == (64, 32), f"尺寸不对: {img.size}"
        assert img.format == "PNG"

    # tex-json
    json_meta = out_dir / "materials" / "textures" / "bg.tex-json"
    if not json_meta.exists():
        print("✗ 未生成 bg.tex-json"); ok = False
    else:
        meta = json.loads(json_meta.read_text())
        print(f"✓ 生成 bg.tex-json: {meta}")
        assert "nomip" in meta and "format" in meta

    # ---- media/ 目录收集 ----
    media_dir = out_dir / "media"
    if not media_dir.is_dir():
        print("✗ 未生成 media 目录"); ok = False
    else:
        media_files = sorted(p.name for p in media_dir.iterdir() if p.is_file())
        print(f"✓ media 目录: {media_files}")
        # 转出的 PNG 应被收集（扁平命名：materials_textures_bg.png）
        if not any(n.endswith("bg.png") for n in media_files):
            print("✗ media 目录里没有 bg.png"); ok = False
        else:
            print(f"✓ media 中包含转出的图片")
        assert len(result.media_files) == len(media_files), \
            f"media_files 数量({len(result.media_files)}) 与实际文件数({len(media_files)}) 不一致"

    # ---- 包内自带媒体也应收进 media/ ----
    pkg2 = Package(magic="PKGV0005")
    pkg2.entries.append(PackageEntry(full_path="video/bg.mp4", data=b"\x00\x00\x00\x18ftypmp42" + bytes(50)))
    pkg2.entries.append(PackageEntry(full_path="materials/bg.tex", data=tex_bytes))
    pkg2_path = tmp / "888777666" / "scene.pkg"
    pkg2_path.parent.mkdir(parents=True, exist_ok=True)
    PackageWriter().write_file(pkg2_path, pkg2)

    out2 = tmp / "output2"
    r2 = extractor.extract_package(pkg2_path, ExtractOptions(output_dir=out2, overwrite=True))
    media2 = sorted(p.name for p in (out2 / "media").iterdir() if p.is_file()) if (out2 / "media").is_dir() else []
    print(f"✓ 包内自带媒体收集: {media2}")
    if not any(n.endswith(".mp4") for n in media2):
        print("✗ 包内自带的 mp4 未被收集"); ok = False
    if not any(n.endswith("bg.png") for n in media2):
        print("✗ 转出的 png 未被收集"); ok = False

    # ---- TEX 解析一致性校验 ----
    tex = TexReader().read_bytes(tex_bytes)
    assert tex.header.image_width == 64
    assert tex.header.image_height == 32
    print(f"\n✓ TEX 解析: format={tex.header.format.name} "
          f"size={tex.header.image_width}x{tex.header.image_height} "
          f"mipmap={tex.first_mipmap.width}x{tex.first_mipmap.height} "
          f"mipmapFormat={tex.first_mipmap.format.name}")

    print()
    if ok:
        print("=" * 50)
        print("端到端验证通过 ✓")
        print("=" * 50)
    else:
        print("端到端验证失败 ✗")

    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
