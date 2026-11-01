"""枚举定义，严格对齐 RePKG.Core 的取值。

注意 FreeImageFormat 中 FIF_LBM 与 FIF_IFF 同为 5（C# 允许重复值，switch 中
FIF_LBM 先匹配）。Python 中同名等值会变成 alias，行为与 C# 一致。
"""
from enum import IntEnum, IntFlag


class TexFormat(IntEnum):
    """TEX header 中的 format 字段。"""
    RGBA8888 = 0
    DXT5 = 4
    DXT3 = 6
    DXT1 = 7
    RG88 = 8
    R8 = 9


class TexFlags(IntFlag):
    """TEX header 中的 flags 字段（位标志）。"""
    NONE = 0
    NO_INTERPOLATION = 1
    CLAMP_UVS = 2
    IS_GIF = 4
    UNK3 = 8
    UNK4 = 16
    IS_VIDEO_TEXTURE = 32
    UNK6 = 64
    UNK7 = 128


class MipmapFormat(IntEnum):
    """贴图实际像素格式。>= 1000 表示"本身就是图片文件"。"""
    INVALID = 0
    RGBA8888 = 1
    R8 = 2
    RG88 = 3
    COMPRESSED_DXT5 = 4
    COMPRESSED_DXT3 = 5
    COMPRESSED_DXT1 = 6
    VIDEO_MP4 = 7
    IMAGE_BMP = 1000
    IMAGE_ICO = 1001
    IMAGE_JPEG = 1002
    IMAGE_JNG = 1003
    IMAGE_KOALA = 1004
    IMAGE_LBM = 1005
    IMAGE_MNG = 1006
    IMAGE_PBM = 1007
    IMAGE_PBMRAW = 1008
    IMAGE_PCD = 1009
    IMAGE_PCX = 1010
    IMAGE_PGM = 1011
    IMAGE_PGMRAW = 1012
    IMAGE_PNG = 1013
    IMAGE_PPM = 1014
    IMAGE_PPMRAW = 1015
    IMAGE_RAS = 1016
    IMAGE_TARGA = 1017
    IMAGE_TIFF = 1018
    IMAGE_WBMP = 1019
    IMAGE_PSD = 1020
    IMAGE_CUT = 1021
    IMAGE_XBM = 1022
    IMAGE_XPM = 1023
    IMAGE_DDS = 1024
    IMAGE_GIF = 1025
    IMAGE_HDR = 1026
    IMAGE_FAXG3 = 1027
    IMAGE_SGI = 1028
    IMAGE_EXR = 1029
    IMAGE_J2K = 1030
    IMAGE_JP2 = 1031
    IMAGE_PFM = 1032
    IMAGE_PICT = 1033
    IMAGE_RAW = 1034


class FreeImageFormat(IntEnum):
    """FreeImage 库的 FIF_* 枚举（原样搬运）。"""
    UNKNOWN = -1
    BMP = 0
    ICO = 1
    JPEG = 2
    JNG = 3
    KOALA = 4
    LBM = 5
    IFF = 5  # alias of LBM
    MNG = 6
    PBM = 7
    PBMRAW = 8
    PCD = 9
    PCX = 10
    PGM = 11
    PGMRAW = 12
    PNG = 13
    PPM = 14
    PPMRAW = 15
    RAS = 16
    TARGA = 17
    TIFF = 18
    WBMP = 19
    PSD = 20
    CUT = 21
    XBM = 22
    XPM = 23
    DDS = 24
    GIF = 25
    HDR = 26
    FAXG3 = 27
    SGI = 28
    EXR = 29
    J2K = 30
    JP2 = 31
    PFM = 32
    PICT = 33
    RAW = 34
    MP4 = 35


class TexImageContainerVersion(IntEnum):
    """TEXB000x 容器版本。"""
    V1 = 1
    V2 = 2
    V3 = 3
    V4 = 4


class EntryType(IntEnum):
    """PKG entry 类型。"""
    BINARY = 0
    TEX = 1


