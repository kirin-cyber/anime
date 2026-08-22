#!/usr/bin/env python3
"""
写真の「FINGERBOARD PARK」サインを 3D モデル化するビルドスクリプト。

レーザー加工の合板サインを模した構成:
  - 背板  : 文字シルエットをオフセットしたプレート + 支柱
  - 前面  : 外周のフチ(リム)と文字が 1.2mm 立ち上がり、その間が彫り下げ
  - 彫り線: 文字とリムの内側に 0.5mm 深さの輪郭線(写真の二重線)
  - 台座  : 20mm 角の合板 2 枚重ね、支柱が差し込まれる

出力: STL / GLB / レーザーカット用 SVG
"""
import os
import sys

import numpy as np
import shapely
import trimesh
from shapely.geometry import Polygon, box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from glyphs import text_polygon  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "out"))
FONT = os.path.join(HERE, "fonts", "Tektur-Medium.ttf")

# ---- パラメータ (すべて mm) -------------------------------------------------
# 比率はすべて元写真からの実測値 (docs/measurements.md 参照)。
# 絶対寸法の基準は TARGET_WIDTH のみ ── 写真に寸法の基準物が写っていないため、
# プレート全幅 80mm を仮定している。実物に合わせるならここだけ変えればよい。
LINE1, LINE2 = "FINGERBOARD", "PARK"
TARGET_WIDTH = 80.0   # 看板プレートの全幅 (仮定値)
CAP = 12.0            # 1 行目の大文字高 (TARGET_WIDTH に合わせて後で再スケール)
CAP2_SCALE = 1.048    # 2 行目 (PARK) の字高比 ── 写真では 1 行目よりわずかに大きい
WIDTH_SCALE = 0.674   # 書体の横方向スケール (実測の 文字幅/字高 に合わせる)
TRACKING = 0.0        # 字間
FATTEN = 0.35         # 書体を太らせる量 (写真のウェイトに寄せる)
LINE_GAP = 2.688      # 2 行目キャップ上端と 1 行目ベースラインの隙間

PLY = 3.0             # 合板 1 枚の厚み
PLAQUE_PAD = 2.297    # 文字からプレート外周までのオフセット
RIM = 1.3             # 外周フチの幅 (これより内側が彫り下げられる)
RELIEF = 1.2          # 文字とフチの立ち上がり
GROOVE_INSET = 0.7    # 彫り線の内側オフセット
GROOVE_W = 0.5        # 彫り線の幅
GROOVE_D = 0.5        # 彫り線の深さ

POST_W = 7.5          # 支柱の幅
POST_FREE = 20.0      # 台座上面からプレート下端までの高さ
POST_OVERLAP = 3.0    # 支柱がプレート裏に食い込む量

BASE_W = 20.0         # 台座下段の一辺
BASE_TOP_W = 19.0     # 台座上段の一辺
BASE_PLY = 3.0        # 台座 1 枚の厚み

QS = 16               # 円弧の分割数


