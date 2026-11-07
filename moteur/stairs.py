"""Escaliers, trémie, plinthes et carrelage pour le prototype v0.3."""
import numpy as np, pymupdf, trimesh
from shapely.geometry import Polygon, Point
from PIL import Image, ImageDraw
import plan2glb as P

M = P.PT_TO_M
def pt(x, y, dx=0, dy=0): return ((x + dx) * M, -(y + dy) * M)

def spiral_center(page, layer='Spiral'):
    """Petit cercle central du calque escalier helicoidal."""
    best = None
    for d in page.get_drawings():
        if d.get('layer', '').startswith(layer) and d['type'] == 's':
            r = d['rect']
            if 4 < r.width < 12 and abs(r.width - r.height) < 1.5 and all(i[0] == 'c' for i in d['items']):
                best = ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
    outer = max((d['rect'] for d in page.get_drawings() if d.get('layer', '').startswith(layer) and d['type'] == 's'),
                key=lambda r: r.width)
    if best is None: best = centre_des_marches(page, layer)
    return best, outer.width / 2

def centre_des_marches(page, layer='Spiral'):
    """Sans petit cercle central : point le plus proche de toutes les lignes de marches (elles rayonnent depuis l'axe)."""
    A, B = np.zeros((2, 2)), np.zeros(2)
    n = 0
    for d in page.get_drawings():
        if not d.get('layer', '').startswith(layer) or d['type'] != 's' or len(d['items']) != 1 or d['items'][0][0] != 'l': continue
        p0, p1 = d['items'][0][1], d['items'][0][2]; v = np.array([p1.x - p0.x, p1.y - p0.y]); L = np.linalg.norm(v)
        if L < 20: continue
        u = v / L; P_ = np.eye(2) - np.outer(u, u); A += P_; B += P_ @ np.array([p0.x, p0.y]); n += 1
    if n < 3: return None
    c = np.linalg.solve(A, B); return (float(c[0]), float(c[1]))

def spiral(center, R, z0, z1, rise=0.19, step_deg=30, start_deg=0, thick=0.05):
    n = max(1, round((z1 - z0) / rise)); h = (z1 - z0) / n
    meshes = []
    for k in range(n):
        a0 = np.radians(start_deg + k * step_deg); a1 = a0 + np.radians(step_deg + 4)
        arc = [(center[0] + R * np.cos(a), center[1] + R * np.sin(a)) for a in np.linspace(a0, a1, 8)]
        poly = Polygon([center] + arc)
        m = trimesh.creation.extrude_polygon(poly, thick); m.apply_translation([0, 0, z0 + (k + 1) * h - thick]); meshes.append(m)
    pole = trimesh.creation.cylinder(radius=0.05, height=z1 - z0 + 0.9, sections=24)
    pole.apply_translation([center[0], center[1], (z0 + z1 + 0.9) / 2]); meshes.append(pole)
    return meshes

def lines(page, layer='Mobilier'):
    out = []
    for d in page.get_drawings():
        if d.get('layer', '').startswith(layer) and d['type'] == 'fs' and len(d['items']) > 20:
            for it in d['items']:
                if it[0] == 'l': out.append((it[1], it[2]))
    return out

def straight_stair(page, z0, z1, dx, dy, cfg=None, layer='Mobilier'):
    cfg = cfg or {}
    lx = cfg.get('volee_basse_x_plan_pt', [425, 440]); ux = cfg.get('volee_haute_x_plan_pt', [370, 430])
    """Escalier droit du sous-sol : volee montant vers le nord, palier, volee vers l'ouest."""
    segs = lines(page, layer)
    lower = sorted({(round(min(a.y, b.y)), round(a.x), round(a.y), round(b.x), round(b.y)) for a, b in segs
                    if abs(a.y - b.y) < 15 and abs(a.x - b.x) > 50 and lx[0] < min(a.x, b.x) < lx[1]}, key=lambda t: -t[2])
    upper = sorted({(round(a.x), round(a.y), round(b.x), round(b.y)) for a, b in segs
                    if abs(a.x - b.x) < 10 and abs(a.y - b.y) > 50 and ux[0] < min(a.x, b.x) < ux[1]}, key=lambda t: -t[0])
    def norm(l):  # gauche->droite ou bas->haut
        x1, y1, x2, y2 = l
        return (x1, y1, x2, y2) if (x1, -y1) <= (x2, -y2) else (x2, y2, x1, y1)
    def dedupe(ls, key):
        out = {}
        for l in ls: out.setdefault(round(key(l) / 4), l)
        return list(out.values())
    lower = sorted(dedupe([norm(l[1:]) for l in lower], lambda l: (l[1] + l[3]) / 2), key=lambda l: -(l[1] + l[3]))
    upper = sorted(dedupe([norm(l) for l in upper], lambda l: (l[0] + l[2]) / 2), key=lambda l: -(l[0] + l[2]))
    landing = [tuple(p) for p in cfg.get('palier_plan_pt', [(433, 434), (440, 367), (500, 381), (497, 453), (432, 444)])]
    n = (len(lower) - 1) + 1 + len(upper)           # marches + palier + volee haute
    h = (z1 - z0) / (n + 1)
    blocks, k = [], 0
    for a, b in zip(lower, lower[1:]):
        k += 1; blocks.append(([a[0], a[1]], [a[2], a[3]], [b[2], b[3]], [b[0], b[1]], k))
    k += 1; land_k = k
    prev = (*landing[0], *landing[1])
    for u in upper:
        k += 1; blocks.append(([prev[0], prev[1]], [prev[2], prev[3]], [u[2], u[3]], [u[0], u[1]], k)); prev = u
    meshes = []
    for *q, kk in blocks:
        poly = Polygon([pt(x, y, dx, dy) for x, y in q]).buffer(0)
        if poly.area < 0.01: continue
        m = trimesh.creation.extrude_polygon(poly, kk * h); m.apply_translation([0, 0, z0]); meshes.append(m)
    lp = Polygon([pt(x, y, dx, dy) for x, y in landing]).buffer(0)
    m = trimesh.creation.extrude_polygon(lp, land_k * h); m.apply_translation([0, 0, z0]); meshes.append(m)
    return meshes, n

def tile_texture(path, px=512, tiles=2, joint=2, color=(74, 74, 72), joint_color=(112, 112, 108)):
    rng = np.random.default_rng(7)
    base = np.full((px, px, 3), tuple(color), np.float32)
    base += rng.normal(0, 4, (px, px, 1))                       # grain du gres cerame
    speck = rng.random((px, px)) > 0.996; base[speck] -= 22
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)); dr = ImageDraw.Draw(img)
    step = px // tiles
    for i in range(tiles + 1):
        dr.rectangle([i * step - joint // 2, 0, i * step + joint // 2, px], fill=tuple(joint_color))
        dr.rectangle([0, i * step - joint // 2, px, i * step + joint // 2], fill=tuple(joint_color))
    img.save(path)
