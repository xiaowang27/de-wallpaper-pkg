"""真实 Web 服务冒烟测试。

与 tests/test_web.py（TestClient）的分工：
    test_web.py   业务逻辑断言，用 TestClient，快且隔离
    web_check.py  真实 uvicorn + 真实 HTTP + multipart 流式上传的冒烟验证

保留 multipart 流式上传的验证，因为 TestClient 与真实服务器的
请求体解析路径不完全一致（真实服务器走 chunked 编码）。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

from repkg.core.package import Package, PackageEntry, PackageWriter

PORT = 8973
BASE = f"http://127.0.0.1:{PORT}"


def make_pkg_bytes() -> bytes:
    """造一个含 PNG 贴图的 PKG。"""
    buf = io.BytesIO()
    Image.new("RGBA", (32, 16), (10, 200, 100, 255)).save(buf, format="PNG")
    png = buf.getvalue()

    tex = io.BytesIO()
    tex.write(b"TEXV0005\x00")
    tex.write(b"TEXI0001\x00")
    tex.write(struct.pack("<iiiiiiI", 0, 0, 32, 16, 32, 16, 0))
    tex.write(b"TEXB0003\x00")
    tex.write(struct.pack("<i", 1))
    tex.write(struct.pack("<i", 13))
    tex.write(struct.pack("<i", 1))
    tex.write(struct.pack("<ii", 32, 16))
    tex.write(struct.pack("<i", 0))
    tex.write(struct.pack("<i", 0))
    tex.write(struct.pack("<i", len(png)))
    tex.write(png)

    package = Package(magic="PKGV0005")
    package.entries.append(
        PackageEntry(full_path="materials/bg.tex", data=tex.getvalue())
    )
    out = io.BytesIO()
    PackageWriter().write_to(out, package)
    return out.getvalue()


def main() -> int:
    import uvicorn

    from repkg.web.app import app

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()

    for _ in range(60):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=1).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.25)
    else:
        print("✗ 服务启动超时")
        return 1

    print("✓ 真实 uvicorn 服务已启动")
    ok = True
    pkg_bytes = make_pkg_bytes()

    # 1) multipart 流式上传（真实服务器路径）
    r = httpx.post(
        f"{BASE}/api/upload",
        files={"file": ("scene.pkg", pkg_bytes, "application/octet-stream")},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    pid = r.json()["project"]["id"]
    print(f"✓ multipart 上传: id={pid} entries={r.json()['project']['entry_count']}")

    # 2) 预览图可访问
    r = httpx.get(f"{BASE}/api/preview/{pid}", timeout=5)
    img = Image.open(io.BytesIO(r.content))
    print(f"✓ 预览图: {r.status_code} {img.size} {img.format}")
    ok &= r.status_code == 200 and img.size == (32, 16)

    # 3) 解包 + 媒体下载
    r = httpx.post(f"{BASE}/api/extract/{pid}", data={"output_dir": ""}, timeout=30)
    j = r.json()
    print(f"✓ 解包: ok={j['ok']} images={j['images_written']} media={j['media_count']}")
    ok &= j["ok"] and j["media_count"] == 1

    r = httpx.get(f"{BASE}{j['media'][0]['url']}", timeout=10)
    print(f"✓ 媒体下载: {r.status_code} {len(r.content)} 字节 "
          f"disposition={r.headers.get('content-disposition')}")
    ok &= r.status_code == 200 and len(r.content) > 0

    # 4) 目录扫描（递归）
    tmp = Path(tempfile.mkdtemp(prefix="repkg_scan_"))
    pkg_path = tmp / "999888777" / "scene.pkg"
    pkg_path.parent.mkdir(parents=True, exist_ok=True)
    pkg_path.write_bytes(pkg_bytes)
    (pkg_path.parent / "project.json").write_text(
        json.dumps({"title": "测试壁纸", "author": "tester", "preview": "preview.jpg"}),
        encoding="utf-8",
    )

    r = httpx.post(
        f"{BASE}/api/scan",
        data={"directory": str(tmp), "recursive": "true"},
        timeout=15,
    )
    j = r.json()
    print(f"✓ 目录扫描: count={j.get('count')} "
          f"title={j['projects'][0]['title'] if j.get('count') else '-'}")
    ok &= j.get("count") == 1

    # 5) 非法文件被拒
    r = httpx.post(
        f"{BASE}/api/upload",
        files={"file": ("bad.txt", b"hello", "text/plain")},
        timeout=5,
    )
    print(f"✓ 非法文件被拒: {r.status_code}")
    ok &= r.status_code == 400

    # 6) 真实弹窗（可选，会打扰桌面）
    if os.environ.get("REPKG_TEST_REVEAL") == "1":
        r = httpx.post(
            f"{BASE}/api/reveal", data={"path": j["projects"][0]["path"]}, timeout=15
        )
        print(f"✓ 真实弹窗: ok={r.json()['ok']}")

    shutil.rmtree(tmp, ignore_errors=True)
    server.should_exit = True
    time.sleep(0.5)

    print()
    print("=" * 50)
    print("Web 层验证通过 ✓" if ok else "Web 层验证失败 ✗")
    print("=" * 50)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
