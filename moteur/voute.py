"""Plafonds non plats : voute en berceau (arc surbaisse) au-dessus d'une piece.
Reglages : etape_2_murs > plafonds (forme, hauteur_naissance_m, hauteur_cle_m, axe_deg)."""
import math, numpy as np, trimesh
from shapely.geometry import box, Polygon
from shapely import affinity


class Berceau:
    def __init__(self, room, naissance, cle, axe_deg=None):
        mr = room.minimum_rotated_rectangle; c = list(mr.exterior.coords)
        e = [(c[i], c[i + 1]) for i in range(2)]
        lng = max(e, key=lambda s: math.dist(*s))
        self.theta = math.degrees(math.atan2(lng[1][1] - lng[0][1], lng[1][0] - lng[0][0])) if axe_deg is None else axe_deg
        self.o = room.centroid
        r = affinity.rotate(room, -self.theta, origin=self.o)      # axe de la voute -> axe x
        y0, y1 = r.bounds[1], r.bounds[3]
        self.vc, self.a = (y0 + y1) / 2, (y1 - y0) / 2             # milieu et demi-portee
        self.f = cle - naissance; self.n = naissance
        self.R = (self.a ** 2 + self.f ** 2) / (2 * self.f)
        self.room, self.rot = room, r

    def h_local(self, v):
        d = np.minimum(np.abs(np.asarray(v) - self.vc), self.a)
        return self.n + np.sqrt(self.R ** 2 - d ** 2) - (self.R - self.f)

    def h(self, x, y):   # hauteur sous voute en un point du plan (m au-dessus du sol)
        p = affinity.rotate(Polygon([(x, y), (x + 1e-3, y), (x, y + 1e-3)]), -self.theta, origin=self.o).exterior.coords[0]
        return float(self.h_local(p[1]))

    def mesh(self, z0, hole=None, step=0.05):
        r = self.rot if hole is None else self.rot.difference(affinity.rotate(hole, -self.theta, origin=self.o))
        x0, y0, x1, y1 = r.bounds; ms = []
        for v in np.arange(y0, y1, step):
            s = r.intersection(box(x0 - 1, v, x1 + 1, min(v + step, y1)))
            for p in getattr(s, 'geoms', [s]):
                if not isinstance(p, Polygon) or p.area < 1e-6: continue
                V, F = trimesh.creation.triangulate_polygon(p)
                V3 = np.c_[V, z0 + self.h_local(V[:, 1])]
                ms.append(trimesh.Trimesh(V3, F[:, ::-1], process=False))   # normales vers le bas
        m = trimesh.util.concatenate(ms); m.merge_vertices()
        t = np.radians(self.theta); ox, oy = self.o.x, self.o.y
        x, y = m.vertices[:, 0] - ox, m.vertices[:, 1] - oy
        m.vertices = np.c_[ox + x * np.cos(t) - y * np.sin(t), oy + x * np.sin(t) + y * np.cos(t), m.vertices[:, 2]]
        return m
