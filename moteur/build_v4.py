"""Prototype v0.7 : plan Illustrator -> GLB. Aucun reglage dans le code : tout vient de reglages.json,
organise comme les etapes de l'editeur (import, murs, ouvertures et escaliers, materiaux).
Usage : python3 build_v4.py plan.ai sortie.glb [reglages.json]"""
import sys, re, json, math, subprocess, numpy as np, pymupdf, trimesh
from shapely.geometry import Point, box, LineString
from shapely.ops import unary_union
from shapely import affinity
from PIL import Image
import plan2glb as P, stairs as S, spiral2 as SP, voute as V, colimacon_blender as CB, portes as PO, equipements as EQ, pieces as PI


def load(path):
    R = json.load(open(path, encoding='utf-8'))
    m = 25.4 / 72 / 1000 * R['etape_1_import']['echelle']      # 1 pt papier -> metres reels
    P.PT_TO_M = S.M = m
    return R, m


def pbr(name, c, tex=None, blend=False):
    rgba = P.lin(list(c['couleur']) + [255])
    if blend: rgba = rgba[:3] + [c.get('opacite', 1.0)]
    kw = dict(name=c.get('nom', name), baseColorFactor=rgba, metallicFactor=c.get('metal', 0.0), roughnessFactor=c.get('rugosite', 0.85))
    if tex is not None: kw.update(baseColorTexture=tex, baseColorFactor=[255, 255, 255, 255])
    if blend: kw.update(alphaMode='BLEND', doubleSided=True)
    return trimesh.visual.material.PBRMaterial(**kw)


def solid(ms):
    return trimesh.util.concatenate(ms) if len(ms) > 1 else (ms[0] if ms else None)


def delta_of(ch):
    return ch['cote_m'] if ch.get('mode') == 'cote' else ch['marches'] * ch['hauteur_marche_m']


def half_plane(line, side, dx, dy):
    (x1, y1), (x2, y2) = [S.pt(x, y, dx, dy) for x, y in line]
    d = np.array([x2 - x1, y2 - y1]); d /= np.linalg.norm(d); nrm = np.array([-d[1], d[0]])
    want = {'nord': (1, 1), 'sud': (1, -1), 'est': (0, 1), 'ouest': (0, -1)}[side]
    if np.sign(nrm[want[0]]) != want[1]: nrm = -nrm
    a, b = np.array([x1, y1]) - 60 * d, np.array([x2, y2]) + 60 * d
    return P.Polygon([tuple(a), tuple(b), tuple(b + 60 * nrm), tuple(a + 60 * nrm)])


