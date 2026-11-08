"""Lecture automatique des elevations et coupes : hauteurs sous plafond, voutes, plafonds cathedrale, marches.

Une coupe est reconnue a ses aplats gris (murs et dalles coupes, valeur entre gris_min et gris_max).
La planche est rendue en image : on y cherche le sol (haut de la dalle grise du bas), les deux murs et le plafond gris.
Si une courbe (trait) traverse la piece d'un mur a l'autre, c'est une voute : sa naissance (bouts de la courbe)
et sa cle (point le plus haut) sont lues sur le trait ; deux traits droits qui montent vers le milieu = cathedrale.
Le sol : paliers a des hauteurs differentes -> marches.
Reglages (etape_1_import.elevations.lecture) : gris_min, gris_max, surface_min_m2, tolerance_plat_m, hauteur_min_m.
"""
import math
import numpy as np


def _rendu(page, zoom, calques=()):
    import pymupdf
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].astype(np.float32) / 255
    return a


def _ouverture(M, r):
    """Erosion puis dilatation (carre de cote 2r+1) : efface ce qui est plus fin que 2r+1 pixels."""
    def dec(A, dy, dx):
        B = np.zeros_like(A); H, W = A.shape
        B[max(dy, 0):H + min(dy, 0), max(dx, 0):W + min(dx, 0)] = A[max(-dy, 0):H + min(-dy, 0), max(-dx, 0):W + min(-dx, 0)]
        return B
    E = M.copy()
    for d in range(-r, r + 1): E &= dec(M, d, 0)
    E2 = E.copy()
    for d in range(-r, r + 1): E2 &= dec(E, 0, d)
    D = E2.copy()
    for d in range(-r, r + 1): D |= dec(E2, d, 0)
    D2 = D.copy()
    for d in range(-r, r + 1): D2 |= dec(D, 0, d)
    return D2


def _composantes(mask, mini):
    """Composantes 4-connexes d'un masque booleen (parcours en largeur), sous forme de boites (x0, y0, x1, y1, nb)."""
    H, W = mask.shape; vu = np.zeros_like(mask); out = []
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys, xs):
        if vu[y, x]: continue
        pile = [(y, x)]; vu[y, x] = True; x0 = x1 = x; y0 = y1 = y; n = 0
        while pile:
            cy, cx = pile.pop(); n += 1
            x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not vu[ny, nx]:
                    vu[ny, nx] = True; pile.append((ny, nx))
        if n >= mini: out.append((x0, y0, x1, y1, n))
    return out


def _courbes(page, cadre):
    """Traits courbes (ou en biais) d'un seul tenant, entierement dans un cadre (points) : [(xs, ys)] echantillonnes."""
    x0, y0, x1, y1 = cadre; out = []
    for d in page.get_drawings():
        r = d['rect']
        if r.x1 < x0 or r.x0 > x1 or r.y1 < y0 or r.y0 > y1: continue
        chaines, cur, fin = [], [], None
        for it in d['items']:
            if it[0] == 'c':
                p0, p1, p2, p3 = it[1:5]
                pts = [p0 * (1 - t) ** 3 + p1 * 3 * (1 - t) ** 2 * t + p2 * 3 * (1 - t) * t * t + p3 * t ** 3 for t in np.linspace(0, 1, 9)]
            elif it[0] == 'l': pts = [it[1], it[2]]
            else: continue
            if fin is None or abs(pts[0].x - fin.x) + abs(pts[0].y - fin.y) > 0.5:
                if len(cur) >= 2: chaines.append(cur)
                cur = []
            cur += pts; fin = pts[-1]
        if len(cur) >= 2: chaines.append(cur)
        for c in chaines:
            xs, ys = np.array([p.x for p in c]), np.array([p.y for p in c])
            if xs.min() < x0 or xs.max() > x1 or ys.min() < y0 or ys.max() > y1: continue
            if np.ptp(ys) < 2: continue          # trait horizontal : pas une voute
            out.append((xs, ys))
    return out