# --------------------------------------------------------------------------
# FreeImageFormat -> MipmapFormat 映射
# --------------------------------------------------------------------------
FREE_IMAGE_TO_MIPMAP = {
    FreeImageFormat.BMP: MipmapFormat.IMAGE_BMP,
    FreeImageFormat.ICO: MipmapFormat.IMAGE_ICO,
    FreeImageFormat.JPEG: MipmapFormat.IMAGE_JPEG,
    FreeImageFormat.JNG: MipmapFormat.IMAGE_JNG,
    FreeImageFormat.KOALA: MipmapFormat.IMAGE_KOALA,
    FreeImageFormat.LBM: MipmapFormat.IMAGE_LBM,
    FreeImageFormat.MNG: MipmapFormat.IMAGE_MNG,
    FreeImageFormat.PBM: MipmapFormat.IMAGE_PBM,
    FreeImageFormat.PBMRAW: MipmapFormat.IMAGE_PBMRAW,
    FreeImageFormat.PCD: MipmapFormat.IMAGE_PCD,
    FreeImageFormat.PCX: MipmapFormat.IMAGE_PCX,
    FreeImageFormat.PGM: MipmapFormat.IMAGE_PGM,
    FreeImageFormat.PGMRAW: MipmapFormat.IMAGE_PGMRAW,
    FreeImageFormat.PNG: MipmapFormat.IMAGE_PNG,
    FreeImageFormat.PPM: MipmapFormat.IMAGE_PPM,
    FreeImageFormat.PPMRAW: MipmapFormat.IMAGE_PPMRAW,
    FreeImageFormat.RAS: MipmapFormat.IMAGE_RAS,
    FreeImageFormat.TARGA: MipmapFormat.IMAGE_TARGA,
    FreeImageFormat.TIFF: MipmapFormat.IMAGE_TIFF,
    FreeImageFormat.WBMP: MipmapFormat.IMAGE_WBMP,
    FreeImageFormat.PSD: MipmapFormat.IMAGE_PSD,
    FreeImageFormat.CUT: MipmapFormat.IMAGE_CUT,
    FreeImageFormat.XBM: MipmapFormat.IMAGE_XBM,
    FreeImageFormat.XPM: MipmapFormat.IMAGE_XPM,
    FreeImageFormat.DDS: MipmapFormat.IMAGE_DDS,
    FreeImageFormat.GIF: MipmapFormat.IMAGE_GIF,
    FreeImageFormat.HDR: MipmapFormat.IMAGE_HDR,
    FreeImageFormat.FAXG3: MipmapFormat.IMAGE_FAXG3,
    FreeImageFormat.SGI: MipmapFormat.IMAGE_SGI,
    FreeImageFormat.EXR: MipmapFormat.IMAGE_EXR,
    FreeImageFormat.J2K: MipmapFormat.IMAGE_J2K,
    FreeImageFormat.JP2: MipmapFormat.IMAGE_JP2,
    FreeImageFormat.PFM: MipmapFormat.IMAGE_PFM,
    FreeImageFormat.PICT: MipmapFormat.IMAGE_PICT,
    FreeImageFormat.RAW: MipmapFormat.IMAGE_RAW,
    FreeImageFormat.MP4: MipmapFormat.VIDEO_MP4,
}

# TexFormat -> MipmapFormat（container 未声明 imageFormat 时使用）
TEX_FORMAT_TO_MIPMAP = {
    TexFormat.RGBA8888: MipmapFormat.RGBA8888,
    TexFormat.DXT5: MipmapFormat.COMPRESSED_DXT5,
    TexFormat.DXT3: MipmapFormat.COMPRESSED_DXT3,
    TexFormat.DXT1: MipmapFormat.COMPRESSED_DXT1,
    TexFormat.R8: MipmapFormat.R8,
    TexFormat.RG88: MipmapFormat.RG88,
}

