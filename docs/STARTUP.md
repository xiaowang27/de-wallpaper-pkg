# 启动方式

本文覆盖三种启动方式：**PyCharm（图形界面）**、**命令行**、**作为库调用**。

---

## 一、PyCharm 启动（推荐）

### 1. 打开项目

`File > Open`，选中项目根目录（即包含 `pyproject.toml` 的那一层）。

> ⚠️ **不要**选 `repkg/` 子目录打开，否则 PyCharm 识别不到项目结构。

### 2. 配置解释器

`File > Settings > Project: repkg-py > Python Interpreter`
→ 齿轮图标 → `Add Interpreter` → `Add Local Interpreter` → `Virtualenv Environment` → `Existing`

选择：

```
<项目根>\.venv\Scripts\python.exe
```

> 项目里已经带了 `.venv`，直接指过去即可，不用重新创建。
> 确认解释器列表里显示的版本是 **Python 3.10+**（本项目开发环境为 3.11）。

### 3. 运行配置

项目自带两个运行配置（在右上角下拉框里能看到）：

| 配置名 | 作用 | 等价命令 |
|---|---|---|
| **Web Server** | 启动 Web 服务 | `python repkg/cli.py web --host 127.0.0.1 --port 8000` |
| **Tests** | 跑全部测试 | `pytest tests/` |

点右上角绿色 ▶️ 旁的下拉箭头选 **Web Server**，再点 ▶️ 即可。
浏览器打开 <http://127.0.0.1:8000>。

> 如果下拉框里看不到这两个配置，说明 `.idea/runConfigurations/` 没被识别，
> 手动新建一个 **Python** 配置即可，参数见下表。

### 4. 手动新建运行配置

`Run > Edit Configurations...` → `+` → `Python`，按下面填：

| 字段 | 值 |
|---|---|
| Name | `Web Server` |
| Script path | `<项目根>\repkg\cli.py` |
| **Parameters** | `web --host 127.0.0.1 --port 8000` |
| Working directory | `<项目根>` |
| Python interpreter | `.venv\Scripts\python.exe` |

> **Parameters 是关键** —— 不填的话 `argparse` 会报
> `the following arguments are required: command`。

### 5. 调试与断点

配置好之后可以直接打断点调试：

- 在 `repkg/core/tex.py`、`repkg/core/package.py` 等核心文件里点行号左侧设断点
- 用 **Debug**（虫子图标）而不是 Run，服务会停在断点处
- `repkg/web/app.py` 里的每个接口都能下断点

### 6. 常见问题

<details>
<summary><b>Run 报 <code>ModuleNotFoundError: No module named 'repkg'</code></b></summary>

解释器选错了。检查 `Settings > Python Interpreter` 里选中的是不是
`.venv\Scripts\python.exe`，而不是系统 Python。
</details>

<details>
<summary><b>Run 报 <code>ImportError: attempted relative import with no known parent package</code></b></summary>

脚本路径选成了 `repkg/cli.py` 之外的某个文件。脚本路径必须是
`repkg/cli.py`，且 Working directory 设为项目根。

> 本项目已对直接执行做了兼容（自动把项目根加入 `sys.path`），
> 但如果 Working directory 不对，仍可能找不到 `repkg` 包。
</details>

<details>
<summary><b>提示 <code>Address already in use</code> / 端口被占用</b></summary>

8000 端口被占了。改 Parameters 里的端口，比如：

```
web --host 127.0.0.1 --port 8001
```

或者先关掉已运行的实例（注意本机可能同时开着命令行启动的服务）。
</details>

<details>
<summary><b>依赖缺失（ModuleNotFoundError: No module named 'PIL' 等）</b></summary>

在 PyCharm 的 Terminal 里执行：

```bash
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

注意要用 `.venv` 里的解释器装，别装到系统 Python 去。
</details>

<details>
<summary><b>改了代码后服务没更新</b></summary>

Web 配置没开热重载。两个办法：
1. Parameters 改成 `web --host 127.0.0.1 --port 8000 --reload`
2. 或者改完代码重启服务
</details>

---

## 二、命令行启动

### 准备环境

```bash
cd <项目根>

# 创建虚拟环境（已有 .venv 可跳过）
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### 启动 Web 服务

```bash
# 推荐：模块方式（热重载）
./.venv/Scripts/python.exe -m repkg.cli web --reload

# 或直接执行（等价，IDE 里也是这个路径）
./.venv/Scripts/python.exe repkg/cli.py web

# 指定地址和端口
./.venv/Scripts/python.exe -m repkg.cli web --host 127.0.0.1 --port 8001
```

