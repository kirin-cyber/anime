#!/usr/bin/env python3
"""レーザーカット用 SVG (原寸 1mm = 1unit) を書き出す。

  赤 (#ff0000) : 切断ライン
  青 (#0000ff) : 彫刻ライン (文字と外周の輪郭)
  グレー塗り   : 面彫刻 (掘り下げる地の部分)
"""
import os
import sys

import shapely
from shapely.geometry import Polygon, box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import (BASE_PLY, BASE_TOP_W, BASE_W, OUT, PLY, POST_W, QS, RIM,  # noqa: E402
                   build_2d)

CUT, ENGRAVE = "#ff0000", "#0000ff"


def paths(geom, dx=0.0, dy=0.0):
    out = []
    for p in (geom.geoms if hasattr(geom, "geoms") else [geom]):
        if p.is_empty or not isinstance(p, Polygon):
            continue
        d = ""
        for ring in [p.exterior] + list(p.interiors):
            pts = list(ring.coords)
            d += "M" + " L".join(f"{x + dx:.3f},{-(y + dy):.3f}" for x, y in pts) + " Z "
        out.append(d.strip())
    return out


def main():
    s = build_2d()
    plaque, text = s["plaque"], s["text"]
    field = plaque.buffer(-RIM, join_style=1, quad_segs=QS).difference(text)

    board = shapely.union_all([plaque, s["post"]])
    slot = box(-POST_W / 2, -PLY / 2, POST_W / 2, PLY / 2)
    bx0, by0, bx1, by1 = board.bounds

    # レイアウト: 看板本体の右下に台座 2 枚を並べる
    gap = 6.0
    base_dx = 0.0
    base_dy = by0 - gap - BASE_W / 2
    base2_dx = BASE_W + gap

    layers = []
    layers.append((ENGRAVE, "none", paths(field)))            # 面彫刻 (地)
    layers.append((ENGRAVE, "none", paths(text)))             # 文字の輪郭
    layers.append((ENGRAVE, "none", paths(
        text.buffer(-0.55, join_style=1, quad_segs=QS))))     # 文字の内側二重線
    layers.append((ENGRAVE, "none", paths(
        plaque.buffer(-0.55, join_style=1, quad_segs=QS))))   # 外周の内側線
    layers.append((CUT, "none", paths(board)))                # 本体の切断
    for dx, w in ((base_dx, BASE_W), (base2_dx, BASE_TOP_W)):
        plate = box(-w / 2, -w / 2, w / 2, w / 2).difference(slot)
        layers.append((CUT, "none", paths(plate, dx, base_dy)))

    xs, ys = [], []
    for g, dx, dy in ((board, 0, 0), (box(-BASE_W / 2, -BASE_W / 2, BASE_W / 2, BASE_W / 2),
                                      base_dx, base_dy),
                      (box(-BASE_TOP_W / 2, -BASE_TOP_W / 2, BASE_TOP_W / 2, BASE_TOP_W / 2),
                       base2_dx, base_dy)):
        x0, y0, x1, y1 = g.bounds
        xs += [x0 + dx, x1 + dx]; ys += [y0 + dy, y1 + dy]
    pad = 5
    x0, x1, y0, y1 = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    w, h = x1 - x0, y1 - y0

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.2f}mm" height="{h:.2f}mm" '
           f'viewBox="{x0:.2f} {-y1:.2f} {w:.2f} {h:.2f}">',
           f'<rect x="{x0:.2f}" y="{-y1:.2f}" width="{w:.2f}" height="{h:.2f}" fill="#ffffff"/>']
    # 面彫刻はグレー塗り、それ以外は線
    for i, (stroke, _fill, ds) in enumerate(layers):
        fill = "#c8c8c8" if i == 0 else "none"
        stroke_w = 0 if i == 0 else 0.1
        for d in ds:
            svg.append(f'<path d="{d}" fill="{fill}" fill-rule="evenodd" '
                       f'stroke="{stroke}" stroke-width="{stroke_w}"/>')
    svg.append("</svg>")

    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "fingerboard-park-sign-lasercut.svg")
    open(p, "w").write("\n".join(svg))
    print("wrote", p, f"({w:.1f} x {h:.1f} mm)")
    print(f"材料: 合板 {PLY:.0f}mm (本体) / {BASE_PLY:.0f}mm x2 (台座)")


if __name__ == "__main__":
    main()
