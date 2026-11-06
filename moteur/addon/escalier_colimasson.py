# -*- coding: utf-8 -*-
"""
Escalier en colimaçon paramétrable pour Blender
===============================================

Ce script crée un escalier en spirale entièrement paramétrable :
moyeu central, marches, contremarches, limon extérieur, panneau ajouré,
balustres ou lisses horizontales et main courante.

Installation
------------
1. Blender > Edit > Preferences > Add-ons > Install...
2. Sélectionnez ce fichier, puis activez "Escalier en colimaçon".
3. Dans la 3D View, ouvrez la sidebar (touche N) > onglet "Escalier".
4. Ajustez les paramètres : l'escalier se régénère automatiquement.

Notes
-----
- Le panneau ajouré utilise un matériau à trous procéduraux (Voronoi) :
  les trous sont visibles au rendu (Cycles / EEVEE) mais ne sont pas
  de la géométrie réelle. Désactivez "Matériaux" pour un panneau plein.
- Fonctionne avec Blender 3.0 et supérieur.

Auteur : Perplexity Computer
Licence : GPL (comme Blender)
"""

bl_info = {
    "name": "Escalier en colimaçon paramétrable",
    "author": "Perplexity Computer",
    "version": (1, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar (N) > Escalier",
    "description": "Génère un escalier en colimaçon (spirale) entièrement paramétrable",
    "category": "Add Mesh",
}

import bpy
import bmesh
import math
from math import sin, cos, pi
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

NOM_COLLECTION = "Escalier Colimaçon"


# ---------------------------------------------------------------------------
# Utilitaires de construction
# ---------------------------------------------------------------------------

def _mesh_depuis_donnees(nom, sommets, faces, uvs=None):
    """Crée un mesh à partir de sommets/faces, corrige les normales,
    et affecte optionnellement des coordonnées UV par sommet."""
    mesh = bpy.data.meshes.new(nom)
    mesh.from_pydata(sommets, [], faces)
    mesh.validate()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    if uvs:
        couche = mesh.uv_layers.new(name="UVMap")
        for poly in mesh.polygons:
            for li, vi in zip(poly.loop_indices, poly.vertices):
                couche.data[li].uv = uvs[vi]
    return mesh


def _creer_coin(nom, r_int, r_ext, a0, a1, z0, z1):
    """Crée un secteur annulaire (part de camembert) plein entre deux angles
    et deux hauteurs. Sert pour les marches et les contremarches."""
    lo, hi = min(a0, a1), max(a0, a1)
    ca_lo, sa_lo = cos(lo), sin(lo)
    ca_hi, sa_hi = cos(hi), sin(hi)

    haut = [
        (r_int * ca_lo, r_int * sa_lo, z1),
        (r_ext * ca_lo, r_ext * sa_lo, z1),
        (r_ext * ca_hi, r_ext * sa_hi, z1),
        (r_int * ca_hi, r_int * sa_hi, z1),
    ]
    bas = [(x, y, z0) for x, y, _ in haut]
    sommets = haut + bas
    faces = [
        (0, 1, 2, 3),          # dessus
        (7, 6, 5, 4),          # dessous
        (0, 4, 5, 1),          # côté radial "lo"
        (1, 5, 6, 2),          # côté extérieur
        (2, 6, 7, 3),          # côté radial "hi"
        (3, 7, 4, 0),          # côté intérieur
    ]
    return _mesh_depuis_donnees(nom, sommets, faces)


def _creer_cylindre(nom, rayon, z0, z1, segments=32):
    """Crée un cylindre vertical fermé (moyeu, balustres)."""
    segments = max(3, segments)
    sommets = [(0.0, 0.0, z0)]
    for i in range(segments):
        a = 2.0 * pi * i / segments
        sommets.append((rayon * cos(a), rayon * sin(a), z0))
    idx_haut = len(sommets)
    sommets.append((0.0, 0.0, z1))
    for i in range(segments):
        a = 2.0 * pi * i / segments
        sommets.append((rayon * cos(a), rayon * sin(a), z1))

    bas = list(range(1, segments + 1))
    haut = list(range(idx_haut + 1, idx_haut + 1 + segments))
    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((bas[i], bas[j], haut[j], haut[i]))   # flanc
        faces.append((0, bas[j], bas[i]))                   # cap bas
        faces.append((idx_haut, haut[i], haut[j]))          # cap haut
    return _mesh_depuis_donnees(nom, sommets, faces)


def _creer_tube_heloidal(nom, points, rayon):
    """Crée une courbe 3D lissée avec un profil circulaire (tube) :
    main courante ou lisses horizontales."""
    donnees = bpy.data.curves.new(nom, 'CURVE')
    donnees.dimensions = '3D'
    donnees.bevel_depth = rayon
    donnees.bevel_resolution = 4
    donnees.use_fill_caps = True
    spline = donnees.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for i, p in enumerate(points):
        spline.points[i].co = (p[0], p[1], p[2], 1.0)
    return bpy.data.objects.new(nom, donnees)


def _creer_ruban(nom, points):
    """Crée un ruban hélicoïdal vertical (limon, panneau ajouré).

    points : liste de (angle, rayon, z_bas, z_haut). Les UV sont en
    mètres (abscisse curviligne, hauteur) pour un motif régulier.
    """
    sommets = []
    uvs = []
    u_cumul = 0.0
    precedent = None
    for (a, r, zb, zh) in points:
        x, y = r * cos(a), r * sin(a)
        if precedent is not None:
            u_cumul += math.dist(precedent, (x, y, zh))
        precedent = (x, y, zh)
        sommets.append((x, y, zb))
        sommets.append((x, y, zh))
        uvs.append((u_cumul, zb))
        uvs.append((u_cumul, zh))

    faces = []
    for i in range(len(points) - 1):
        b0, h0 = 2 * i, 2 * i + 1
        b1, h1 = 2 * i + 2, 2 * i + 3
        faces.append((b0, b1, h1, h0))
    return _mesh_depuis_donnees(nom, sommets, faces, uvs)


def _lier_objet(objet, collection, lissage=False, materiau=None):
    collection.objects.link(objet)
    if lissage and objet.type == 'MESH' and objet.data.polygons:
        objet.data.polygons.foreach_set("use_smooth", [True] * len(objet.data.polygons))
    if materiau is not None and objet.type == 'MESH':
        objet.data.materials.append(materiau)
    return objet


# ---------------------------------------------------------------------------
# Matériaux (bois clair / acier anthracite / tôle perforée)
# ---------------------------------------------------------------------------

def _creer_materiaux():
    """Récupère ou crée les matériaux (réutilisés entre les régénérations)."""
    # --- Bois clair (marches) ---
    bois = bpy.data.materials.get("Escalier_Bois")
    if bois is None:
        bois = bpy.data.materials.new("Escalier_Bois")
    bois.use_nodes = True
    bsdf = bois.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.72, 0.50, 0.28, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.45
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.0

    # --- Acier anthracite (structure) ---
    metal = bpy.data.materials.get("Escalier_Acier")
    if metal is None:
        metal = bpy.data.materials.new("Escalier_Acier")
    metal.use_nodes = True
    bsdf = metal.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (0.035, 0.037, 0.042, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.5
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 1.0

    # --- Tôle perforée (panneau ajouré) ---
    panneau = bpy.data.materials.get("Escalier_Tole")
    if panneau is None:
        panneau = bpy.data.materials.new("Escalier_Tole")
    panneau.use_nodes = True
    nt = panneau.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    sortie = nt.nodes.get("Material Output")
    if bsdf and sortie:
        bsdf.inputs["Base Color"].default_value = (0.035, 0.037, 0.042, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.5
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 1.0

        # Nettoyage des nodes de l'ancienne version éventuelle
        for n in list(nt.nodes):
            if n.name in ("Escalier_UV", "Escalier_Voronoi",
                          "Escalier_Trous", "Escalier_Alpha"):
                nt.nodes.remove(n)

        uv = nt.nodes.new('ShaderNodeTexCoord')
        uv.name = "Escalier_UV"
        voronoi = nt.nodes.new('ShaderNodeTexVoronoi')
        voronoi.name = "Escalier_Voronoi"
        voronoi.inputs["Vector"].default_value = (0.0, 0.0, 0.0)
        voronoi.inputs["Scale"].default_value = 10.0
        masque = nt.nodes.new('ShaderNodeMath')
        masque.name = "Escalier_Trous"
        masque.operation = 'GREATER_THAN'
        masque.inputs[1].default_value = 0.25  # rayon des trous (fraction de cellule)
        nt.links.new(uv.outputs["UV"], voronoi.inputs["Vector"])
        nt.links.new(voronoi.outputs["Distance"], masque.inputs[0])
        # Alpha : 1 = tôle, 0 = trou
        nt.links.new(masque.outputs["Value"], bsdf.inputs["Alpha"])

    # Transparence (EEVEE) : méthode "blended" en 4.2+, blend_mode avant
    try:
        panneau.surface_render_method = 'BLENDED'
    except AttributeError:
        pass
    try:
        panneau.blend_method = 'BLEND'
    except Exception:
        pass

    return {"bois": bois, "metal": metal, "panneau": panneau}


# ---------------------------------------------------------------------------
# Génération de l'escalier
# ---------------------------------------------------------------------------

def _purger(context):
    """Supprime l'escalier existant (objets + collection + données orphelines)."""
    scene = _scene(context)
    coll = bpy.data.collections.get(NOM_COLLECTION)
    if coll is None:
        return
    for objet in list(coll.objects):
        coll.objects.unlink(objet)
        if objet.users == 0:
            bpy.data.objects.remove(objet, do_unlink=True)
    for parent in bpy.data.collections:
        if coll.name in parent.children:
            parent.children.unlink(coll)
            break
    try:
        scene.collection.children.unlink(coll)
    except Exception:
        pass
    bpy.data.collections.remove(coll)
    bpy.data.orphans_purge(do_recursive=True)


def _scene(context):
    scene = getattr(context, "scene", None)
    if scene is None and bpy.data.scenes:
        scene = bpy.data.scenes[0]
    return scene


def generer_escalier(props, context):
    """Construit tout l'escalier à partir des paramètres."""
    _purger(context)
    scene = _scene(context)
    if scene is None:
        return

    mats = _creer_materiaux() if props.appliquer_materiaux else {}
    mat_bois = mats.get("bois")
    mat_metal = mats.get("metal")
    mat_panneau = mats.get("panneau")

    collection = bpy.data.collections.new(NOM_COLLECTION)
    scene.collection.children.link(collection)

    # --- Paramètres dérivés -------------------------------------------------
    n = max(3, props.nb_marches)
    hauteur_marche = props.hauteur_totale / n
    angle_total = props.nb_tours * 2.0 * pi
    angle_marche = angle_total / n
    sens = -1.0 if props.sens_horaire else 1.0
    lissage = props.lissage
    sous_ech = 8  # sous-échantillonnage des hélices (rubans et tubes)

    def points_helice(z_bas, z_haut, r):
        """Échantillonne un ruban hélicoïdal de t=0 à t=n marches."""
        pts = []
        nb = n * sous_ech
        for k in range(nb + 1):
            t = k / sous_ech
            a = sens * t * angle_marche
            pts.append((a, r, z_bas(t), z_haut(t)))
        return pts

    # --- Moyeu central -------------------------------------------------------
    z_moyeu = props.hauteur_totale + 0.1
    _lier_objet(
        bpy.data.objects.new(
            "Moyeu",
            _creer_cylindre("Moyeu", props.rayon_moyeu, 0.0, z_moyeu, 32),
        ),
        collection, lissage, mat_metal,
    )

    # --- Marches, contremarches, balustres -----------------------------------
    for i in range(n):
        z_i = i * hauteur_marche
        a_lo = sens * i * angle_marche
        a_hi = sens * (i + 1) * angle_marche

        # Marche
        marche = bpy.data.objects.new(
            "Marche_%03d" % (i + 1),
            _creer_coin(
                "Marche_%03d" % (i + 1),
                props.rayon_interieur,
                props.rayon_exterieur,
                a_lo, a_hi,
                z_i, z_i + props.epaisseur_marche,
            ),
        )
        _lier_objet(marche, collection, lissage, mat_bois)

        # Contremarche (optionnelle) : sous le bord "lo" de la marche
        if props.afficher_contremarche:
            delta_a = max(
                math.atan2(props.epaisseur_contremarche, props.rayon_interieur + 0.1),
                0.001)
            a0 = min(a_lo, a_lo + sens * delta_a)
            a1 = max(a_lo, a_lo + sens * delta_a)
            contremarche = bpy.data.objects.new(
                "Contremarche_%03d" % (i + 1),
                _creer_coin(
                    "Contremarche_%03d" % (i + 1),
                    props.rayon_interieur,
                    props.rayon_exterieur,
                    a0, a1,
                    z_i - hauteur_marche, z_i,
                ),
            )
            _lier_objet(contremarche, collection, lissage, mat_metal)

        # Balustre (optionnel, garde-corps "balustres") : au milieu de la
        # marche, côté extérieur. Son sommet atteint la main courante à son
        # propre angle (le rail est incliné d'une demi-marche à l'angle médian).
        if props.type_garde_corps == 'BALUSTRES' and props.afficher_balustres:
            a_mid = (a_lo + a_hi) * 0.5
            bx = props.rayon_exterieur * cos(a_mid)
            by = props.rayon_exterieur * sin(a_mid)
            z_base = z_i + props.epaisseur_marche
            z_haut = (i + 0.5) * hauteur_marche \
                + props.epaisseur_marche + props.hauteur_garde_corps
            balustre = bpy.data.objects.new(
                "Balustre_%03d" % (i + 1),
                _creer_cylindre(
                    "Balustre_%03d" % (i + 1),
                    props.epaisseur_balustre * 0.5,
                    0.0, z_haut - z_base, 12),
            )
            balustre.location = (bx, by, z_base)
            _lier_objet(balustre, collection, lissage, mat_metal)

    # --- Limon extérieur (optionnel) ----------------------------------------
    # Ruban hélicoïdal dont le bord supérieur affleure le dessous des marches.
    if props.afficher_limon:
        limon = bpy.data.objects.new(
            "Limon",
            _creer_ruban(
                "Limon",
                points_helice(
                    lambda t: max(-0.001, t * hauteur_marche - props.hauteur_limon),
                    lambda t: t * hauteur_marche,
                    props.rayon_exterieur),
            ),
        )
        _lier_objet(limon, collection, lissage, mat_metal)

    # --- Panneau ajouré (optionnel) -------------------------------------------
    # Tôle hélicoïdale au-dessus des marches, effet trous via matériau.
    if props.afficher_panneau:
        panneau = bpy.data.objects.new(
            "Panneau ajouré",
            _creer_ruban(
                "Panneau ajouré",
                points_helice(
                    lambda t: t * hauteur_marche + props.epaisseur_marche,
                    lambda t: t * hauteur_marche + props.epaisseur_marche
                    + props.hauteur_panneau,
                    props.rayon_exterieur),
            ),
        )
        _lier_objet(panneau, collection, False, mat_panneau)

    # --- Main courante et lisses horizontales (optionnelles) -------------------
    if props.afficher_main_courante:
        # Main courante : tube hélicoïdal au-dessus des marches
        pts_main = []
        nb = n * sous_ech
        for k in range(nb + 1):
            t = k / sous_ech
            a = sens * t * angle_marche
            z = t * hauteur_marche + props.epaisseur_marche \
                + props.hauteur_garde_corps
            pts_main.append(
                (props.rayon_exterieur * cos(a),
                 props.rayon_exterieur * sin(a),
                 z))
        main = _creer_tube_heloidal(
            "Main courante", pts_main, props.epaisseur_main_courante * 0.5)
        collection.objects.link(main)
        if mat_metal:
            main.data.materials.append(mat_metal)

        # Lisses horizontales : tubes répartis entre le panneau (ou les
        # marches) et la main courante.
        if props.type_garde_corps == 'LISSES':
            z_bas_rempl = props.hauteur_panneau if props.afficher_panneau else 0.06
            for l in range(props.nb_lisses):
                frac = (l + 1) / (props.nb_lisses + 1)
                decal = z_bas_rempl + frac * (
                    props.hauteur_garde_corps - z_bas_rempl)
                pts_lisse = []
                for k in range(nb + 1):
                    t = k / sous_ech
                    a = sens * t * angle_marche
                    z = t * hauteur_marche + props.epaisseur_marche + decal
                    pts_lisse.append(
                        (props.rayon_exterieur * cos(a),
                         props.rayon_exterieur * sin(a),
                         z))
                lisse = _creer_tube_heloidal(
                    "Lisse_%02d" % (l + 1), pts_lisse,
                    props.epaisseur_main_courante * 0.5)
                collection.objects.link(lisse)
                if mat_metal:
                    lisse.data.materials.append(mat_metal)

        # Poteaux de départ et d'arrivée : ils ancrent la main courante
        # au sol comme sur un escalier réel.
        if props.afficher_poteaux:
            for nom_poteau, t in (("Poteau_depart", 0.0), ("Poteau_arrivee", float(n))):
                a = sens * t * angle_marche
                px = props.rayon_exterieur * cos(a)
                py = props.rayon_exterieur * sin(a)
                z_rail = t * hauteur_marche + props.epaisseur_marche \
                    + props.hauteur_garde_corps
                poteau = bpy.data.objects.new(
                    nom_poteau,
                    _creer_cylindre(
                        nom_poteau,
                        props.epaisseur_main_courante * 0.6,
                        0.0, z_rail, 16),
                )
                poteau.location = (px, py, 0.0)
                _lier_objet(poteau, collection, lissage, mat_metal)


# ---------------------------------------------------------------------------
# Propriétés
# ---------------------------------------------------------------------------

def _maj_escalier(self, context):
    try:
        if self.mise_a_jour_auto:
            generer_escalier(self, context)
    except Exception:
        pass  # évite les crashs pendant le glissement des curseurs


class EscalierProps(bpy.types.PropertyGroup):
    # Dimensions générales
    hauteur_totale: FloatProperty(
        name="Hauteur totale",
        description="Hauteur de sol à plancher",
        default=3.0, min=0.5, max=50.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)
    nb_marches: IntProperty(
        name="Nombre de marches",
        description="Nombre de marches de l'escalier",
        default=16, min=3, max=400,
        update=_maj_escalier)
    nb_tours: FloatProperty(
        name="Nombre de tours",
        description="Rotation totale de l'escalier (1.0 = 360°)",
        default=1.0, min=0.1, max=10.0, precision=2,
        update=_maj_escalier)
    sens_horaire: BoolProperty(
        name="Sens horaire",
        description="Inverser le sens de rotation de l'escalier",
        default=False,
        update=_maj_escalier)

    # Rayons
    rayon_exterieur: FloatProperty(
        name="Rayon extérieur",
        description="Rayon extérieur des marches",
        default=1.2, min=0.2, max=20.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)
    rayon_interieur: FloatProperty(
        name="Rayon intérieur",
        description="Rayon intérieur des marches (bord du moyeu)",
        default=0.18, min=0.0, max=20.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)
    rayon_moyeu: FloatProperty(
        name="Rayon du moyeu",
        description="Rayon du cylindre central",
        default=0.09, min=0.0, max=5.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)

    # Marches
    epaisseur_marche: FloatProperty(
        name="Épaisseur des marches",
        default=0.06, min=0.005, max=2.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)
    afficher_contremarche: BoolProperty(
        name="Contremarches",
        description="Ajouter des contremarches verticales",
        default=False,
        update=_maj_escalier)
    epaisseur_contremarche: FloatProperty(
        name="Épaisseur des contremarches",
        default=0.04, min=0.005, max=1.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)

    # Limon extérieur
    afficher_limon: BoolProperty(
        name="Limon extérieur",
        description="Ruban métallique hélicoïdal sous le bord extérieur des marches",
        default=True,
        update=_maj_escalier)
    hauteur_limon: FloatProperty(
        name="Hauteur du limon",
        default=0.28, min=0.05, max=3.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)

    # Garde-corps
    type_garde_corps: EnumProperty(
        name="Type de garde-corps",
        description="Remplissage entre les marches et la main courante",
        items=[
            ('LISSES', "Lisses horizontales",
             "Tubes horizontaux hélicoïdaux (style moderne)"),
            ('BALUSTRES', "Balustres",
             "Un poteau vertical par marche"),
            ('AUCUN', "Aucun", "Seulement la main courante"),
        ],
        default='LISSES',
        update=_maj_escalier)
    afficher_main_courante: BoolProperty(
        name="Main courante",
        description="Ajouter une main courante hélicoïdale",
        default=True,
        update=_maj_escalier)
    epaisseur_main_courante: FloatProperty(
        name="Diamètre main courante",
        default=0.05, min=0.01, max=1.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)
    afficher_panneau: BoolProperty(
        name="Panneau ajouré",
        description="Tôle hélicoïcale ajourée au-dessus des marches "
                    "(trous simulés par le matériau)",
        default=True,
        update=_maj_escalier)
    hauteur_panneau: FloatProperty(
        name="Hauteur du panneau",
        default=0.45, min=0.05, max=3.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)
    afficher_balustres: BoolProperty(
        name="Balustres",
        description="Ajouter un balustre par marche",
        default=True,
        update=_maj_escalier)
    afficher_poteaux: BoolProperty(
        name="Poteaux de départ / arrivée",
        description="Poteaux verticaux ancrant la main courante au sol",
        default=True,
        update=_maj_escalier)
    epaisseur_balustre: FloatProperty(
        name="Diamètre des balustres",
        default=0.04, min=0.01, max=0.5, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)
    hauteur_garde_corps: FloatProperty(
        name="Hauteur du garde-corps",
        default=0.9, min=0.3, max=3.0, subtype='DISTANCE', unit='LENGTH',
        update=_maj_escalier)
    nb_lisses: IntProperty(
        name="Nombre de lisses",
        description="Tubes horizontaux entre le panneau et la main courante",
        default=3, min=0, max=12,
        update=_maj_escalier)

    # Matériaux
    appliquer_materiaux: BoolProperty(
        name="Matériaux (bois / acier / tôle ajourée)",
        description="Appliquer des matériaux simples : bois clair pour les "
                    "marches, acier anthracite pour la structure, tôle "
                    "perforée pour le panneau",
        default=True,
        update=_maj_escalier)

    # Divers
    lissage: BoolProperty(
        name="Lissage (smooth shading)",
        description="Activer le smooth shading sur les pièces",
        default=True,
        update=_maj_escalier)
    mise_a_jour_auto: BoolProperty(
        name="Mise à jour automatique",
        description="Régénérer l'escalier à chaque modification",
        default=True)


# ---------------------------------------------------------------------------
# Opérateur et interface
# ---------------------------------------------------------------------------

class ESCALIER_OT_generer(bpy.types.Operator):
    """Génère / régénère l'escalier en colimaçon"""
    bl_idname = "escalier.generer"
    bl_label = "Générer l'escalier"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.escalier
        generer_escalier(props, context)
        return {'FINISHED'}


class ESCALIER_PT_panel(bpy.types.Panel):
    bl_label = "Escalier en colimaçon"
    bl_idname = "ESCALIER_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Escalier"

    def draw(self, context):
        layout = self.layout
        props = context.scene.escalier

        boite = layout.box()
        boite.label(text="Dimensions")
        boite.prop(props, "hauteur_totale")
        boite.prop(props, "nb_marches")
        boite.prop(props, "nb_tours")
        boite.prop(props, "sens_horaire")

        boite = layout.box()
        boite.label(text="Rayons")
        boite.prop(props, "rayon_exterieur")
        boite.prop(props, "rayon_interieur")
        boite.prop(props, "rayon_moyeu")

        boite = layout.box()
        boite.label(text="Marches")
        boite.prop(props, "epaisseur_marche")
        boite.prop(props, "afficher_contremarche")
        if props.afficher_contremarche:
            boite.prop(props, "epaisseur_contremarche")
        boite.prop(props, "afficher_limon")
        if props.afficher_limon:
            boite.prop(props, "hauteur_limon")

        boite = layout.box()
        boite.label(text="Garde-corps")
        boite.prop(props, "type_garde_corps", text="")
        boite.prop(props, "afficher_main_courante")
        if props.afficher_main_courante:
            boite.prop(props, "epaisseur_main_courante")
            boite.prop(props, "afficher_poteaux")
        boite.prop(props, "hauteur_garde_corps")
        if props.type_garde_corps == 'LISSES':
            boite.prop(props, "nb_lisses")
        if props.type_garde_corps == 'BALUSTRES':
            boite.prop(props, "afficher_balustres")
            if props.afficher_balustres:
                boite.prop(props, "epaisseur_balustre")
        boite.prop(props, "afficher_panneau")
        if props.afficher_panneau:
            boite.prop(props, "hauteur_panneau")

        boite = layout.box()
        boite.label(text="Options")
        boite.prop(props, "appliquer_materiaux")
        boite.prop(props, "lissage")
        boite.prop(props, "mise_a_jour_auto")

        layout.operator("escalier.generer")


# ---------------------------------------------------------------------------
# Enregistrement
# ---------------------------------------------------------------------------

_classes = (
    EscalierProps,
    ESCALIER_OT_generer,
    ESCALIER_PT_panel,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.escalier = PointerProperty(type=EscalierProps)


def unregister():
    del bpy.types.Scene.escalier
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