> `python -m repkg.cli` 和 `python repkg/cli.py` 都支持，
> 前者更适合命令行（`sys.path` 由解释器保证），后者更贴近 IDE 的 Run 行为。

### 跑测试

```bash
# 全部测试
./.venv/Scripts/python.exe -m pytest tests/ -v

# 端到端验证（构造 PKG -> 解包 -> TEX -> PNG 全链路）
./.venv/Scripts/python.exe tests/e2e_check.py

# 真实 uvicorn 服务冒烟测试（会真实起服务并发 HTTP 请求）
./.venv/Scripts/python.exe tests/web_check.py

# 只跑某个文件
./.venv/Scripts/python.exe -m pytest tests/test_web.py -v
```

### 其他命令

```bash
# 解包单个 PKG
./.venv/Scripts/python.exe -m repkg.cli extract scene.pkg

# 递归解包整个 workshop 目录
./.venv/Scripts/python.exe -m repkg.cli extract -r E:\steamapps\workshop\content\123

# 只保留 .tex 和 .json
./.venv/Scripts/python.exe -m repkg.cli extract scene.pkg -e tex,json

# 排除不想解的
./.venv/Scripts/python.exe -m repkg.cli extract scene.pkg -i tex,json

# TEX 转图片
./.venv/Scripts/python.exe -m repkg.cli convert texture.tex

# 扫描目录里的所有 PKG
./.venv/Scripts/python.exe -m repkg.cli scan E:\steamapps\workshop\content\123

# 查看 PKG 内部结构
./.venv/Scripts/python.exe -m repkg.cli info scene.pkg
```

**输出位置**：默认写到 `<项目根>/out/<工程名>/`，不受当前工作目录影响。
用 `-o` 可以指定别的目录。

---

## 三、作为库调用

核心解析层零 Web 依赖，可以单独 import 用：

```python
from pathlib import Path
from repkg.core import Extractor, ExtractOptions, PackageReader

# 解包
result = Extractor().extract_package(
    Path("scene.pkg"),
    ExtractOptions(output_dir=Path("out")),
)
print(result.files_written, result.images_written, result.media_files)

# 只读包结构，不解包
pkg = PackageReader().read_file(Path("scene.pkg"))
for entry in pkg.entries:
    print(entry.full_path, entry.length)
```

分层说明：

| 层 | 位置 | 依赖 |
|---|---|---|
| 核心解析 | `repkg/core/` | 无第三方依赖（Pillow/lz4/texture2ddecoder） |
| Web | `repkg/web/` | FastAPI + uvicorn |
| CLI | `repkg/cli.py` | argparse |

---

## 四、输出目录

所有输出统一在 **`<项目根>/out/`**：

```
out/
└── <工程名>/
    ├── materials/          ← 原始解包结构（保留来源路径）
    │   └── textures/
    ├── video/              ← 包内自带的视频
    ├── scene.json
    ├── project.json
    └── media/              ← 所有图片视频的汇总（硬链接，零额外占用）
```

- 目录由 `repkg/core/paths.py` 统一管理，**向上查找 `pyproject.toml` 定位项目根**，
  不依赖当前工作目录
- 可用环境变量 `REPKG_OUT_DIR` 覆盖
- `-o` 参数优先级最高

---

## 五、常见问题排查

| 现象 | 原因 | 解决 |
|---|---|---|
| `ModuleNotFoundError: No module named 'repkg'` | 解释器选错 / 工作目录不对 | 选 `.venv\Scripts\python.exe`，工作目录设为项目根 |
| `attempted relative import with no known parent package` | 脚本路径不对 | 必须是 `repkg/cli.py` |
| `the following arguments are required: command` | Run 配置没填 Parameters | 填 `web --host 127.0.0.1 --port 8000` |
| `Address already in use` | 8000 端口被占 | 换端口，或关掉旧实例 |
| `No module named 'PIL'` | 依赖没装 | `.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| 页面能开但上传报错 | 旧代码在跑 | 重启服务（配置加 `--reload` 可自动重载） |
| 输出找不到 | 以为输出到 cwd | 实际在 `<项目根>/out/` |

---

## 相关文档

- [README](../README.md) —— 项目总览、格式实现要点、许可
- 格式解析规格 —— PKG/TEX 二进制结构的逆向分析，对应 C# 原项目
  `E:\projects\repkg\docs\FORMAT-ANALYSIS.md`
