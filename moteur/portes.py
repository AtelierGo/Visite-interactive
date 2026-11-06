"""Vantaux de portes (calques Portes / Porte coulissante) et vitrine cintree.
Reglages : etape_3_ouvertures_escaliers > portes, vitrines."""
import math, numpy as np, trimesh
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union
import stairs as S, plan2glb as P


def leaves(page, prefixes, dx, dy, min_len_pt=25, ep=0.04):
    """Vantaux tels que dessines sur le plan (ouverts) : quadrilateres pleins et traits longs."""
    quads, segs = {}, []
    for d in page.get_drawings():
        if not any(d.get('layer', '').startswith(p) for p in prefixes): continue
        for it in d['items']:
            if it[0] == 'qu':
                q = it[1]; poly = Polygon([S.pt(v.x, v.y, dx, dy) for v in (q.ul, q.ur, q.lr, q.ll)]).buffer(0)
                quads[tuple(round(c, 2) for c in poly.bounds)] = poly
            elif it[0] == 'l' and math.dist((it[1].x, it[1].y), (it[2].x, it[2].y)) > min_len_pt:
                segs.append(LineString([S.pt(it[1].x, it[1].y, dx, dy), S.pt(it[2].x, it[2].y, dx, dy)]))
    out = list(quads.values())
    if segs:   # deux traits paralleles proches = un vantail epais
        g = unary_union([s.buffer(ep / 2, cap_style=2) for s in segs]).buffer(0.05, join_style=2).buffer(-0.05, join_style=2)
        qu = unary_union(out).buffer(0.03) if out else Polygon()
        out += [p for p in P.polys(g) if not qu.contains(p)]   # traits qui doublent un quadrilatere
    return out


def arch_profile(W, spring, crown, n=48):
    """Ouverture : rectangle jusqu'a la naissance + arc surbaisse jusqu'a la cle (coordonnees u, z)."""
    f = crown - spring; a = W / 2; R = (a * a + f * f) / (2 * f)
    pts = [(0, 0), (W, 0), (W, spring)]
    for t in np.linspace(0, 1, n)[1:-1]:
        u = W - t * W; pts.append((u, spring + math.sqrt(max(R * R - (u - a) ** 2, 0)) - (R - f)))
    pts.append((0, spring)); return Polygon(pts)


def facade_mesh(shape2d, p0, p1, z0, t, inward):
    """Extrude une forme (u le long de p0->p1, z vertical) sur l'epaisseur t, du cote 'inward'."""
    m = trimesh.creation.extrude_polygon(shape2d, t)
    ux, uy = (p1[0] - p0[0]), (p1[1] - p0[1]); L = math.hypot(ux, uy); ux, uy = ux / L, uy / L
    nx, ny = inward
    T = np.array([[ux, 0, nx, p0[0]], [uy, 0, ny, p0[1]], [0, 1, 0, z0], [0, 0, 0, 1]])
    m.apply_transform(T)
    if np.linalg.det(T[:3, :3]) < 0: m.invert()
    return m


def vitrine(v, dx, dy, z0, ceil, center_hint):
    """Mur de facade au-dessus de l'arc, chassis et vitrages. Retourne (mur, chassis, verre)."""
    p0, p1 = S.pt(*v['de_plan_pt'], dx, dy), S.pt(*v['a_plan_pt'], dx, dy)
    W = math.dist(p0, p1); ux, uy = (p1[0] - p0[0]) / W, (p1[1] - p0[1]) / W
    n = (-uy, ux)
    if (center_hint[0] - p0[0]) * n[0] + (center_hint[1] - p0[1]) * n[1] < 0: n = (uy, -ux)
    spring, crown, ep = v['hauteur_naissance_m'], v['hauteur_cle_m'], v.get('epaisseur_mur_m', 0.30)
    hole = arch_profile(W, spring, crown)
    wall = box(0, 0, W, ceil).difference(hole)
    fr = v.get('chassis_m', 0.06)
    # chassis : contour de l'arc, imposte a la hauteur de la porte, montants aux limites des vitrages fixes
    frame = hole.difference(hole.buffer(-fr, join_style=2))
    frame = frame.union(box(0, v['hauteur_imposte_m'] - fr / 2, W, v['hauteur_imposte_m'] + fr / 2))
    for u in v.get('montants_u_m', []): frame = frame.union(box(u - fr / 2, 0, u + fr / 2, spring + 1))
    frame = frame.intersection(hole)
    glass = hole.buffer(-fr / 2)
    # pas de vitrage fixe dans la baie de la porte (vantail dessine sur le plan)
    for a, b in v.get('baies_porte_u_m', []): glass = glass.difference(box(a, 0, b, v['hauteur_imposte_m']))
    off = lambda d: (n[0] * d, n[1] * d)
    mk = lambda g, t, d: [facade_mesh(q, (p0[0] + off(d)[0], p0[1] + off(d)[1]), (p1[0] + off(d)[0], p1[1] + off(d)[1]), z0, t, n)
                          for q in P.polys(g)]
    return mk(wall, ep, -ep / 2), mk(frame, 0.07, -0.035), mk(glass, 0.02, -0.01)
