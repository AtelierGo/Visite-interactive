"""Escalier helicoidal d'apres les photos : limon exterieur en tole, marches bois sur platines acier,
fut central, main courante + 3 lisses, garde-corps circulaire autour de la tremie au niveau haut."""
import numpy as np, trimesh
from shapely.geometry import Polygon

def sweep(center, samples, profile):
    """Balaye un profil (dr, dz) le long d'une suite de points (angle, rayon, z)."""
    cx, cy = center; P = len(profile); V, F = [], []
    for a, r, z in samples:
        for dr, dz in profile:
            V.append((cx + (r + dr) * np.cos(a), cy + (r + dr) * np.sin(a), z + dz))
    n = len(samples)
    for i in range(n - 1):
        for j in range(P):
            a, b = i * P + j, i * P + (j + 1) % P
            c, d = a + P, b + P
            F += [(a, b, d), (a, d, c)]
    F += [tuple(range(P))[::-1][k:k + 3] for k in []]
    for k in range(1, P - 1):  # bouchons
        F.append((0, k + 1, k)); F.append(((n - 1) * P, (n - 1) * P + k, (n - 1) * P + k + 1))
    return trimesh.Trimesh(np.array(V), np.array(F), process=True)

def circle_profile(rad, k=8): return [(rad * np.cos(t), rad * np.sin(t)) for t in np.linspace(0, 2 * np.pi, k, endpoint=False)]

def build(center, R, z_low, z_high, cfg=None):
    """Montee dans le sens trigonometrique (vu de dessus, nord en haut), de angle_depart_deg (pied) a angle_arrivee_deg.
    Tous les parametres viennent de reglages.json > etape_3_ouvertures_escaliers > escalier_helicoidal."""
    c = cfg or {}; g = c.get('garde_corps', {})
    rise = c.get('hauteur_marche_max_m', 0.19); tk = c.get('epaisseur_marche_m', 0.04)
    n = max(2, round((z_high - z_low) / rise)); h = (z_high - z_low) / n
    rot = c.get('rotation_deg', 0)       # pivote tout l'escalier (marches, limon, garde-corps) autour de son axe
    a0, a_end = np.radians(c.get('angle_depart_deg', -12) + rot), np.radians(c.get('angle_arrivee_deg', 270) + rot); d = (a_end - a0) / n
    z_at = lambda a: z_low + (a - a0) / d * h          # nez de marche le long de l'helice
    wood, steel, panel = [], [], []
    for k in range(n - 1):                              # la derniere "marche" est le plancher haut
        a1 = a0 + (k + 1) * d; a2 = a1 + d * 0.96; zt = z_low + (k + 1) * h
        arc = [(center[0] + (R - 0.01) * np.cos(t), center[1] + (R - 0.01) * np.sin(t)) for t in np.linspace(a1, a2, 10)]
        tread = Polygon([center] + arc).buffer(0)
        m = trimesh.creation.extrude_polygon(tread, tk); m.apply_translation([0, 0, zt - tk]); wood.append(m)
        s = trimesh.creation.extrude_polygon(tread.buffer(-0.03), 0.012); s.apply_translation([0, 0, zt - tk - 0.012]); steel.append(s)
    pole = trimesh.creation.cylinder(radius=c.get('rayon_fut_m', 0.075), height=z_high - z_low + 1.0, sections=32)
    pole.apply_translation([center[0], center[1], (z_low + z_high + 1.0) / 2]); steel.append(pole)
    # limon exterieur helicoidal en tole 8 mm
    lh = c.get('limon_hauteur_m', 0.32)
    ang = np.linspace(a0 + d * 0.6, a_end, 200)
    steel.append(sweep(center, [(a, R, z_at(a) - 0.25) for a in ang],
                       [(0, -0.05), (0.008, -0.05), (0.008, lh - 0.05), (0, lh - 0.05)]))
    tube = circle_profile(0.021); bar = circle_profile(0.008, 6)
    hr = c.get('main_courante_hauteur_m', 0.92); rails = c.get('lisses_hauteurs_m', [0.36, 0.55, 0.74])
    steel.append(sweep(center, [(a, R + 0.03, z_at(a) + hr) for a in ang], tube))
    for off in rails:
        steel.append(sweep(center, [(a, R + 0.025, z_at(a) + off) for a in ang], bar))
    for a in np.arange(a0 + d * 1.5, a_end, d * c.get('montants_tous_les_n_pas', 3)):
        z = z_at(a); p = trimesh.creation.cylinder(radius=0.012, height=0.7, sections=10)
        p.apply_translation([center[0] + (R + 0.025) * np.cos(a), center[1] + (R + 0.025) * np.sin(a), z + hr - 0.35]); steel.append(p)
    if g.get('actif', True):   # garde-corps circulaire autour de la tremie, ouvert sur l'arrivee
        gh = g.get('hauteur_m', 1.0); p0, p1 = g.get('panneau_perfore_m', [0.08, 0.53])
        g0, g1 = a_end + np.radians(g.get('ouverture_apres_arrivee_deg', 15)), a_end + 2 * np.pi - 2 * d
        ga = np.linspace(g0, g1, 160); rg = R + c.get('tremie_marge_m', 0.08) + 0.01
        steel.append(sweep(center, [(a, rg, z_high + gh) for a in ga], tube))
        for off in g.get('lisses_hauteurs_m', [0.62, 0.78]):
            steel.append(sweep(center, [(a, rg, z_high + off) for a in ga], bar))
        panel.append(sweep(center, [(a, rg, z_high + p0) for a in ga], [(0, 0), (0.004, 0), (0.004, p1 - p0), (0, p1 - p0)]))
        for a in np.linspace(g0, g1, 9):
            p = trimesh.creation.cylinder(radius=0.014, height=gh, sections=10)
            p.apply_translation([center[0] + rg * np.cos(a), center[1] + rg * np.sin(a), z_high + gh / 2]); steel.append(p)
        bh = g.get('bandeau_sous_tremie_m', 0.2)
        panel.append(sweep(center, [(a, R + c.get('tremie_marge_m', 0.08), z_high - bh) for a in np.linspace(0, 2 * np.pi, 160)],
                           [(0, 0), (0.004, 0), (0.004, bh), (0, bh)]))
    return wood, steel, panel, n
