"""Analyse d'un plan neuf : reglages de depart construits uniquement a partir du fichier, sans rien reprendre d'un autre projet.

    python3 analyse.py plan.ai reglages.json [nom du projet]

Ce qui est lu sur le plan : echelle (nom des calques « ... (1:50) »), calques par type d'element, niveaux (pages qui ont
des murs), calage des niveaux (axe du colimacon s'il est dessine sur plusieurs pages), pages d'elevation.
Tout le reste part de valeurs neutres, marquees « a verifier » dans l'editeur.
"""
import json, re, sys, os
import pymupdf

CALQUES = [   # cle du reglage, mots reconnus dans le nom du calque (sans accents ni majuscules)
    ('murs', [r'^mur', r'\bmurs?\b', r'^wall']),
    ('portes_coulissantes', [r'coulissant', r'galandage', r'sliding']),
    ('portes', [r'^porte', r'\bportes?\b', r'^door']),
    ('escalier_helicoidal', [r'spiral', r'colima', r'helico']),
    ('placards', [r'placard', r'rangement', r'dressing']),
    ('mobilier', [r'mobilier', r'furniture', r'meuble']),
]


def sans_accents(t):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn').lower()


def nom_court(n):        # « Murs (1:50) » -> « Murs »
    return re.sub(r'\s*\(\s*1\s*:\s*\d+\s*\)\s*$', '', n).strip()


