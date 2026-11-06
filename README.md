# Atelier 3D

Logiciel de bureau (macOS, Windows) qui transforme un plan Illustrator à l'échelle en maquette 3D GLB, pour une visite sur le web, en VR ou intégrée à un site.

## Organisation

| Dossier | Rôle |
|---|---|
| `main.js`, `preload.js` | Logiciel Electron : fenêtres, menus, projets, lancement du moteur |
| `accueil.html` | Écran d'accueil : nouveau projet, projets récents, chemins de Python et de Blender |
| `editeur/template.html` | Éditeur en 8 étapes (même fichier que la page web de démonstration) |
| `editeur/assemble.py` | Assemble la version web de l'éditeur (page de démonstration) |
| `moteur/` | Moteur Python : lit le plan, construit le GLB (`build_v4.py plan.ai sortie.glb reglages.json`) |
| `exemples/rue-des-balances/` | Réglages du projet pilote (le plan n'est pas versionné) |

## Un projet

Un projet est un dossier :

```
Mon projet/
  projet.json        nom, fichier plan, dates
  plan.ai            copie du plan
  reglages.json      tous les réglages de l'éditeur
  sortie/            maquette.glb, maquette.pieces.json, maquette.axe.json, textures, journal.txt
```

« Générer la maquette » (ou Cmd/Ctrl+G) enregistre `reglages.json`, lance le moteur et recharge l'éditeur sur la nouvelle maquette.

## Lancer en développement

Prérequis : Node.js 20 ou plus, Python 3.10 ou plus. Blender est facultatif : il génère l'escalier hélicoïdal avec l'extension `moteur/addon/escalier_colimasson.py`. Sans lui, le moteur produit une version simplifiée.

```
npm install
python3 -m pip install -r moteur/requirements.txt     # Windows : py -3 -m pip install -r moteur\requirements.txt
npm start
```

## Paquets

`npm run dist:mac` produit un .dmg (à lancer sur un Mac), `npm run dist:win` un installateur .exe (sur Windows). Pour l'instant, Python doit être installé sur la machine. L'intégration de Python dans l'installateur viendra ensuite.
