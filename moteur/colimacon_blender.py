"""Escalier helicoidal genere par l'extension Blender d'Olivier (escalier_colimasson.py), lancee sans interface,
puis complete d'apres les photos : palier d'arrivee, fut prolonge, montants plats, garde-corps de tremie.
Reglages : etape_3_ouvertures_escaliers > escalier_helicoidal (moteur = "extension_blender")."""
import os, json, subprocess, tempfile, numpy as np, trimesh
from shapely.geometry import Polygon
from spiral2 import sweep, circle_profile

HERE = os.path.dirname(os.path.abspath(__file__))


def flat_post(x, y, a, z0, z1, w=0.04, t=0.008, tip=0.05):
    """Montant plat (fer plat) termine en pointe, oriente tangentiellement."""
    prof = Polygon([(-w / 2, 0), (w / 2, 0), (w / 2, z1 - z0 - tip), (0, z1 - z0), (-w / 2, z1 - z0 - tip)])
    m = trimesh.creation.extrude_polygon(prof, t)                    # dans le plan XY, epaisseur en Z
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))   # profil debout
    m.apply_translation([0, t / 2, 0])
    m.apply_transform(trimesh.transformations.rotation_matrix(a + np.pi / 2, [0, 0, 1]))
    m.apply_translation([x, y, z0]); return m


def build(center, R, z_low, z_high, cfg):
    c = cfg; ext = c.get('extension_blender', {}); g = c.get('garde_corps', {}); pal = c.get('palier', {})
    H = z_high - z_low; n = max(3, round(H / c.get('hauteur_marche_max_m', 0.19))); h = H / n
    rot = c.get('rotation_deg', 0)
    a0 = np.radians(c['angle_depart_deg'] + rot); a_end = np.radians(c['angle_arrivee_deg'] + rot)
    ep = c.get('epaisseur_marche_m', 0.04); hr = c.get('main_courante_hauteur_m', 0.92)
    params = dict(_extension=os.path.join(HERE, ext.get('fichier', 'addon/escalier_colimasson.py')),
                  hauteur_totale=H, nb_marches=n, nb_tours=(c['angle_arrivee_deg'] - c['angle_depart_deg']) / 360.0,
                  sens_horaire=c['angle_arrivee_deg'] < c['angle_depart_deg'],
                  rayon_exterieur=R, rayon_interieur=c.get('rayon_fut_m', 0.075), rayon_moyeu=c.get('rayon_fut_m', 0.075),
                  epaisseur_marche=ep, hauteur_limon=c.get('limon_hauteur_m', 0.32), hauteur_garde_corps=hr,
                  nb_lisses=len(c.get('lisses_hauteurs_m', [0, 0, 0])), epaisseur_main_courante=0.042,
                  afficher_panneau=False, afficher_poteaux=False, type_garde_corps='LISSES')
    params.update({k: v for k, v in ext.items() if k not in ('fichier', 'python_blender')})
    if params['sens_horaire']: params['nb_tours'] = -params['nb_tours']
    with tempfile.TemporaryDirectory() as td:
        pj, out = os.path.join(td, 'p.json'), os.path.join(td, 'esc.glb')
        json.dump(params, open(pj, 'w'))
        script = os.path.join(HERE, 'blender_colimacon.py')
        if os.environ.get('ATELIER_BLENDER'):          # Blender installe sur l'ordinateur (logiciel de bureau)
            cmd = [os.environ['ATELIER_BLENDER'], '-b', '--factory-startup', '--python', script, '--', pj, out]
        else:                                          # Python avec le module bpy
            cmd = [os.environ.get('ATELIER_PYTHON_BLENDER') or os.path.join(HERE, ext.get('python_blender', '../bvenv/bin/python')), script, pj, out]
        subprocess.run(cmd, check=True, capture_output=True)
        sc = trimesh.load(out)
        T = trimesh.transformations.rotation_matrix(a0, [0, 0, 1])
        T[:3, 3] = [center[0], center[1], z_low + h - ep]          # le dessus de la marche k est a (k+1) hauteurs
        wood, steel, panel = [], [], []
        for node in sc.graph.nodes_geometry:
            M, gname = sc.graph[node]
            m = sc.geometry[gname].copy(); m.apply_transform(T @ M)
            (wood if node.startswith('Marche') else steel).append(m)
    cx, cy = center
    # fut prolonge au-dessus du plancher haut (photos : ~1 m)
    pole = trimesh.creation.cylinder(radius=c.get('rayon_fut_m', 0.075), height=g.get('hauteur_m', 1.0) + 0.02, sections=32)
    pole.apply_translation([cx, cy, z_high + g.get('hauteur_m', 1.0) / 2]); steel.append(pole)
    # palier d'arrivee au niveau du plancher haut
    pa = np.radians(pal.get('angle_deg', 90))
    if pa > 0:
        arc = [(cx + (R - 0.01) * np.cos(t), cy + (R - 0.01) * np.sin(t)) for t in np.linspace(a_end, a_end + pa, 24)]
        m = trimesh.creation.extrude_polygon(Polygon([center] + arc).buffer(0), ep); m.apply_translation([0, 0, z_high - ep]); wood.append(m)
    # montants plats le long de la volee
    d = (a_end - a0) / n; z_at = lambda a: z_low + (a - a0) / d * h
    for a in np.arange(a0 + d * 1.5, a_end - d * 0.5, d * c.get('montants_tous_les_n_pas', 3)):
        z = z_at(a); steel.append(flat_post(cx + R * np.cos(a), cy + R * np.sin(a), a, z, z + hr + 0.02))
    # garde-corps circulaire de la tremie, ouvert sur le palier
    if g.get('actif', True):
        gh = g.get('hauteur_m', 1.0); p0, p1 = g.get('panneau_perfore_m', [0.08, 0.53])
        g0, g1 = a_end + pa + np.radians(g.get('ouverture_apres_arrivee_deg', 0)), a_end + 2 * np.pi - np.radians(3)
        ga = np.linspace(g0, g1, 200); rg = R + c.get('tremie_marge_m', 0.08) + 0.01
        steel.append(sweep(center, [(a, rg, z_high + gh) for a in ga], circle_profile(0.021)))
        for off in g.get('lisses_hauteurs_m', [0.62, 0.74, 0.86]) + [p0, p1]:
            steel.append(sweep(center, [(a, rg, z_high + off) for a in ga], circle_profile(0.008, 6)))
        panel.append(sweep(center, [(a, rg, z_high + p0) for a in ga], [(0, 0), (0.004, 0), (0.004, p1 - p0), (0, p1 - p0)]))
        for a in np.linspace(g0, g1, g.get('nombre_montants', 9)):
            steel.append(flat_post(cx + (rg + 0.012) * np.cos(a), cy + (rg + 0.012) * np.sin(a), a, z_high, z_high + gh + 0.02))
        bh = g.get('bandeau_sous_tremie_m', 0.2)
        panel.append(sweep(center, [(a, R + c.get('tremie_marge_m', 0.08), z_high - bh) for a in np.linspace(0, 2 * np.pi, 160)],
                           [(0, 0), (0.004, 0), (0.004, bh), (0, bh)]))
    return wood, steel, panel, n