def lire_page(page, m_par_pt, cfg=None, calques=()):
    cfg = cfg or {}; zoom = cfg.get('zoom', 2.0)
    gmin, gmax = cfg.get('gris_min', 0.6), cfg.get('gris_max', 0.84)
    a = _rendu(page, zoom, calques)
    v = a.mean(2); sat = a.max(2) - a.min(2)
    G = (v >= gmin) & (v <= gmax) & (sat < 0.05)
    G = _ouverture(G, cfg.get('ouverture_px', 3))      # retire les traits fins anticrenelés (gris) : seuls les aplats restent
    m = m_par_pt / zoom                                  # metres par pixel
    # cadres : composantes grises assez grandes (recherche sur une image reduite)
    k = max(1, int(round(zoom * 2)))
    Gr = G[: G.shape[0] // k * k, : G.shape[1] // k * k].reshape(G.shape[0] // k, k, G.shape[1] // k, k).any(axis=(1, 3))
    vues = []
    hmin = cfg.get('hauteur_min_m', 1.8)
    for x0, y0, x1, y1, n in _composantes(Gr, 40):
        X0, Y0, X1, Y1 = x0 * k, y0 * k, (x1 + 1) * k, (y1 + 1) * k
        if (X1 - X0) * m < 1.5 or (Y1 - Y0) * m < hmin: continue
        r = _mesurer(page, G[Y0:Y1, X0:X1], X0, Y0, m, zoom, cfg, v[Y0:Y1])
        if r: vues.append(r)
    vues.sort(key=lambda v: (v['cadre_pt'][1], v['cadre_pt'][0]))
    return vues


def _mesurer(page, g, X0, Y0, m, zoom, cfg, blanc):
    H, W = g.shape; hmin = cfg.get('hauteur_min_m', 1.8)
    cols = range(int(W * 0.3), int(W * 0.7))
    # sol : en partant du bas, premiere ligne non grise apres la dalle
    sols = []
    for c in cols:
        col = g[:, c]; y = H - 1
        while y > 0 and not col[y]: y -= 1          # sous la dalle (marge du cadre)
        while y > 0 and col[y]: y -= 1              # dalle
        y0_ = y
        while y > 0 and y0_ - y < 0.25 / m and blanc[y, X0 + c] < 0.93: y -= 1     # revetement de sol dessine (aplat colore, trait)
        if blanc[y, X0 + c] < 0.93: y = y0_
        if y > 0: sols.append(y)
    if len(sols) < 5: return None
    sol = int(np.median(sols))
    # plafond gris : en montant depuis le sol, premier gris
    def plafond(c):
        y = sol - int(0.3 / m)
        while y > 0 and not g[y, c]: y -= 1
        return y if y > 0 else None
    # murs : a 1 m du sol, du milieu vers les cotes jusqu'au premier gris
    yl = sol - int(1.0 / m); mid = W // 2
    if yl <= 0: return None
    xl = mid
    while xl > 0 and not g[yl, xl]: xl -= 1
    xr = mid
    while xr < W - 1 and not g[yl, xr]: xr += 1
    L = (xr - xl) * m
    if L < 1.0: return None
    hs = [plafond(c) for c in range(xl + 2, xr - 1)]
    hs = [(sol - y) * m for y in hs if y is not None]
    if not hs or max(hs) < hmin: return None
    hp = float(np.median(hs))
    to_pt = lambda px, py: ((X0 + px) / zoom, (Y0 + py) / zoom)
    xa, ya = to_pt(xl, 0); xb, yb = to_pt(xr, sol)
    out = dict(cadre_pt=[round(xa, 1), round(ya, 1), round(xb, 1), round(yb, 1)], largeur_m=round(L, 3))
    # voute ou cathedrale dessinee en trait : courbe d'un mur a l'autre sous le plafond gris
    cands = []
    for xs, ys in _courbes(page, (xa - 5, ya, xb + 5, yb)):
        if xs.max() - xs.min() < 0.6 * (xb - xa): continue
        h = (yb - ys) * m * zoom
        if h.max() > hp + 0.2 or h.min() < 0.8: continue
        cands.append((xs, h))
    tol = cfg.get('tolerance_plat_m', 0.04)
    if cands:
        xs, h = max(cands, key=lambda c: c[1].max() - min(c[1][np.argmin(c[0])], c[1][np.argmax(c[0])]))   # l'arc qui monte le plus d'un mur a l'autre
        nais, cle = float(min(h[np.argmin(xs)], h[np.argmax(xs)])), float(h.max())
        if cle - nais > tol:
            a_ = (xs.max() - xs.min()) * m * zoom / 2; f = cle - nais; R = (a_ * a_ + f * f) / (2 * f); xc = xs[np.argmax(h)]
            d = np.minimum(np.abs(xs - xc) * m * zoom, a_)
            e_arc = float(((h - (nais + np.sqrt(np.maximum(R * R - d * d, 0)) - (R - f))) ** 2).sum())
            e_lin = float(((h - (nais + f * (1 - d / a_))) ** 2).sum())
            out.update(forme='voute_berceau' if e_arc <= e_lin else 'cathedrale', hauteur_naissance_m=round(nais, 3), hauteur_cle_m=round(cle, 3),
                       hauteur_sous_dalle_m=round(hp, 3))
    if 'forme' not in out:
        cen = sorted(hs[len(hs) // 5: len(hs) * 4 // 5] or hs)
        if cen[-1] - cen[0] <= max(tol, 0.1 * hp):
            out.update(forme='plat', hauteur_m=round(float(np.median(cen)), 3))
        else:     # plafond gris courbe (voute dessinee en aplat)
            nais, cle = min(hs[:3] + hs[-3:]), max(hs)
            out.update(forme='voute_berceau', hauteur_naissance_m=round(nais, 3), hauteur_cle_m=round(cle, 3))
    # cotes ecrites a cote de la coupe (« 282 cm », « 273 ») : une cote proche d'une hauteur lue la remplace (valeur voulue par le dessinateur)
    cotes = []
    for b in page.get_text('blocks'):
        if b[2] < xa - 80 or b[0] > xb + 80 or b[3] < ya - 20 or b[1] > yb + 20: continue
        for t in b[4].replace(',', '.').split():
            try: x_ = float(t.replace('cm', ''))
            except ValueError: continue
            if 80 <= x_ <= 900: cotes.append(round(x_ / 100, 3))
    lues = []
    for k_ in ('hauteur_m', 'hauteur_naissance_m', 'hauteur_cle_m'):
        if k_ in out and cotes:
            c_ = min(cotes, key=lambda c: abs(c - out[k_]))
            if abs(c_ - out[k_]) <= cfg.get('ecart_max_cote_m', 0.25): out[k_ + '_mesure'] = out[k_]; out[k_] = c_; lues.append(k_)
    if lues: out['cotes_lues'] = lues
    # marches : paliers du sol entre les murs
    bas = []
    for c in range(xl + 2, xr - 1, 2):
        y = sol + int(0.4 / m)
        y = min(y, H - 1)
        while y > sol - int(1.0 / m) and g[y, c]: y -= 1
        bas.append((sol - y) * m)
    pal = sorted({round(b / 0.02) * 0.02 for b in bas if b > 0.04})
    if pal and len([b for b in bas if b > 0.04]) > 0.1 * len(bas):
        out['marches'] = dict(denivele_m=round(max(pal), 2))
    return out


def lire(doc, pages, m_par_pt, cfg=None, calques=()):
    res = []
    for num in pages:
        for v in lire_page(doc[num - 1], m_par_pt, cfg, calques):
            v.update(page=num, nom=f'Coupe {len(res) + 1} (planche {num})'); res.append(v)
    return res


if __name__ == '__main__':
    import sys, json, pymupdf
    doc = pymupdf.open(sys.argv[1]); m = 25.4 / 72 / 1000 * float(sys.argv[3] if len(sys.argv) > 3 else 50)
    print(json.dumps(lire(doc, [int(sys.argv[2])], m), indent=1, ensure_ascii=False))
