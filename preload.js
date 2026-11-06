// Pont entre les pages (éditeur, accueil) et le logiciel : seules ces fonctions sont exposées.
const { contextBridge, ipcRenderer } = require('electron');
let fournisseur = null, surMsg = null;
ipcRenderer.on('demande-reglages', () => ipcRenderer.send('reglages', fournisseur ? fournisseur() : null));
ipcRenderer.on('generation-lancee', () => surMsg && surMsg('Le moteur reconstruit la maquette (quelques secondes)…'));
ipcRenderer.on('erreur', (_e, t) => surMsg && surMsg(t));
contextBridge.exposeInMainWorld('atelier', {
  // éditeur
  generer: R => ipcRenderer.invoke('generer', R),
  exporterGLB: () => ipcRenderer.invoke('exporter-glb'),
  ouvrirVisite: () => ipcRenderer.invoke('ouvrir-visite'),
  exporterVisite: () => ipcRenderer.invoke('exporter-visite'),
  etat: () => ipcRenderer.sendSync('etat'),
  modifie: n => ipcRenderer.send('modifie', n),
  fournir: f => { fournisseur = f; },
  surMessage: f => { surMsg = f; },
  // accueil
  accueil: () => ipcRenderer.invoke('accueil'),
  ouvrir: dossier => ipcRenderer.invoke('ouvrir', dossier),
  nouveau: nom => ipcRenderer.invoke('nouveau', nom),
  parametres: p => ipcRenderer.invoke('parametres', p),
  choisirFichier: titre => ipcRenderer.invoke('choisir-fichier', titre),
});
