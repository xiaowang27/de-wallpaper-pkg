"""核心解析层：与 Web / CLI 完全解耦。

模块划分（对齐 RePKG.Core + RePKG.Application 的分层）：
    enums.py      枚举定义
    package.py    PKG 读写
    tex.py        TEX 读写
    dxt.py        DXT1/3/5 解压
    converter.py  TEX -> PNG/GIF/MP4
    texjson.py    .tex-json 元数据生成
    extractor.py  高层解包流程编排
    paths.py      输出路径配置
"""
from .converter import ConversionError, ImageResult, TexToImageConverter
from .enums import (
    EntryType,
    FreeImageFormat,
    MipmapFormat,
    TexFlags,
    TexFormat,
    TexImageContainerVersion,
    entry_type_from_filename,
    get_file_extension,
    get_mipmap_format,
    is_compressed_format,
    is_image_format,
    is_raw_format,
)
from .extractor import (
    ExtractOptions,
    ExtractResult,
    Extractor,
    is_media_path,
    is_video_path,
    media_mime_type,
)
from .package import Package, PackageEntry, PackageReader, PackageWriter
from .paths import OUT_DIR, PROJECT_ROOT, resolve_out_dir
from .tex import (
    EnumNotValidError,
    Tex,
    TexError,
    TexFrameInfo,
    TexFrameInfoContainer,
    TexHeader,
    TexImage,
    TexImageContainer,
    TexMipmap,
    TexReader,
    TexWriter,
    UnknownMagicError,
    UnsafeTexError,
)
from .texjson import generate_info

__all__ = [
    "ConversionError",
    "ImageResult",
    "TexToImageConverter",
    "EntryType",
    "FreeImageFormat",
    "MipmapFormat",
    "TexFlags",
    "TexFormat",
    "TexImageContainerVersion",
    "entry_type_from_filename",
    "get_file_extension",
    "get_mipmap_format",
    "is_compressed_format",
    "is_image_format",
    "is_raw_format",
    "ExtractOptions",
    "ExtractResult",
    "Extractor",
    "is_media_path",
    "is_video_path",
    "media_mime_type",
    "Package",
    "PackageEntry",
    "PackageReader",
    "PackageWriter",
    "OUT_DIR",
    "PROJECT_ROOT",
    "resolve_out_dir",
    "EnumNotValidError",
    "Tex",
    "TexError",
    "TexFrameInfo",
    "TexFrameInfoContainer",
    "TexHeader",
    "TexImage",
    "TexImageContainer",
    "TexMipmap",
    "TexReader",
    "TexWriter",
    "UnknownMagicError",
    "UnsafeTexError",
    "generate_info",
]
