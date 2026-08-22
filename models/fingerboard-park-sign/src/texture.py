#!/usr/bin/env python3
"""元写真をモデルの前面に投影して、テクスチャ付き GLB を書き出す。

単一の写真から真の 3D 形状を復元することはできないので、代わりに
「写真から採寸して起こした形状」+「写真そのものの色」を組み合わせる。
やっていること:

  1. モデル前面 (x, z) 平面 → 写真ピクセル のホモグラフィを推定する
     モデルのプレート外形と文字輪郭を写真のエッジ画像に重ね、
     一致度が最大になる射影変換を Nelder-Mead で探索する
  2. その変換で写真を正面から見た状態に歪み補正し、テクスチャ画像にする
  3. 前向きの面には (x, z) から UV を貼り、それ以外の面 (小口・上面・裏面) には
     写真から拾った無地の色を貼る

使い方:
    python3 src/texture.py reference/source-photo.jpg
"""
import argparse
import os
import sys

import numpy as np
import shapely
import trimesh
from PIL import Image, ImageFilter
from scipy.optimize import minimize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import BASE_PLY, OUT, POST_FREE, build_2d, build_mesh  # noqa: E402

# 初期値: 写真中のプレート外接矩形の 4 隅 (左上→右上→右下→左下, px)
INIT_CORNERS = [30, 443, 562, 441, 566, 597, 26, 599]
TEX_W = 1024
STRIP = 24          # 前面以外の面に使う無地帯の高さ (px)


# ---- ホモグラフィ推定 -------------------------------------------------------
def ring_points(geom, z0, step=0.35):
    out = []
    for g in (geom.geoms if hasattr(geom, "geoms") else [geom]):
        for r in [g.exterior] + list(g.interiors):
            n = max(int(r.length / step), 8)
            for i in range(n):
                p = r.interpolate(i * r.length / n)
                out.append((p.x, p.y + z0))
    return np.array(out)


def homography(src, dst):
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst.reshape(4, 2)):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    return np.append(np.linalg.solve(np.array(A), np.array(b)), 1).reshape(3, 3)


def project(H, P):
    q = np.c_[P, np.ones(len(P))] @ H.T
    return q[:, :2] / q[:, 2:3]


def bilinear(img, uv):
    h, w = img.shape[:2]
    u = np.clip(uv[:, 0], 0, w - 1.001); v = np.clip(uv[:, 1], 0, h - 1.001)
    x0 = u.astype(int); y0 = v.astype(int); fx = (u - x0)[..., None]; fy = (v - y0)[..., None]
    if img.ndim == 2:
        fx, fy = fx[:, 0], fy[:, 0]
    return ((1 - fx) * (1 - fy) * img[y0, x0] + fx * (1 - fy) * img[y0, x0 + 1]
            + (1 - fx) * fy * img[y0 + 1, x0] + fx * fy * img[y0 + 1, x0 + 1])


def fit_homography(photo, shapes, z0, seed=0, restarts=14):
    """モデルの輪郭が写真のエッジに最も乗る射影変換を探す。"""
    edge = np.asarray(photo.convert("L").filter(ImageFilter.FIND_EDGES)
                      .filter(ImageFilter.GaussianBlur(2)), dtype=np.float32)
    edge /= edge.max()
    pts = np.vstack([ring_points(shapes["plaque"], z0), ring_points(shapes["text"], z0)])
    b = shapes["plaque"].bounds
    src = np.array([[b[0], b[3] + z0], [b[2], b[3] + z0], [b[2], z0], [b[0], z0]], dtype=float)

    def cost(d):
        try:
            return -float(bilinear(edge, project(homography(src, d), pts)).mean())
        except np.linalg.LinAlgError:
            return 1e6

    best = (cost(np.array(INIT_CORNERS, dtype=float)), np.array(INIT_CORNERS, dtype=float))
    rng = np.random.default_rng(seed)
    for k in range(restarts):
        x0 = best[1] if k == 0 else best[1] + rng.normal(0, 4.0, 8)
        r = minimize(cost, x0, method="Nelder-Mead",
                     options=dict(maxiter=6000, xatol=0.05, fatol=1e-6))
        if r.fun < best[0]:
            best = (r.fun, r.x)
    print(f"位置合わせスコア {-best[0]:.4f}  (初期値 {-cost(np.array(INIT_CORNERS, dtype=float)):.4f})")
    return homography(src, best[1])


