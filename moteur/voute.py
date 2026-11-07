"""Plafonds non plats au-dessus d'une piece : voute en berceau, voute d'aretes, plafond cathedrale.
Reglages : etape_2_murs > plafonds[] (niveau, piece_plan_pt, forme, hauteur_naissance_m, hauteur_cle_m, axe_deg, travees).

  voute_berceau : arc surbaisse dans la largeur de la piece, constant sur sa longueur (axe = longueur de la piece).
  voute_aretes  : berceaux croises, en travees a peu pres carrees le long de la piece (reglage travees, vide = auto).
  cathedrale    : deux pans droits, faitage au milieu, dans l'axe de la piece.
Les hauteurs sont mesurees depuis le sol du niveau.
"""
import math, numpy as np, trimesh
from shapely.geometry import box, Polygon
from shapely import affinity

FORMES = ('voute_berceau', 'voute_aretes', 'cathedrale')


class Voute:
    def __init__(self, room, naissance, cle, axe_deg=None, forme='voute_berceau', travees=None):
        mr = room.minimum_rotated_rectangle; c = list(mr.exterior.coords)
        e = [(c[i], c[i + 1]) for i in range(2)]
        lng = max(e, key=lambda s: math.dist(*s))
        self.theta = math.degrees(math.atan2(lng[1][1] - lng[0][1], lng[1][0] - lng[0][0])) if axe_deg is None else axe_deg
        self.o = room.centroid
        r = affinity.rotate(room, -self.theta, origin=self.o)      # axe de la voute -> axe x
        x0, y0, x1, y1 = r.bounds
        self.vc, self.a = (y0 + y1) / 2, (y1 - y0) / 2             # milieu et demi-portee (largeur)
        self.uc, self.b = (x0 + x1) / 2, (x1 - x0) / 2             # milieu et demi-longueur (voute d'aretes)
        self.f = max(1e-3, cle - naissance); self.n = naissance
        self.forme = forme if forme in FORMES else 'voute_berceau'
        self.nb = max(1, int(travees or round(self.b / max(self.a, 1e-3))))    # voute d'aretes : travees a peu pres carrees
        self.room, self.rot = room, r

    def _arc(self, d, a):
        R = (a ** 2 + self.f ** 2) / (2 * self.f)
        d = np.minimum(np.abs(d), a)
        return self.n + np.sqrt(np.maximum(R ** 2 - d ** 2, 0)) - (R - self.f)

    def h_uv(self, u, v):
        u, v = np.asarray(u, float), np.asarray(v, float)
        if self.forme == 'cathedrale':
            return self.n + self.f * (1 - np.minimum(np.abs(v - self.vc), self.a) / self.a)
        hv = self._arc(v - self.vc, self.a)
        if self.forme == 'voute_aretes':
            L = 2 * self.b / self.nb
            return np.maximum(hv, self._arc(np.mod(u - (self.uc - self.b), L) - L / 2, L / 2))
        return hv

    def h_local(self, v):     # compatibilite : berceau
        return self.h_uv(self.uc, v)

    def h(self, x, y):   # hauteur sous voute en un point du plan (m au-dessus du sol)
        t = math.radians(-self.theta); dx, dy = x - self.o.x, y - self.o.y
        u, v = self.o.x + dx * math.cos(t) - dy * math.sin(t), self.o.y + dx * math.sin(t) + dy * math.cos(t)
        return float(self.h_uv(u, v))

    def mesh(self, z0, hole=None, step=0.05):
        r = self.rot if hole is None else self.rot.difference(affinity.rotate(hole, -self.theta, origin=self.o))
        x0, y0, x1, y1 = r.bounds; ms = []
        vs = sorted(set(np.round(np.r_[np.arange(y0, y1, step), self.vc, y1], 6)))
        us = sorted(set(np.round(np.r_[np.arange(x0, x1, 0.1), self.uc - self.b + np.arange(self.nb * 2 + 1) * self.b / self.nb, x1], 6))) if self.forme == 'voute_aretes' else [x0 - 1, x1 + 1]
        for va, vb in zip(vs[:-1], vs[1:]):
            for ua, ub in zip(us[:-1], us[1:]):
                s = r.intersection(box(ua, va, ub, vb))
                for p in getattr(s, 'geoms', [s]):
                    if not isinstance(p, Polygon) or p.area < 1e-7: continue
                    V, F = trimesh.creation.triangulate_polygon(p)
                    V3 = np.c_[V, z0 + self.h_uv(V[:, 0], V[:, 1])]
                    ms.append(trimesh.Trimesh(V3, F[:, ::-1], process=False))   # normales vers le bas
        m = trimesh.util.concatenate(ms); m.merge_vertices()
        t = np.radians(self.theta); ox, oy = self.o.x, self.o.y
        x, y = m.vertices[:, 0] - ox, m.vertices[:, 1] - oy
        m.vertices = np.c_[ox + x * np.cos(t) - y * np.sin(t), oy + x * np.sin(t) + y * np.cos(t), m.vertices[:, 2]]
        return m


def Berceau(room, naissance, cle, axe_deg=None):
    return Voute(room, naissance, cle, axe_deg, 'voute_berceau')
