"""Font outline -> shapely polygons."""
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import RecordingPen
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
import shapely

def _q(p0, p1, p2, n=12):
    return [( (1-t)**2*p0[0]+2*(1-t)*t*p1[0]+t*t*p2[0],
              (1-t)**2*p0[1]+2*(1-t)*t*p1[1]+t*t*p2[1]) for t in [i/n for i in range(1, n+1)]]

def _c(p0, p1, p2, p3, n=16):
    out=[]
    for i in range(1, n+1):
        t=i/n; mt=1-t
        out.append((mt**3*p0[0]+3*mt*mt*t*p1[0]+3*mt*t*t*p2[0]+t**3*p3[0],
                    mt**3*p0[1]+3*mt*mt*t*p1[1]+3*mt*t*t*p2[1]+t**3*p3[1]))
    return out

def glyph_contours(font, glyphset, name):
    pen = RecordingPen()
    glyphset[name].draw(pen)
    contours, cur, start = [], [], (0,0)
    for op, args in pen.value:
        if op == "moveTo":
            if len(cur) > 2: contours.append(cur)
            start = args[0]; cur = [start]
        elif op == "lineTo":
            cur.append(args[0])
        elif op == "qCurveTo":
            pts = list(args)
            on = pts[-1]
            offs = pts[:-1]
            if on is None:               # all-offcurve TrueType contour
                on = ((offs[0][0]+offs[-1][0])/2, (offs[0][1]+offs[-1][1])/2)
            prev = cur[-1]
            for i, ctl in enumerate(offs):
                nxt = on if i == len(offs)-1 else ((ctl[0]+offs[i+1][0])/2, (ctl[1]+offs[i+1][1])/2)
                cur.extend(_q(prev, ctl, nxt)); prev = nxt
        elif op == "curveTo":
            pts = list(args); prev = cur[-1]
            for i in range(0, len(pts)-2, 2):
                cur.extend(_c(prev, pts[i], pts[i+1], pts[i+2])); prev = pts[i+2]
        elif op == "closePath":
            if len(cur) > 2: contours.append(cur)
            cur = []
    if len(cur) > 2: contours.append(cur)
    return contours

def _contours_to_geom(contours):
    """Classify contours into outers/holes by nesting depth (even-odd containment)."""
    polys = []
    for c in contours:
        p = Polygon(c)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty or p.area <= 0:
            continue
        polys.append(p if isinstance(p, Polygon) else max(p.geoms, key=lambda q: q.area))
    # Nesting depth: how many strictly larger contours enclose this one.
    polys.sort(key=lambda p: p.area, reverse=True)
    outers, holes = [], []
    for i, p in enumerate(polys):
        depth = sum(1 for q in polys[:i] if q.contains(p.buffer(-1e-9)))
        (holes if depth % 2 else outers).append(p)
    g = unary_union(outers) if outers else Polygon()
    if holes:
        g = g.difference(unary_union(holes))
    return g


def text_polygon(font_path, text, cap_height_mm, tracking_mm=0.0, width_scale=1.0):
    """Return (shapely geometry, advance_width_mm) with baseline at y=0, left edge x=0."""
    font = TTFont(font_path)
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upm = font["head"].unitsPerEm
    cap = font["OS/2"].sCapHeight if hasattr(font["OS/2"], "sCapHeight") and font["OS/2"].sCapHeight else upm*0.7
    s = cap_height_mm / cap
    hmtx = font["hmtx"]
    kern = None
    x = 0.0
    glyphs = []
    for ch in text:
        gname = cmap.get(ord(ch))
        if gname is None:
            x += cap_height_mm*0.5; continue
        cs = [[((px*s*width_scale)+x, py*s) for px, py in c]
              for c in glyph_contours(font, gs, gname)]
        if cs:
            glyphs.append(_contours_to_geom(cs))
        x += hmtx[gname][0]*s*width_scale + tracking_mm
    return unary_union(glyphs), x - tracking_mm
