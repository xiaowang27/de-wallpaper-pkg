# repkg-py

Wallpaper Engine **PKG / TEX** 格式的 Python 解析与解包工具。

参考 C# 项目 [notscuffed/repkg](https://github.com/notscuffed/repkg) 的逆向成果重新实现，
**架构上做了针对 Web 化的改造**：核心解析层与 Web 层完全解耦。

> **致谢与许可**：本项目基于 [notscuffed/repkg](https://github.com/notscuffed/repkg)
> （MIT License）的格式研究成果实现，遵循 MIT 协议。
> 详见 [LICENSE](LICENSE) 与 [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt)。

---

## 快速开始

```bash
# 1. 创建虚拟环境（已在项目内准备好 .venv）
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# 2. 跑测试
./.venv/Scripts/python.exe -m pytest tests/ -v

# 3. 启动 Web 服务
./.venv/Scripts/python.exe -m repkg.cli web --reload
# 浏览器打开 http://127.0.0.1:8000
```

> **PyCharm 用户**：`File > Settings > Project > Python Interpreter` 选择项目内
> 的 `.venv\Scripts\python.exe`。
> 调试入口推荐用 `repkg/cli.py` 的 `main()`（右键 Run），或直接跑
> `tests/e2e_check.py` 看全链路。

---

## 目录结构

```
repkg-py/
├── repkg/
│   ├── core/                  ← 纯解析层，零 Web 依赖，可独立使用
│   │   ├── enums.py           枚举定义（TexFormat / TexFlags / MipmapFormat ...）
│   │   ├── package.py         PKG 读写
│   │   ├── tex.py             TEX 读写
│   │   ├── dxt.py             DXT1/3/5 解压（native + 纯 Python 兜底）
│   │   ├── converter.py       TEX → PNG / GIF / MP4
│   │   ├── texjson.py         .tex-json 元数据生成
│   │   ├── extractor.py       高层解包流程编排 + media 收集
│   │   └── paths.py           输出路径配置（<项目根>/out）
│   ├── web/
│   │   ├── app.py             FastAPI 应用
│   │   ├── explorer.py        资源管理器 / 剪贴板集成
│   │   └── static/index.html  单页前端（拖拽上传 / 目录扫描 / 预览 / 多选删除）
│   └── cli.py                 命令行入口
├── tests/
│   ├── test_core.py           核心层单元测试（19）
│   ├── test_media.py          media 收集行为测试（5）
│   ├── test_real_asset.py     真实素材 byte-exact 回归测试（6）
│   ├── test_web.py            Web 业务逻辑测试（TestClient，10）
│   ├── e2e_check.py           端到端验证（PKG→TEX→PNG）
│   └── web_check.py           真实 uvicorn + 真实 HTTP 冒烟测试
├── pyproject.toml
└── requirements.txt
```

## 测试

```bash
# 单元 + 集成测试（40 个）
./.venv/Scripts/python.exe -m pytest tests/ -v

# 端到端：解包 -> TEX -> PNG -> tex-json
./.venv/Scripts/python.exe tests/e2e_check.py

# 真实 uvicorn 服务冒烟（multipart 流式上传）
./.venv/Scripts/python.exe tests/web_check.py
```

**真实素材回归**：`tests/3276927533/` 是一个真实的 Wallpaper Engine 工程
（含中文路径 + 4K 贴图）。`test_real_asset.py` 用它做 **PKG / TEX 逐字节往返比对**——
这是唯一能证明实现与 Wallpaper Engine 兼容的验证，构造数据只能证明代码自洽。
样本缺失时该模块自动跳过。

---

## Web 功能

| 功能 | 接口 | 说明 |
|---|---|---|
| 拖拽上传 | `POST /api/upload` | 接受 `.pkg` / `.tex`，自动生成预览 |
| 目录扫描 | `POST /api/scan` | 提交服务器端目录，递归找出所有 `.pkg` |
| 工程列表 | `GET /api/projects` | 列出所有已注册工程 |
| 预览 | `GET /api/preview/{id}` | PNG / GIF / MP4 |
| 条目列表 | `GET /api/entries/{id}` | 包内条目 + 大小 + 类型 |
| 解包 | `POST /api/extract/{id}` | 解包到输出目录 |
| 批量删除 | `POST /api/projects/delete` | 多选删除，可选连带删除磁盘产物 |
| 媒体列表 | `GET /api/media/{id}` | 该工程解出的图片/视频 |
| 媒体下载 | `GET /api/media/{id}/{name}` | 带 `Content-Disposition: attachment` |
| 定位文件 | `POST /api/reveal` | 在系统文件管理器中定位并高亮 |
| 复制路径 | `POST /api/copy` | 写入系统剪贴板 |

前端是**Wallpaper 式预览**：卡片网格 + 16:9 缩略图 + 点击放大 +
GIF 自动播放 / MP4 静音循环播放。

- **多选删除**：卡片左上角复选框，支持全选；可选「同时删除解包的文件」
  （扫描来的工程只删自己的副本，**绝不触碰你 Steam 目录里的原始文件**）
- **媒体操作**：点击缩略图 → 在资源管理器中定位；`📋` 按钮 → 复制路径

**输出位置**：一律为 `<项目根>/out/<工程名>/`，其中 `media/` 汇总所有图片视频
（用**硬链接**，零额外磁盘占用 —— 4K 视频单个 mp4 可达数百 MB）。

**预览图来源优先级**：
1. PKG 旁边的 `preview.jpg` / `preview.png`（或 `project.json` 里 `preview` 字段指定的）
2. 从 PKG 内部找 `.tex` 条目，实时转成 PNG/GIF/MP4

---

## 命令行

```bash
# 解包单个 PKG
python -m repkg.cli extract E:\path\to\scene.pkg -o ./output

# 递归解包整个 workshop 目录（每个 PKG 输出到独立子目录）
python -m repkg.cli extract -r E:\steamapps\workshop\content\123 -o ./out

# 只保留 .tex 和 .json
python -m repkg.cli extract scene.pkg -e tex,json

# 排除不想解的
python -m repkg.cli extract scene.pkg -i tex,json

# TEX 转图片
python -m repkg.cli convert E:\path\to\texture.tex -o ./out

# 扫描目录里的所有 PKG
python -m repkg.cli scan E:\steamapps\workshop\content\123

# 查看 PKG 内部结构
python -m repkg.cli info E:\path\to\scene.pkg
```

---

## 格式实现要点

完整说明见 `E:\projects\repkg\docs\FORMAT-ANALYSIS.md`。这里只列最容易踩的坑：

1. **PKG entry 的 `offset` 相对 body 起点**，不是文件头
2. **LZ4 是 block 格式**（无 4 字节长度前缀），不是 frame 格式
3. **PKG 字符串长度前缀用字节数**——C# 原版 `WriteStringI32Size` 写的是字符数，
   含中文路径会损坏整个包，本实现已修正
4. **TEX magic 是 `\0` 结尾的 C 字符串**，不是长度前缀
5. **TEXB0004 字段顺序**：magic → imageCount → imageFormat → isVideoMp4
6. **非 mp4 的 V4 容器按 V3 处理**（只有 mp4 才走 V4 的 mipmap 布局）
7. **TEXS0001 用 int32 坐标，TEXS0002/0003 用 float32**
8. **RG88 的 R 是 alpha、G 是灰度**（不是两个色彩通道）
9. **GIF 的 Width/Height 为 0 时回退用 HeightX/WidthY**，旋转角由 `atan2` 推出

---

## 已知限制

| 限制 | 说明 |
|---|---|
| V4 写回未支持 | V4 mipmap 前有 3 个语义未确认的参数，无法正确写回（与原项目一致） |
| GIF 只支持原始像素格式 | DXT 压缩的 GIF 暂不支持 |
| 内存占用 | 解包时整个 PKG 读进内存，超大包会占用较多内存 |
| 路径穿越未防护 | 恶意 PKG 的 `../` 路径未做校验（与原项目一致） |

---

## 许可

本项目是对 [notscuffed/repkg](https://github.com/notscuffed/repkg)（MIT）的重新实现。
原项目包含来自 **LibSquish** 的第三方代码（见其 `THIRD-PARTY-NOTICES.txt`），
本项目的 `repkg/core/dxt.py` 中纯 Python 回退实现同样源自 LibSquish 算法，
移植到其它语言时请保留对应的许可声明。
