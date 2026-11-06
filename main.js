// Atelier 3D : logiciel de bureau (macOS, Windows).
// Un projet est un dossier : projet.json, le plan (.ai / .pdf), reglages.json et sortie/ (maquette générée).
const { app, BrowserWindow, Menu, dialog, ipcMain, shell } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, spawnSync } = require('child_process');

const RACINE = __dirname;
const MOTEUR = path.join(RACINE.replace('app.asar', 'app.asar.unpacked'), 'moteur', 'build_v4.py');   // Python ne lit pas dans l'archive asar
const EXEMPLE = path.join(RACINE, 'exemples', 'rue-des-balances');
const THREE_DIR = path.join(RACINE, 'node_modules', 'three');
const PARAMS = () => path.join(app.getPath('userData'), 'parametres.json');

let win = null;
let projet = null;          // { dossier, nom, plan }
let modifications = 0;      // réglages modifiés dans l'éditeur et pas encore générés
let journal = '';           // sortie du dernier passage du moteur

// ---------- paramètres (chemins de Python et de Blender, projets récents) ----------
function lireParams() {
  try { return JSON.parse(fs.readFileSync(PARAMS(), 'utf-8')); } catch { return {}; }
}
function ecrireParams(p) {
  fs.mkdirSync(path.dirname(PARAMS()), { recursive: true });
  fs.writeFileSync(PARAMS(), JSON.stringify(p, null, 2));
}
function blenderParDefaut() {
  const cands = process.platform === 'darwin'
    ? ['/Applications/Blender.app/Contents/MacOS/Blender']
    : process.platform === 'win32'
      ? (() => { const base = 'C:\\Program Files\\Blender Foundation';
          try { return fs.readdirSync(base).sort().reverse().map(d => path.join(base, d, 'blender.exe')); } catch { return []; } })()
      : ['/usr/bin/blender', '/usr/local/bin/blender'];
  return cands.find(c => fs.existsSync(c)) || '';
}
function pythonParDefaut() { return process.platform === 'win32' ? 'py' : 'python3'; }
function config() {
  const p = lireParams();
  return { python: p.python || pythonParDefaut(), blender: p.blender || blenderParDefaut(), recents: p.recents || [] };
}
function verifierPython() {
  const c = config();
  const r = spawnSync(c.python, ['-c', 'import pymupdf, shapely, trimesh, PIL, numpy; print("ok")'], { encoding: 'utf-8' });
  if (r.error) return { ok: false, message: `Python introuvable (${c.python}).` };
  if (r.status !== 0) return { ok: false, message: 'Python est là mais il manque des modules. Installez-les avec : '
    + `${c.python} -m pip install -r "${path.join(RACINE, 'moteur', 'requirements.txt')}"` };
  return { ok: true, message: `Python prêt (${c.python}).` };
}
function ajouterRecent(dossier) {
  const p = lireParams();
  p.recents = [dossier].concat((p.recents || []).filter(d => d !== dossier)).slice(0, 8);
  ecrireParams(p);
}

// ---------- projets ----------
function lireProjet(dossier) {
  const meta = JSON.parse(fs.readFileSync(path.join(dossier, 'projet.json'), 'utf-8'));
  return { dossier, nom: meta.nom, plan: meta.plan };
}
function creerProjet(dossier, nom, planSource, reglagesSource) {
  fs.mkdirSync(path.join(dossier, 'sortie'), { recursive: true });
  const plan = path.basename(planSource);
  fs.copyFileSync(planSource, path.join(dossier, plan));
  fs.copyFileSync(reglagesSource, path.join(dossier, 'reglages.json'));
  const maintenant = new Date().toISOString();
  fs.writeFileSync(path.join(dossier, 'projet.json'),
    JSON.stringify({ nom, plan, version: 1, cree: maintenant, modifie: maintenant }, null, 2));
  return lireProjet(dossier);
}
const sortie = (nom) => path.join(projet.dossier, 'sortie', nom);