# ---- 2D 形状 ----------------------------------------------------------------
def build_2d():
    """看板の 2D 形状群を返す。原点はプレート下端中央、Y+ が上。"""
    cap2 = CAP * CAP2_SCALE
    g1, w1 = text_polygon(FONT, LINE1, CAP, TRACKING, WIDTH_SCALE)
    g2, w2 = text_polygon(FONT, LINE2, cap2, TRACKING, WIDTH_SCALE)
    if FATTEN:
        g1 = g1.buffer(FATTEN, join_style=2, mitre_limit=2.0)
        g2 = g2.buffer(FATTEN, join_style=2, mitre_limit=2.0)
    g1 = shapely.affinity.translate(g1, -g1.bounds[0] - (g1.bounds[2] - g1.bounds[0]) / 2,
                                    cap2 + LINE_GAP)
    g2 = shapely.affinity.translate(g2, -g2.bounds[0] - (g2.bounds[2] - g2.bounds[0]) / 2, 0)
    text = shapely.union_all([g1, g2])

    # プレート外周: 文字をオフセットし、細かい凹みを埋めて滑らかにする
    plaque = (text.buffer(PLAQUE_PAD, join_style=1, quad_segs=QS)
                  .buffer(-0.9, join_style=1, quad_segs=QS)
                  .buffer(0.9, join_style=1, quad_segs=QS))

    # 全幅が TARGET_WIDTH になるよう一括スケール
    x0, y0, x1, y1 = plaque.bounds
    s = TARGET_WIDTH / (x1 - x0)
    fix = lambda g: shapely.affinity.translate(
        shapely.affinity.scale(g, s, s, origin=(0, 0)), 0, -y0 * s)
    text, plaque = fix(text), fix(plaque)

    rim = plaque.difference(plaque.buffer(-RIM, join_style=1, quad_segs=QS))
    ring = lambda g: (g.buffer(-GROOVE_INSET, join_style=1, quad_segs=QS)
                      .difference(g.buffer(-GROOVE_INSET - GROOVE_W, join_style=1, quad_segs=QS)))
    grooves = shapely.union_all([ring(text), ring(plaque)])

    px0, py0, px1, py1 = plaque.bounds
    post = box(-POST_W / 2, -POST_FREE - BASE_PLY * 2, POST_W / 2, py0 + POST_OVERLAP)
    return dict(text=text, plaque=plaque, rim=rim, grooves=grooves, post=post,
                bounds=(px0, py0, px1, py1))


# ---- 3D 組み立て ------------------------------------------------------------
def extrude(geom, height, z0=0.0):
    if geom.is_empty:
        return None
    parts = [g for g in (geom.geoms if hasattr(geom, "geoms") else [geom])
             if isinstance(g, Polygon) and not g.is_empty]
    meshes = [trimesh.creation.extrude_polygon(p, height) for p in parts]
    m = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    m.apply_translation([0, 0, z0])
    return m


def build_mesh():
    s = build_2d()
    body = extrude(shapely.union_all([s["plaque"], s["post"]]), PLY)          # 背板 + 支柱
    relief = extrude(shapely.union_all([s["text"], s["rim"]]), RELIEF, PLY)   # 文字 + フチ
    sign = trimesh.boolean.union([body, relief])

    cut = extrude(s["grooves"], GROOVE_D + 0.4, PLY + RELIEF - GROOVE_D)      # 彫り線
    sign = trimesh.boolean.difference([sign, cut])

    # 看板を立てる: (x, y, z) -> (x, -z, y)
    sign.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))
    sign.apply_translation([0, 0, POST_FREE + BASE_PLY * 2])   # 支柱の下端を z=0 に合わせる

    lower = trimesh.creation.box(extents=[BASE_W, BASE_W, BASE_PLY])
    lower.apply_translation([0, -PLY / 2, BASE_PLY / 2])
    upper = trimesh.creation.box(extents=[BASE_TOP_W, BASE_TOP_W, BASE_PLY])
    upper.apply_translation([0, -PLY / 2, BASE_PLY * 1.5])

    model = trimesh.boolean.union([sign, lower, upper])
    model.merge_vertices()
    model.fix_normals()
    return model, s


def main():
    os.makedirs(OUT, exist_ok=True)
    model, s = build_mesh()
    model.visual = trimesh.visual.ColorVisuals(
        model, face_colors=np.tile([196, 158, 105, 255], (len(model.faces), 1)))

    model.export(os.path.join(OUT, "fingerboard-park-sign.stl"))
    model.export(os.path.join(OUT, "fingerboard-park-sign.glb"))

    ext = model.bounds[1] - model.bounds[0]
    print(f"watertight : {model.is_watertight}")
    print(f"volume     : {model.volume/1000:.2f} cm^3")
    print(f"triangles  : {len(model.faces)}")
    print(f"size (mm)  : W {ext[0]:.1f} x D {ext[1]:.1f} x H {ext[2]:.1f}")
    return model, s


if __name__ == "__main__":
    main()
