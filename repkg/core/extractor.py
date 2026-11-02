"""高层解包流程编排。

对应 RePKG/Command/Extract.cs 的功能，但剥离了 CLI 细节，改为可复用的 API，
供 CLI 和 Web 层共用。
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .converter import ConversionError, ImageResult, TexToImageConverter
from .enums import EntryType
from .package import Package, PackageEntry, PackageReader
from .paths import MEDIA_DIR_NAME
from .tex import Tex, TexError, TexReader
from .texjson import generate_info

#: 会被收集到 media/ 目录的媒体扩展名
MEDIA_EXTENSIONS = {
    # 图片
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tga", ".tiff", ".tif",
    ".dds", ".hdr", ".exr", ".psd", ".ico",
    # 视频
    ".mp4", ".webm", ".mov", ".avi", ".mkv",
}

#: 视频扩展名子集（用于判定 kind 与 MIME 类型）
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".avi", ".mkv"}

#: 媒体扩展名 -> MIME 类型
MEDIA_MIME_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp",
    "mp4": "video/mp4", "webm": "video/webm", "mov": "video/quicktime",
}


def is_media_path(path: str | Path) -> bool:
    """判断路径是否是媒体文件（图片或视频）。"""
    return Path(path).suffix.lower() in MEDIA_EXTENSIONS


def _link_or_copy(source: Path, target: Path) -> bool:
    """把 source 放到 target：优先硬链接（零额外占用），失败退回复制。

    硬链接让 media/ 里的文件与源文件共享同一份数据，删除源文件不影响链接，
    但用户直接编辑 media/ 里的文件会影响源文件——对解包场景可接受。
    """
    try:
        os.link(source, target)
        return True
    except (OSError, AttributeError, NotImplementedError):
        pass

    try:
        shutil.copy2(source, target)
        return True
    except OSError:
        return False


def is_video_path(path: str | Path) -> bool:
    """判断路径是否是视频文件。"""
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def media_mime_type(path: str | Path) -> str:
    """媒体文件的 MIME 类型。"""
    ext = Path(path).suffix.lstrip(".").lower()
    return MEDIA_MIME_TYPES.get(ext, "application/octet-stream")


@dataclass
class ExtractOptions:
    """解包选项。"""

    output_dir: Path
    ignore_exts: list[str] = field(default_factory=list)
    only_exts: list[str] = field(default_factory=list)
    single_dir: bool = False
    convert_tex: bool = True
    copy_project: bool = False
    use_name: bool = False
    overwrite: bool = False
    recursive: bool = True
    collect_media: bool = True   # 是否把图片/视频汇总到 media/ 目录

    def normalized_ignore(self) -> list[str]:
        return [self._normalize_ext(e) for e in self.ignore_exts]

    def normalized_only(self) -> list[str]:
        return [self._normalize_ext(e) for e in self.only_exts]

    @staticmethod
    def _normalize_ext(ext: str) -> str:
        ext = ext.strip().lower()
        if not ext:
            return ""
        return ext if ext.startswith(".") else "." + ext


@dataclass
class ExtractResult:
    """一次解包的结果汇总。"""

    files_written: list[Path] = field(default_factory=list)
    images_written: list[Path] = field(default_factory=list)
    media_files: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class Extractor:
    """解包器。

    核心依赖只有两个：PackageReader（读 PKG）和 TexReader / TexToImageConverter（处理贴图）。
    """

    def __init__(self) -> None:
        self.package_reader = PackageReader()
        self.tex_reader = TexReader()
        self.converter = TexToImageConverter()

    # ------------------------------------------------------------------
    # PKG
    # ------------------------------------------------------------------

    def extract_package(
        self,
        pkg_path: Path,
        options: ExtractOptions,
        log: Callable[[str], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> ExtractResult:
        """解包单个 PKG 文件。

        Args:
            pkg_path: PKG 路径。
            options: 解包选项。
            log: 逐条日志回调。
            progress: 进度回调 (当前序号, 总数, 当前条目路径)。
        """
        result = ExtractResult()
        emit = log or (lambda _msg: None)

        try:
            package = self.package_reader.read_file(pkg_path)
        except Exception as exc:
            result.errors.append(f"读取 PKG 失败 {pkg_path}: {exc}")
            return result

        output_dir = options.output_dir
        entries = list(self._filter_entries(package.entries, options))
        total = len(entries)

        for index, entry in enumerate(entries, start=1):
            if progress is not None:
                try:
                    progress(index, total, entry.full_path)
                except Exception:
                    pass
            self._extract_entry(entry, output_dir, options, result, emit)

        return result

    def _filter_entries(
        self, entries: Iterable[PackageEntry], options: ExtractOptions
    ) -> Iterator[PackageEntry]:
        ignore = options.normalized_ignore()
        only = options.normalized_only()

        for entry in entries:
            path_lower = entry.full_path.lower()
            if ignore and any(path_lower.endswith(ext) for ext in ignore):
                continue
            if only and not any(path_lower.endswith(ext) for ext in only):
                continue
            yield entry

    def _extract_entry(
        self,
        entry: PackageEntry,
        output_dir: Path,
        options: ExtractOptions,
        result: ExtractResult,
        emit: Callable[[str], None],
    ) -> None:
        if options.single_dir:
            stem_path = output_dir / entry.name
        else:
            stem_path = output_dir / entry.directory_path / entry.name

        file_path = stem_path.with_name(stem_path.name + entry.extension)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        if not options.overwrite and file_path.exists():
            result.skipped.append(str(file_path))
            emit(f"跳过（已存在）: {file_path}")
        else:
            file_path.write_bytes(entry.data)
            result.files_written.append(file_path)
            emit(f"解出: {entry.full_path}")

        # 包内自带的媒体文件（视频壁纸的 .mp4、图片等）也收集到 media/
        if options.collect_media and is_media_path(entry.full_path):
            self._write_media_copy(file_path, options, result, emit)

        if not options.convert_tex or entry.entry_type != EntryType.TEX:
            return

        tex = self.read_tex(entry.data, entry.full_path)
        if tex is None:
            return

        try:
            image_result = self.converter.convert_to_image(tex)
        except (ConversionError, TexError) as exc:
            result.errors.append(f"转换贴图失败 {entry.full_path}: {exc}")
            emit(f"贴图转换失败 {entry.full_path}: {exc}")
            return

        image_path = stem_path.with_name(stem_path.name + "." + image_result.extension)
        if not options.overwrite and image_path.exists():
            result.skipped.append(str(image_path))
        else:
            image_path.write_bytes(image_result.data)
            result.images_written.append(image_path)
            emit(f"转出图片: {image_path.name}")

        # 同步收集到 media/ 目录，方便用户直接找到并下载
        if options.collect_media:
            media_path = self._write_media_copy(image_path, options, result, emit)

        json_path = stem_path.with_name(stem_path.name + ".tex-json")
        try:
            json_path.write_text(generate_info(tex), encoding="utf-8")
            result.files_written.append(json_path)
        except ValueError as exc:
            result.errors.append(f"生成 tex-json 失败 {entry.full_path}: {exc}")

    def _write_media_copy(
        self,
        image_path: Path,
        options: ExtractOptions,
        result: ExtractResult,
        emit: Callable[[str], None],
    ) -> Path | None:
        """把图片/视频收集到解包目录顶层的 media/ 下。

        命名策略：<原路径用 '/' 替换为 '_'>，保证不同目录下的同名文件不互相覆盖。

        实现上优先用**硬链接**（零额外磁盘占用），失败时退回复制。
        4K 视频壁纸单个 mp4 可达数百 MB，复制一份会白白翻倍占用磁盘。
        """
        media_root = options.output_dir / MEDIA_DIR_NAME
        try:
            media_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            result.errors.append(f"创建 media 目录失败: {exc}")
            return None

        # 用相对路径拼出可读的扁平文件名
        try:
            relative = image_path.relative_to(options.output_dir)
        except ValueError:
            relative = Path(image_path.name)

        flat_name = "_".join(part for part in relative.parts if part not in (".", ""))
        target = media_root / flat_name

        if target.exists() and not options.overwrite:
            result.skipped.append(str(target))
            return target

        try:
            if not _link_or_copy(image_path, target):
                result.errors.append(f"写入 media 文件失败 {target.name}")
                return None
        except OSError as exc:
            result.errors.append(f"写入 media 文件失败 {target.name}: {exc}")
            return None

        result.media_files.append(target)
        emit(f"收集媒体: {target.name}")
        return target

    # ------------------------------------------------------------------
    # TEX
    # ------------------------------------------------------------------

    def read_tex(self, data: bytes, name: str = "") -> Tex | None:
        """解析 TEX，失败时返回 None（不抛异常）。"""
        try:
            return self.tex_reader.read_bytes(data)
        except Exception as exc:
            if name:
                print(f"读取贴图失败 {name}: {exc}")
            return None

    def convert_tex_file(self, tex_path: Path, output_dir: Path) -> ImageResult | None:
        """把单个 .tex 文件转成图片并保存。"""
        data = tex_path.read_bytes()
        tex = self.read_tex(data, str(tex_path))
        if tex is None:
            return None
        try:
            result = self.converter.convert_to_image(tex)
        except (ConversionError, TexError) as exc:
            print(f"转换失败 {tex_path}: {exc}")
            return None

        stem = output_dir / tex_path.stem
        (output_dir).mkdir(parents=True, exist_ok=True)
        stem.with_name(stem.name + "." + result.extension).write_bytes(result.data)
        try:
            stem.with_name(stem.name + ".tex-json").write_text(
                generate_info(tex), encoding="utf-8"
            )
        except ValueError:
            pass
        return result

    # ------------------------------------------------------------------
    # 目录扫描
    # ------------------------------------------------------------------

    def scan_directory(self, root: Path, recursive: bool = True) -> list[Path]:
        """递归扫描目录下的所有 .pkg 文件。"""
        if recursive:
            return sorted(root.rglob("*.pkg"))
        return sorted(root.glob("*.pkg"))

    def scan_tex_directory(self, root: Path, recursive: bool = True) -> list[Path]:
        """递归扫描目录下的所有 .tex 文件。"""
        if recursive:
            return sorted(root.rglob("*.tex"))
        return sorted(root.glob("*.tex"))

    def extract_directory(
        self,
        root: Path,
        options: ExtractOptions,
        log: Callable[[str], None] | None = None,
    ) -> ExtractResult:
        """扫描目录并解包其中所有 PKG。

        每个 PKG 输出到独立子目录（用父目录名，即 WE 的 workshop item id），
        这与原项目 -c 模式的工程组织方式一致。
        """
        emit = log or (lambda _msg: None)
        total = ExtractResult()

        packages = self.scan_directory(root, options.recursive)
        if not packages:
            total.errors.append(f"在 {root} 下没有找到 .pkg 文件")
            return total

        for pkg_path in packages:
            emit(f"\n### 解包: {pkg_path}")
            sub_options = ExtractOptions(
                output_dir=options.output_dir / pkg_path.parent.name,
                ignore_exts=options.ignore_exts,
                only_exts=options.only_exts,
                single_dir=options.single_dir,
                convert_tex=options.convert_tex,
                copy_project=options.copy_project,
                use_name=options.use_name,
                overwrite=options.overwrite,
                recursive=options.recursive,
                collect_media=options.collect_media,
            )
            result = self.extract_package(pkg_path, sub_options, emit)
            total.files_written.extend(result.files_written)
            total.images_written.extend(result.images_written)
            total.media_files.extend(result.media_files)
            total.skipped.extend(result.skipped)
            total.errors.extend(result.errors)

            if options.copy_project:
                self._copy_project_files(pkg_path, sub_options.output_dir, total, emit)

        return total

    def _copy_project_files(
        self,
        pkg_path: Path,
        output_dir: Path,
        result: ExtractResult,
        emit: Callable[[str], None],
    ) -> None:
        """复制 PKG 旁边的 project.json 和预览图。"""
        parent = pkg_path.parent
        if not parent.exists():
            return

        preview_name = None
        project_json = parent / "project.json"
        if project_json.exists():
            try:
                data = json.loads(project_json.read_text(encoding="utf-8"))
                preview_name = data.get("preview")
            except (json.JSONDecodeError, OSError):
                pass

        candidates = [project_json] if project_json.exists() else []
        if preview_name:
            preview = parent / preview_name
            if preview.exists():
                candidates.append(preview)

        for src in candidates:
            dst = output_dir / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
            result.files_written.append(dst)
            emit(f"复制工程文件: {src.name}")
