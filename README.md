# repkg-py

> 解压 wallpaper engine pkg 包

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

### PyCharm 启动

1. `File > Open` 选中**项目根目录**（含 `pyproject.toml` 的那层，别选 `repkg/` 子目录）
2. `Settings > Project > Python Interpreter` → Add Interpreter → Virtualenv → Existing
   → 选 `<项目根>\.venv\Scripts\python.exe`
3. 右上角运行配置选 **Web Server**（项目自带），点 ▶️

> ⚠️ Run 配置里 **Parameters 必填** `web --host 127.0.0.1 --port 8000`，
> 否则 argparse 会报 `the following arguments are required: command`。

完整的图文步骤、调试断点设置、常见问题排查见 **[docs/STARTUP.md](docs/STARTUP.md)**。

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
│   │   ├── metadata.py        Wallpaper Engine 元数据（分级 / 类型 / 标签）
│   │   ├── tasks.py           后台解包任务 + 进度跟踪
│   │   ├── history.py         扫描目录历史持久化
│   │   └── paths.py           输出路径配置（<项目根>/out）
│   ├── web/
│   │   ├── app.py             FastAPI 应用
│   │   ├── explorer.py        资源管理器 / 剪贴板集成
│   │   └── static/index.html  单页前端（拖拽上传 / 目录扫描 / 预览 / 双侧栏 / 分类筛选）
│   └── cli.py                 命令行入口
├── tests/
│   ├── test_core.py           核心层单元测试（19）
│   ├── test_cli.py            CLI 各子命令 + argparse 守卫（13）
│   ├── test_media.py          media 收集行为测试（5）
│   ├── test_real_asset.py     真实素材 byte-exact 回归测试（6）
│   ├── test_web.py            Web 业务逻辑测试（TestClient）
│   ├── test_new_features.py   解包进度 / 分类筛选 / 目录历史测试
│   ├── e2e_check.py           端到端验证（PKG→TEX→PNG）
│   ├── web_check.py           真实 uvicorn + 真实 HTTP 冒烟测试
│   └── ui_check.py            真实 Chrome 无头模式 UI 验证
├── docs/
│   └── STARTUP.md             启动方式详解（PyCharm / 命令行 / 作为库）
├── .idea/runConfigurations/    PyCharm 共享运行配置（Web Server / Tests）
├── pyproject.toml
└── requirements.txt
```

## 测试

```bash
# 单元 + 集成测试（83 个）
./.venv/Scripts/python.exe -m pytest tests/ -v

# 端到端：解包 -> TEX -> PNG -> tex-json
./.venv/Scripts/python.exe tests/e2e_check.py

# 真实 uvicorn 服务冒烟（multipart 流式上传）
./.venv/Scripts/python.exe tests/web_check.py

# 前端 UI 验证（真实 Chrome 无头模式，需先启动 Web 服务）
./.venv/Scripts/python.exe tests/ui_check.py
```

**真实素材回归**：`tests/3276927533/` 是一个真实的 Wallpaper Engine 工程
（含中文路径 + 4K 贴图）。`test_real_asset.py` 用它做 **PKG / TEX 逐字节往返比对**——
这是唯一能证明实现与 Wallpaper Engine 兼容的验证，构造数据只能证明代码自洽。
样本缺失时该模块自动跳过。

**前端为什么需要真实浏览器**：侧栏遮挡、按钮尺寸、元素重叠这类问题，
静态检查和 `TestClient` 都验证不了 —— 必须让真实渲染引擎算出实际元素矩形。
`tests/ui_check.py` 通过 CDP 驱动无头 Chrome，断言元素实际位置、按钮尺寸、
控制台无 JS 错误。开发新界面时先跑它，能省掉大量「页面白屏」的排查时间。

---

## Web 功能

| 功能 | 接口 | 说明 |
|---|---|---|
| 拖拽上传 | `POST /api/upload` | 接受 `.pkg` / `.tex`，自动生成预览 |
| 目录扫描 | `POST /api/scan` | 提交服务器端目录，递归找出所有 `.pkg` |
| 扫描历史 | `GET /api/scan/history` | 记录扫过的目录，点击回填 |
| 工程列表 | `GET /api/projects` | 列出工程，支持分类筛选 |
| 预览 | `GET /api/preview/{id}` | PNG / GIF / MP4 |
| 条目列表 | `GET /api/entries/{id}` | 包内条目 + 大小 + 类型 |
| 解包 | `POST /api/extract/{id}` | 启动解包任务，返回 `task_id` |
| 任务进度 | `GET /api/task/{id}` | 当前条目 / 总数 / 百分比 / 状态 |
| 进行中任务 | `GET /api/tasks` | 左侧栏与右侧栏的任务列表 |
| 批量删除 | `POST /api/projects/delete` | 多选删除，可选连带删除磁盘产物 |
| 媒体列表 | `GET /api/media/{id}` | 该工程解出的图片/视频 |
| 媒体下载 | `GET /api/media/{id}/{name}` | 带 `Content-Disposition: attachment` |
| 定位文件 | `POST /api/reveal` | 在系统文件管理器中定位并高亮 |
| 复制路径 | `POST /api/copy` | 写入系统剪贴板 |

前端是**Wallpaper 式预览**：卡片网格 + 16:9 缩略图 + 点击放大 +
GIF 自动播放 / MP4 静音循环播放。

- **左右双侧栏**：左侧显示**排队/进行中**的解包（进度条 + 当前条目），
  右侧显示**已完成**的解包（可直接下载 / 复制路径）。同时解包多个时，
  刚解完的东西一眼就能找到；侧栏展开时主内容自动让位，不会被遮挡
- **分页展示**：工程库每页 12 条（可调 6/12/24/48/96），页码可点击跳转；
  工程多时不用滚动到底部
- **解包按钮在卡片左侧**：竖排悬浮条，鼠标移入卡片即显示，
  不用翻到卡片底部才能找到
- **分类筛选**：按 Wallpaper Engine 的**年龄分级**（所有人 / 存疑 / 成熟）、
  **场景类型**（场景 / 壁纸 / 视频 / 网页）、**作者标签** 和标题关键字筛选，
  卡片上直接显示分级与类型徽章
- **扫描目录历史**：扫过的目录记入 `data/scan_history.json`，
  下次直接点选，不用重新敲路径
- **多选删除**：卡片左上角复选框，支持全选（只作用于当前页）；
  可选「同时删除解包的文件」（扫描来的工程只删自己的副本，
  **绝不触碰你 Steam 目录里的原始文件**）
- **媒体操作**：缩略图 → 在资源管理器中定位；**⬇ 下载** / **📋 复制** 是
  带文字的按钮（不是小图标），不容易点错
- **打开目录**：已解包的工程显示「📂 打开目录」按钮，直接跳到输出目录

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

原项目的 `DXT.cs` 头部注明其解压算法移植自 **LibSquish**
（<http://code.google.com/p/libsquish/>），原作者为 **Xalcon @ mmowned.com-Forum**。
本项目的 `repkg/core/dxt.py` 中纯 Python 回退实现沿用同一套算法，
移植到其它语言时请保留对应的许可声明。

完整的第三方许可声明见 [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt)。