// ---------- moteur ----------
function generer() {
  return new Promise((resolve) => {
    const c = config();
    fs.mkdirSync(path.join(projet.dossier, 'sortie'), { recursive: true });
    const env = Object.assign({}, process.env, { PYTHONIOENCODING: 'utf-8' });
    if (c.blender) env.ATELIER_BLENDER = c.blender;
    const args = [MOTEUR, path.join(projet.dossier, projet.plan), sortie('maquette.glb'), path.join(projet.dossier, 'reglages.json')];
    const pyArgs = c.python === 'py' ? ['-3'].concat(args) : args;
    journal = '';
    let p;
    try { p = spawn(c.python, pyArgs, { cwd: path.join(projet.dossier, 'sortie'), env }); }
    catch (e) { return resolve({ ok: false, erreur: String(e.message || e) }); }
    p.stdout.on('data', d => { journal += d; });
    p.stderr.on('data', d => { journal += d; });
    p.on('error', e => resolve({ ok: false, erreur: `Python introuvable (${c.python}) : ${e.message}` }));
    p.on('close', code => {
      fs.writeFileSync(sortie('journal.txt'), journal);
      if (code === 0) return resolve({ ok: true });
      const lignes = journal.trim().split('\n');
      resolve({ ok: false, erreur: lignes[lignes.length - 1] || `code ${code}` });
    });
  });
}

