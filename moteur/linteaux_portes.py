"""Mur au-dessus de chaque porte, trouve a partir de la porte elle-meme (et non plus seulement en refermant les murs).

Pour une porte battante, le vantail est dessine ouvert : sa charniere et le bout de son arc donnent la ligne de l'ouverture
(porte fermee). Pour une porte coulissante (sans arc), le vantail est deja dans la ligne du mur. Le long de cette ligne,
on cherche l'intervalle sans mur qui contient la porte : ses deux bords sont les tableaux, et le linteau va de l'un a l'autre,
sur l'epaisseur commune des deux tableaux.
Reglages (etape_2_murs) : linteaux_par_porte (oui par defaut), epaisseur_max_ouverture_m (largeur de recherche du mur),
epaisseur_linteau_seul_m (porte entre deux murs perpendiculaires, sans mur dans son axe).
"""
import math
from shapely.geometry import Point, LineString, Polygon, box
from shapely.ops import unary_union
from shapely import affinity
import plan2glb as P
import stairs as S


def _bouts_arcs(page, prefixes, dx, dy):
    pts = []
    for d in page.get_drawings():
        if not any(d.get('layer', '').startswith(p) for p in prefixes): continue
        for it in d['items']:
            if it[0] == 'c': pts += [Point(S.pt(it[1].x, it[1].y, dx, dy)), Point(S.pt(it[4].x, it[4].y, dx, dy))]
    return pts


def _axe_vantail(l):
    rc = list(l.minimum_rotated_rectangle.exterior.coords)[:4]
    sides = sorted([(math.dist(rc[j], rc[(j + 1) % 4]), j) for j in range(4)])[:2]
    e = [Point((rc[j][0] + rc[(j + 1) % 4][0]) / 2, (rc[j][1] + rc[(j + 1) % 4][1]) / 2) for _, j in sides]
    return e[0], e[1]


def _intervalle(W, O, u, cible, demi, portee=2.0):
    """Ouverture le long de la droite (O, u) : intervalle libre de mur qui contient l'abscisse cible, borne par du mur des deux cotes."""
    ang = math.degrees(math.atan2(u[1], u[0]))
    band = affinity.rotate(box(-portee, -demi, portee, demi), ang, origin=(0, 0))
    band = affinity.translate(band, O.x, O.y)
    loc = affinity.rotate(affinity.translate(W.intersection(band), -O.x, -O.y), -ang, origin=(0, 0))
    parts = [p for p in P.polys(loc) if p.area > 1e-4]
    iv = sorted((p.bounds[0], p.bounds[2]) for p in parts)
    fus = []
    for a, b in iv:
        if fus and a <= fus[-1][1] + 0.005: fus[-1][1] = max(fus[-1][1], b)
        else: fus.append([a, b])
    for k in range(len(fus) - 1):
        a, b = fus[k][1], fus[k + 1][0]
        if a - 0.02 <= cible <= b + 0.02: return a, b, parts, ang
    return None


def linteaux(page, prefixes, W, dx, dy, demi=0.4, largeur_min=0.3, largeur_max=2.0, seul=0.2):
    """Formes (repere du modele) a fermer au-dessus de chaque porte."""
    import portes as PO
    out = []
    arcs = _bouts_arcs(page, prefixes, dx, dy)
    for l in PO.leaves(page, prefixes, dx, dy):
        e1, e2 = _axe_vantail(l); L = e1.distance(e2)
        if L < 0.25: continue
        essais = []
        # porte battante : le bout de l'arc qui n'est pas au bout du vantail donne la position fermee
        for tip, hinge in ((e1, e2), (e2, e1)):
            if not any(a.distance(tip) < 0.12 for a in arcs): continue
            fermes = [a for a in arcs if a.distance(tip) > 0.15 and abs(a.distance(hinge) - L) < 0.2 * L]
            if fermes:
                c = min(fermes, key=lambda a: a.distance(W))
                essais.append((hinge, c))
        if not essais:      # sans arc : porte coulissante (vantail dans la ligne du mur), sinon porte dessinee ouverte a 90 deg
            essais.append((e1, e2))
            v = (e2.x - e1.x, e2.y - e1.y)
            for s in (1, -1):
                for h, t in ((e1, e2), (e2, e1)):
                    w_ = (t.x - h.x, t.y - h.y)
                    essais.append((h, Point(h.x - s * w_[1], h.y + s * w_[0])))
        for h, c in essais:
            d = h.distance(c)
            if d < 1e-3: continue
            u = ((c.x - h.x) / d, (c.y - h.y) / d)
            r = _intervalle(W, h, u, d / 2, demi)
            if r is None: continue
            a, b, parts, ang = r
            if not (largeur_min <= b - a <= largeur_max): continue
            # tableaux : les morceaux de mur qui bordent l'ouverture ; epaisseur commune des deux
            ga = [p for p in parts if abs(p.bounds[2] - a) < 0.01]; gb = [p for p in parts if abs(p.bounds[0] - b) < 0.01]
            if not ga or not gb: continue
            ja = unary_union(ga).intersection(box(a - 0.25, -demi, a + 0.001, demi)); jb = unary_union(gb).intersection(box(b - 0.001, -demi, b + 0.25, demi))
            if ja.is_empty or jb.is_empty: continue
            # un tableau « dans l'axe » (bout d'un mur qui suit l'ouverture) donne l'epaisseur ; un mur perpendiculaire traverse la bande
            long_ = [j for j in (ja, jb) if j.bounds[1] > -demi + 0.01 and j.bounds[3] < demi - 0.01]
            if len(long_) == 2: y0, y1 = min(ja.bounds[1], jb.bounds[1]), max(ja.bounds[3], jb.bounds[3])
            elif len(long_) == 1: y0, y1 = long_[0].bounds[1], long_[0].bounds[3]
            else: y0, y1 = -seul / 2, seul / 2      # entre deux murs perpendiculaires : linteau seul, centre sur la porte fermee
            g = box(a - 0.002, y0, b + 0.002, y1)
            g = affinity.translate(affinity.rotate(g, ang, origin=(0, 0)), h.x, h.y).difference(W).buffer(-0.005).buffer(0.005)
            if g.area > 0.01: out.append(g); break
    return [g for g in out if not g.is_empty]
