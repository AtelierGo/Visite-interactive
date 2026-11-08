"""Detection des pieces d'un niveau et application des reglages de l'etape Pieces.

Une piece = une zone du sol separee des autres par les murs, les ouvertures de porte
(calques Porte*) et les passages etroits. Les separations dessinees a la main coupent
les espaces ouverts ; les pieces dessinees a la main remplacent la detection sur leur emprise.
"""
from shapely.geometry import Point, Polygon, LineString, box
from shapely.ops import unary_union
import re, unicodedata
import plan2glb as P

TYPES = ['piece', 'sejour', 'chambre', 'cuisine', 'salle_de_bain', 'toilettes', 'couloir', 'entree', 'boutique', 'reserve', 'cave', 'escalier', 'autre']


# mots du nom -> type de piece (sans accents, minuscules)
MOTS_TYPES = [('salle_de_bain', r'salle (de|d) ?(bain|eau)|\bsdb\b|\bsde\b|douche|bathroom'), ('toilettes', r'\bwc\b|toilette|\bw\.c'),
              ('cuisine', r'cuisine|kitchen|kitchenette'), ('chambre', r'chambre|bedroom|\bch\.? ?\d'),
              ('sejour', r'sejour|salon|living|salle a manger|\bsam\b|piece de vie'), ('entree', r'entree|hall|vestibule|sas\b'),
              ('couloir', r'couloir|degagement|circulation|palier|corridor'), ('cave', r'\bcave|cellier|sous-sol'),
              ('boutique', r'boutique|magasin|commerce|showroom|atelier'), ('reserve', r'reserve|stock|rangement|buanderie|local'),
              ('escalier', r'escalier|stair')]
IGNORES = r'echelle|\bplan\b|\bniveau\b|\bcote\b|coupe|elevation|\bnord\b|^n$|scale|\bngf\b|hsp|\bh ?='


def sans_accents(t):
    return ''.join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn').lower()


def type_du_nom(nom):
    s = sans_accents(nom)
    return next((t for t, m in MOTS_TYPES if re.search(m, s)), None)


def est_un_nom(t):
    """Un nom de piece : au moins 3 lettres, surtout des lettres ; pas une cote (« 192 cm », « 2,50 ») ni un titre de plan."""
    t = t.strip(); lettres = sum(c.isalpha() for c in t); autres = sum(not c.isspace() for c in t)
    if lettres < 2 or lettres < 0.5 * autres: return False
    if re.fullmatch(r'[\d\s.,:x×+\-=]*(cm|mm|m|m2|m²|ml)?[\d\s.,]*', sans_accents(t)): return False
    return type_du_nom(t) is not None or (lettres >= 3 and not re.search(IGNORES, sans_accents(t)))


def textes_du_plan(page, exclus=(), seuls=()):
    """Textes du plan regroupes en etiquettes (lignes proches d'un meme calque) : [(x, y, texte)] en points du plan."""
    spans = []
    for s in page.get_texttrace():
        lay = s.get('layer') or ''
        if seuls and not lay.startswith(tuple(seuls)): continue
        if not seuls and exclus and lay.startswith(tuple(exclus)): continue
        t = ''.join(chr(c[0]) for c in s['chars'] if c[0] > 0)
        if t.strip(): spans.append([list(s['bbox']), t, lay, s['size']])
    spans.sort(key=lambda s: (s[0][1], s[0][0]))
    groupes = []
    for b, t, lay, sz in spans:   # meme ligne (bout a bout) ou ligne suivante alignee : meme etiquette
        for g in groupes:
            gb = g[0]
            if g[2] != lay: continue
            meme_ligne = abs(b[1] - gb[3] + (gb[3] - gb[1]) - (b[3] - b[1])) < 0.5 * sz and -0.2 * sz < b[0] - gb[2] < 0.8 * sz
            dessous = 0 <= b[1] - gb[3] < 0.6 * sz and min(b[2], gb[2]) - max(b[0], gb[0]) > -0.3 * sz
            if meme_ligne or dessous:
                g[1] += ('' if meme_ligne and b[0] - gb[2] < 0.15 * sz else ' ') + t
                g[0] = [min(gb[0], b[0]), min(gb[1], b[1]), max(gb[2], b[2]), max(gb[3], b[3])]; break
        else: groupes.append([b, t, lay])
    return [((g[0][0] + g[0][2]) / 2, (g[0][1] + g[0][3]) / 2, re.sub(r'\s+', ' ', g[1]).strip()) for g in groupes if est_un_nom(g[1])]


