"""Lance l'extension Blender d'Olivier (escalier_colimasson.py) sans interface et exporte un GLB en Z vers le haut.
Usage : python (avec bpy) blender_colimacon.py params.json sortie.glb"""
import sys, json, importlib.util, bpy
args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]   # Blender passe ses propres arguments avant '--'
params, out = json.load(open(args[0])), args[1]
spec = importlib.util.spec_from_file_location('escalier_colimasson', params.pop('_extension'))
ext = importlib.util.module_from_spec(spec); spec.loader.exec_module(ext)
bpy.ops.wm.read_factory_settings(use_empty=True)
ext.register()
props = bpy.context.scene.escalier
props.mise_a_jour_auto = False
for k, v in params.items(): setattr(props, k, v)
ext.generer_escalier(props, bpy.context)
coll = bpy.data.collections[ext.NOM_COLLECTION]
for o in list(coll.objects):            # main courante et lisses : courbes -> maillages
    if o.type == 'CURVE':
        bpy.context.view_layer.objects.active = o; o.select_set(True)
        bpy.ops.object.convert(target='MESH'); o.select_set(False)
for o in bpy.context.view_layer.objects: o.select_set(o.name in coll.objects)
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', use_selection=True, export_yup=False, export_apply=True)
print('ok', len(coll.objects), 'objets')
