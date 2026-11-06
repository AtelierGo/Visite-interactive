"""Placards (calque Placards), rails d'eclairage et suspensions.
Reglages : etape_5_mobilier_eclairage."""
import math, numpy as np, trimesh
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
import stairs as S, plan2glb as P


def placards(page, layer, W, floor, dx, dy, depth=0.62, min_len_pt=25):
    """Facade de placard = traits longs du calque ; caisson = bande entre la facade et le mur."""
    fronts, bodies = [], []
    for d in page.get_drawings():
        if not d.get('layer', '').startswith(layer): continue
        for it in d['items']:
            if it[0] != 'l' or math.dist((it[1].x, it[1].y), (it[2].x, it[2].y)) < min_len_pt: continue
            ln = LineString([S.pt(it[1].x, it[1].y, dx, dy), S.pt(it[2].x, it[2].y, dx, dy)])
            sides = [ln.buffer(depth, single_sided=True), ln.buffer(-depth, single_sided=True)]
            body = max(sides, key=lambda s: s.intersection(W).area)      # cote du mur
            fronts.append(ln); bodies.append(body.difference(W.buffer(0.005)).intersection(floor.buffer(0.01)))
    return fronts, unary_union(bodies) if bodies else None


def rail(p0, p1, z, spot_step, aim=(0.0, 0.0), tilt=0.5, drop=0.0, z1=None):
    """Rail noir sous le plafond (z au debut, z1 a la fin si le plafond n'est pas plat) + spots orientes vers 'aim'."""
    z1 = z if z1 is None else z1
    (x0, y0), (x1, y1) = p0, p1
    A = np.array([x0, y0, z - 0.0175 - drop]); B = np.array([x1, y1, z1 - 0.0175 - drop])
    u = B - A; L = np.linalg.norm(u); u /= L
    h = np.array([-u[1], u[0], 0.0]); h /= np.linalg.norm(h); w = np.cross(u, h)
    T = np.eye(4); T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = u, h, w, (A + B) / 2
    r = trimesh.creation.box([L, 0.035, 0.035]); r.apply_transform(T)
    spots = []
    k = max(1, int(L // spot_step))
    v = np.array([aim[0] * math.sin(tilt), aim[1] * math.sin(tilt), -math.cos(tilt)])
    for i in range(k):
        t = (i + 0.5) / k; top = A + t * (B - A) - [0, 0, 0.0175]; a_ = top - [0, 0, 0.03]; b_ = a_ + v * 0.12
        spots.append(trimesh.creation.cylinder(radius=0.03, segment=[a_, b_], sections=16))
        spots.append(trimesh.creation.cylinder(radius=0.008, segment=[top, a_], sections=8))
    return [r], spots


def clearance_under(meshes, ceil_fn):
    """Plus petite distance (m) entre les sommets et le plafond au-dessus ; negatif = penetration."""
    best = 9.0
    for m in meshes:
        for x, y, zz in m.vertices: best = min(best, ceil_fn(x, y) - zz)
    return best


def clip_rail(p0, p1, libre, longueur_min):
    """Decoupe le trace du rail dans la zone libre (piece moins une marge aux murs et obstacles)."""
    g = LineString([p0, p1]).intersection(libre)
    parts = [g] if g.geom_type == 'LineString' else list(getattr(g, 'geoms', []))
    return [tuple(map(tuple, (q.coords[0], q.coords[-1]))) for q in parts if q.geom_type == 'LineString' and q.length >= longueur_min]


def side_to_wall(p0, p1, W):
    """Normale horizontale du rail tournee vers le mur le plus proche."""
    (x0, y0), (x1, y1) = p0, p1; L = math.dist(p0, p1); n = np.array([-(y1 - y0) / L, (x1 - x0) / L])
    m = Point((x0 + x1) / 2, (y0 + y1) / 2)
    d_plus = W.distance(Point(m.x + n[0], m.y + n[1])); d_minus = W.distance(Point(m.x - n[0], m.y - n[1]))
    return tuple(n if d_plus < d_minus else -n)


def suspension(x, y, z_ceil, h_bas, diam):
    disc = trimesh.creation.cone(radius=diam / 2, height=0.12, sections=48)
    disc.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))   # coupole ouverte vers le bas
    disc.apply_translation([x, y, h_bas + 0.12])
    cab = [trimesh.creation.cylinder(radius=0.002, height=z_ceil - h_bas - 0.1, sections=6) for _ in (0, 1)]
    for c, s in zip(cab, (-1, 1)): c.apply_translation([x + s * diam * 0.3, y, (z_ceil + h_bas + 0.1) / 2])
    can = trimesh.creation.cylinder(radius=0.07, height=0.03, sections=24); can.apply_translation([x, y, z_ceil - 0.015])
    return [disc], cab + [can]
