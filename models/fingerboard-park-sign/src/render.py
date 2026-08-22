#!/usr/bin/env python3
"""生成したメッシュのプレビュー画像を書き出す (依存: numpy / PIL のみの自前ラスタライザ)。"""
import os
import sys

import numpy as np
import trimesh
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import BASE_PLY, OUT, PLY, POST_FREE, RELIEF, build_mesh  # noqa: E402

BG = np.array([0.94, 0.92, 0.885])
WOOD = np.array([0.82, 0.66, 0.44])
BURN = np.array([0.46, 0.33, 0.20])   # レーザーで彫り下げた面 (焼け色)
GROUND = np.array([0.88, 0.855, 0.815])
SHADOW = np.array([0.78, 0.755, 0.72])
LIGHT = np.array([-0.40, -0.72, 0.57]); LIGHT /= np.linalg.norm(LIGHT)
FILL = np.array([0.72, -0.45, 0.30]); FILL /= np.linalg.norm(FILL)


def look_at(eye, target, up=(0, 0, 1)):
    f = np.array(target, float) - np.array(eye, float)
    f /= np.linalg.norm(f)
    r = np.cross(f, np.array(up, float)); r /= np.linalg.norm(r)
    u = np.cross(r, f)
    M = np.eye(4)
    M[:3, :3] = np.vstack([r, u, -f])
    M[:3, 3] = -M[:3, :3] @ np.array(eye, float)
    return M


def _raster(items, M, W, H, fov, ortho):
    img = np.ones((H, W, 3)) * BG
    zbuf = np.full((H, W), np.inf)
    for V, F, cols in items:
        cam = (M[:3, :3] @ V.T).T + M[:3, 3]
        if ortho:
            k = W / ortho
            sx, sy, depth = cam[:, 0] * k + W / 2, H / 2 - cam[:, 1] * k, -cam[:, 2]
        else:
            fl = (H / 2) / np.tan(np.radians(fov) / 2)
            z = np.maximum(-cam[:, 2], 1e-6)
            sx, sy, depth = cam[:, 0] * fl / z + W / 2, H / 2 - cam[:, 1] * fl / z, z
        tri = np.stack([sx[F], sy[F]], axis=-1)
        td = depth[F]
        for i in np.argsort(-td.mean(axis=1)):
            p = tri[i]
            x0 = max(int(p[:, 0].min()), 0); x1 = min(int(p[:, 0].max()) + 2, W)
            y0 = max(int(p[:, 1].min()), 0); y1 = min(int(p[:, 1].max()) + 2, H)
            if x1 <= x0 or y1 <= y0:
                continue
            (ax, ay), (bx, by), (cx, cy) = p
            den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(den) < 1e-9:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
            w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
            w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
            w2 = 1 - w0 - w1
            m = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
            if not m.any():
                continue
            zz = w0 * td[i, 0] + w1 * td[i, 1] + w2 * td[i, 2]
            sub = zbuf[y0:y1, x0:x1]
            hit = m & (zz < sub)
            if not hit.any():
                continue
            sub[hit] = zz[hit]
            img[y0:y1, x0:x1][hit] = cols[i]
    return img


def face_colors(mesh):
    """看板前面のうち彫り下げられた面 (地の面と彫り線の底) だけ焼け色にする。"""
    n = mesh.face_normals
    shade = np.clip(0.34 + 0.60 * np.clip(n @ LIGHT, 0, 1) + 0.20 * np.clip(n @ FILL, 0, 1), 0, 1.3)
    cols = np.tile(WOOD, (len(mesh.faces), 1))
    c = mesh.triangles.mean(axis=1)
    burn_y = -(PLY + RELIEF) + 0.25          # レリーフ頂面より奥
    plaque_z = POST_FREE + BASE_PLY * 2      # プレート下端 (支柱前面を除外する)
    cols[(n[:, 1] < -0.9) & (c[:, 1] > burn_y) & (c[:, 2] > plaque_z)] = BURN
    return np.clip(cols * shade[:, None], 0, 1)


def render(mesh, eye, target, size=1000, ss=2, fov=28.0, ortho=None, ground=True):
    W = H = size * ss
    cols = face_colors(mesh)
    items = []
    if ground:
        g = trimesh.creation.box(extents=[900, 900, 2])
        g.apply_translation([0, 0, -1])
        items.append((g.vertices, g.faces, np.tile(GROUND, (len(g.faces), 1))))
        # 平面へ光線方向に落とした接地影
        v = mesh.vertices.copy()
        t = v[:, 2] / LIGHT[2]
        v[:, 0] -= LIGHT[0] * t; v[:, 1] -= LIGHT[1] * t; v[:, 2] = 0.05
        items.append((v, mesh.faces, np.tile(SHADOW, (len(mesh.faces), 1))))
    items.append((mesh.vertices, mesh.faces, cols))
    img = _raster(items, look_at(eye, target), W, H, fov, ortho)
    return Image.fromarray((img * 255).astype(np.uint8)).resize((size, size), Image.LANCZOS)