def main(src, dst, cfg='reglages.json'):
    R, M = load(cfg)
    imp, murs, esc, mat = R['etape_1_import'], R['etape_2_murs'], R['etape_3_ouvertures_escaliers'], R['etape_4_materiaux']
    eq = R.get('etape_5_mobilier_eclairage', {})
    cal = imp['calques']; niveaux = imp['niveaux']
    by_name = {n['nom']: i for i, n in enumerate(niveaux)}
    SLAB, LINTEL = murs['epaisseur_dalle_m'], murs['hauteur_linteau_m']
    CLOSE, FOOT = murs['linteaux_ouverture_max_m'] / 2, murs['emprise_fermeture_m']
    sol, pl = mat['sol'], mat['plinthes']

    # niveaux empiles dans l'ordre de la liste, le premier a z = 0, les suivants en dessous
    # (TODO editeur : choisir pour chaque niveau s'il est au-dessus ou en dessous du precedent)
    Z = [0.0]
    for n in niveaux[1:]: Z.append(Z[-1] - (n['hauteur_sous_plafond_m'] + SLAB))
    CEIL = [n['hauteur_sous_plafond_m'] for n in niveaux]

    doc = pymupdf.open(src)
    pages = [doc[n['page'] - 1] for n in niveaux]
    centers = [S.spiral_center(p, cal['escalier_helicoidal']) for p in pages]
    al = imp['alignement_niveaux']
    if al.get('decalage_manuel_m'):
        shift = [(0, 0)] + [(dx / M, -dy / M) for dx, dy in al['decalage_manuel_m']]
    else:   # caler chaque niveau sur l'axe de l'escalier helicoidal du premier
        c0 = centers[0][0]; shift = [(c0[0] - c[0][0], c0[1] - c[0][1]) for c in centers]
    for i, s in enumerate(shift[1:], 1):
        print('decalage %s -> %s : %.2f m, %.2f m' % (niveaux[i]['nom'], niveaux[0]['nom'], s[0] * M, s[1] * M))

    tiles = 2
    def sol_of(over):        # reglages de sol : generaux, completes par ceux de la piece
        d = dict(sol); d.update({k: v for k, v in (over or {}).items() if v is not None}); return d
    def joint_px(d, px=1024):  # largeur du joint en mm -> pixels de la texture (2 x 2 carreaux)
        return max(1, round(d.get('largeur_joint_mm', 9) / 1000 / d['taille_carreau_m'] * px / tiles))
    S.tile_texture('carrelage.png', px=1024, tiles=tiles, joint=joint_px(sol), color=sol['couleur'], joint_color=sol['couleur_joint'])
    md = dict(sol_of(None), **mat.get('marches', {}))     # carrelage des marches : propre, sinon celui du sol
    S.tile_texture('carrelage_marches.png', px=1024, tiles=tiles, joint=joint_px(md), color=md['couleur'], joint_color=md['couleur_joint'])
    mats = dict(murs=pbr('murs', mat['murs']), sol=pbr('carrelage', sol, Image.open('carrelage.png')),
                marches=pbr('carrelage marches', dict(md, nom='carrelage marches'), Image.open('carrelage_marches.png')),
                plinthes=pbr('plinthes', pl), dalle=pbr('plafond', mat['plafond']), escalier=pbr('escalier', mat['escalier_droit']),
                voute=trimesh.visual.material.PBRMaterial(name='plafond voute', baseColorFactor=P.lin(list(mat['plafond']['couleur']) + [255]),
                    roughnessFactor=mat['plafond'].get('rugosite', 0.95), metallicFactor=0.0, doubleSided=True),
                porte=pbr('portes', mat['portes']), lum=pbr('luminaires', mat['luminaires']), rail=pbr('rails', mat['rails']), placard=pbr('placards', mat['placards']), chassis=pbr('chassis', mat['chassis']), verre=pbr('verre', mat['verre'], blend=True),
                bois=pbr('bois', mat['bois']), acier=pbr('acier', mat['acier']), tole=pbr('tole perforee', mat['tole_perforee'], blend=True))

    hel = esc['escalier_helicoidal']
    lo, hi = by_name[hel['niveau_bas']], by_name[hel['niveau_haut']]
    spiral_xy = S.pt(*centers[hi][0], *shift[hi]); Rsp = centers[hi][1] * M * hel['rayon_facteur']
    tremie = Point(spiral_xy).buffer(Rsp + hel['tremie_marge_m'], 64)

    scene = trimesh.Scene()
    def add(name, mesh, m, uv=None, box_uv=False):
        if mesh is None: return
        if box_uv:   # faces verticales (contremarches) : u le long de la face, v en hauteur
            mesh = mesh.copy(); mesh.unmerge_vertices()
        v = mesh.vertices
        if uv:   # uv = reglages de sol : carreaux de taille t, decales de (x, y) metres
            t = uv['taille_carreau_m']
            UV = np.c_[v[:, 0] - uv.get('decalage_x_m', 0), v[:, 1] - uv.get('decalage_y_m', 0)]
            if box_uv:
                fn = mesh.face_normals; side = np.abs(fn[:, 2]) < 0.5
                for f_, nrm in zip(mesh.faces[side], fn[side]):
                    tx, ty = -nrm[1], nrm[0]
                    UV[f_, 0] = v[f_, 0] * tx + v[f_, 1] * ty - uv.get('decalage_x_m', 0)
                    UV[f_, 1] = v[f_, 2] - uv.get('decalage_y_m', 0)
            th = math.radians(uv.get('rotation_deg', 0) or 0); c_, s_ = math.cos(th), math.sin(th)
            UV = np.c_[c_ * UV[:, 0] + s_ * UV[:, 1], -s_ * UV[:, 0] + c_ * UV[:, 1]]     # motif tourne de rotation_deg
            mesh.visual = trimesh.visual.TextureVisuals(uv=UV / (tiles * t), material=m)
        else: mesh.visual = trimesh.visual.TextureVisuals(material=m)
        scene.add_geometry(mesh, geom_name=name)

    DEP = esc.get('deplacements', {})      # {element: {x_m, y_m, z_m}} : elements deplaces dans l'editeur (X est, Y nord, Z haut)
    def deplacement(el):
        d_ = DEP.get(el) or {}
        return (float(d_.get('x_m', 0) or 0), float(d_.get('y_m', 0) or 0), float(d_.get('z_m', 0) or 0))

    clean = murs['nettoyage_bandes_etroites_m'] / 2
    vaults = {}
    pcfg_p = imp.get('pieces', {})
    rooms_out = []; walls_out = []; marches_out = []; portes_out = []
    for i, page in enumerate(pages):
        z, H = Z[i], CEIL[i]; dx, dy = shift[i]
        mv = lambda g: affinity.translate(g, dx * M, -dy * M)
        W = mv(P.walls_of(page, cal['murs']))
        cl = niveaux[i].get('linteaux_ouverture_max_m', 2 * CLOSE) / 2      # reglage par niveau, sinon global
        closed = W.buffer(cl, join_style='mitre').buffer(-cl, join_style='mitre')
        doors = mv(unary_union([box(d['rect'].x0 * M, -d['rect'].y1 * M, d['rect'].x1 * M, -d['rect'].y0 * M)
                     for d in page.get_drawings() if d.get('layer', '').startswith(cal['portes'])]).buffer(murs['linteaux_marge_portes_m']))
        lintels = closed.difference(W).intersection(doors).buffer(-0.01).buffer(0.01)
        n = f'niveau{i}'
        # linteaux ajustes : relier les deux murs de part et d'autre de l'ouverture (meme epaisseur que les murs)
        extra_lintels = []     # linteaux traces a la main sur une ouverture sans porte : (forme, hauteur du dessous)
        for la in [x for x in murs.get('linteaux_traces', []) if by_name[x['niveau']] == i]:
            zone = LineString([S.pt(x, y, dx, dy) for x, y in la['ligne_plan_pt']]).buffer(la.get('rayon_recherche_m', 0.35))
            hull = unary_union(P.polys(W.intersection(zone))).convex_hull.difference(W).buffer(-0.01).buffer(0.01)
            lintels = lintels.difference(zone)
            extra_lintels.append((hull, la.get('hauteur_dessous_m', LINTEL)))
            print(f"  linteau trace : {la['nom']} ({hull.area:.2f} m2, dessous a {la.get('hauteur_dessous_m', LINTEL):.2f} m)")
        for la in [x for x in murs.get('linteaux_ajustes', []) if by_name[x['niveau']] == i]:
            q = Point(*la['porte_plan_pt'])
            rr = next((dd['rect'] for dd in page.get_drawings() if dd.get('layer', '').startswith(cal['portes'][:5])
                       and dd['rect'].x0 - 1 <= q.x <= dd['rect'].x1 + 1 and dd['rect'].y0 - 1 <= q.y <= dd['rect'].y1 + 1), None)
            if rr is None: print('  porte introuvable :', la['nom']); continue
            zone = mv(box(rr.x0 * M, -rr.y1 * M, rr.x1 * M, -rr.y0 * M)).buffer(la.get('rayon_recherche_m', 0.4))
            hull = unary_union(P.polys(W.intersection(zone))).convex_hull.difference(W).buffer(-0.01).buffer(0.01)
            lintels = lintels.difference(zone).union(hull)
            print(f"  linteau ajuste : {la['nom']} ({hull.area:.2f} m2)")
        # portes deplacees (etape Ouvertures) : l'ancienne ouverture est rebouchee, le mur est perce au nouvel endroit
        pcfg = esc.get('portes', {})
        lv = PO.leaves(page, [cal['portes'], cal.get('portes_coulissantes', 'Porte coulissante')], dx, dy,
                       pcfg.get('longueur_min_trait_pt', 25), pcfg.get('epaisseur_vantail_m', 0.04))
        # ouvertures des portes dans les murs, apres les linteaux ajustes. On ne garde que la partie de l'epaisseur d'un mur :
        # une petite piece refermee par la fermeture (toilettes) n'est pas une ouverture.
        r_ep = murs.get('epaisseur_max_ouverture_m', 0.80) / 2
        def ouverture(g_):    # bande entre les deux tableaux (bouts de mur qui bordent l'ouverture), sans ce qui deborde dans les pieces
            b_ = W.intersection(g_.buffer(0.03)).convex_hull.intersection(g_)
            return b_.difference(b_.buffer(-r_ep).buffer(r_ep, join_style='mitre')).buffer(-0.005).buffer(0.005)
        ouvertures0 = [q for g_ in P.polys(lintels) for q in P.polys(ouverture(g_)) if q.area > 0.01]
        door_shift, alleges = {}, []
        # charniere et angle de chaque vantail : 0 deg = porte fermee (dans l'axe de son ouverture), angle du plan = a0
        baies_c = []
        for v in [v for v in esc.get('vitrines', []) if by_name[v['niveau']] == i]:
            p0_, p1_ = S.pt(*v['de_plan_pt'], dx, dy), S.pt(*v['a_plan_pt'], dx, dy); L_ = math.dist(p0_, p1_)
            for a_, b_ in v.get('baies_porte_u_m', []):
                u_ = (a_ + b_) / 2; baies_c.append(Point(p0_[0] + (p1_[0] - p0_[0]) * u_ / L_, p0_[1] + (p1_[1] - p0_[1]) * u_ / L_))
        door_info = {}
        for k, l in enumerate(lv):
            rc = list(l.minimum_rotated_rectangle.exterior.coords)[:4]
            sides = sorted([(math.dist(rc[j], rc[(j + 1) % 4]), j) for j in range(4)])[:2]     # les deux petits cotes
            ends = [Point((rc[j][0] + rc[(j + 1) % 4][0]) / 2, (rc[j][1] + rc[(j + 1) % 4][1]) / 2) for _, j in sides]
            near_ = [g_ for g_ in ouvertures0 if g_.distance(l) < 0.6]
            gap = max(near_, key=lambda g_: g_.area / (0.05 + g_.distance(l)), default=None)
            bc = min(baies_c, key=lambda q: q.distance(l), default=None)
            if bc is not None and bc.distance(l) > 1.2: bc = None
            ref = gap if gap is not None else (bc if bc is not None else W)
            h_, o_ = sorted(ends, key=lambda e: e.distance(ref))
            tl = math.atan2(o_.y - h_.y, o_.x - h_.x)
            if gap is not None or bc is not None:
                if gap is not None:
                    gr = list(gap.minimum_rotated_rectangle.exterior.coords)[:4]
                    j = max(range(2), key=lambda j: math.dist(gr[j], gr[j + 1])); ax = (gr[j + 1][0] - gr[j][0], gr[j + 1][1] - gr[j][1])
                    tgt = gap.centroid
                else:
                    tgt = bc; ax = (tgt.x - h_.x, tgt.y - h_.y)
                if ax[0] * (tgt.x - h_.x) + ax[1] * (tgt.y - h_.y) < 0: ax = (-ax[0], -ax[1])
                tg = math.atan2(ax[1], ax[0])
            else:
                tg = tl - math.pi / 2                # ouverture inconnue : on suppose le vantail dessine ouvert a 90 deg
            a0 = (math.degrees(tl - tg) + 180) % 360 - 180
            door_info[k] = (h_, round(a0, 1))
        W0 = W                               # murs du plan : emprise du batiment et pieces restent les memes quand une porte bouge
        for k, l in enumerate(lv):
            ddx, ddy, ddz = deplacement(f'{n}_porte_{k}')
            if not (ddx or ddy or ddz): continue
            door_shift[k] = (ddx, ddy, ddz)
            near_ = [g_ for g_ in ouvertures0 if g_.distance(l) < 0.6]
            gap = max(near_, key=lambda g_: g_.area / (0.05 + g_.distance(l)), default=None)
            if gap is None or gap.distance(l) > 0.6: print(f'  porte {k} : ouverture introuvable, seul le vantail bouge'); continue
            filled = W.union(gap)
            ng = affinity.translate(gap, ddx, ddy).intersection(filled).buffer(-0.005).buffer(0.005)
            W = filled.difference(ng)
            lintels = lintels.difference(gap.buffer(0.03))
            extra_lintels = [(g_.difference(gap.buffer(0.03)), h_) for g_, h_ in extra_lintels] + [(ng, LINTEL + ddz)]
            if ddz > 0: alleges.append((ng, ddz))           # porte ou fenetre surelevee : mur plein en dessous
            print(f'  porte {k} deplacee de ({ddx:.2f}, {ddy:.2f}, {ddz:.2f}) m, ouverture deplacee avec')
        big = W0.buffer(FOOT, join_style='mitre').buffer(-FOOT, join_style='mitre')
        outline = unary_union([P.Polygon(p.exterior) for p in P.polys(big)])
        walls_out.append([r_ for p_ in P.polys(W.simplify(0.005)) for r_ in [p_.exterior] + list(p_.interiors)])   # pour l'accroche de l'editeur
        # zones exclues (etape import) : rien n'y est genere, ni murs, ni sol, ni equipements
        EX = unary_union([P.Polygon([S.pt(x, y, dx, dy) for x, y in z_['polygone_plan_pt']]).buffer(0)
                          for z_ in imp.get('zones_exclues', []) if by_name[z_['niveau']] == i and len(z_['polygone_plan_pt']) >= 3])
        if not EX.is_empty:
            W, lintels, outline = W.difference(EX), lintels.difference(EX), outline.difference(EX)
            print(f"  zones exclues : {EX.area:.1f} m2")
        floor = outline.difference(W)
        if i == hi and lo != hi: floor, outline = floor.difference(tremie), outline.difference(tremie)
        plinth = W.buffer(pl['epaisseur_m'], join_style='mitre').difference(W).intersection(floor)
        if not EX.is_empty: extra_lintels = [(g_.difference(EX), h_) for g_, h_ in extra_lintels]
        add(f'{n}_murs', solid(P.extrude(W, z, H, None) + P.extrude(lintels, z + LINTEL, H - LINTEL, None)
                               + [m_ for g_, h_ in extra_lintels for m_ in P.extrude(g_, z + h_, H - h_, None)]
                               + [m_ for g_, h_ in alleges for m_ in P.extrude(g_, z, h_, None)]), mats['murs'])
        sols, plin, marches_parts = [], [], []      # sols : (forme, z bas, epaisseur), decoupes ensuite par piece
        # zones de sol a hauteur constante : [sol, plinthes, hauteur]. Chaque marche releve la partie qui touche sa ligne, cote haut,
        # a partir de la hauteur de la zone ou elle se trouve (les marches successives se cumulent)
        regions = [[floor, plinth, 0.0]]
        for ch in [c for c in murs['changements_de_niveau'] if by_name[c['niveau']] == i]:
            dz = delta_of(ch)
            N = max(1, int(ch.get('marches', 1))) if ch.get('mode', 'marches') == 'marches' else 1
            hstep = dz / N
            Lp = [S.pt(x, y, dx, dy) for x, y in ch['ligne_plan_pt']]; LS = LineString(Lp)
            hp0 = half_plane(ch['ligne_plan_pt'], ch['cote_qui_monte'], dx, dy)
            G = P.Polygon([S.pt(x, y, dx, dy) for x, y in ch['giron_plan_pt']]).buffer(0.01) if ch.get('giron_plan_pt') else None
            new_regions = []
            for reg in regions:
                rf, rp, h0 = reg[:3]
                if len(reg) > 3 or rf.is_empty or rf.distance(LS) > 0.3: new_regions.append(reg); continue
                # cote haut : seulement les parties reliees a la ligne (pas tout le demi-plan)
                hp = rf.intersection(hp0).buffer(-clean, join_style='mitre').buffer(clean + 0.02, join_style='mitre')
                hp = unary_union([g_ for g_ in P.polys(hp) if g_.distance(LS) < 0.1])
                treads = []      # marches intermediaires : (forme, hauteur du dessus)
                if N == 1 and G is not None:     # une seule marche : le giron dessine est au niveau haut
                    hp = hp.union(G).intersection(hp0).union(G)
                elif N >= 2:     # la ligne est la derniere contremarche ; les girons descendent du cote bas
                    low = rf.difference(hp0)
                    if G is not None:
                        depth = max(LS.distance(Point(c)) for c in G.exterior.coords); zone = G
                    else:
                        depth = ch.get('giron_m', 0.28) * (N - 1); zone = LS.buffer(depth, cap_style='flat')
                    d1 = depth / (N - 1)
                    for k in range(1, N):
                        band = LS.buffer(k * d1 + 0.005, cap_style='flat').difference(LS.buffer((k - 1) * d1, cap_style='flat'))
                        treads.append((band.intersection(zone).intersection(low).buffer(0), h0 + dz - k * hstep))
                if hp.is_empty: new_regions.append([rf, rp, h0]); continue
                hp = hp.buffer(0.02).intersection(rf.union(rp))
                new_regions.append([rf.intersection(hp), rp.intersection(hp), h0 + dz])
                rf, rp = rf.difference(hp), rp.difference(hp)
                for tg, top in treads:
                    if tg.is_empty: continue
                    new_regions.append([tg.intersection(rf), rp.intersection(tg.buffer(0.03)), top, 'giron'])
                    rf, rp = rf.difference(tg), rp.difference(tg.buffer(0.03))
                new_regions.append([rf, rp, h0])
            regions = new_regions
            print(f"  {ch['nom']} : {N} marche(s) de {hstep * 100:.1f} cm, {dz * 100:.0f} cm")
        for reg in regions:
            rf, rp, h = reg[:3]
            if rf.is_empty and rp.is_empty: continue
            plin += P.extrude(rp, z + h, pl['hauteur_m'], None)
            if len(reg) > 3:      # giron : tout en carrelage de marche
                marches_parts.append((rf, z - 0.02, h + 0.02)); continue
            # sol : dalle fine au carrelage de la piece, posee sur un massif au carrelage des marches (contremarches)
            sols.append((rf, z + h - 0.02, 0.02))
            if h > 0: marches_parts.append((rf, z - 0.02, h))
        if marches_parts:
            mm = [m2 for f_, z0, h in marches_parts for m2 in P.extrude(f_, z0, h, None)]
            add(f'{n}_marches', solid(mm), mats['marches'], uv=dict(sol_of(None), **mat.get('marches', {})), box_uv=True)
        # pieces : detection automatique + pieces et separations dessinees a la main
        to_model = lambda x, y, dx=dx, dy=dy: S.pt(x, y, dx, dy)
        prs = PI.door_rects(page, [cal['portes'], cal.get('portes_coulissantes', 'Porte coulissante')], M, mv)
        steps_l = [c['ligne_plan_pt'] for c in murs['changements_de_niveau'] if by_name[c['niveau']] == i]
        rooms = PI.detect(W0 if EX.is_empty else W0.difference(EX), floor, prs, pcfg_p, niveaux[i]['nom'], to_model, steps_l)
        for ci, ch in enumerate(murs['changements_de_niveau']):    # pieces de part et d'autre de chaque marche, pour l'editeur
            if by_name[ch['niveau']] != i: continue
            Lp = LineString([S.pt(x, y, dx, dy) for x, y in ch['ligne_plan_pt']]); mid = Lp.interpolate(0.5, normalized=True)
            hp0 = half_plane(ch['ligne_plan_pt'], ch['cote_qui_monte'], dx, dy)
            def near(up, mid=mid, hp0=hp0):
                (ax, ay), (bx, by) = Lp.coords[0], Lp.coords[-1]; L_ = Lp.length; nx, ny = -(by - ay) / L_, (bx - ax) / L_
                for k in (0.2, 0.4, 0.7, 1.0):
                    for q in (Point(mid.x + k * nx, mid.y + k * ny), Point(mid.x - k * nx, mid.y - k * ny)):
                        if hp0.contains(q) != up: continue
                        for r in rooms:
                            if not r['supprimee'] and r['poly'].contains(q): return r['nom']
                return None
            marches_out.append(dict(index=ci, niveau_index=i, haut=near(True), bas=near(False)))
        done = P.Polygon()
        for k, r in enumerate(rooms):
            if r['supprimee']:
                rooms_out.append(dict(niveau=niveaux[i]['nom'], index=k, nom=r['nom'], type=r['type'], mode=r['mode'], surface_m2=round(r['poly'].area, 2),
                                      liste_index=r.get('liste_index'), point_plan_pt=r.get('point_plan_pt'), poly=r['poly'], niveau_index=i, supprimee=True))
                print(f"  piece {k + 1} : {r['nom']} supprimee"); continue
            g = r['poly'].difference(done); done = done.union(r['poly'])
            d = sol_of(r['sol'])
            if r['sol']:     # texture propre a la piece
                fn = f'carrelage_{i}_{k}.png'
                S.tile_texture(fn, px=1024, tiles=tiles, joint=joint_px(d), color=d['couleur'], joint_color=d['couleur_joint'])
                m_ = pbr(f'carrelage {niveaux[i]["nom"]} {r["nom"]}', d, Image.open(fn))
            else: m_ = mats['sol']
            add(f'{n}_sol_p{k}', solid([m2 for f_, z0, h in sols for m2 in P.extrude(f_.intersection(g), z0, h, None)]), m_, uv=d)
            print(f"  piece {k + 1} : {r['nom']} ({r['type']}, {r['mode']}) {r['poly'].area:.1f} m2")
            rooms_out.append(dict(niveau=niveaux[i]['nom'], index=k, nom=r['nom'], type=r['type'], mode=r['mode'], surface_m2=round(r['poly'].area, 2),
                                  liste_index=r.get('liste_index'), point_plan_pt=r.get('point_plan_pt'), poly=r['poly'], niveau_index=i))
        add(f'{n}_sol', solid([m2 for f_, z0, h in sols for m2 in P.extrude(f_.difference(done), z0, h, None)]), mats['sol'], uv=sol)
        add(f'{n}_plinthes', solid(plin), mats['plinthes'])
        add(f'{n}_dalle', solid(P.extrude(outline, z - SLAB, SLAB - 0.02, None)), mats['dalle'])
        for pf in [p for p in murs.get('plafonds', []) if by_name[p['niveau']] == i and p['forme'] == 'voute_berceau']:
            k = pf.get('detection_pieces_fermeture_m', 1.5)
            sealed = W.buffer(k, join_style='mitre').buffer(-k, join_style='mitre')
            pt0 = Point(S.pt(*pf['piece_plan_pt'], dx, dy))
            room = next((P.Polygon(h) for p_ in P.polys(sealed) for h in p_.interiors if P.Polygon(h).contains(pt0)), None)
            if room is None: print('  piece introuvable pour', pf['nom']); continue
            vb = V.Berceau(room, pf['hauteur_naissance_m'], pf['hauteur_cle_m'], pf.get('axe_deg'))
            vaults.setdefault(i, []).append(vb)
            add(f'{n}_voute', vb.mesh(z, tremie if i == lo and lo != hi else None), mats['voute'])
            print(f"  {pf['nom']} : portee {2 * vb.a:.2f} m, axe {vb.theta:.0f} deg, naissance {vb.n:.2f} m, cle {vb.n + vb.f:.2f} m")
        # portes : vantaux dessines sur le plan, vitres si un point de reglage tombe dedans
        vit = [Point(S.pt(*q['point'], dx, dy)) for q in pcfg.get('vantaux_vitres_plan_pt', []) if by_name[q['niveau']] == i]
        hv = pcfg.get('hauteur_vantail_m', 2.04)
        npl = nvi = 0
        for k, l in enumerate(lv):          # un element par vantail : niveauN_porte_K (deplacable dans l'editeur)
            if not (EX.is_empty or l.intersection(EX).area < 0.5 * l.area): continue
            sx, sy, sz = door_shift.get(k, (0, 0, 0))
            vitre = any(l.buffer(0.05).contains(q) for q in vit)
            h_, a0 = door_info[k]; el = f'{n}_porte_{k}'
            ouv = (DEP.get(el) or {}).get('ouverture_deg')
            if ouv is not None and abs(float(ouv) - a0) > 0.05:      # angle d'ouverture regle : rotation autour de la charniere
                l = affinity.rotate(l, float(ouv) - a0, origin=h_)
            portes_out.append(dict(element=el, charniere=(h_.x + sx, h_.y + sy), ouverture_plan_deg=a0))
            l = affinity.translate(l, sx, sy)
            if vitre:
                add(f'{n}_porte_{k}__chassis', solid(P.extrude(l.difference(l.buffer(-0.03)) if l.buffer(-0.03).area > 0 else l, z + sz, hv, None)), mats['chassis'])
                add(f'{n}_porte_{k}__vitrage', solid(P.extrude(l, z + sz + 0.06, hv - 0.12, None)), mats['verre']); nvi += 1
            else:
                add(f'{n}_porte_{k}', solid(P.extrude(l, z + sz, hv, None)), mats['porte']); npl += 1
        fr, gl = [], []
        print(f'  portes : {npl} pleines, {nvi} vitree(s)')
        hint = S.pt(*centers[i][0], dx, dy)
        for v in [v for v in esc.get('vitrines', []) if by_name[v['niveau']] == i]:
            # porte de la vitrine deplacee : sa baie (et les montants qui la bordent) glisse le long de la vitrine, sans trou dans le vitrage
            p0_, p1_ = S.pt(*v['de_plan_pt'], dx, dy), S.pt(*v['a_plan_pt'], dx, dy); L_ = math.dist(p0_, p1_)
            ux_, uy_ = (p1_[0] - p0_[0]) / L_, (p1_[1] - p0_[1]) / L_
            baies, mont = [list(b_) for b_ in v.get('baies_porte_u_m', [])], list(v.get('montants_u_m', []))
            for k, (sx, sy, sz) in door_shift.items():
                c_ = lv[k].centroid
                if LineString([p0_, p1_]).distance(c_) > 0.6: continue
                u0, du = (c_.x - p0_[0]) * ux_ + (c_.y - p0_[1]) * uy_, sx * ux_ + sy * uy_
                for b_ in baies:
                    if b_[0] - 0.3 <= u0 <= b_[1] + 0.3:
                        mont = [m_ + du if min(abs(m_ - b_[0]), abs(m_ - b_[1])) < 0.08 else m_ for m_ in mont]
                        b_[0], b_[1] = b_[0] + du, b_[1] + du
                        print(f'  {v["nom"]} : baie de la porte {k} glissee de {du:.2f} m')
            v = dict(v, baies_porte_u_m=baies, montants_u_m=mont)
            wm, fm, gm = PO.vitrine(v, dx, dy, z, H, hint)
            add(f'{n}_vitrine_mur', solid(wm), mats['murs']); fr += fm; gl += gm
            print(f"  {v['nom']} : naissance {v['hauteur_naissance_m']} m, cle {v['hauteur_cle_m']} m")
        add(f'{n}_chassis', solid(fr), mats['chassis']); add(f'{n}_vitrages', solid(gl), mats['verre'])
        # placards, rails d'eclairage, suspensions
        pc = eq.get('placards', {})
        fronts, body = EQ.placards(page, cal.get('placards', 'Placards'), W, floor, dx, dy, pc.get('profondeur_m', 0.62), pc.get('longueur_min_trait_pt', 25))
        if body is not None and not body.is_empty:
            for k, b_ in enumerate(P.polys(body)): add(f'{n}_placard_{k}', solid(P.extrude(b_, z, pc.get('hauteur_m', 2.4), None)), mats['placard'])
            print(f'  placards : {len(fronts)} facade(s), {body.area:.2f} m2')
        rl, sp = [], []
        rg = eq.get('rails_regles', {})
        obst = [Point(*S.pt(*p_['position_plan_pt'], dx, dy)).buffer(p_['diametre_m'] / 2) for p_ in murs['poteaux'] if by_name[p_['niveau']] == i]
        libre = (outline.union(tremie) if i == hi else outline).difference(W.buffer(rg.get('distance_min_murs_m', 0.30)))   # le plafond couvre la tremie
        for o_ in obst: libre = libre.difference(o_.buffer(rg.get('distance_min_obstacles_m', 0.15)))
        for j, r in enumerate([r for r in eq.get('rails', []) if by_name[r['niveau']] == i]):
            rl, sp = [], []
            p0, p1 = S.pt(*r['de_plan_pt'], dx, dy), S.pt(*r['a_plan_pt'], dx, dy)
            for q0, q1 in EQ.clip_rail(p0, p1, libre, rg.get('longueur_min_m', 0.6)):
                mid = Point((q0[0] + q1[0]) / 2, (q0[1] + q1[1]) / 2)
                vb_ = next((vb for vb in vaults.get(i, []) if vb.room.contains(mid)), None)
                aim = EQ.side_to_wall(q0, q1, W)
                marge = rg.get('marge_sous_plafond_m', 0.01)
                if vb_ is None:
                    zA = zB = z + H
                    ceil_fn = lambda x, y: z + H
                else:   # sous une voute : prendre le point le plus bas sous chaque extremite (bord cote mur du rail)
                    ceil_fn = lambda x, y, vb_=vb_: z + vb_.h(x, y)
                    ed = lambda q: min(ceil_fn(q[0] + s_ * aim[0] * 0.02, q[1] + s_ * aim[1] * 0.02) for s_ in (-1, 1))
                    zA, zB = ed(q0) - marge, ed(q1) - marge
                a_, b_ = EQ.rail(q0, q1, zA, r.get('spots_tous_les_m', 1.4), aim, math.radians(rg.get('inclinaison_spots_deg', 30)), z1=zB)
                rl += a_; sp += b_
                jeu = EQ.clearance_under(a_ + b_, ceil_fn)
                ls_ = LineString([q0, q1])
                print(f"  {r.get('nom', 'rail')} {ls_.length:.2f} m : {ls_.distance(W):.2f} m du mur le plus proche"
                      + (f", {min(ls_.distance(o_) for o_ in obst):.2f} m d'un poteau" if obst else '') + f", jeu sous plafond {jeu * 100:.1f} cm")
            add(f'{n}_rail_{j}__rail', solid(rl), mats['rail']); add(f'{n}_rail_{j}__spots', solid(sp), mats['lum'])
        for j, s_ in enumerate([s_ for s_ in eq.get('suspensions', []) if by_name[s_['niveau']] == i]):
            x_, y_ = S.pt(*s_['position_plan_pt'], dx, dy)
            a_, b_ = EQ.suspension(x_, y_, z + H, z + s_['hauteur_bas_m'], s_['diametre_m'])
            add(f'{n}_suspension_{j}__lampe', solid(a_), mats['lum']); add(f'{n}_suspension_{j}__cable', solid(b_), mats['rail'])
        b = W.bounds; print(f"{niveaux[i]['nom']}: {b[2]-b[0]:.2f} x {b[3]-b[1]:.2f} m, plafond {H:.2f} m")

    gen = CB.build if hel.get('moteur') == 'extension_blender' else SP.build
    try:
        wood, steel, panel, nsp = gen(spiral_xy, Rsp, Z[lo], Z[hi], hel)
    except (OSError, subprocess.CalledProcessError) as e:     # Blender introuvable : escalier genere sans Blender
        print('ATTENTION : Blender indisponible (' + str(e).split(':')[0] + '), escalier genere sans Blender')
        wood, steel, panel, nsp = SP.build(spiral_xy, Rsp, Z[lo], Z[hi], hel)
    print('colimacon :', nsp, 'hauteurs de marche')
    post_meshes = {}
    for j, p in enumerate(murs['poteaux']):
        k = by_name[p['niveau']]; x, y = S.pt(*p['position_plan_pt'], *shift[k])
        hp_ = next((vb.h(x, y) for vb in vaults.get(k, []) if vb.room.contains(Point(x, y))), CEIL[k])   # jusqu'a la voute
        c = trimesh.creation.cylinder(radius=p['diametre_m'] / 2, height=hp_, sections=32)
        c.apply_translation([x, y, Z[k] + hp_ / 2])
        post_meshes[(k, j)] = (p.get('materiau', 'acier'), [c])
    add(f'niveau{lo}_colimacon_bois', solid(wood), mats['bois'])
    add(f'niveau{lo}_colimacon_acier', solid(steel), mats['acier'])
    add(f'niveau{hi}_garde_corps', solid(panel), mats['tole'])
    for (k, j), (m, ms) in post_meshes.items(): add(f'niveau{k}_poteau_{j}', solid(ms), mats.get(m, mats['acier']))

    dr = esc.get('escalier_droit')
    if dr:
        lo2, hi2 = by_name[dr['niveau_bas']], by_name[dr['niveau_haut']]
        ms, n = S.straight_stair(pages[lo2], Z[lo2], Z[hi2], *shift[lo2], cfg=dr, layer=cal['mobilier'])
        print('escalier droit :', n, 'marches')
        add(f'niveau{lo2}_escalier', solid(ms), mats['escalier'])

    for gname, g_ in scene.geometry.items():
        el = gname.split('__')[0]
        if re.match(r'niveau\d+_porte_\d+$', el): continue
        t_ = deplacement(el)
        if any(t_): g_.apply_translation(t_); print(f'  {el} deplace de ({t_[0]:.2f}, {t_[1]:.2f}, {t_[2]:.2f}) m')
    scene.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    c = scene.bounds.mean(axis=0); scene.apply_translation([-c[0], 0, -c[2]])
    scene.export(dst); print('ok', dst, scene.extents)
    # axe du colimacon dans le repere du GLB, pour le curseur de rotation de la visionneuse
    axe = dict(x=float(spiral_xy[0] - c[0]), z=float(-spiral_xy[1] - c[2]), rotation_deg=hel.get('rotation_deg', 0), niveaux_y=[float(v) for v in Z])
    json.dump(axe, open(dst.rsplit('.', 1)[0] + '.axe.json', 'w')); print('axe colimacon', axe)
    # pieces dans le repere du GLB (x, z), avec de quoi revenir aux points du plan pour l'editeur
    ring = lambda r_: [[round(x - c[0], 3), round(-y - c[2], 3)] for x, y in r_.coords]
    out = dict(M=M, cx=float(c[0]), cz=float(c[2]), niveaux=[dict(nom=nv['nom'], y=float(Z[k]), dx=shift[k][0], dy=shift[k][1]) for k, nv in enumerate(niveaux)], pieces=[])
    out['murs'] = [[ring(r_) for r_ in lv_] for lv_ in walls_out]
    out['marches'] = marches_out
    out['portes'] = [dict(element=d_['element'], charniere=[round(d_['charniere'][0] - c[0], 3), round(-d_['charniere'][1] - c[2], 3)], ouverture_plan_deg=d_['ouverture_plan_deg']) for d_ in portes_out]
    for r in rooms_out:
        g = r.pop('poly')
        r['contours'] = [dict(ext=ring(p_.exterior), trous=[ring(h) for h in p_.interiors]) for p_ in P.polys(g)]
        lp = g.representative_point(); r['centre'] = [round(lp.x - c[0], 3), round(-lp.y - c[2], 3)]
        out['pieces'].append(r)
    json.dump(out, open(dst.rsplit('.', 1)[0] + '.pieces.json', 'w'), ensure_ascii=False)


if __name__ == '__main__': main(*sys.argv[1:4])
