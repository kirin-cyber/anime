#!/usr/bin/env python3
"""Meshy (https://meshy.ai) の OpenAPI クライアント。

Mac のローカルでも、Claude Code のリモート実行環境でも同じように動かせるよう、
標準ライブラリのみで実装し、プロキシと CA バンドルを環境変数から拾う。

必要な環境変数:
    MESHY_API_KEY   Meshy の API キー (必須)

使い方:
    # 写真から 3D を生成 (Image to 3D)。ローカルパスでも https URL でも可
    python3 src/meshy.py image ~/Desktop/sign.jpg

    # テキストから 3D を生成 (Text to 3D)。--preset でこの看板用のプロンプトを使う
    python3 src/meshy.py text --preset
    python3 src/meshy.py text "a small wooden sign" --refine

    # 途中で切れたタスクの再取得
    python3 src/meshy.py status <task_id> --kind image

    # ネットワークに出ずにリクエスト内容だけ確認
    python3 src/meshy.py image photo.jpg --dry-run

注意:
    エンドポイントとバージョンは下の定数にまとめてある。Meshy 側の API が更新されて
    いた場合はここだけ直せば追従できる (https://docs.meshy.ai/)。
"""
import argparse
import base64
import json
import mimetypes
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.meshy.ai"
EP_IMAGE = "/openapi/v1/image-to-3d"      # Image to 3D
EP_TEXT = "/openapi/v2/text-to-3d"        # Text to 3D (preview -> refine の 2 段)
AI_MODEL = "meshy-5"

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "out", "meshy"))

DEFAULT_PROMPT = (
    "A small laser-cut plywood sign for a fingerboard skatepark. Two lines of bold squared "
    "sans-serif text reading \"FINGERBOARD\" over \"PARK\", raised in relief on a rounded "
    "plaque whose outline follows the letters. A thin engraved outline runs inside each "
    "letter and inside the plaque border; the recessed background is darkened by laser burn. "
    "The plaque sits on a narrow vertical post mounted in a small square two-layer plywood "
    "base. Natural birch plywood, matte finish, product photo on a white background."
)

TERMINAL = {"SUCCEEDED", "FAILED", "CANCELED", "EXPIRED"}


# ---- HTTP -------------------------------------------------------------------
def _ssl_context():
    """リモート実行環境の CA バンドルを拾う (Mac ではそのまま既定の証明書を使う)。"""
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        p = os.environ.get(var)
        if p and os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    p = "/root/.ccr/ca-bundle.crt"
    if os.path.exists(p):
        return ssl.create_default_context(cafile=p)
    return ssl.create_default_context()


def _opener():
    # urllib は HTTPS_PROXY / https_proxy を自動で拾う
    handlers = [urllib.request.ProxyHandler(), urllib.request.HTTPSHandler(context=_ssl_context())]
    return urllib.request.build_opener(*handlers)