# ---- テクスチャ生成 ---------------------------------------------------------
def bake(mesh, photo, H, wood, shapes, z0):
    """前面を写真から、それ以外を無地色から作ったテクスチャと UV を返す。"""
    x0, x1 = mesh.bounds[0][0], mesh.bounds[1][0]
    zmin, zmax = mesh.bounds[0][2], mesh.bounds[1][2]
    W = TEX_W
    Hf = int(round(W * (zmax - zmin) / (x1 - x0)))

    gx, gz = np.meshgrid(np.linspace(x0, x1, W), np.linspace(zmax, zmin, Hf))
    uv = project(H, np.c_[gx.ravel(), gz.ravel()])
    src = np.asarray(photo, dtype=np.float32)
    front = bilinear(src, uv).reshape(Hf, W, 3)
    # 写真の外に出た画素は無地で埋める
    out = ((uv[:, 0] < 0) | (uv[:, 0] > photo.width - 2)
           | (uv[:, 1] < 0) | (uv[:, 1] > photo.height - 2)).reshape(Hf, W)
    front[out] = wood["side"]

    # 看板の輪郭の外 (背景の作業台や石) は使わないので無地で塗り潰す。
    # 台座は看板より手前にあり同じ射影に乗らないため、ここも無地にする。
    sign = shapely.union_all([shapely.affinity.translate(shapes["plaque"], 0, z0),
                              shapely.affinity.translate(shapes["post"], 0, z0)])
    inside = shapely.contains_xy(sign, gx.ravel(), gz.ravel()).reshape(Hf, W)
    front[~inside] = wood["side"]
    front[gz <= BASE_PLY * 2 + 0.4] = wood["base"]

    tex = np.zeros((Hf + STRIP, W, 3), dtype=np.float32)
    tex[:Hf] = front
    for i, key in enumerate(("side", "top", "back")):
        tex[Hf + i * 8: Hf + (i + 1) * 8] = wood[key]
    img = Image.fromarray(np.clip(tex, 0, 255).astype(np.uint8))

    n = mesh.face_normals
    c = mesh.triangles.mean(axis=1)
    v = mesh.vertices
    U = (v[:, 0] - x0) / (x1 - x0)
    V = (zmax - v[:, 2]) / (zmax - zmin) * (Hf / (Hf + STRIP))
    face_uv = np.stack([U[mesh.faces], V[mesh.faces]], axis=-1)     # (F,3,2)

    band = {"side": 0, "top": 1, "back": 2}
    for key, sel in (("back", n[:, 1] > 0.5), ("top", n[:, 2] > 0.5),
                     ("side", (np.abs(n[:, 1]) <= 0.5) & (n[:, 2] <= 0.5))):
        y = (Hf + band[key] * 8 + 4) / (Hf + STRIP)
        face_uv[sel] = [[0.5, y]] * 3
    is_front = n[:, 1] < -0.5
    print(f"前面に写真を投影した面: {int(is_front.sum())} / {len(n)}")

    # 面ごとに UV が違うので頂点を面単位に展開する
    verts = mesh.vertices[mesh.faces].reshape(-1, 3)
    faces = np.arange(len(verts)).reshape(-1, 3)
    m = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    m.visual = trimesh.visual.TextureVisuals(
        uv=face_uv.reshape(-1, 2),
        material=trimesh.visual.material.SimpleMaterial(image=img, diffuse=[255, 255, 255, 255]))
    # UV は上下反転で参照されるため V を反転しておく
    m.visual.uv[:, 1] = 1.0 - m.visual.uv[:, 1]
    return m, img


def wood_colors(photo, H, shapes, z0):
    """小口・上面・裏面に使う無地色を写真から拾う。"""
    a = np.asarray(photo, dtype=np.float32)
    b = shapes["plaque"].bounds
    # プレート上端のすぐ上 = 板の小口 (上面)
    top_line = project(H, np.array([[x, b[3] + z0 + 0.6] for x in np.linspace(-30, 30, 60)]))
    top = np.median(bilinear(a, top_line), axis=0)
    # プレート内の明るい部分 = 素地の色
    face = project(H, np.array([[x, b[3] + z0 - 1.0] for x in np.linspace(-35, 35, 70)]))
    side = np.median(bilinear(a, face), axis=0)
    # 支柱の下半分 = 台座まわりの素地色
    post = project(H, np.array([[x, z0 - 8.0] for x in np.linspace(-2.5, 2.5, 30)]))
    base = np.median(bilinear(a, post), axis=0)
    return {"top": top, "side": side * 0.92, "back": side * 0.78, "base": base}


def alignment_overlay(photo, H, shapes, z0, path):
    """位置合わせの確認用に、モデルの輪郭を写真に重ねた画像を保存する。"""
    from PIL import ImageDraw
    im = photo.copy()
    d = ImageDraw.Draw(im)
    for geom, col in ((shapes["plaque"], (0, 255, 0)), (shapes["text"], (255, 0, 255))):
        for g in (geom.geoms if hasattr(geom, "geoms") else [geom]):
            for r in [g.exterior] + list(g.interiors):
                pts = np.array(r.coords, dtype=float)
                pts[:, 1] += z0
                d.line([tuple(v) for v in project(H, pts)], fill=col, width=2)
    im.save(path)
    return path


def main():
    ap = argparse.ArgumentParser(description="写真を投影したテクスチャ付き GLB を作る")
    ap.add_argument("photo", help="元写真のパス")
    ap.add_argument("--out", default=None, help="出力 GLB のパス")
    a = ap.parse_args()

    photo = Image.open(os.path.expanduser(a.photo)).convert("RGB")
    mesh, shapes = build_mesh()
    z0 = POST_FREE + BASE_PLY * 2

    H = fit_homography(photo, shapes, z0)
    wood = wood_colors(photo, H, shapes, z0)
    textured, img = bake(mesh, photo, H, wood, shapes, z0)
    os.makedirs(OUT, exist_ok=True)
    print("wrote", alignment_overlay(photo, H, shapes, z0, os.path.join(OUT, "alignment-check.png")))

    dst = a.out or os.path.join(OUT, "fingerboard-park-sign-textured.glb")
    textured.export(dst)
    img.save(os.path.join(OUT, "texture.png"))
    np.save(os.path.join(OUT, "homography.npy"), H)
    print("wrote", dst)
    print("wrote", os.path.join(OUT, "texture.png"), img.size)


if __name__ == "__main__":
    main()