def render_textured(mesh, tex, eye, target, size=1000, ss=2, fov=28.0, ground=True):
    """UV 付きメッシュをテクスチャを貼って描画する。"""
    W = H = size * ss
    M = look_at(eye, target)
    n = mesh.face_normals
    shade = np.clip(0.55 + 0.42 * np.clip(n @ LIGHT, 0, 1) + 0.14 * np.clip(n @ FILL, 0, 1), 0, 1.25)
    T = np.asarray(tex, dtype=np.float32) / 255.0
    th, tw = T.shape[:2]
    uv = mesh.visual.uv[mesh.faces]            # (F,3,2)

    img = np.ones((H, W, 3)) * BG
    zbuf = np.full((H, W), np.inf)
    items = []
    if ground:
        g = trimesh.creation.box(extents=[900, 900, 2]); g.apply_translation([0, 0, -1])
        items.append((g, np.tile(GROUND, (len(g.faces), 1))))
        v = mesh.vertices.copy()
        t = v[:, 2] / LIGHT[2]
        v[:, 0] -= LIGHT[0] * t; v[:, 1] -= LIGHT[1] * t; v[:, 2] = 0.05
        sh = trimesh.Trimesh(vertices=v, faces=mesh.faces, process=False)
        items.append((sh, np.tile(SHADOW, (len(mesh.faces), 1))))
    for m, cols in items:
        img = _raster([(m.vertices, m.faces, cols)], M, W, H, fov, None)  # 下地
        break
    if items:
        img = _raster([(m.vertices, m.faces, c) for m, c in items], M, W, H, fov, None)

    cam = (M[:3, :3] @ mesh.vertices.T).T + M[:3, 3]
    fl = (H / 2) / np.tan(np.radians(fov) / 2)
    z = np.maximum(-cam[:, 2], 1e-6)
    sx = cam[:, 0] * fl / z + W / 2
    sy = H / 2 - cam[:, 1] * fl / z
    tri = np.stack([sx[mesh.faces], sy[mesh.faces]], axis=-1)
    td = z[mesh.faces]
    for i in np.argsort(-td.mean(axis=1)):
        p = tri[i]
        x0 = max(int(p[:, 0].min()), 0); x1 = min(int(p[:, 0].max()) + 2, W)
        y0 = max(int(p[:, 1].min()), 0); y1 = min(int(p[:, 1].max()) + 2, H)
        if x1 <= x0 or y1 <= y0:
            continue
        (ax, ay), (bx, by), (cx, cy) = p
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        w2 = 1 - w0 - w1
        m_ = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not m_.any():
            continue
        zz = w0 * td[i, 0] + w1 * td[i, 1] + w2 * td[i, 2]
        sub = zbuf[y0:y1, x0:x1]
        hit = m_ & (zz < sub)
        if not hit.any():
            continue
        sub[hit] = zz[hit]
        u = w0 * uv[i, 0, 0] + w1 * uv[i, 1, 0] + w2 * uv[i, 2, 0]
        v = w0 * uv[i, 0, 1] + w1 * uv[i, 1, 1] + w2 * uv[i, 2, 1]
        px = np.clip((u * tw).astype(int), 0, tw - 1)
        py = np.clip(((1 - v) * th).astype(int), 0, th - 1)
        img[y0:y1, x0:x1][hit] = np.clip(T[py[hit], px[hit]] * shade[i], 0, 1)

    return Image.fromarray((img * 255).astype(np.uint8)).resize((size, size), Image.LANCZOS)


def main():
    mesh, _ = build_mesh()
    os.makedirs(OUT, exist_ok=True)
    top = mesh.bounds[1][2]
    views = {
        "preview-hero.png":  dict(eye=(46, -136, 40), target=(0, 0, top * 0.62), fov=38),
        "preview-front.png": dict(eye=(9, -172, 38), target=(0, 0, top * 0.66), fov=36),
        "preview-side.png":  dict(eye=(128, -86, 46), target=(0, 0, top * 0.55), fov=34),
    }
    for name, kw in views.items():
        render(mesh, **kw).save(os.path.join(OUT, name))
        print("wrote", os.path.join(OUT, name))


if __name__ == "__main__":
    main()
