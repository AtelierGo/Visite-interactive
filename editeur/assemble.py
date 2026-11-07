"""Assemble l'éditeur pour la page web (artifact) : python3 editeur/assemble.py, lancé depuis le dossier du prototype."""
import base64, json, os
t = open(os.path.join(os.path.dirname(__file__), 'template.html'), encoding='utf-8').read()
reg = open('reglages.json', encoding='utf-8').read().replace('</', '<\\/')
axe = json.load(open('v07.axe.json'))
pcs = open('v07.pieces.json', encoding='utf-8').read().replace('</', '<\\/')
glb = open('v07.glb', 'rb').read()
t = (t.replace('__TITRE__', 'Rue des Balances').replace('__PLAN__', 'A2018_032_Rue_Des_Balances-3D.ai')
      .replace('__TAILLE__', f'{len(glb) / 1e6:.1f} Mo'.replace('.', ','))
      .replace('__PIECES__', pcs).replace('__REGLAGES__', reg).replace('__AXE__', json.dumps(axe)).replace('__ELEVATIONS__', '[]')
      .replace('__GLB__', base64.b64encode(glb).decode()))
open('editeur/index.html', 'w', encoding='utf-8').write(t)