def analyser(src, nom_projet=None):
    doc = pymupdf.open(src)
    if any('without PDF Content' in pg.get_text() for pg in doc):
        sys.exit("ERREUR : ce fichier Illustrator a ete enregistre sans contenu PDF. Dans Illustrator : Fichier > Enregistrer sous, "
                 "format Adobe Illustrator, puis cochez « Creer un fichier compatible PDF » et enregistrez.")
    noms = [o['name'] for o in (doc.get_ocgs() or {}).values()]
    utilises = {}
    for pg in doc:
        for d in pg.get_drawings():
            if d.get('layer'): utilises.setdefault(d['layer'], set()).add(pg.number + 1)
    noms = sorted(set(noms) | set(utilises))
    verifier = []

    # echelle : « (1:50) » dans le nom des calques
    ech = [int(m.group(1)) for n in noms for m in [re.search(r'\(\s*1\s*:\s*(\d+)\s*\)', n)] if m]
    echelle = max(set(ech), key=ech.count) if ech else 50
    if not ech: verifier.append(['Échelle', 'Aucune échelle trouvée dans le nom des calques : 1:50 par défaut. Vérifiez-la à l’étape Import.', 'import'])

    # calques : le premier calque reconnu pour chaque type (le debut du nom sert de filtre au moteur)
    cal = {}
    for cle, motifs in CALQUES:
        for n in noms:
            s = sans_accents(nom_court(n))
            if cle == 'portes' and any(re.search(m, s) for m in CALQUES[1][1]): continue
            if any(re.search(m, s) for m in motifs) and n not in cal.values():
                cal[cle] = ('Porte' if nom_court(n).startswith('Porte') else nom_court(n)) if cle == 'portes' else nom_court(n); break
    if 'murs' not in cal:    # a defaut : le calque qui a le plus de surfaces pleines
        pleins = {}
        for pg in doc:
            for d in pg.get_drawings():
                if d.get('layer') and d.get('fill') is not None: pleins[d['layer']] = pleins.get(d['layer'], 0) + 1
        if pleins:
            cal['murs'] = nom_court(max(pleins, key=pleins.get))
            verifier.append(['Calque des murs', f'Aucun calque « Murs » : « {cal["murs"]} » est pris pour les murs (le plus de surfaces pleines).', 'import'])
        else: sys.exit('ERREUR : aucun calque de murs (surfaces pleines) dans ce fichier.')
    for cle, defaut in (('portes', 'Porte'), ('portes_coulissantes', 'Porte coulissante'), ('escalier_helicoidal', 'Escalier hélicoïdal'),
                        ('placards', 'Placards'), ('mobilier', 'Mobilier')):
        cal.setdefault(cle, defaut)

    # niveaux : les pages qui portent des murs, dans l'ordre du fichier
    pages_murs = []
    for pg in doc:
        n_ = sum(1 for d in pg.get_drawings() if d.get('layer', '').startswith(cal['murs']) and d.get('fill') is not None)
        if n_: pages_murs.append(pg.number + 1)
    if not pages_murs: sys.exit(f"ERREUR : le calque « {cal['murs']} » ne contient aucune surface pleine.")
    niveaux = []
    for k, p in enumerate(pages_murs):
        niveaux.append(dict(page=p, nom='Rez-de-chaussée' if k == 0 else f'Niveau {k + 1}', hauteur_sous_plafond_m=2.5,
                            position='dessus' if k else None))
        if niveaux[-1]['position'] is None: niveaux[-1].pop('position')
    if len(niveaux) > 1:
        verifier.append(['Niveaux', f'{len(niveaux)} pages avec des murs : chacune devient un niveau, empilé au-dessus du précédent. '
                         'Renommez-les et indiquez si un niveau est en dessous (sous-sol) à l’étape Import.', 'import'])
    verifier.append(['Hauteurs sous plafond', '2,50 m par défaut pour chaque niveau. Mesurez-les sur vos coupes à l’étape Élévations, ou tapez-les à l’étape Murs et plafonds.', 'murs'])

    # escalier helicoidal dessine sur au moins deux niveaux : il relie ces niveaux et sert de calage
    pages_hel = [k for k, nv in enumerate(niveaux) if any(d.get('layer', '').startswith(cal['escalier_helicoidal']) for d in doc[nv['page'] - 1].get_drawings())]
    hel = None
    if len(pages_hel) >= 2:
        hel = dict(moteur='extension_blender', extension_blender=dict(fichier='addon/escalier_colimasson.py'),
                   niveau_bas=niveaux[pages_hel[0]]['nom'], niveau_haut=niveaux[pages_hel[1]]['nom'],
                   angle_depart_deg=0, angle_arrivee_deg=270, rotation_deg=0, hauteur_marche_max_m=0.19, rayon_facteur=0.96,
                   epaisseur_marche_m=0.04, rayon_fut_m=0.075, limon_hauteur_m=0.32, main_courante_hauteur_m=0.92,
                   lisses_hauteurs_m=[0.36, 0.55, 0.74], montants_tous_les_n_pas=3, tremie_marge_m=0.08,
                   garde_corps=dict(actif=True, hauteur_m=1.0, lisses_hauteurs_m=[0.62, 0.74, 0.86], panneau_perfore_m=[0.08, 0.53],
                                    ouverture_apres_arrivee_deg=0, bandeau_sous_tremie_m=0.2, nombre_montants=9),
                   palier=dict(angle_deg=90))
        verifier.append(['Escalier hélicoïdal', 'Trouvé sur deux niveaux. Réglez le pied, l’arrivée et la rotation à l’étape Ouvertures et escaliers.', 'ouvertures'])
    alignement = dict(methode='axe_escalier_helicoidal' if hel else 'aucun', decalage_manuel_m=None)
    if len(niveaux) > 1 and not hel:
        verifier.append(['Calage des niveaux', 'Aucun élément commun trouvé entre les pages : les niveaux sont superposés tels quels.', 'import'])

    gris = lambda v: [v, v, v - 2]
    R = {
        'version': '0.8', 'analyse_auto': True,
        'projet': dict(nom=nom_projet or os.path.splitext(os.path.basename(src))[0], fichier_plan=os.path.basename(src)),
        'points_a_verifier': verifier,
        'etape_1_import': dict(echelle=echelle, calques=cal, niveaux=niveaux, alignement_niveaux=alignement,
                               pieces=dict(detection_auto=True, ouverture_max_m=1.8, surface_max_passage_m2=1.2, surface_min_m2=1.2,
                                           couper_aux_changements_de_niveau=True, separations=[], liste=[]),
                               zones_exclues=[], elevations=dict(pages=[], calques=[], mesures=[])),
        'etape_2_murs': dict(epaisseur_dalle_m=0.2, hauteur_linteau_m=2.1, linteaux_ouverture_max_m=1.1, linteaux_marge_portes_m=0.15,
                             emprise_fermeture_m=2.0, changements_de_niveau=[], nettoyage_bandes_etroites_m=0.2, poteaux=[], plafonds=[],
                             linteaux_ajustes=[], linteaux_traces=[], epaisseur_max_ouverture_m=0.8),
        'etape_3_ouvertures_escaliers': dict(portes=dict(hauteur_vantail_m=2.04, epaisseur_vantail_m=0.04, longueur_min_trait_pt=25, vantaux_vitres_plan_pt=[]),
                                             vitrines=[], deplacements={}),
        'etape_4_materiaux': dict(
            murs=dict(couleur=[244, 243, 240], rugosite=0.9),
            sol=dict(type='carrelage', taille_carreau_m=0.6, couleur=gris(190), couleur_joint=gris(160), largeur_joint_mm=3,
                     decalage_x_m=0, decalage_y_m=0, rotation_deg=0, rugosite=0.55),
            plinthes=dict(hauteur_m=0.08, epaisseur_m=0.012, couleur=[244, 243, 240], rugosite=0.5),
            plafond=dict(couleur=[246, 246, 244], rugosite=0.95), escalier_droit=dict(couleur=[238, 238, 236], rugosite=0.6),
            bois=dict(nom='bois', couleur=[190, 150, 105], rugosite=0.5), acier=dict(nom='acier', couleur=[92, 97, 104], metal=0.4, rugosite=0.45),
            tole_perforee=dict(couleur=[92, 97, 104], opacite=0.55, metal=0.4, rugosite=0.5), portes=dict(couleur=[240, 240, 236], rugosite=0.6),
            chassis=dict(nom='chassis', couleur=[78, 82, 88], metal=0.5, rugosite=0.4), verre=dict(couleur=[200, 215, 220], opacite=0.18, metal=0, rugosite=0.05),
            luminaires=dict(couleur=[245, 245, 242], rugosite=0.4), rails=dict(couleur=[25, 25, 27], rugosite=0.5), placards=dict(couleur=[246, 246, 243], rugosite=0.5)),
        'etape_5_mobilier_eclairage': dict(placards=dict(profondeur_m=0.6, hauteur_m=2.4, longueur_min_trait_pt=25), rails=[], suspensions=[],
                                           rails_regles=dict(distance_min_murs_m=0.3, distance_min_obstacles_m=0.15, longueur_min_m=0.6, inclinaison_spots_deg=30,
                                                             orientation_spots='vers_le_mur_le_plus_proche', marge_sous_plafond_m=0.01)),
    }
    if hel: R['etape_3_ouvertures_escaliers']['escalier_helicoidal'] = hel
    print(f"  analyse : echelle 1:{echelle}, {len(niveaux)} niveau(x) (pages {', '.join(map(str, pages_murs))}), calques {cal}"
          + (', escalier helicoidal' if hel else ''))
    return R


if __name__ == '__main__':
    R = analyser(sys.argv[1], sys.argv[3] if len(sys.argv) > 3 else None)
    json.dump(R, open(sys.argv[2], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