// ---------- éditeur ----------
function assemblerEditeur() {
  const t = fs.readFileSync(path.join(RACINE, 'editeur', 'template.html'), 'utf-8');
  const esc = s => s.replace(/<\//g, '<\\/');
  const glb = fs.readFileSync(sortie('maquette.glb'));
  const url = f => 'file://' + path.join(THREE_DIR, f).replace(/\\/g, '/');
  const html = t
    .replace('https://cdn.jsdelivr.net/npm/three@0.147.0/build/three.min.js', url('build/three.min.js'))
    .replace('https://cdn.jsdelivr.net/npm/three@0.147.0/examples/js/loaders/GLTFLoader.js', url('examples/js/loaders/GLTFLoader.js'))
    .replace('https://cdn.jsdelivr.net/npm/three@0.147.0/examples/js/controls/OrbitControls.js', url('examples/js/controls/OrbitControls.js'))
    .replace('__TITRE__', projet.nom.replace(/</g, '&lt;'))
    .replace('__PLAN__', projet.plan.replace(/</g, '&lt;'))
    .replace('__TAILLE__', (glb.length / 1e6).toFixed(1).replace('.', ',') + ' Mo')
    .replace('__PIECES__', () => esc(fs.readFileSync(sortie('maquette.pieces.json'), 'utf-8')))
    .replace('__REGLAGES__', () => esc(fs.readFileSync(path.join(projet.dossier, 'reglages.json'), 'utf-8')))
    .replace('__AXE__', () => fs.readFileSync(sortie('maquette.axe.json'), 'utf-8'))
    .replace('__GLB__', () => glb.toString('base64'));
  const f = path.join(app.getPath('userData'), 'editeur.html');
  fs.writeFileSync(f, '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">' + html);
  return f;
}
async function ouvrirProjet(dossier) {
  projet = lireProjet(dossier);
  ajouterRecent(dossier);
  modifications = 0;
  win.setTitle(`${projet.nom} · Atelier 3D`);
  if (!fs.existsSync(sortie('maquette.glb'))) {
    win.loadFile(path.join(RACINE, 'accueil.html'), { hash: 'generation' });
    const r = await generer();
    if (!r.ok) { win.webContents.send('erreur', 'La génération a échoué : ' + r.erreur); return; }
  }
  win.loadFile(assemblerEditeur());
  construireMenu();
}
function etat() {
  try { return 'Dernière génération : ' + fs.statSync(sortie('maquette.glb')).mtime.toLocaleString('fr-FR', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' }); }
  catch { return ''; }
}
function enregistrerReglages(R) {
  fs.writeFileSync(path.join(projet.dossier, 'reglages.json'), JSON.stringify(R, null, 2));
  const mp = path.join(projet.dossier, 'projet.json');
  const meta = JSON.parse(fs.readFileSync(mp, 'utf-8')); meta.modifie = new Date().toISOString();
  fs.writeFileSync(mp, JSON.stringify(meta, null, 2));
}
async function exporterGLB() {
  if (!projet) return {};
  const r = await dialog.showSaveDialog(win, { title: 'Enregistrer le GLB', defaultPath: projet.nom + '.glb', filters: [{ name: 'GLB', extensions: ['glb'] }] });
  if (r.canceled || !r.filePath) return {};
  fs.copyFileSync(sortie('maquette.glb'), r.filePath);
  return { chemin: r.filePath };
}
function demanderReglages() {
  return new Promise(resolve => {
    ipcMain.once('reglages', (_e, R) => resolve(R));
    win.webContents.send('demande-reglages');
  });
}

// ---------- dialogues ----------
async function choisirEtOuvrir() {
  const r = await dialog.showOpenDialog(win, { title: 'Ouvrir un projet', properties: ['openDirectory'] });
  if (r.canceled || !r.filePaths[0]) return;
  if (!fs.existsSync(path.join(r.filePaths[0], 'projet.json'))) {
    dialog.showMessageBox(win, { type: 'warning', message: 'Ce dossier n’est pas un projet Atelier 3D.', detail: 'Il doit contenir un fichier projet.json.' }); return;
  }
  ouvrirProjet(r.filePaths[0]);
}
async function nouveauProjet(nom, planSource) {
  if (!planSource) {
    const r = await dialog.showOpenDialog(win, { title: 'Choisir le plan Illustrator', properties: ['openFile'],
      filters: [{ name: 'Plans', extensions: ['ai', 'pdf'] }] });
    if (r.canceled || !r.filePaths[0]) return { ok: false };
    planSource = r.filePaths[0];
  }
  nom = nom || path.basename(planSource).replace(/\.[^.]+$/, '');
  const d = await dialog.showSaveDialog(win, { title: 'Où enregistrer le projet ?', defaultPath: nom, buttonLabel: 'Créer le projet' });
  if (d.canceled || !d.filePath) return { ok: false };
  if (fs.existsSync(d.filePath) && fs.readdirSync(d.filePath).length) {
    dialog.showMessageBox(win, { type: 'warning', message: 'Ce dossier existe déjà et n’est pas vide.' }); return { ok: false };
  }
  creerProjet(d.filePath, nom, planSource, path.join(EXEMPLE, 'reglages.json'));
  ouvrirProjet(d.filePath);
  return { ok: true };
}
async function genererDepuisMenu() {
  if (!projet) return;
  const R = await demanderReglages();
  win.webContents.send('generation-lancee');
  enregistrerReglages(R);
  const r = await generer();
  if (r.ok) { modifications = 0; win.loadFile(assemblerEditeur()); }
  else win.webContents.send('erreur', 'La génération a échoué : ' + r.erreur);
}

// ---------- IPC ----------
ipcMain.handle('generer', async (_e, R) => {
  enregistrerReglages(R);
  const r = await generer();
  if (r.ok) { modifications = 0; setTimeout(() => win.loadFile(assemblerEditeur()), 50); }
  return r;
});
ipcMain.handle('exporter-glb', exporterGLB);
ipcMain.on('etat', e => { e.returnValue = projet ? etat() : ''; });
ipcMain.on('modifie', (_e, n) => { modifications = n; });
ipcMain.handle('accueil', () => ({ recents: config().recents.filter(d => fs.existsSync(path.join(d, 'projet.json'))).map(d => { try { return lireProjet(d); } catch { return null; } }).filter(Boolean),
  python: verifierPython(), config: config(), exemple: fs.existsSync(path.join(EXEMPLE, 'reglages.json')) }));
ipcMain.handle('ouvrir', (_e, d) => d ? ouvrirProjet(d) : choisirEtOuvrir());
ipcMain.handle('nouveau', (_e, nom) => nouveauProjet(nom));
ipcMain.handle('parametres', (_e, p) => { const cur = lireParams();
  if (p.blender && p.blender.endsWith('.app')) p.blender = path.join(p.blender, 'Contents', 'MacOS', 'Blender'); Object.assign(cur, p); ecrireParams(cur); return { python: verifierPython(), config: config() }; });
ipcMain.handle('choisir-fichier', async (_e, titre) => {
  const r = await dialog.showOpenDialog(win, { title: titre, properties: ['openFile'] });
  return r.canceled ? '' : r.filePaths[0];
});

// ---------- menu ----------
function construireMenu() {
  const mac = process.platform === 'darwin';
  const p = !!projet;
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(mac ? [{ role: 'appMenu' }] : []),
    { label: 'Fichier', submenu: [
      { label: 'Nouveau projet…', accelerator: 'CmdOrCtrl+N', click: () => nouveauProjet() },
      { label: 'Ouvrir un projet…', accelerator: 'CmdOrCtrl+O', click: choisirEtOuvrir },
      { label: 'Accueil', click: () => { projet = null; win.setTitle('Atelier 3D'); win.loadFile(path.join(RACINE, 'accueil.html')); construireMenu(); } },
      { type: 'separator' },
      { label: 'Enregistrer les réglages', accelerator: 'CmdOrCtrl+S', enabled: p, click: async () => { enregistrerReglages(await demanderReglages()); modifications = 0; } },
      { label: 'Générer la maquette', accelerator: 'CmdOrCtrl+G', enabled: p, click: genererDepuisMenu },
      { label: 'Enregistrer le GLB…', accelerator: 'CmdOrCtrl+E', enabled: p, click: exporterGLB },
      { type: 'separator' },
      { label: 'Afficher le dossier du projet', enabled: p, click: () => shell.openPath(projet.dossier) },
      { label: 'Journal du moteur', enabled: p, click: () => shell.openPath(sortie('journal.txt')) },
      ...(mac ? [] : [{ type: 'separator' }, { role: 'quit', label: 'Quitter' }]) ] },
    { label: 'Édition', submenu: [{ role: 'undo', label: 'Annuler' }, { role: 'redo', label: 'Rétablir' }, { type: 'separator' },
      { role: 'cut', label: 'Couper' }, { role: 'copy', label: 'Copier' }, { role: 'paste', label: 'Coller' }, { role: 'selectAll', label: 'Tout sélectionner' }] },
    { label: 'Affichage', submenu: [{ role: 'reload', label: 'Recharger' }, { role: 'toggleDevTools', label: 'Outils de développement' },
      { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'togglefullscreen', label: 'Plein écran' }] },
  ]));
}

// ---------- démarrage ----------
app.whenReady().then(() => {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 900, minHeight: 600, title: 'Atelier 3D', backgroundColor: '#f4f2ee',
    webPreferences: { preload: path.join(RACINE, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: false },
  });
  win.on('close', e => {
    if (!modifications) return;
    const r = dialog.showMessageBoxSync(win, { type: 'question', buttons: ['Quitter sans enregistrer', 'Annuler'], defaultId: 1, cancelId: 1,
      message: `${modifications} réglage${modifications > 1 ? 's' : ''} modifié${modifications > 1 ? 's' : ''} pas encore enregistré${modifications > 1 ? 's' : ''}.`,
      detail: 'Utilisez Fichier › Enregistrer les réglages, ou Générer la maquette.' });
    if (r === 1) e.preventDefault();
  });
  construireMenu();
  const arg = process.argv.find(a => a.startsWith('--projet='));
  if (arg) ouvrirProjet(path.resolve(arg.slice(9))); else win.loadFile(path.join(RACINE, 'accueil.html'));
});
app.on('window-all-closed', () => app.quit());
