"""Elevations et coupes du fichier Illustrator : images des planches et points d'accroche pour la mesure dans l'editeur.

Reglage etape_1_import.elevations :
  pages   : numeros de pages (plans de travail) qui portent des elevations. Vide = toutes les pages qui ne sont pas un niveau.
  calques : debuts de noms de calques d'elevation. S'ils sont donnes, seuls ces calques sont dessines, et ils sont
            aussi cherches sur les pages des niveaux (elevation placee a cote du plan).
  mesures : mesures faites dans l'editeur et appliquees a un reglage (trace de l'origine de la valeur).
"""
import base64, json


def _calques_ok(nom, prefixes):
    return not prefixes or any(nom.startswith(p) for p in prefixes)


def exporter(doc, niveaux, cfg, m_par_pt, chemin, zoom=3.0):
    import pymupdf
    cfg = cfg or {}
    prefixes = [p for p in cfg.get('calques', []) if p]
    pages_niv = {n['page'] for n in niveaux}
    pages = [p for p in cfg.get('pages', []) if 1 <= p <= len(doc)] or [k + 1 for k in range(len(doc)) if k + 1 not in pages_niv]
    if prefixes:     # elevations dessinees sur un calque a part, aussi sur les pages des niveaux
        pages += [k for k in sorted(pages_niv) if k <= len(doc) and k not in pages
                  and any(_calques_ok(d.get('layer', ''), prefixes) for d in doc[k - 1].get_drawings())]
    ocgs = doc.get_ocgs() or {}
    if prefixes and ocgs:      # n'afficher que les calques d'elevation
        doc.set_layer(-1, on=[x for x, o in ocgs.items() if _calques_ok(o['name'], prefixes)],
                      off=[x for x, o in ocgs.items() if not _calques_ok(o['name'], prefixes)])
    out = []
    for num in pages:
        page = doc[num - 1]
        pts = set()
        for d in page.get_drawings():
            if prefixes and not _calques_ok(d.get('layer', ''), prefixes): continue
            for it in d['items']:
                for q in it[1:]:
                    if hasattr(q, 'x'): pts.add((round(q.x * 2) / 2, round(q.y * 2) / 2))
                    elif hasattr(q, 'x0'):
                        for x_, y_ in ((q.x0, q.y0), (q.x1, q.y0), (q.x1, q.y1), (q.x0, q.y1)): pts.add((round(x_ * 2) / 2, round(y_ * 2) / 2))
        if len(pts) < 10: continue
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        img = 'data:image/jpeg;base64,' + base64.b64encode(pix.tobytes('jpeg', jpg_quality=82)).decode()
        pts = sorted(pts)[:40000]
        try:      # lecture automatique : coupes, hauteurs, voutes, marches
            import lecture_elevations as LE
            lect = LE.lire_page(page, m_par_pt, cfg.get('lecture'), prefixes)
            for k, v in enumerate(lect): v['nom'] = f'Coupe {k + 1}'
            if lect: print(f'  elevations : page {num}, ' + ' ; '.join(f"{v['nom']} {v['forme']} " + (f"{v['hauteur_m']:.2f} m" if v['forme'] == 'plat' else f"{v['hauteur_naissance_m']:.2f}/{v['hauteur_cle_m']:.2f} m") for v in lect))
        except Exception as e:
            lect = []; print('  lecture des elevations impossible :', e)
        out.append(dict(lectures=lect, nom=f'Planche {num}', page=num, largeur_pt=page.rect.width, hauteur_pt=page.rect.height,
                        m_par_pt=m_par_pt, image=img, points=[v for p_ in pts for v in p_]))
        print(f'  elevations : page {num}, {len(pts)} points d\'accroche')
    if prefixes and ocgs: doc.set_layer(-1, on=[x for x, o in ocgs.items() if o['on']], off=[x for x, o in ocgs.items() if not o['on']])
    json.dump(out, open(chemin, 'w'))
    return out
