"""DXT1 / DXT3 / DXT5 块压缩解压。

输出统一为 RGBA8888。

优先使用 texture2ddecoder（Perfade Texture2DDecoder 的绑定，C 扩展，速度快）；
若未安装则回退到纯 Python 实现（算法等价，来自 LibSquish，见原项目 THIRD-PARTY-NOTICES.txt）。

函数名对应关系：
    DXT1 -> decode_bc1
    DXT3 -> decode_bc2   (BC2 = DXT3，显式 4bit alpha)
    DXT5 -> decode_bc3   (BC3 = DXT5，插值 8bit alpha)
"""
from __future__ import annotations

try:  # pragma: no cover - 取决于运行环境
    from texture2ddecoder import decode_bc1, decode_bc2, decode_bc3  # type: ignore

    _HAS_T2D = True
except ImportError:  # pragma: no cover
    _HAS_T2D = False


def has_native_decoder() -> bool:
    """是否可用原生（texture2ddecoder）解码器。"""
    return _HAS_T2D


def decompress_dxt1(width: int, height: int, data: bytes) -> bytes:
    """DXT1 -> RGBA8888。"""
    if _HAS_T2D:
        return decode_bc1(data, width, height)
    return _decompress_dxt1_py(width, height, data)


def decompress_dxt3(width: int, height: int, data: bytes) -> bytes:
    """DXT3 -> RGBA8888。"""
    if _HAS_T2D:
        return decode_bc2(data, width, height)
    return _decompress_dxt3_py(width, height, data)


def decompress_dxt5(width: int, height: int, data: bytes) -> bytes:
    """DXT5 -> RGBA8888。"""
    if _HAS_T2D:
        return decode_bc3(data, width, height)
    return _decompress_dxt5_py(width, height, data)


# --------------------------------------------------------------------------
# 纯 Python 实现（LibSquish 移植的等价算法）
# --------------------------------------------------------------------------


def _unpack_565(block: bytes, offset: int) -> tuple[int, int, int, int]:
    """从 RGB565 端点解出 8bit 的 RGBA（alpha 固定 255）。"""
    value = block[offset] | (block[offset + 1] << 8)
    r = (value >> 11) & 0x1F
    g = (value >> 5) & 0x3F
    b = value & 0x1F
    return (
        (r << 3) | (r >> 2),
        (g << 2) | (g >> 4),
        (b << 3) | (b >> 2),
        255,
    )


def _decompress_color_block(block: bytes, offset: int, is_dxt1: bool) -> list[tuple[int, int, int, int]]:
    """解压 4x4 的颜色块，返回 16 个 RGBA 像素。"""
    c0_raw = block[offset] | (block[offset + 1] << 8)
    c1_raw = block[offset + 2] | (block[offset + 3] << 8)
    c0 = _unpack_565(block, offset)
    c1 = _unpack_565(block, offset + 2)

    codes = [c0, c1, (0, 0, 0, 0), (0, 0, 0, 0)]
    # DXT1 的 1-bit alpha 模式：两个端点按 16bit 无符号比较，c0 <= c1 时
    # 第四个码为全透明。
    use_transparent = is_dxt1 and c0_raw <= c1_raw

    for i in range(3):
        a = c0[i]
        b = c1[i]
        if use_transparent:
            codes[2] = codes[2][:i] + ((a + b) // 2,) + codes[2][i + 1:]
            codes[3] = (0, 0, 0, 0)
        else:
            codes[2] = codes[2][:i] + ((2 * a + b) // 3,) + codes[2][i + 1:]
            codes[3] = codes[3][:i] + ((a + 2 * b) // 3,) + codes[3][i + 1:]

    codes[2] = codes[2][:3] + (255,)
    codes[3] = codes[3][:3] + (0 if use_transparent else 255,)

    pixels = []
    for i in range(4):
        packed = block[offset + 4 + i]
        indices = (packed & 0x3, (packed >> 2) & 0x3, (packed >> 4) & 0x3, (packed >> 6) & 0x3)
        pixels.extend(codes[idx] for idx in indices)
    return pixels


def _decompress_alpha_dxt3(block: bytes, offset: int) -> list[int]:
    """DXT3 的显式 4bit alpha，8 个字节展开成 16 个 alpha 值。"""
    alphas = []
    for i in range(8):
        quant = block[offset + i]
        lo = quant & 0x0F
        hi = quant & 0xF0
        alphas.append(lo | (lo << 4))
        alphas.append(hi | (hi >> 4))
    return alphas


def _decompress_alpha_dxt5(block: bytes, offset: int) -> list[int]:
    """DXT5 的插值 8bit alpha + 3bit 索引。"""
    alpha0 = block[offset]
    alpha1 = block[offset + 1]
    codes = [0] * 8
    codes[0] = alpha0
    codes[1] = alpha1
    if alpha0 <= alpha1:
        for i in range(1, 5):
            codes[1 + i] = ((5 - i) * alpha0 + i * alpha1) // 5
        codes[6] = 0
        codes[7] = 255
    else:
        for i in range(1, 7):
            codes[i + 1] = ((7 - i) * alpha0 + i * alpha1) // 7

    indices = []
    for i in range(2):
        value = block[offset + 2 + i * 3] | (block[offset + 3 + i * 3] << 8) | (
            block[offset + 4 + i * 3] << 16
        )
        for j in range(8):
            indices.append((value >> (3 * j)) & 0x07)

    return [codes[idx] for idx in indices]


def _blocks_to_rgba(
    width: int,
    height: int,
    data: bytes,
    bytes_per_block: int,
    color_offset: int,
    is_dxt1: bool,
    alpha_fn=None,
) -> bytes:
    """把 DXT 块展开成 RGBA8888 像素数组。"""
    rgba = bytearray(width * height * 4)
    src_pos = 0

    for y in range(0, height, 4):
        for x in range(0, width, 4):
            if src_pos + bytes_per_block > len(data):
                break

            block = data
            color_pixels = _decompress_color_block(block, src_pos + color_offset, is_dxt1)
            alphas = alpha_fn(block, src_pos) if alpha_fn else None

            for py in range(4):
                for px in range(4):
                    sx = x + px
                    sy = y + py
                    if sx >= width or sy >= height:
                        continue
                    pixel_index = py * 4 + px
                    r, g, b, a = color_pixels[pixel_index]
                    if alphas is not None:
                        a = alphas[pixel_index]
                    target = 4 * (width * sy + sx)
                    rgba[target] = r
                    rgba[target + 1] = g
                    rgba[target + 2] = b
                    rgba[target + 3] = a

            src_pos += bytes_per_block

    return bytes(rgba)


def _decompress_dxt1_py(width: int, height: int, data: bytes) -> bytes:
    return _blocks_to_rgba(width, height, data, 8, 0, True)


def _decompress_dxt3_py(width: int, height: int, data: bytes) -> bytes:
    return _blocks_to_rgba(width, height, data, 16, 8, False, _decompress_alpha_dxt3)


def _decompress_dxt5_py(width: int, height: int, data: bytes) -> bytes:
    return _blocks_to_rgba(width, height, data, 16, 8, False, _decompress_alpha_dxt5)
