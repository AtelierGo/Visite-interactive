"""Detection des pieces d'un niveau et application des reglages de l'etape Pieces.

Une piece = une zone du sol separee des autres par les murs, les ouvertures de porte
(calques Porte*) et les passages etroits. Les separations dessinees a la main coupent
les espaces ouverts ; les pieces dessinees a la main remplacent la detection sur leur emprise.
"""
from shapely.geometry import Point, Polygon, LineString, box
from shapely.ops import unary_union
import plan2glb as P

TYPES = ['piece', 'sejour', 'chambre', 'cuisine', 'salle_de_bain', 'toilettes', 'couloir', 'entree', 'boutique', 'reserve', 'cave', 'escalier', 'autre']


def door_rects(page, prefixes, M, mv):
    rs = [box(d['rect'].x0 * M, -d['rect'].y1 * M, d['rect'].x1 * M, -d['rect'].y0 * M).buffer(0.03, join_style='mitre')
          for d in page.get_drawings() if d.get('layer', '').startswith(tuple(prefixes))]
    return mv(unary_union(rs)) if rs else Polygon()


def separators(W, doors, cfg):
    """Ouvertures a couper : fermetures morphologiques de petite surface + emprise des portes."""
    parts = [doors]
    base = W.union(doors)          # les portes comptent comme des murs : on comble l'ecart mur-porte
    smax = cfg.get('ouverture_max_m', 1.8) / 2
    for k in range(1, 7):
        s = smax * k / 6
        c = base.buffer(s, join_style='mitre').buffer(-s, join_style='mitre').difference(base).buffer(-0.01).buffer(0.01)
        parts += [g for g in P.polys(c) if g.area < cfg.get('surface_max_passage_m2', 1.2)]
    return unary_union(parts)


def detect(W, floor, doors, cfg, level, to_model, step_lines=()):
    """Retourne [{poly, nom, type, mode, sol, point}] pour un niveau."""
    entries = [e for e in cfg.get('liste', []) if e['niveau'] == level]
    o = to_model(0, 0); u = to_model(1, 1); sx, sy = u[0] - o[0], u[1] - o[1]
    from_model = lambda X, Y: (round((X - o[0]) / sx, 1), round((Y - o[1]) / sy, 1))
    manual = []
    for e in [e for e in entries if e.get('polygone_plan_pt')]:
        g = Polygon([to_model(*q) for q in e['polygone_plan_pt']]).buffer(0).intersection(floor)
        if not g.is_empty: manual.append((g, e))
    rest = floor.difference(unary_union([g for g, _ in manual])) if manual else floor
    cut = separators(W, doors, cfg) if cfg.get('detection_auto', True) else Polygon()
    lines = [s['ligne_plan_pt'] for s in cfg.get('separations', []) if s['niveau'] == level]
    if cfg.get('couper_aux_changements_de_niveau', True): lines += list(step_lines)
    for ln in lines:      # prolongee de 30 cm de chaque cote pour bien toucher les murs
        L = LineString([to_model(*q) for q in ln]); a, b = L.coords[0], L.coords[-1]
        ux, uy = (b[0] - a[0]) / L.length, (b[1] - a[1]) / L.length
        L = LineString([(a[0] - ux * 0.3, a[1] - uy * 0.3), (b[0] + ux * 0.3, b[1] + uy * 0.3)])
        cut = cut.union(L.buffer(0.02, cap_style='flat'))
    comps = sorted([p for p in P.polys(rest.difference(cut)) if p.area >= cfg.get('surface_min_m2', 0.8)], key=lambda p: -p.area)
    # les morceaux restants (seuils, emprises de portes) rejoignent la piece voisine la plus en contact
    left = P.polys(rest.difference(unary_union(comps)))
    comps = [c for c in comps]
    for g in left:
        gb = g.buffer(0.03)
        k = max(range(len(comps)), key=lambda j: gb.intersection(comps[j]).area, default=None)
        if k is not None and gb.intersects(comps[k]): comps[k] = comps[k].union(g)
    out, used = [], set()
    for idx, c in enumerate(comps):
        c = c.buffer(0.005).buffer(-0.005)
        cand = [(c.distance(Point(to_model(*e['point_plan_pt']))), j) for j, e in enumerate(entries)
                if not e.get('polygone_plan_pt') and e.get('point_plan_pt') and j not in used]
        cand = [x for x in cand if x[0] < 0.5]       # le point peut tomber dans une tremie ou un seuil
        e = entries[min(cand)[1]] if cand else None
        if e is not None: used.add(entries.index(e))
        rp = c.representative_point()
        out.append(dict(poly=c, mode='auto', entry=e, point_plan_pt=e['point_plan_pt'] if e else list(from_model(rp.x, rp.y))))
    for g, e in manual: out.append(dict(poly=g, mode='manuel', entry=e, point_plan_pt=None))
    for r in out: r['supprimee'] = bool((r['entry'] or {}).get('supprimee'))   # supprimee : son sol prend le reglage general
    n = 0
    for r in out:
        n += 1; e0 = r.pop('entry'); e = e0 or {}
        r['liste_index'] = cfg.get('liste', []).index(e0) if e0 is not None else None
        r.update(nom=e.get('nom', f'Pièce {n}'), type=e.get('type', 'piece'), sol=e.get('sol', {}))
    return out