def api(method, path, body=None, key=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with _opener().open(req, data, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise SystemExit(f"Meshy API エラー {e.code} {e.reason}\n  {method} {path}\n  {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(
            f"Meshy に接続できません: {e.reason}\n"
            f"  リモート実行環境の場合は、環境のネットワークポリシーで meshy.ai の許可が必要です。"
        )


def download(url, dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with _opener().open(url, timeout=300) as r, open(dest, "wb") as f:
        f.write(r.read())
    return dest


# ---- ヘルパ -----------------------------------------------------------------
def image_ref(src):
    """ローカルパスなら data URI に、http(s) ならそのまま返す。"""
    if src.startswith(("http://", "https://", "data:")):
        return src
    path = os.path.expanduser(src)
    if not os.path.exists(path):
        raise SystemExit(f"画像が見つかりません: {path}")
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    b = open(path, "rb").read()
    if len(b) > 20 * 1024 * 1024:
        raise SystemExit(f"画像が大きすぎます ({len(b)/1e6:.1f} MB)。20 MB 以下に縮小してください。")
    return f"data:{mime};base64," + base64.b64encode(b).decode()


def poll(endpoint, task_id, key, interval=5, timeout=1800):
    """完了するまでタスクを監視して、最後のレスポンスを返す。"""
    start = time.time()
    last = None
    while True:
        r = api("GET", f"{endpoint}/{task_id}", key=key)
        status, prog = r.get("status"), r.get("progress", 0)
        if (status, prog) != last:
            print(f"  [{status}] {prog}%", flush=True)
            last = (status, prog)
        if status in TERMINAL:
            return r
        if time.time() - start > timeout:
            raise SystemExit(f"タイムアウト ({timeout}s)。task_id={task_id} で status から再取得できます。")
        time.sleep(interval)


def save_result(res, task_id, label):
    """model_urls / texture_urls / thumbnail をまとめて保存する。"""
    if res.get("status") != "SUCCEEDED":
        err = (res.get("task_error") or {}).get("message") or res.get("status")
        raise SystemExit(f"生成に失敗しました: {err}")
    d = os.path.join(OUT, f"{label}-{task_id}")
    saved = []
    for ext, url in (res.get("model_urls") or {}).items():
        if url:
            saved.append(download(url, os.path.join(d, f"model.{ext}")))
    for i, url in enumerate(res.get("texture_urls") or []):
        if isinstance(url, dict):
            for k, u in url.items():
                if u:
                    saved.append(download(u, os.path.join(d, f"texture{i}-{k}.png")))
        elif url:
            saved.append(download(url, os.path.join(d, f"texture{i}.png")))
    if res.get("thumbnail_url"):
        saved.append(download(res["thumbnail_url"], os.path.join(d, "thumbnail.png")))
    json.dump(res, open(os.path.join(d, "task.json"), "w"), indent=2, ensure_ascii=False)
    print(f"\n保存先: {d}")
    for p in saved:
        print("  ", os.path.relpath(p, d))
    return d


def key_or_die():
    k = os.environ.get("MESHY_API_KEY")
    if not k:
        raise SystemExit(
            "MESHY_API_KEY が設定されていません。\n"
            "  Mac:      export MESHY_API_KEY=msy_xxxxx\n"
            "  リモート: 環境設定の環境変数に MESHY_API_KEY を追加してセッションを作り直す"
        )
    return k


# ---- サブコマンド -----------------------------------------------------------
def cmd_image(a):
    body = {
        "image_url": image_ref(a.source),
        "ai_model": AI_MODEL,
        "topology": a.topology,
        "target_polycount": a.polycount,
        "should_remesh": True,
        "should_texture": not a.no_texture,
        "enable_pbr": not a.no_pbr,
        "symmetry_mode": a.symmetry,
    }
    if a.dry_run:
        return dump(EP_IMAGE, body)
    key = key_or_die()
    print(f"Image to 3D を投入中 ({a.source}) ...")
    task_id = api("POST", EP_IMAGE, body, key)["result"]
    print(f"task_id = {task_id}")
    save_result(poll(EP_IMAGE, task_id, key, a.interval), task_id, "image")


def cmd_text(a):
    prompt = DEFAULT_PROMPT if a.preset else a.prompt
    if not prompt:
        raise SystemExit("プロンプトを指定するか --preset を付けてください。")
    body = {
        "mode": "preview",
        "prompt": prompt,
        "art_style": a.art_style,
        "ai_model": AI_MODEL,
        "topology": a.topology,
        "target_polycount": a.polycount,
        "should_remesh": True,
        "symmetry_mode": a.symmetry,
    }
    if a.dry_run:
        return dump(EP_TEXT, body)
    key = key_or_die()
    print("Text to 3D (preview) を投入中 ...")
    task_id = api("POST", EP_TEXT, body, key)["result"]
    print(f"preview task_id = {task_id}")
    res = poll(EP_TEXT, task_id, key, a.interval)
    if not a.refine:
        return save_result(res, task_id, "text-preview")
    save_result(res, task_id, "text-preview")
    print("\nrefine (テクスチャ付き) を投入中 ...")
    rid = api("POST", EP_TEXT,
              {"mode": "refine", "preview_task_id": task_id, "enable_pbr": not a.no_pbr}, key)["result"]
    print(f"refine task_id = {rid}")
    save_result(poll(EP_TEXT, rid, key, a.interval), rid, "text-refine")


def cmd_status(a):
    key = key_or_die()
    ep = EP_IMAGE if a.kind == "image" else EP_TEXT
    save_result(poll(ep, a.task_id, key, a.interval), a.task_id, a.kind)


def dump(path, body):
    shown = dict(body)
    if isinstance(shown.get("image_url"), str) and shown["image_url"].startswith("data:"):
        u = shown["image_url"]
        shown["image_url"] = f"{u[:40]}... ({len(u)} 文字の data URI)"
    print(f"POST {BASE}{path}")
    print("Authorization: Bearer $MESHY_API_KEY")
    print(json.dumps(shown, indent=2, ensure_ascii=False))


def main(argv=None):
    p = argparse.ArgumentParser(description="Meshy で 3D モデルを生成する")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--polycount", type=int, default=30000, help="目標ポリゴン数 (既定 30000)")
        sp.add_argument("--topology", choices=["triangle", "quad"], default="triangle")
        sp.add_argument("--symmetry", choices=["off", "auto", "on"], default="auto")
        sp.add_argument("--interval", type=int, default=5, help="ポーリング間隔 (秒)")
        sp.add_argument("--no-pbr", action="store_true", help="PBR テクスチャを生成しない")
        sp.add_argument("--dry-run", action="store_true", help="送信内容だけ表示して終了")

    si = sub.add_parser("image", help="画像から生成 (Image to 3D)")
    si.add_argument("source", help="ローカルパス または https URL")
    si.add_argument("--no-texture", action="store_true")
    common(si)
    si.set_defaults(func=cmd_image)

    st = sub.add_parser("text", help="テキストから生成 (Text to 3D)")
    st.add_argument("prompt", nargs="?", help="プロンプト (--preset なら省略可)")
    st.add_argument("--preset", action="store_true", help="この看板用のプロンプトを使う")
    st.add_argument("--refine", action="store_true", help="preview の後に refine まで走らせる")
    st.add_argument("--art-style", default="realistic", choices=["realistic", "sculpture"])
    common(st)
    st.set_defaults(func=cmd_text)

    ss = sub.add_parser("status", help="既存タスクの取得・ダウンロード")
    ss.add_argument("task_id")
    ss.add_argument("--kind", choices=["image", "text"], default="image")
    ss.add_argument("--interval", type=int, default=5)
    ss.set_defaults(func=cmd_status)

    a = p.parse_args(argv)
    a.func(a)


if __name__ == "__main__":
    main()