def zones_de_couleur(page, M, mv, exclus=(), seuls=(), surface_min=1.5):
    """Aplats de couleur fermes (hors murs, portes, mobilier...) : [(polygone, (r, g, b))] en metres, recales comme les murs.
    Une couleur = une zone ; les aplats blancs ou gris ne comptent que sur un calque de pieces (« seuls »)."""
    par_couleur = {}
    for d in page.get_drawings():
        lay = d.get('layer') or ''; f = d.get('fill')
        if f is None or len(f) < 3 or (d.get('fill_opacity') or 1) < 0.05: continue
        if seuls and not lay.startswith(tuple(seuls)): continue
        if not seuls and exclus and lay.startswith(tuple(exclus)): continue
        if not seuls and max(f) - min(f) < 0.08: continue          # blanc, gris, noir : pas une couleur de piece
        rings = [Polygon([(x * M, -y * M) for x, y in sp]).buffer(0) for sp in P.subpaths(d['items'])]
        g = unary_union([r for r in rings if r.area > 1e-4]) if rings else Polygon()
        if g.is_empty: continue
        k = tuple(round(c * 20) / 20 for c in f[:3])
        par_couleur.setdefault(k, []).append(g)
    out = []
    for k, gs in par_couleur.items():
        for p in P.polys(mv(unary_union(gs)).buffer(0)):
            if p.area >= surface_min: out.append((p, tuple(int(c * 255) for c in k)))
    return out


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


def detect(W, floor, doors, cfg, level, to_model, step_lines=(), etiquettes=(), zones=()):
    """Retourne [{poly, nom, type, mode, sol, point}] pour un niveau.
    etiquettes : [(x, y, texte)] en points du plan (noms ecrits sur le plan) ; zones : [(polygone, couleur)] aplats de couleur."""
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
    for z, _ in zones:    # la limite entre deux aplats de couleur separe deux pieces
        cut = cut.union(z.exterior.buffer(0.02))
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
    # noms ecrits sur le plan : l'etiquette dans la piece (celle qui dit un type de piece, sinon la plus proche du centre)
    labs = [(Point(to_model(x, y)), t) for x, y, t in etiquettes]
    for r in out:
        ins = [(type_du_nom(t) is None, r['poly'].centroid.distance(q), t) for q, t in labs if r['poly'].buffer(0.05).contains(q)]
        r['nom_plan'] = min(ins)[2] if ins else None
    for z, col in zones:  # couleur de l'aplat qui couvre la piece
        for r in out:
            if r['poly'].intersection(z).area > 0.6 * r['poly'].area: r['couleur_plan'] = list(col)
    n = 0; vus = {}
    for r in out:
        n += 1; e0 = r.pop('entry'); e = e0 or {}
        r['liste_index'] = cfg.get('liste', []).index(e0) if e0 is not None else None
        np_ = r['nom_plan']
        if np_:      # meme nom sur deux pieces : « Chambre », « Chambre 2 »
            vus[np_] = vus.get(np_, 0) + 1
            if vus[np_] > 1: np_ = f'{np_} {vus[np_]}'
        r.update(nom=e.get('nom') or np_ or f'Pièce {n}', type=e.get('type') or (type_du_nom(np_) if np_ else None) or 'piece', sol=e.get('sol', {}), hauteur=e.get('hauteur_sous_plafond_m'))
        r['source_nom'] = 'reglage' if e.get('nom') else ('plan' if np_ else 'auto')
    return out
