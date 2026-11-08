"""Marches entre pieces trouvees sur le plan (etape Pieces, changements_de_niveau).

Une marche se dessine comme un trait (ou une barre fine) en travers d'un passage, d'un mur a l'autre.
Plusieurs traits paralleles proches = plusieurs marches (le giron est leur ecart).
Le sens de montee ne se lit pas sur un plan : par defaut on monte du cote oppose aux autres traits ;
il est signale a verifier.
Reglages (etape_2_murs.marches_auto) : epaisseur_max_m (barre plus fine = trait de marche, pas un mur),
longueur_min_m, longueur_max_m, ecart_max_m (entre deux nez de marche), distance_mur_m (bouts contre les murs).
"""
import math
from shapely.geometry import LineString, Point
from shapely.ops import unary_union
from shapely.affinity import scale
import plan2glb as P


def _segments_traits(page, layer, M):
    out = []
    for d in page.get_drawings():
        if not d.get('layer', '').startswith(layer): continue
        if d.get('fill') is not None:     # plein sans surface (un trait rempli) : c'est un trait
            if len(d['items']) > 2 or any(it[0] != 'l' for it in d['items']): continue
        for it in d['items']:
            if it[0] == 'l':
                a, b = it[1], it[2]; out.append(LineString([(a.x * M, -a.y * M), (b.x * M, -b.y * M)]))
            elif it[0] == 're':
                r = it[1]; pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                out += [LineString([(pts[k][0] * M, -pts[k][1] * M), (pts[(k + 1) % 4][0] * M, -pts[(k + 1) % 4][1] * M)]) for k in range(4)]
    return out


def _tous_traits(page, M):
    """Tous les cotes droits de tous les calques (le haut d'une marche peut etre le bord d'un palier ou d'un meuble)."""
    out = []
    for d in page.get_drawings():
        for it in d['items']:
            if it[0] == 'l':
                a, b = it[1], it[2]; out.append(LineString([(a.x * M, -a.y * M), (b.x * M, -b.y * M)]))
            elif it[0] == 're':
                r = it[1]; pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                out += [LineString([(pts[k][0] * M, -pts[k][1] * M), (pts[(k + 1) % 4][0] * M, -pts[(k + 1) % 4][1] * M)]) for k in range(4)]
    return out


def _axe(poly):
    c = list(poly.minimum_rotated_rectangle.exterior.coords)
    e = [(c[0], c[1]), (c[1], c[2])]; lo, la = max(e, key=lambda s: math.dist(*s)), min(e, key=lambda s: math.dist(*s))
    cx, cy = (c[0][0] + c[2][0]) / 2, (c[0][1] + c[2][1]) / 2      # centre du rectangle : l'axe est le grand cote ramene au milieu
    mx, my = cx - (lo[0][0] + lo[1][0]) / 2, cy - (lo[0][1] + lo[1][1]) / 2
    return LineString([(lo[0][0] + mx, lo[0][1] + my), (lo[1][0] + mx, lo[1][1] + my)]), math.dist(*la)


