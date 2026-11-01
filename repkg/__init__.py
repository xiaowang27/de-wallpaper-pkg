"""repkg-py —— Wallpaper Engine PKG/TEX 解析与解包工具。

分层：
    repkg.core      纯解析层（无 Web / CLI 依赖，可独立测试）
    repkg.web       Web 层（FastAPI：上传、目录扫描、预览）
    repkg.cli       命令行入口
"""

__version__ = "0.1.0"