# MipmapFormat -> 文件扩展名
MIPMAP_EXTENSIONS = {
    MipmapFormat.IMAGE_BMP: "bmp",
    MipmapFormat.IMAGE_ICO: "ico",
    MipmapFormat.IMAGE_JPEG: "jpg",
    MipmapFormat.IMAGE_JNG: "jng",
    MipmapFormat.IMAGE_KOALA: "koa",
    MipmapFormat.IMAGE_LBM: "lbm",
    MipmapFormat.IMAGE_MNG: "mng",
    MipmapFormat.IMAGE_PBM: "pbm",
    MipmapFormat.IMAGE_PBMRAW: "pbm",
    MipmapFormat.IMAGE_PCD: "pcd",
    MipmapFormat.IMAGE_PCX: "pcx",
    MipmapFormat.IMAGE_PGM: "pgm",
    MipmapFormat.IMAGE_PGMRAW: "pgm",
    MipmapFormat.IMAGE_PNG: "png",
    MipmapFormat.IMAGE_PPM: "ppm",
    MipmapFormat.IMAGE_PPMRAW: "ppm",
    MipmapFormat.IMAGE_RAS: "ras",
    MipmapFormat.IMAGE_TARGA: "tga",
    MipmapFormat.IMAGE_TIFF: "tif",
    MipmapFormat.IMAGE_WBMP: "wbmp",
    MipmapFormat.IMAGE_PSD: "psd",
    MipmapFormat.IMAGE_CUT: "cut",
    MipmapFormat.IMAGE_XBM: "xbm",
    MipmapFormat.IMAGE_XPM: "xpm",
    MipmapFormat.IMAGE_DDS: "dds",
    MipmapFormat.IMAGE_GIF: "gif",
    MipmapFormat.IMAGE_HDR: "hdr",
    MipmapFormat.IMAGE_FAXG3: "g3",
    MipmapFormat.IMAGE_SGI: "sgi",
    MipmapFormat.IMAGE_EXR: "exr",
    MipmapFormat.IMAGE_J2K: "j2k",
    MipmapFormat.IMAGE_JP2: "jp2",
    MipmapFormat.IMAGE_PFM: "pfm",
    MipmapFormat.IMAGE_PICT: "pict",
    MipmapFormat.IMAGE_RAW: "raw",
    MipmapFormat.VIDEO_MP4: "mp4",
}


def get_mipmap_format(image_format: FreeImageFormat, tex_format: TexFormat) -> MipmapFormat:
    """两级判定：container 声明了 imageFormat 就用整图格式，否则按 header 像素格式。"""
    if image_format != FreeImageFormat.UNKNOWN:
        try:
            return FREE_IMAGE_TO_MIPMAP[image_format]
        except KeyError:
            pass
    try:
        return TEX_FORMAT_TO_MIPMAP[tex_format]
    except KeyError:
        raise ValueError(f"无法从 FreeImageFormat={image_format} / TexFormat={tex_format} 判定贴图格式")


def get_file_extension(mipmap_format: MipmapFormat) -> str:
    """MipmapFormat 对应的输出文件扩展名。"""
    try:
        return MIPMAP_EXTENSIONS[mipmap_format]
    except KeyError:
        raise ValueError(f"不支持的贴图格式: {mipmap_format}")


def is_image_format(mipmap_format: MipmapFormat) -> bool:
    """整图格式（本身就是图片文件），>= 1000。"""
    return int(mipmap_format) >= 1000


def is_raw_format(mipmap_format: MipmapFormat) -> bool:
    """原始像素格式：R8 / RG88 / RGBA8888（对应数值 1~3）。"""
    format_id = int(mipmap_format)
    return 1 <= format_id <= 3


def is_compressed_format(mipmap_format: MipmapFormat) -> bool:
    """DXT 块压缩格式。"""
    return mipmap_format in (
        MipmapFormat.COMPRESSED_DXT5,
        MipmapFormat.COMPRESSED_DXT3,
        MipmapFormat.COMPRESSED_DXT1,
    )


def entry_type_from_filename(path: str) -> EntryType:
    """按扩展名判定 entry 类型。"""
    lower = path.lower()
    if lower.endswith(".tex"):
        return EntryType.TEX
    return EntryType.BINARY