def detecter(page, layer, M, cfg=None):
    """Retourne (volees, barres) : volees = [{lignes: [LineString] tries, giron_m}], barres = polygones fins a retirer des murs (m, repere page)."""
    cfg = cfg or {}
    ep = cfg.get('epaisseur_max_m', 0.12); lmin, lmax = cfg.get('longueur_min_m', 0.5), cfg.get('longueur_max_m', 4.0)
    dm = cfg.get('distance_mur_m', 0.12); ecart = cfg.get('ecart_max_m', 0.5)
    W = P.walls_of(page, layer)
    if W is None or W.is_empty: return [], []
    r = ep / 2
    Wm = W.buffer(-r, join_style='mitre').buffer(r, join_style='mitre')          # murs epais seulement
    fins = [p for p in P.polys(W.difference(Wm.buffer(0.01, join_style='mitre'))) if p.area > 1e-4]
    cands = []
    for p in fins:
        ax, la = _axe(p)
        if la <= ep and lmin <= ax.length <= lmax:     # la barre a perdu 1 cm a chaque bout en la separant des murs : on le lui rend
            k = (ax.length + 0.024) / ax.length; cands.append((scale(ax, k, k, origin='centroid'), p))
    cands += [(s, None) for s in _segments_traits(page, layer, M) if lmin <= s.length <= lmax]
    bons = []
    for s, p in cands:
        a, b = Point(s.coords[0]), Point(s.coords[-1]); mid = s.interpolate(0.5, normalized=True)
        if a.distance(Wm) <= dm and b.distance(Wm) <= dm and mid.distance(Wm) > 0.15 and not any(s.distance(t) < 0.03 and abs(s.length - t.length) < 0.05 for t, _ in bons):
            bons.append((s, p))
    ang = lambda s: math.atan2(s.coords[-1][1] - s.coords[0][1], s.coords[-1][0] - s.coords[0][0]) % math.pi
    # marches qui depassent dans la piece : traits paralleles et de meme longueur, a moins d'un giron d'une marche deja trouvee
    ajout = True
    while ajout:
        ajout = False
        for s, p in cands:
            if any(s.equals(t) or (s.distance(t) < 0.03 and abs(s.length - t.length) < 0.05) for t, _ in bons): continue
            for t, _ in bons:
                da = abs(ang(s) - ang(t)); da = min(da, math.pi - da)
                if da < math.radians(6) and 0.1 < s.distance(t) < ecart and abs(s.length - t.length) < 0.3 * t.length \
                        and s.interpolate(0.5, normalized=True).distance(t) < ecart and s.interpolate(0.5, normalized=True).distance(Wm) > 0.15:
                    bons.append((s, p)); ajout = True; break
    # traits paralleles proches : une volee
    volees, vus, tous = [], set(), None
    for i, (s, _) in enumerate(bons):
        if i in vus: continue
        grp = [i]; vus.add(i)
        for j, (t, _) in enumerate(bons):
            if j in vus: continue
            da = abs(ang(s) - ang(t)); da = min(da, math.pi - da)
            if da < math.radians(6) and any(bons[k][0].distance(t) < ecart for k in grp): grp.append(j); vus.add(j)
        lignes = [bons[k][0] for k in grp]
        u = (math.cos(ang(s)), math.sin(ang(s))); nrm = (-u[1], u[0])
        off = lambda l: l.interpolate(0.5, normalized=True).x * nrm[0] + l.interpolate(0.5, normalized=True).y * nrm[1]
        lignes.sort(key=off)
        if len(lignes) == 1 and cfg.get('chercher_le_haut', True):
            # un seul trait : le haut de la marche est souvent le bord d'autre chose (palier, meuble), parallele et de meme longueur
            s0 = lignes[0]; m0 = s0.interpolate(0.5, normalized=True)
            if tous is None: tous = _tous_traits(page, M)
            parts = []
            for t in tous:
                if t.length < 0.7 * s0.length or t.length > 1.3 * s0.length: continue
                da = abs(ang(s0) - ang(t)); da = min(da, math.pi - da)
                dd = t.distance(m0)
                if da < math.radians(6) and 0.15 < dd < ecart and t.interpolate(0.5, normalized=True).distance(m0) < ecart: parts.append((dd, t))
            if parts:
                t = min(parts, key=lambda x: x[0])[1]
                sg = 1 if off(s0) > off(t) else -1
                nrm = (sg * nrm[0], sg * nrm[1])      # les autres traits du cote +n du haut
                lignes = [t, s0]
        off = lambda l: l.interpolate(0.5, normalized=True).x * nrm[0] + l.interpolate(0.5, normalized=True).y * nrm[1]
        giron = abs(off(lignes[-1]) - off(lignes[0])) / (len(lignes) - 1) if len(lignes) > 1 else None
        volees.append(dict(lignes=lignes, giron_m=giron, normale=nrm))
    barres = [p for _, p in bons if p is not None]
    return volees, barres


def cote(n):
    """Normale (x est, y nord) -> cote cardinal au sens de build_v4.half_plane."""
    return ('nord' if n[1] > 0 else 'sud') if abs(n[1]) >= abs(n[0]) else ('est' if n[0] > 0 else 'ouest')


def reglages(page, layer, M, niveau, cfg=None, depart=0):
    """Entrees changements_de_niveau pour une page : la ligne du haut est le premier trait, on monte du cote oppose aux autres."""
    volees, _ = detecter(page, layer, M, cfg)
    out = []
    for k, v in enumerate(volees):
        L = v['lignes']; haut = L[0]; n = v['normale']
        monte = (-n[0], -n[1])         # les autres traits sont du cote +n : on monte de l'autre cote
        to_pt = lambda c: [round(c[0] / M, 1), round(-c[1] / M, 1)]
        out.append(dict(niveau=niveau, nom=f'marches {depart + k + 1} (lues sur le plan)', ligne_plan_pt=[to_pt(haut.coords[0]), to_pt(haut.coords[-1])],
                        cote_qui_monte=cote(monte), mode='marches', marches=len(L), hauteur_marche_m=(cfg or {}).get('hauteur_marche_m', 0.17), cote_m=None,
                        giron_m=round(v['giron_m'], 3) if v['giron_m'] else 0.28, auto=True))
        if len(L) > 1:      # girons : du haut jusqu'a la derniere marche, extremites dans le meme ordre
            a0, b0 = haut.coords[0], haut.coords[-1]; bas = L[-1]; a1, b1 = bas.coords[0], bas.coords[-1]
            if math.dist(a0, a1) + math.dist(b0, b1) > math.dist(a0, b1) + math.dist(b0, a1): a1, b1 = b1, a1
            out[-1]['giron_plan_pt'] = [to_pt(a0), to_pt(a1), to_pt(b1), to_pt(b0)]
    return out
