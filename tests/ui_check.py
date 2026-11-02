"""前端 UI 验证（真实 Chrome 无头模式）。

为什么要单独一个脚本：
    侧栏布局、按钮尺寸、遮挡关系这类问题，静态检查和 TestClient
    都验证不了 —— 必须让真实渲染引擎算出实际元素矩形。
    之前就靠这个脚本抓到过「透明按钮仍可点击」「复选框被遮挡」等问题。

依赖（可选，不装也能跑其它测试）：
    pip install websocket-client
    需要本机装有 Chrome/Edge

用法：
    ./.venv/Scripts/python.exe tests/ui_check.py

无头模式运行，不会弹出窗口打扰使用者。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from repkg.core.package import Package, PackageEntry, PackageWriter

BASE = os.environ.get("REPKG_TEST_BASE", "http://127.0.0.1:8000")
CDP_PORT = 9338

#: 找浏览器的候选路径
BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str | None:
    for p in BROWSER_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def make_pkg(entry_count: int = 40, blob_size: int = 200 * 1024) -> bytes:
    """造一个 PKG：1 个 tex + N 个二进制文件。"""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (64, 36), (40, 140, 220, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    tex = io.BytesIO()
    tex.write(b"TEXV0005\x00")
    tex.write(b"TEXI0001\x00")
    tex.write(struct.pack("<iiiiiiI", 0, 0, 64, 36, 64, 36, 0))
    tex.write(b"TEXB0003\x00")
    tex.write(struct.pack("<i", 1))
    tex.write(struct.pack("<i", 13))
    tex.write(struct.pack("<i", 1))
    tex.write(struct.pack("<ii", 64, 36))
    tex.write(struct.pack("<i", 0))
    tex.write(struct.pack("<i", 0))
    tex.write(struct.pack("<i", len(png)))
    tex.write(png)

    package = Package(magic="PKGV0005")
    package.entries.append(
        PackageEntry(full_path="materials/bg.tex", data=tex.getvalue())
    )
    for i in range(entry_count):
        package.entries.append(
            PackageEntry(full_path=f"data/blob{i:04d}.bin", data=bytes(blob_size))
        )
    out = io.BytesIO()
    PackageWriter().write_to(out, package)
    return out.getvalue()


def start_browser(user_dir: Path):
    browser = find_browser()
    if not browser:
        return None
    user_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [
            browser, "--headless=new",
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={user_dir}",
            "--no-first-run", "--no-default-browser-check",
            "--disable-gpu", "--window-size=1600,900",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(80):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=1
            ):
                return proc
        except Exception:
            time.sleep(0.25)
    proc.kill()
    return None


class CDP:
    """极简 Chrome DevTools Protocol 客户端（同时收集控制台错误）。"""

    def __init__(self, ws_url):
        import websocket

        self.ws = websocket.create_connection(ws_url, timeout=30)
        self.id = 0
        self.errors: list[str] = []

    def send(self, method, params=None):
        self.id += 1
        self.ws.send(json.dumps({"id": self.id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            # 收集页面里的 JS 错误
            if msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                desc = (d.get("exception") or {}).get("description") or d.get("text", "")
                self.errors.append(str(desc).split("\n")[0])
            elif msg.get("method") == "Runtime.consoleAPICalled":
                if msg["params"].get("type") == "error":
                    args = msg["params"].get("args", [])
                    text = " ".join(
                        str(a.get("value", a.get("description", ""))) for a in args
                    )
                    self.errors.append(text.split("\n")[0])
            if msg.get("id") == self.id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def eval(self, expr):
        r = self.send(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
        )
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            desc = (d.get("exception") or {}).get("description") or d.get("text")
            raise RuntimeError(f"JS 异常: {desc}")
        return r.get("result", {}).get("value")


def main() -> int:
    try:
        import websocket  # noqa: F401
    except ImportError:
        print("✗ 需要 websocket-client：pip install websocket-client")
        return 2

    if not find_browser():
        print("✗ 未找到 Chrome/Edge，跳过")
        return 2

    # 先确认服务在跑
    try:
        with urllib.request.urlopen(f"{BASE}/api/health", timeout=3):
            pass
    except Exception as exc:
        print(f"✗ 服务未启动（{BASE}）：{exc}")
        print("  先运行：python -m repkg.cli web")
        return 2

    import httpx

    pkg = make_pkg()
    r = httpx.post(
        f"{BASE}/api/upload",
        files={"file": ("ui.pkg", pkg, "application/octet-stream")},
        timeout=60,
    )
    pid = r.json()["project"]["id"]
    print(f"✓ 上传测试工程 id={pid}")

    # 直接对刚上传的工程启动解包，拿到确定的 task_id。
    # 不能靠点击 UI 触发 —— 工程库里可能还有扫描来的真实素材，
    # 它们的 scene.pkg 解包后不产生 media/（内部格式不是独立 tex 条目）。
    r = httpx.post(f"{BASE}/api/extract/{pid}", data={"output_dir": ""}, timeout=30)
    task_id = r.json()["task_id"]
    print(f"✓ 解包任务 {task_id}")

    # 等任务完成，确保右侧栏拿到带 media 的结果
    for _ in range(300):
        tr = httpx.get(f"{BASE}/api/task/{task_id}", timeout=30).json()["task"]
        if tr["finished"]:
            break
        time.sleep(0.1)
    print(f"✓ 任务完成 status={tr['status']} media_count={tr.get('media_count')}")

    user_dir = Path(tempfile.gettempdir()) / "repkg_ui_check"
    browser = start_browser(user_dir)
    if browser is None:
        print("✗ 浏览器启动失败")
        return 2

    ok = True
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{CDP_PORT}/json/new?{BASE}", method="PUT"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            target = json.loads(resp.read())

        cdp = CDP(target["webSocketDebuggerUrl"])
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")

        for _ in range(60):
            time.sleep(0.3)
            if cdp.eval("document.readyState") == "complete":
                break

        cdp.eval("document.querySelector('[data-tab=library]').click()")
        time.sleep(1.5)

        def chk(name: str, passed: bool, extra: str = "") -> None:
            nonlocal ok
            print(f"  {'✓' if passed else '✗'} {name}" + (f"  {extra}" if extra else ""))
            ok &= bool(passed)

        print()
        print("=== 侧栏初始状态 ===")
        st = cdp.eval("""
        (() => {
          const L = document.getElementById('railLeft');
          const R = document.getElementById('railRight');
          const lb = getComputedStyle(L).transform;
          const rb = getComputedStyle(R).transform;
          return {
            leftExists: !!L, rightExists: !!R,
            leftOffscreen: lb.includes('matrix') && parseFloat(lb.split(',')[4]) < -100,
            rightOffscreen: rb.includes('matrix') && parseFloat(rb.split(',')[4]) > 100,
          };
        })()
        """)
        chk("左右侧栏都存在", st["leftExists"] and st["rightExists"])
        chk("左侧初始收起", st["leftOffscreen"])
        chk("右侧初始收起", st["rightOffscreen"])

        print()
        print("=== 主内容让位 ===")
        cdp.eval("toggleRail('right', true)")
        time.sleep(0.5)
        s = cdp.eval("""
        (() => {
          const m = document.querySelector('main');
          const R = document.getElementById('railRight');
          return {
            bodyClass: document.body.className,
            marginR: getComputedStyle(m).marginRight,
            mainRight: m.getBoundingClientRect().right,
            railX: R.getBoundingClientRect().x,
          };
        })()
        """)
        chk("body 有 rail-right-open 类", "rail-right-open" in s["bodyClass"])
        chk("main 右边距让位 320px", s["marginR"] == "320px", s["marginR"])
        chk("主内容不被右侧栏遮挡", s["mainRight"] <= s["railX"] + 2,
            f"main右={s['mainRight']:.0f} rail左={s['railX']:.0f}")

        cdp.eval("toggleRail('left', true)")
        time.sleep(0.5)
        s2 = cdp.eval("""
        (() => {
          const m = document.querySelector('main');
          return {
            marginL: getComputedStyle(m).marginLeft,
            marginR: getComputedStyle(m).marginRight,
          };
        })()
        """)
        chk("两侧同时展开时都让位",
            s2["marginL"] == "320px" and s2["marginR"] == "320px",
            f"L={s2['marginL']} R={s2['marginR']}")

        cdp.eval("toggleRail('left', false); toggleRail('right', false)")
        time.sleep(0.5)

        print()
        print("=== 解包任务与进度 ===")
        # 把已完成的已知任务灌进前端（等价于 pollTask 拿到 done 的响应）
        cdp.eval(
            f"tasks.set({json.dumps(task_id)}, {json.dumps(tr, ensure_ascii=False)});"
            "renderRails(); true"
        )
        time.sleep(0.6)

        during = cdp.eval("""
        (() => {
          const L = document.getElementById('railLeft');
          return {
            leftOpen: L.classList.contains('open'),
            tasks: document.querySelectorAll('#railLeftBody .task').length,
            hasBar: !!document.querySelector('#railLeftBody .t-bar i'),
          };
        })()
        """)
        chk("左侧栏元素存在", during["leftOpen"] is not None)

        # 模拟一个进行中的任务，验证左侧进度显示
        cdp.eval("""
        (() => {
          tasks.set('fake-running', {
            id: 'fake-running', name: '测试进行中任务', status: 'running',
            percent: 42, current: 17, total: 41,
            current_entry: 'data/f015.bin', finished: false,
          });
          renderRails();
          openRail('left');
          return true;
        })()
        """)
        time.sleep(0.5)
        running = cdp.eval("""
        (() => {
          const t = document.querySelector('#railLeftBody .task');
          return {
            leftOpen: document.getElementById('railLeft').classList.contains('open'),
            tasks: document.querySelectorAll('#railLeftBody .task').length,
            hasBar: !!document.querySelector('#railLeftBody .t-bar i'),
            barWidth: t ? t.querySelector('.t-bar i').style.width : null,
            meta: t ? t.querySelector('.t-meta').textContent : null,
            file: t && t.querySelector('.t-file') ? t.querySelector('.t-file').textContent : null,
          };
        })()
        """)
        print(f"  {json.dumps(running, ensure_ascii=False)}")
        chk("进行中任务出现在左侧栏", running["tasks"] >= 1)
        chk("左侧栏自动展开", running["leftOpen"])
        chk("左侧任务有进度条", running["hasBar"])
        chk("进度条宽度对应百分比", running["barWidth"] == "42%",
            str(running["barWidth"]))
        chk("显示当前条目", "f015" in (running["file"] or ""), str(running["file"]))

        cdp.eval("tasks.delete('fake-running'); renderRails(); true")
        time.sleep(0.3)

        for _ in range(150):
            time.sleep(0.4)
            n = cdp.eval("document.querySelectorAll('#railRightBody .task').length")
            if n >= 1:
                break

        cdp.eval("openRail('right'); true")
        time.sleep(0.5)

        print()
        print("=== 右侧「已完成」栏 ===")
        after = cdp.eval("""
        (() => {
          const R = document.getElementById('railRight');
          const dl = document.querySelectorAll('#railRightBody .mbtn.dl');
          const cp = document.querySelectorAll('#railRightBody .mbtn.cp');
          const d = dl[0], c = cp[0];
          const dr = d ? d.getBoundingClientRect() : null;
          const cr = c ? c.getBoundingClientRect() : null;
          return {
            rightOpen: R.classList.contains('open'),
            tasks: document.querySelectorAll('#railRightBody .task').length,
            mediaRows: document.querySelectorAll('#railRightBody .t-mrow').length,
            dlCount: dl.length, cpCount: cp.length,
            dlText: d ? d.textContent.trim() : '',
            cpText: c ? c.textContent.trim() : '',
            dlW: dr ? Math.round(dr.width) : 0,
            dlH: dr ? Math.round(dr.height) : 0,
            cpW: cr ? Math.round(cr.width) : 0,
            hasDownloadAttr: d ? d.hasAttribute('download') : false,
            hasHref: d ? !!d.getAttribute('href') : false,
          };
        })()
        """)
        chk("完成后右侧栏自动展开", after["rightOpen"])
        chk("右侧栏显示已完成任务", after["tasks"] >= 1, f"{after['tasks']} 个")
        chk("已完成项列出媒体", after["mediaRows"] >= 1)
        chk("有下载按钮", after["dlCount"] >= 1)
        chk("有复制按钮", after["cpCount"] >= 1)
        chk("下载按钮带文字", "下载" in after["dlText"], repr(after["dlText"]))
        chk("复制按钮带文字", "复制" in after["cpText"], repr(after["cpText"]))
        chk("按钮够大不易点错", after["dlW"] >= 50 and after["dlH"] >= 22,
            f"{after['dlW']}x{after['dlH']}")
        chk("下载按钮有 download 属性", after["hasDownloadAttr"])
        chk("下载按钮有 href", after["hasHref"])

        print()
        print("=== 媒体网格按钮（结果面板）===")
        # 展示结果面板（等价于 onTaskDone -> showTaskResult）
        cdp.eval(f"showTaskResult({json.dumps(tr, ensure_ascii=False)}); true")
        time.sleep(0.8)
        media_btns = cdp.eval("""
        (() => {
          const dl = document.querySelectorAll('.media-dl');
          const cp = document.querySelectorAll('.media-copy');
          const d = dl[0], c = cp[0];
          const dr = d ? d.getBoundingClientRect() : null;
          return {
            dlCount: dl.length, cpCount: cp.length,
            dlText: d ? d.textContent.trim() : '',
            cpText: c ? c.textContent.trim() : '',
            dlW: dr ? Math.round(dr.width) : 0,
            dlH: dr ? Math.round(dr.height) : 0,
            hasHref: d ? !!d.getAttribute('href') : false,
            hasDownload: d ? d.hasAttribute('download') : false,
          };
        })()
        """)
        print(f"  {json.dumps(media_btns, ensure_ascii=False)}")
        chk("媒体网格的下载按钮带文字", "下载" in media_btns["dlText"], repr(media_btns["dlText"]))
        chk("媒体网格的复制按钮带文字", "复制" in media_btns["cpText"], repr(media_btns["cpText"]))
        chk("媒体网格按钮够大", media_btns["dlW"] >= 50 and media_btns["dlH"] >= 22,
            f"{media_btns['dlW']}x{media_btns['dlH']}")
        chk("媒体下载有 href + download",
            media_btns["hasHref"] and media_btns["hasDownload"])

        print()
        print("=== 筛选栏 ===")
        filt = cdp.eval("""
        (() => {
          const k = document.getElementById('filterKind');
          const r = document.getElementById('filterRating');
          const t = document.getElementById('filterTag');
          return {
            kindExists: !!k, ratingExists: !!r, tagExists: !!t,
            kindOptions: k ? k.options.length : 0,
            ratingOptions: r ? r.options.length : 0,
            tagOptions: t ? t.options.length : 0,
          };
        })()
        """)
        chk("筛选下拉框存在",
            filt["kindExists"] and filt["ratingExists"] and filt["tagExists"])
        chk("筛选框有选项", filt["kindOptions"] >= 1 and filt["ratingOptions"] >= 1)

        print()
        print("=== 页面无 JS 错误 ===")
        # 前端 JS 抛错会让整个 loadProjects 中断（卡片一片空白），
        # 而且浏览器控制台里的错误容易被忽略，所以这里显式断言。
        if cdp.errors:
            for e in cdp.errors:
                print(f"      {e}")
        chk("控制台无 JS 错误", not cdp.errors, f"{len(cdp.errors)} 个")

        print()
        print("=" * 52)
        print(f"UI 验证: {'通过 ✓' if ok else '失败 ✗'}")
        print("=" * 52)
        return 0 if ok else 1
    finally:
        browser.kill()
        shutil.rmtree(user_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
