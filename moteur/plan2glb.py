"""Prototype: plan Illustrator (PDF-compatible) au 1:50 -> GLB brut (murs, sols, linteaux)."""
import sys, numpy as np, pymupdf, trimesh
from shapely.geometry import Polygon, MultiPolygon, box
from shapely.ops import unary_union, polygonize
from shapely.geometry import LineString
from shapely import make_valid

PT_TO_M = 25.4 / 72 / 1000 * 50          # 1 pt papier au 1:50 -> metres reels
CEIL, SLAB, LINTEL = 2.50, 0.20, 2.10    # hauteur sous plafond, dalle, haut des portes
CLOSE = 0.55
OFFSETS = [0, -1]                        # page 1 = rez-de-chaussee, page 2 = sous-sol
FOOT = 2.0                               # emprise du batiment (ferme la vitrine)
COLORS = {'murs': [242,240,235,255], 'linteaux': [242,240,235,255], 'sol': [176,138,98,255], 'dalle': [200,200,200,255]}                             # ouvertures plus etroites que 2*CLOSE m -> linteau

def lin(rgba):   # glTF attend des couleurs lineaires
    f = lambda c: (c/255)/12.92 if c/255 <= 0.04045 else ((c/255 + 0.055)/1.055)**2.4
    return [f(c) for c in rgba[:3]] + [rgba[3]/255]

def subpaths(items):
    out, cur, last = [], [], None
    for it in items:
        k = it[0]
        if k == 'l': a, b = it[1], it[2]; pts = [a, b]
        elif k == 'c': a, b = it[1], it[4]; pts = [it[1] + (it[2]-it[1])*0 , *(bez(it[1], it[2], it[3], it[4]))]
        elif k == 're': r = it[1]; pts = [r.tl, r.tr, r.br, r.bl, r.tl]; a, b = pts[0], pts[-1]
        elif k == 'qu': q = it[1]; pts = [q.ul, q.ur, q.lr, q.ll, q.ul]; a, b = pts[0], pts[-1]
        else: continue
        if last is None or abs(a.x-last.x) + abs(a.y-last.y) > 0.01:
            if len(cur) > 2: out.append(cur)
            cur = [(a.x, a.y)]
        cur += [(p.x, p.y) for p in pts[1:]]
        last = b
    if len(cur) > 2: out.append(cur)
    return out

def bez(p0, p1, p2, p3, n=12):
    for t in np.linspace(0, 1, n)[1:]:
        u = 1 - t
        yield p0*(u**3) + p1*(3*u*u*t) + p2*(3*u*t*t) + p3*(t**3)

def nonzero(rings):
    sgn = [1 if Polygon(r.exterior).exterior.is_ccw else -1 for r in rings]
    vals = [make_valid(r) for r in rings]
    faces = list(polygonize(unary_union([LineString(r.exterior.coords) for r in rings])))
    keep = []
    for f in faces:
        q = f.representative_point()
        if sum(s_ for s_, v in zip(sgn, vals) if v.contains(q)) != 0: keep.append(f)
    return unary_union(keep) if keep else Polygon()

def walls_of(page, layer='Murs'):
    geom = None
    for d in page.get_drawings():
        if not d.get('layer', '').startswith(layer) or d.get('fill') is None: continue
        rings = [Polygon([(x*PT_TO_M, -y*PT_TO_M) for x, y in sp]) for sp in subpaths(d['items'])]
        rings = [r for r in rings if abs(r.area) > 1e-6]
        if not rings: continue
        if d.get('even_odd'):
            g = None
            for r in rings:
                r = make_valid(r); g = r if g is None else g.symmetric_difference(r)
        elif len(rings) == 1: g = make_valid(rings[0])
        else:   # regle non nulle (comme Illustrator) : une zone est pleine si la somme des sens de parcours des contours qui l'entourent n'est pas nulle
            g = nonzero(rings)
        if g is not None: geom = g if geom is None else geom.union(g)
    return geom.buffer(0)

def polys(g):
    g = make_valid(g)
    if isinstance(g, Polygon): return [g]
    return [p for p in getattr(g, 'geoms', []) if isinstance(p, Polygon) and p.area > 1e-4] + \
           [q for p in getattr(g, 'geoms', []) if isinstance(p, MultiPolygon) for q in p.geoms]

def extrude(g, z0, h, color):
    ms = []
    for p in polys(g):
        p = p.buffer(0)
        if p.is_empty or p.area < 1e-4 or p.geom_type != 'Polygon': ms += extrude(p, z0, h, color) if p.geom_type == 'MultiPolygon' else []; continue
        m = trimesh.creation.extrude_polygon(p, h); m.apply_translation([0, 0, z0])
        ms.append(m)
    return ms

def level(page, z, name):
    W = walls_of(page)
    closed = W.buffer(CLOSE, join_style='mitre').buffer(-CLOSE, join_style='mitre')
    doors = unary_union([box(d['rect'].x0*PT_TO_M, -d['rect'].y1*PT_TO_M, d['rect'].x1*PT_TO_M, -d['rect'].y0*PT_TO_M)
                         for d in page.get_drawings() if d.get('layer', '').startswith('Porte')]).buffer(0.15)
    lintels = closed.difference(W).intersection(doors).buffer(-0.01).buffer(0.01)
    big = W.buffer(FOOT, join_style='mitre').buffer(-FOOT, join_style='mitre')
    outline = unary_union([Polygon(p.exterior) for p in polys(big)])
    parts = {
        f'{name}_murs': extrude(W, z, CEIL, [242, 240, 235, 255]),
        f'{name}_linteaux': extrude(lintels, z + LINTEL, CEIL - LINTEL, [242, 240, 235, 255]),
        f'{name}_sol': extrude(outline.difference(W), z - 0.02, 0.02, [176, 138, 98, 255]),
        f'{name}_dalle': extrude(outline, z - SLAB, SLAB - 0.02, [200, 200, 200, 255]),
    }
    return parts, W

def main(src, dst):
    doc = pymupdf.open(src)
    scene = trimesh.Scene()
    for i, page in enumerate(doc):
        parts, W = level(page, OFFSETS[i] * (CEIL + SLAB), f'niveau{i}')
        b = W.bounds; print(f'page {i}: {b[2]-b[0]:.2f} x {b[3]-b[1]:.2f} m, murs {W.area:.1f} m2')
        for k, ms in parts.items():
            if not ms: continue
            m = trimesh.util.concatenate(ms) if len(ms) > 1 else ms[0]
            m.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
                name=k.split('_')[1], baseColorFactor=lin(COLORS[k.split('_')[1]]), metallicFactor=0.0, roughnessFactor=0.9))
            scene.add_geometry(m, geom_name=k)
    # glTF : Y vers le haut
    scene.apply_transform(trimesh.transformations.rotation_matrix(-np.pi/2, [1, 0, 0]))
    c = scene.bounds.mean(axis=0); scene.apply_translation([-c[0], 0, -c[2]])   # sol du RDC a y = 0
    scene.export(dst); print('ok', dst, scene.extents)

if __name__ == '__main__': main(*sys.argv[1:3])
