#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Araignée de bureau (desktop pet) pour Windows - Python + tkinter, aucune dépendance.

 - Elle se balade sur le bureau, curieuse de la souris, et fuit si on fonce dessus.
 - Elle tisse une toile dans un coin de l'écran.
 - Si tu traverses la toile avec la souris (la détruis), elle te saute dessus
   et s'accroche à ton curseur en signe de désaccord.
   Secoue vite la souris pour la faire tomber.
 - L'araignée ne gêne jamais les clics (fenêtre transparente "click-through").

Quitter : Ctrl + Alt + Q   (ou arreter_araignee.bat)

Options : --corner tr|tl|br|bl   coin de la toile (défaut tr)
          --scale 1.3            taille de l'araignée
"""
import atexit
import ctypes
import io
import math
import os
import random
import sys
import time
import shutil
import struct
import tempfile
import tkinter as tk
import wave as wavemod
from ctypes import wintypes

try:
    import winsound
except Exception:
    winsound = None

user32 = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]

KEY = '#010203'          # couleur rendue transparente
BODY = '#2e1f40'
SHINE = '#40342d'
WEB_LIGHT = '#f4f4f4'
WEB_SHADOW = '#262626'
PI = math.pi


# ----------------------------------------------------------------- maths utiles
def clamp(v, a, b):
    return a if v < a else b if v > b else v


def lerp(a, b, t):
    return a + (b - a) * t


def mix(h1, h2, t):
    """Mélange deux couleurs '#rrggbb' (t=0 -> h1, t=1 -> h2)."""
    a = [int(h1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(h2[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def angdiff(a, b):
    return (b - a + PI) % (2 * PI) - PI


def pt_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else clamp(((px - ax) * dx + (py - ay) * dy) / l2, 0.0, 1.0)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _ccw(ax, ay, bx, by, cx, cy):
    return (cy - ay) * (bx - ax) > (by - ay) * (cx - ax)


def seg_seg_dist(a, b, c, d):
    if (_ccw(a[0], a[1], c[0], c[1], d[0], d[1]) != _ccw(b[0], b[1], c[0], c[1], d[0], d[1])
            and _ccw(a[0], a[1], b[0], b[1], c[0], c[1]) != _ccw(a[0], a[1], b[0], b[1], d[0], d[1])):
        return 0.0
    return min(pt_seg(a[0], a[1], c[0], c[1], d[0], d[1]),
               pt_seg(b[0], b[1], c[0], c[1], d[0], d[1]),
               pt_seg(c[0], c[1], a[0], a[1], b[0], b[1]),
               pt_seg(d[0], d[1], a[0], a[1], b[0], b[1]))


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD)]


MON = {'ox': 0, 'oy': 0, 'rect': None, 'index': 1}        # origine (coin haut-gauche) du moniteur choisi, en coordonnées bureau


def list_monitors():
    """[{primary, rect, work}] : le principal d'abord, puis de gauche à droite."""
    res = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hm, hdc, rc, lp):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        user32.GetMonitorInfoW(hm, ctypes.byref(mi))
        r, w = mi.rcMonitor, mi.rcWork
        res.append(dict(primary=bool(mi.dwFlags & 1), rect=(r.left, r.top, r.right, r.bottom), work=(w.left, w.top, w.right, w.bottom)))
        return True

    try:
        user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    except Exception:
        pass
    res.sort(key=lambda m: (not m['primary'], m['rect'][0]))
    return res


def real_cursor():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return float(pt.x - MON['ox']), float(pt.y - MON['oy'])


def work_area():
    r = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)   # SPI_GETWORKAREA
    return r.left, r.top, r.right, r.bottom



# ------------------------------------------------------------------------ sons
class Sound:
    """Petits sons synthétisés en mémoire (aucun fichier), doux et cohérents :
    - interface (clic, objet, réussite) : notes douces accordées ensemble (do - mi - sol), très discrètes ;
    - voix des animaux, version bébé : « miou ? » du chaton, « yip yip » du chiot, « mééé » du chevreau, « dook-dook » du furet ;
    - petits bruits de dessin animé : « nom nom », « bzzz », « cui-cui », « fiuuu » en dormant.
    Tous les sons sont ramenés au même niveau perçu, puis le volume suit une courbe en décibels (10 % = vraiment bas)."""
    RATE = 22050
    # f0, f1 (Hz, glissando), duree, type, niveau relatif, enveloppe, options
    #   type : 'tone' (harmoniques douces), 'noise' (bruit filtre)  -  env : 'pluck' (attaque nette, extinction) | 'swell' (monte puis descend)
    TABLE = {
        # --- interface : petites notes douces (do - mi - sol), dans le medium
        'tap': (170, 120, 0.05, 'tone', 0.20, 'pluck', dict(h=((1, 1), (2, 0.2)), k=8)),                 # « pof » feutre (sauts, pas, clics)
        'pop': (440, 740, 0.07, 'tone', 0.38, 'pluck', dict(k=5)),                                       # petite bulle
        'ding': (784, 784, 0.12, 'tone', 0.36, 'pluck', dict(h=((1, 1), (2, 0.12)), k=4, pulses=3, gap=0.0, notes=(1, 1.26, 1.5))),   # « tin-tin-tin »
        'clink': (1047, 1047, 0.14, 'tone', 0.26, 'pluck', dict(h=((1, 1), (2.76, 0.15)), k=8, pulses=2, gap=0.03, notes=(1, 1.26))),
        'boing': (220, 440, 0.26, 'tone', 0.30, 'pluck', dict(vib=(9, 0.04), k=4, arc=True)),            # ressort, grave et court
        # --- araignee / proies
        'buzz': (260, 245, 0.3, 'tone', 0.14, 'swell', dict(h=((1, 1), (2, 0.3)), am=(32, 0.6))),
        'chirp': (1319, 1568, 0.06, 'tone', 0.24, 'pluck', dict(pulses=2, gap=0.05, notes=(1, 1.12))),
        'crunch': (440, 350, 0.08, 'tone', 0.34, 'pluck', dict(h=((1, 1), (2, 0.25)), am=(30, 0.5), pulses=2, gap=0.09, notes=(1, 0.9), k=3)),   # « nom nom »
        'hiss': (0, 0, 0.22, 'noise', 0.20, 'swell', dict(lp=0.45)),
        # --- chat (chaton)
        'meow': (620, 860, 0.26, 'tone', 0.45, 'swell', dict(h=((1, 1), (2, 0.2)), vib=(7, 0.02), arc=True)),          # « miou ? »
        'purr': (520, 640, 0.07, 'tone', 0.20, 'pluck', dict(am=(26, 0.6), pulses=2, gap=0.03, notes=(1, 1.19), k=3)),  # « mrrp »
        'snore': (700, 520, 0.36, 'tone', 0.12, 'swell', dict(vib=(4, 0.01))),                           # « fiuuu » tout doux
        # --- chien (chiot)
        'woof': (540, 740, 0.11, 'tone', 0.45, 'pluck', dict(h=((1, 1), (2, 0.3)), arc=True, k=3, pulses=2, gap=0.07, notes=(1, 1.06))),  # « yip yip »
        'pant': (0, 0, 0.11, 'noise', 0.12, 'swell', dict(lp=0.25, pulses=2, gap=0.08)),
        # --- chevre naine (chevreau)
        'bleat': (580, 650, 0.40, 'tone', 0.42, 'swell', dict(h=((1, 1), (2, 0.25)), vib=(9, 0.06), arc=True)),       # « mééé »
        'bleat_s': (620, 670, 0.18, 'tone', 0.28, 'swell', dict(vib=(9, 0.05), arc=True)),
        # --- furet
        'dook': (880, 720, 0.05, 'tone', 0.38, 'pluck', dict(h=((1, 1), (2, 0.15)), pulses=3, gap=0.05, notes=(1, 1.06, 1.12), k=3)),
        'dook_s': (800, 720, 0.045, 'tone', 0.22, 'pluck', dict(pulses=2, gap=0.06, k=3)),
    }
    # un meme son ne revient pas avant ce delai (secondes) : rien ne tourne en boucle ni ne devient agacant
    COOLDOWN = {'tap': 0.4, 'pop': 0.4, 'ding': 0.8, 'clink': 1.0, 'boing': 2.0, 'buzz': 6.0, 'chirp': 4.0, 'crunch': 1.5,
                'hiss': 3.0, 'meow': 8.0, 'purr': 5.0, 'snore': 7.0, 'woof': 7.0, 'pant': 5.0, 'bleat': 9.0, 'bleat_s': 6.0,
                'dook': 7.0, 'dook_s': 5.0}
    RANGE_DB = 36.0                       # 100 % -> 10 % = -32 dB environ

    def __init__(self):
        self.on = winsound is not None
        self.volume = 0.3                 # 0.1 .. 1.0
        self.cache = {}
        self.last = 0.0
        self.next_ok = {}
        self.dir = None

    def set_volume(self, v):
        self.volume = clamp(round(v * 20) / 20.0, 0.1, 1.0)   # par pas de 5 %
        self.cache = {}                   # les sons sont régénérés au nouveau volume

    def gain(self):
        """Volume percu : courbe en decibels (lineaire, 10 % etait encore beaucoup trop fort)."""
        return 10 ** (-self.RANGE_DB * (1.0 - self.volume) / 20.0)

    def _make(self, name):
        f0, f1, dur, kind, level, envk, o = self.TABLE[name]
        R = self.RATE
        pulses, gap = o.get('pulses', 1), o.get('gap', 0.0)
        n1, ng = int(R * dur), int(R * gap)
        harm = o.get('h', ((1, 1),))
        vib_f, vib_d = o.get('vib', (0, 0))
        am_f, am_d = o.get('am', (0, 0))
        bend = o.get('bend', 0.0)                       # le miaou retombe a la fin
        k = o.get('k', 5)
        lp = o.get('lp', 1.0)
        att, rel = int(R * 0.004), int(R * 0.006)        # pas de « clic » au debut ni a la fin
        sig = []
        notes = o.get('notes', (1,))
        for p_ in range(pulses):
            nm = notes[p_ % len(notes)]                 # chaque coup peut etre une autre note (arpege)
            ph = [0.0] * len(harm)
            y = 0.0
            for i in range(n1):
                t = i / n1
                f = (f0 + (f1 - f0) * (math.sin(PI * t) if o.get('arc') else t)) * nm   # arc : monte puis redescend (« miou ? »)
                if bend:
                    f *= 1.0 + bend * max(0.0, t - 0.6) / 0.4
                if vib_f:
                    f *= 1.0 + vib_d * math.sin(2 * PI * vib_f * i / R)
                if kind == 'noise':
                    y += lp * (random.uniform(-1, 1) - y)
                    v = y
                else:
                    v = 0.0
                    for j, (r_, a_) in enumerate(harm):
                        ph[j] += 2 * PI * f * r_ / R
                        v += a_ * math.sin(ph[j])
                env = math.exp(-k * t) if envk == 'pluck' else math.sin(PI * t) ** 0.8
                env *= min(1.0, i / max(1, att)) * min(1.0, (n1 - i) / max(1, rel))
                if am_f:
                    env *= 1.0 - am_d * (0.5 + 0.5 * math.sin(2 * PI * am_f * i / R))
                sig.append(v * env)
            if p_ < pulses - 1:
                sig.extend([0.0] * ng)
        rms = math.sqrt(sum(x * x for x in sig) / max(1, len(sig))) or 1.0
        g = 0.22 / rms * level * self.gain()                # meme niveau percu pour tous les sons, puis le volume
        out = bytearray()
        for x in sig:
            out += struct.pack('<h', int(math.tanh(x * g) * 32767))
        buf = io.BytesIO()
        with wavemod.open(buf, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(R)
            w.writeframes(bytes(out))
        return buf.getvalue()

    def _path(self, name):
        """winsound ne sait pas jouer un son en mémoire en asynchrone : on passe par de petits .wav temporaires."""
        key = (name, int(round(self.volume * 100)))
        if key not in self.cache:
            if self.dir is None:
                self.dir = tempfile.mkdtemp(prefix='araignee_snd_')
                atexit.register(shutil.rmtree, self.dir, True)
            path = os.path.join(self.dir, '%s_%d.wav' % key)
            with open(path, 'wb') as f:
                f.write(self._make(name))
            self.cache[key] = path
        return self.cache[key]

    def play(self, name, force=False):
        if not self.on or winsound is None or name not in self.TABLE:
            return
        now = time.perf_counter()
        if not force and (now - self.last < 0.2 or now < self.next_ok.get(name, 0.0)):
            return
        self.last = now
        self.next_ok[name] = now + self.COOLDOWN.get(name, 1.0)
        try:
            winsound.PlaySound(self._path(name), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass


# ------------------------------------------------------------------------ toile
class Seg:
    __slots__ = ('a', 'b', 'c', 'kind', 'prog', 'built', 'len', 'poly', 'dew')

    def __init__(self, a, b, c, kind):
        self.a, self.b, self.c, self.kind = a, b, c, kind
        self.prog = 0.0
        self.built = False
        self.dew = None
        self.len = math.hypot(b[0] - a[0], b[1] - a[1]) * 1.03
        self.poly = [self.point(i / 8) for i in range(9)] if kind == 'ring' else [a, b]

    def point(self, t):
        if self.kind == 'radial':
            return (lerp(self.a[0], self.b[0], t), lerp(self.a[1], self.b[1], t))
        u = 1 - t
        return (u * u * self.a[0] + 2 * u * t * self.c[0] + t * t * self.b[0],
                u * u * self.a[1] + 2 * u * t * self.c[1] + t * t * self.b[1])

    def hit(self, p, q, radius):
        pl = self.poly
        return any(seg_seg_dist(p, q, pl[i], pl[i + 1]) < radius for i in range(len(pl) - 1))

    def nearest(self, x, y):
        best, bd = self.a, 1e18
        pl = self.poly
        for i in range(len(pl) - 1):
            ax, ay = pl[i]
            bx, by = pl[i + 1]
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else clamp(((x - ax) * dx + (y - ay) * dy) / l2, 0.0, 1.0)
            px, py = ax + t * dx, ay + t * dy
            d = math.hypot(x - px, y - py)
            if d < bd:
                best, bd = (px, py), d
        return best

    def points(self, prog):
        if self.kind == 'radial':
            return [self.a, self.point(prog)]
        n = max(2, int(6 * prog) + 1)
        return [self.point(prog * i / (n - 1)) for i in range(n)]


class Web:
    def __init__(self, area, corner, s):
        l, t, r, b = area
        sx = 1 if 'l' in corner else -1
        sy = 1 if 't' in corner else -1
        self.hub = (l if sx == 1 else r, t if sy == 1 else b)
        hx, hy = self.hub
        self.sx, self.sy = sx, sy
        self.s = s
        R = 170 * s
        self.R = R
        n = 7
        radii = [R * f for f in (0.2, 0.34, 0.5, 0.66, 0.83, 1.0)]
        angs = [math.radians(5 + 80 * k / (n - 1)) for k in range(n)]

        def P(i, k):
            return (hx + sx * math.cos(angs[k]) * radii[i], hy + sy * math.sin(angs[k]) * radii[i])

        self.segs = []
        for k in range(n):                                   # rayons
            self.segs.append(Seg(self.hub, P(len(radii) - 1, k), None, 'radial'))
        for i in range(len(radii)):                          # spirale en zigzag
            order = range(n - 1) if i % 2 == 0 else range(n - 2, -1, -1)
            for k in order:
                p, q = P(i, k), P(i, k + 1)
                if i % 2:
                    p, q = q, p
                mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
                ctrl = (mid[0] + (hx - mid[0]) * 0.22, mid[1] + (hy - mid[1]) * 0.22)
                self.segs.append(Seg(p, q, ctrl, 'ring'))
        self.debris = []
        self.lw = 1 if s < 1.5 else 2

    def next_unbuilt(self):
        for sg in self.segs:
            if not sg.built:
                return sg
        return None

    def missing(self):
        return sum(1 for sg in self.segs if not sg.built)

    def built_ratio(self):
        return 1 - self.missing() / len(self.segs)

    def cut_path(self, p, q, radius):
        cut = []
        for sg in self.segs:
            if sg.built and sg.hit(p, q, radius):
                sg.built = False
                sg.prog = 0.0
                cut.append(sg)
                g = 900 * self.s
                self.debris.append([sg.a[0], sg.a[1], sg.b[0], sg.b[1],
                                    random.uniform(-60, 60), random.uniform(-80, 0),
                                    random.uniform(-60, 60), random.uniform(-80, 0), 0.0, g])
        return cut

    def update_debris(self, dt):
        for d in self.debris:
            d[4] *= 0.98
            d[6] *= 0.98
            d[5] += d[9] * dt
            d[7] += d[9] * dt * 1.3
            d[0] += d[4] * dt
            d[1] += d[5] * dt
            d[2] += d[6] * dt
            d[3] += d[7] * dt
            d[8] += dt
        self.debris = [d for d in self.debris if d[8] < 0.8]

    def ensure_dew(self):
        for sg in self.segs:
            if not sg.built:
                sg.dew = None
            elif sg.dew is None:
                sg.dew = [(random.uniform(0.15, 0.85), random.uniform(0, 6.28))
                          for _ in range(2 if sg.kind == 'ring' else 3)]

    def draw(self, c, dew=False, now=0.0, jit=False, part='all'):
        lw = self.lw
        for sg in self.segs:
            if not sg.built and sg.prog <= 0:
                continue
            if (part == 'static' and not sg.built) or (part == 'dyn' and sg.built):
                continue
            pts = sg.points(1.0 if sg.built else sg.prog)
            flat = [v for p in pts for v in p]
            c.create_line(*[v + 1 for v in flat], fill=WEB_SHADOW, width=lw)
            c.create_line(*flat, fill=WEB_LIGHT, width=lw)
        if dew and part != 'dyn':                           # gouttes de rosée
            r_ = max(2.0, 1.1 * self.s)
            for sg in self.segs:
                if not sg.built:
                    sg.dew = None
                    continue
                if sg.dew is None:
                    sg.dew = [(random.uniform(0.15, 0.85), random.uniform(0, 6.28))
                              for _ in range(2 if sg.kind == 'ring' else 3)]
                for tt, ph in sg.dew:
                    x, y = sg.point(tt)
                    if jit:
                        x += random.uniform(-1, 1)
                        y += random.uniform(-1, 1)
                    c.create_oval(x - r_, y - r_, x + r_, y + r_, fill='#d7ecff', outline='#6f9fc6')
                    if math.sin(now * 2.4 + ph) > 0.1:
                        c.create_oval(x - r_ * 0.55, y - r_ * 0.65, x - r_ * 0.1, y - r_ * 0.15, fill='#ffffff', outline='')
        if part != 'static':
            for d in self.debris:
                c.create_line(d[0] + 1, d[1] + 1, d[2] + 1, d[3] + 1, fill=WEB_SHADOW, width=lw)
                c.create_line(d[0], d[1], d[2], d[3], fill=WEB_LIGHT, width=lw)


# --------------------------------------------------------------------- araignée
HIP_F = [6, 3, -1, -4]
REST_F = [18, 8, -6, -18]
REST_D = [17, 21, 21, 18]

SPECIES = {
    'peacock': dict(name='Peacock (Maratus)', L=(12, 16), size=1.0, speed=1.0),
    'regius': dict(name='Phidippus regius', L=(11, 14), size=1.0, speed=1.0),
    'widow': dict(name='Veuve noire', L=(13, 18), size=1.0, speed=0.85,
                  rest_f=[19, 9, -6, -19], rest_d=[19, 24, 25, 21]),
    'tarantula': dict(name='Mygale', L=(10, 13), size=1.5, speed=0.55,
                      rest_f=[17, 8, -6, -17], rest_d=[16, 20, 20, 17]),
    'wolf': dict(name='Lycose', L=(12, 16), size=1.1, speed=1.5),
    'pholcus': dict(name='Pholque', L=(22, 30), size=0.85, speed=0.8,
                    rest_f=[32, 15, -12, -32], rest_d=[28, 38, 38, 31]),
    'crab': dict(name='Araignee-crabe', L=(13, 17), size=1.0, speed=0.8,
                 rest_f=[22, 10, -8, -20], rest_d=[22, 27, 27, 24], off=PI / 2),
}
POUNCE = {'default': (0.6, 320, 60, 60), 'wolf': (0.15, 480, 40, 75), 'crab': (0.1, 300, 25, 70),
          'tarantula': (0.3, 250, 14, 70)}
SPECIES_ORDER = ['peacock', 'regius', 'widow', 'tarantula', 'wolf', 'pholcus', 'crab']
# (contour, couleur, bague, bout, épaisseur)
LEGSTYLE = {
    'widow': ('#050505', '#1c1c20', None, None, 0.85),
    'tarantula': ('#2a1c14', '#5a4332', '#e0652a', None, 1.9),
    'wolf': ('#3a2d22', '#9a8461', '#5a4632', '#3a2d22', 1.0),
    'pholcus': ('#7b6e58', '#d8ccb0', None, None, 0.55),
    'crab': ('#8a8050', None, None, None, 1.0),
}
IRIS = {'regius': '#3d7a5e', 'peacock': '#8a5a2a', 'widow': '#a21a1a', 'tarantula': '#7a4a22',
        'wolf': '#c8a02e', 'pholcus': '#5a86a8', 'crab': '#8a9a3a'}
FACE = {'peacock': ('#d29a58', '#1a1015'), 'regius': ('#e6e6ea', '#1a1015'), 'widow': ('#14141a', '#f2f2f2'),
        'tarantula': ('#5a4332', '#f2e6d2'), 'wolf': ('#9a8461', '#1a1015'), 'pholcus': ('#d8ccb0', '#1a1015'),
        'crab': (None, '#1a1015')}


CUTE_PAL = {
    'peacock': ('#8a6ad8', '#3a2a78', '#f2c230'),
    'regius': ('#f6f0f8', '#9a8fa6', '#ff8fb8'),
    'widow': ('#3a3a4c', '#0c0c14', '#ff4a5a'),
    'tarantula': ('#b88a5c', '#5a3c22', '#ff9a4a'),
    'wolf': ('#c9a97a', '#6a5036', '#fff0c8'),
    'pholcus': ('#f4e8c8', '#b09a6a', '#8ccaff'),
    'crab': (None, None, '#ff8aa8'),
}


ANIMALS = {'spider': 'Araignee', 'cat': 'Chat', 'dog': 'Chien', 'goat': 'Chevre naine', 'ferret': 'Furet'}
ANIMALS_READY = {'spider', 'cat', 'dog', 'goat', 'ferret'}                 # les autres sont affichés mais grisés tant qu'ils ne sont pas faits


def next_species(sp_name):
    return SPECIES_ORDER[(SPECIES_ORDER.index(sp_name) + 1) % len(SPECIES_ORDER)] if sp_name in SPECIES_ORDER else 'peacock'


class Spider:
    def __init__(self, x, y, s, species='peacock'):
        self.s = s
        self.species = species
        self.dance = 0.0
        self.dphase = 0.0
        self.wave = 0.0
        self.happy = 0.0
        self.gphase = 0.0
        self.pang = None
        self.gaze = (0.0, 0.0)
        self.splay = False
        self.wash = 0.0
        self.sleeping = False
        self.pulse = 0.0
        self.x, self.y = x, y
        self.ang = random.uniform(-PI, PI)
        self.z = 0.0
        self.elev = 0.0
        self.vx = self.vy = 0.0
        self.camo = [235.0, 225.0, 160.0]
        self.threat = 0.0
        self.hidden = False
        self.carry = 0
        self.cute = False
        self.t_anim = 0.0
        self.leg_k = 1.0
        self.body_off = 0.0
        self.rest_f, self.rest_d = REST_F, REST_D
        self.L1 = self.L2 = 10 * s
        self.feet = [None] * 8
        self.step = [None] * 8
        self.apply_species(species, s)

    def apply_species(self, species, base):
        spec = SPECIES[species]
        self.species = species
        self.base = base
        self.s = base * spec['size']
        self.leg_k = 0.82 if self.cute else 1.0
        self.L1, self.L2 = spec['L'][0] * self.s * self.leg_k, spec['L'][1] * self.s * self.leg_k
        self.rest_f = spec.get('rest_f', REST_F)
        self.rest_d = spec.get('rest_d', REST_D)
        self.body_off = spec.get('off', 0.0)
        self.dance = self.wave = self.happy = self.threat = 0.0
        self.snap_feet()

    def camo_hex(self, mul=1.0):
        return '#%02x%02x%02x' % tuple(int(clamp(v * mul, 0, 255)) for v in self.camo)

    def loc(self, f, d, k=1.0):
        ea = self.ang + self.body_off
        ca, sa = math.cos(ea), math.sin(ea)
        return self.x + (f * ca - d * sa) * k, self.y + (f * sa + d * ca) * k

    def rest_world(self, i, lead=(0.0, 0.0), ext=1.0):
        j = i % 4
        sd = -1 if i < 4 else 1
        s = self.s
        lk = self.leg_k
        fx, fy = self.loc(self.rest_f[j] * s * lk, sd * self.rest_d[j] * s * lk, ext)
        return fx + lead[0], fy + lead[1]

    def snap_feet(self):
        for i in range(8):
            self.feet[i] = self.rest_world(i)
            self.step[i] = None

    @staticmethod
    def _group(i):
        return ((i % 4) + (i // 4)) % 2

    def update_legs(self, dt):
        """Démarche en tétrapode : les deux groupes de 4 pattes alternent à une cadence liée à la vitesse,
        chaque patte posée reste fixe au sol, les 4 paires partent avec un léger décalage (avant -> arrière)."""
        s = self.s
        speed = math.hypot(self.vx, self.vy)
        self.t_anim += dt
        if self.pang is None:
            self.pang = self.ang
        omega = abs(angdiff(self.pang, self.ang)) / max(dt, 1e-3)
        self.pang = self.ang
        if self.z > 2 or self.splay:        # en l'air / pendue : pattes écartées
            for i in range(8):
                self.feet[i] = self.rest_world(i, ext=1.3)
                self.step[i] = None
            return
        for i in range(8):                  # avance des pas en cours
            st = self.step[i]
            if st is None:
                continue
            st[0] += dt
            t = st[0] / st[1]
            if t < 0:
                continue
            if t >= 1:
                self.feet[i] = (st[4], st[5])
                self.step[i] = None
            else:
                e = t * t * (3 - 2 * t)
                self.feet[i] = (lerp(st[2], st[4], e), lerp(st[3], st[5], e))
        if speed > 12 * s or omega > 1.0:
            freq = clamp(speed / (24 * s), 2.2, 9.0)
            dur = 0.42 / freq
            k = dur + 0.25 / freq
            lx, ly = self.vx * k, self.vy * k
            ll = math.hypot(lx, ly)
            if ll > 24 * s:
                lx, ly = lx * 24 * s / ll, ly * 24 * s / ll
            prev_h = int(self.gphase * 2)
            self.gphase += dt * freq
            if int(self.gphase * 2) != prev_h:
                g = int(self.gphase * 2) % 2
                for i in range(8):
                    if self._group(i) == g and self.step[i] is None:
                        rx, ry = self.rest_world(i, (lx, ly))
                        fx, fy = self.feet[i]
                        self.step[i] = [-0.025 * (i % 4), dur, fx, fy, rx, ry]
            limit = 30 * s
        else:                               # à l'arrêt : remet les pattes en place une par une
            dur = 0.12
            limit = 9 * s
        for i in range(8):
            if self.step[i] is None:
                rx, ry = self.rest_world(i)
                fx, fy = self.feet[i]
                d = math.hypot(rx - fx, ry - fy)
                if d > s * 60:
                    self.feet[i] = (rx, ry)
                elif d > limit:
                    g = self._group(i)
                    if limit > 20 * s or not any(self.step[k] is not None and self._group(k) != g
                                                 for k in range(8)):
                        self.step[i] = [0.0, dur, fx, fy, rx, ry]

    def _ell(self, f0, d0, a, b, k, zoff, n=14):
        pts = []
        for q in range(n):
            t = 2 * PI * q / n
            x, y = self.loc(f0 + a * math.cos(t), d0 + b * math.sin(t), k)
            pts += [x, y + zoff]
        return pts

    def _iris(self, c, x, y, er, angry):
        """Iris + pupille + reflet : le regard glisse vers le curseur."""
        gx, gy = self.gaze
        ir = er * 0.62
        ix, iy = x + gx * er * 0.32, y + gy * er * 0.32
        col = '#c0182c' if angry else IRIS.get(self.species, '#8a5a2a')
        c.create_oval(ix - ir, iy - ir, ix + ir, iy + ir, fill=col, outline='')
        pr = ir * 0.58
        px, py = ix + gx * er * 0.14, iy + gy * er * 0.14
        c.create_oval(px - pr, py - pr, px + pr, py + pr, fill='#050505', outline='')
        hr = max(1.0, 0.3 * er)
        hx, hy = ix - ir * 0.38, iy - ir * 0.42
        c.create_oval(hx - hr, hy - hr, hx + hr, hy + hr, fill='#ffffff', outline='')

    def _happy_eyes(self, c, k, zoff):
        """Yeux fermés en arc (^ ^) et joues roses : elle adore les caresses."""
        s = self.s
        face, line = FACE.get(self.species, ('#e6e6ea', '#1a1015'))
        if face is None:
            face = self.camo_hex()
        ex, ey = (9.2, 2.6) if self.species in ('widow', 'crab', 'tarantula') else (10.7, 3.5)
        if self.cute:
            face = self._pal()[0]
            ex, ey = 7.4, 4.7
        for dd in (-1, 1):
            x, y = self.loc(ex * s, dd * ey * s, k)
            y += zoff
            er = (5.4 if self.cute else (4.4 if ex > 10 else 3.4)) * s
            c.create_oval(x - er, y - er, x + er, y + er, fill=face, outline='')
            if self.sleeping:                                  # yeux clos (dort)
                c.create_arc(x - er * 0.8, y - er * 0.9, x + er * 0.8, y + er * 0.5, start=200, extent=140,
                             style=tk.ARC, outline=line, width=max(2, int(2 * s)))
                continue
            c.create_arc(x - er * 0.8, y - er * 0.6, x + er * 0.8, y + er * 0.9, start=15, extent=150,
                         style=tk.ARC, outline=line, width=max(2, int(2 * s)))
            bx, by = self.loc(7.2 * s, dd * 7.4 * s, k)
            by += zoff
            r = 2.0 * s
            c.create_oval(bx - r, by - r * 0.8, bx + r, by + r * 0.8, fill='#ff9ab8', outline='')

    def _body_peacock(self, c, k, zoff, angry):
        """Peacock spider (Maratus volans) : abdomen-éventail bleu / rouge / jaune, 3e paire de pattes blanche."""
        s = self.s
        dn = self.dance
        cf = -5 * s
        ab = 1 - 0.85 * dn
        c.create_polygon(self._ell(-9.5 * s, 0, 9.5 * s * ab, 7 * s * (1 - 0.3 * dn), k, zoff),
                         fill='#1f2f78', outline='#0e1440')
        if dn < 0.5:
            for f, a_, b_, col in ((-6, 1.3, 6.0, '#d4322b'), (-10, 1.3, 6.3, '#f2c230'), (-14, 1.1, 4.4, '#d4322b')):
                c.create_polygon(self._ell(f * s, 0, a_ * s, b_ * s, k, zoff), fill=col, outline='')
        if dn > 0.02:                                       # éventail déployé vers l'arrière
            vib = 1 + 0.035 * math.sin(self.dphase * 4.5)
            R = 27 * s * dn * vib

            def pt(r, t):
                x, y = self.loc(cf + r * math.cos(t), r * math.sin(t) * 1.1, k)
                return x, y + zoff

            x0, y0 = pt(0, 0)
            for fr, col in ((1.0, '#f7f1e1'), (0.9, '#f2c230'), (0.74, '#d4322b'),
                            (0.52, '#2a4bd0'), (0.32, '#141c5c'), (0.14, '#f07a1a')):
                pts = []
                for q in range(21):
                    pts += pt(R * fr, PI / 2 + PI * q / 20)
                pts += [x0, y0]
                c.create_polygon(pts, fill=col, outline='')
            for q in range(1, 8):
                t = PI / 2 + PI * q / 8
                x1, y1 = pt(R * 0.14, t)
                x2, y2 = pt(R * 0.98, t)
                c.create_line(x1, y1, x2, y2, fill='#ffffff')
            for q in range(0, 13):
                x, y = pt(R * 1.0, PI / 2 + PI * q / 12)
                r_ = 1.1 * s
                c.create_oval(x - r_, y - r_, x + r_, y + r_, fill='#ffffff', outline='')
        c.create_polygon(self._ell(3.5 * s, 0, 9.3 * s, 8.2 * s, k, zoff), fill='#3a2626', outline='#1b1012')
        c.create_polygon(self._ell(0.5 * s, 0, 2.2 * s, 7.4 * s, k, zoff), fill='#efe4cf', outline='')
        c.create_polygon(self._ell(8.5 * s, 0, 4.6 * s, 6.6 * s, k, zoff), fill='#d29a58', outline='')
        c.create_polygon(self._ell(7.5 * s, -1 * s, 2.5 * s, 3.5 * s, k, zoff), fill='#f0c88e', outline='')
        for dd in (-1, 1):                                  # palpes blancs duveteux
            x, y = self.loc(15 * s, dd * 3.4 * s, k)
            y += zoff
            r = 2.8 * s
            c.create_oval(x - r, y - r, x + r, y + r, fill='#f6efe0', outline='#b9ad96')
        ring = '#e0102a' if angry else '#1a1015'
        for dd in (-1, 1):
            x, y = self.loc(10.8 * s, dd * 3.5 * s, k)
            y += zoff
            er = 4.2 * s
            c.create_oval(x - er, y - er, x + er, y + er, fill='#07070b', outline=ring,
                          width=max(1, int(1.6 * s)))
            self._iris(c, x, y, er, angry)
            x, y = self.loc(8.0 * s, dd * 7.8 * s, k)
            y += zoff
            r = 1.6 * s
            c.create_oval(x - r, y - r, x + r, y + r, fill='#0a0a10', outline='')
        if angry:
            for dd in (-1, 1):
                x1, y1 = self.loc(15.5 * s, dd * 0.8 * s, k)
                x2, y2 = self.loc(13.4 * s, dd * 7 * s, k)
                c.create_line(x1, y1 + zoff, x2, y2 + zoff, fill='#f6efe0', width=max(2, int(2.4 * s)),
                              capstyle=tk.ROUND)

    def _body_regius(self, c, k, zoff, angry):
        s = self.s
        # Phidippus regius juvénile : duveteuse gris-blanc, abdomen beige, gros yeux noirs
        edge = '#6b6670'
        tan, tan_d = '#bda98a', '#7d6a54'
        c.create_polygon(self._ell(-9.5 * s, 0, 10 * s, 8 * s, k, zoff), fill=tan, outline=edge, width=1)
        c.create_polygon(self._ell(-10.5 * s, -2 * s, 5.5 * s, 3.2 * s, k, zoff), fill='#d8c9ae', outline='')
        for q in range(3):                                   # chevrons bruns
            cf = (-6 - 4 * q) * s
            pts = []
            for f, dd in ((cf + 2.2 * s, 0.0), (cf - 1.6 * s, -4.2 * s + q * 0.9 * s),
                          (cf - 0.4 * s, 0.0), (cf - 1.6 * s, 4.2 * s - q * 0.9 * s)):
                x, y = self.loc(f, dd, k)
                pts += [x, y + zoff]
            c.create_polygon(pts, fill=tan_d, outline='')
        c.create_polygon(self._ell(4 * s, 0, 9.8 * s, 8.5 * s, k, zoff), fill='#e6e6ea', outline=edge, width=1)
        c.create_polygon(self._ell(2.5 * s, -1.5 * s, 5 * s, 4 * s, k, zoff), fill='#f7f7f9', outline='')
        c.create_polygon(self._ell(-1.5 * s, 0, 3 * s, 6 * s, k, zoff), fill='#c9b695', outline='')  # bande beige
        for dd in (-1, 1):                                   # palpes duveteux
            x, y = self.loc(15 * s, dd * 3.4 * s, k)
            y += zoff
            r = 3.1 * s
            c.create_oval(x - r, y - r, x + r, y + r, fill='#d9cfd3', outline='#8f858b')
            r2 = 1.4 * s
            c.create_oval(x - r2, y - r2 - 0.8 * s, x + r2, y + r2 - 0.8 * s, fill='#f3ecee', outline='')
        ring = '#e0102a' if angry else '#2a2a35'
        for dd in (-1, 1):                                   # gros yeux
            x, y = self.loc(10.6 * s, dd * 3.5 * s, k)
            y += zoff
            er = 4.2 * s
            c.create_oval(x - er, y - er, x + er, y + er, fill='#07070b', outline=ring,
                          width=max(1, int(1.6 * s)))
            self._iris(c, x, y, er, angry)
            lx, ly = self.loc(9.0 * s, dd * 4.8 * s, k)
            ly += zoff
            c.create_oval(lx - 0.6 * s, ly - 0.6 * s, lx + 0.6 * s, ly + 0.6 * s, fill='#8f94b0', outline='')
            x, y = self.loc(8.0 * s, dd * 7.8 * s, k)        # petits yeux latéraux
            y += zoff
            r = 1.6 * s
            c.create_oval(x - r, y - r, x + r, y + r, fill='#0a0a10', outline='')
        if angry:                                            # sourcils fâchés
            for dd in (-1, 1):
                x1, y1 = self.loc(15.5 * s, dd * 0.8 * s, k)
                x2, y2 = self.loc(13.4 * s, dd * 7 * s, k)
                c.create_line(x1, y1 + zoff, x2, y2 + zoff, fill='#4a3a30', width=max(2, int(2.4 * s)),
                              capstyle=tk.ROUND)

    def _pal(self):
        base, edge, acc = CUTE_PAL[self.species]
        if base is None:                                     # araignée-crabe : camouflage
            base, edge = self.camo_hex(), self.camo_hex(0.6)
        return base, edge, acc

    def _peacock_fan(self, c, k, zoff):
        s = self.s
        dn = self.dance
        cf = -5 * s
        vib = 1 + 0.035 * math.sin(self.dphase * 4.5)
        R = 25 * s * dn * vib

        def pt(r, t):
            x, y = self.loc(cf + r * math.cos(t), r * math.sin(t) * 1.1, k)
            return x, y + zoff

        x0, y0 = pt(0, 0)
        for fr, col in ((1.0, '#f7f1e1'), (0.9, '#f2c230'), (0.74, '#e8453c'), (0.52, '#3f6fe0'),
                        (0.32, '#2a2f8c'), (0.14, '#f07a1a')):
            pts = []
            for q in range(21):
                pts += pt(R * fr, PI / 2 + PI * q / 20)
            pts += [x0, y0]
            c.create_polygon(pts, fill=col, outline='')

    def _body_cute(self, c, k, zoff, angry):
        """Style mignon (chibi) : grosse tête ronde, yeux immenses et brillants, joues roses, petit accessoire."""
        s = self.s
        base, edge, acc = self._pal()
        light = mix(base, '#ffffff', 0.45)
        sp_ = self.species
        if sp_ == 'peacock' and self.dance > 0.02:
            self._peacock_fan(c, k, zoff)
        # abdomen rond
        c.create_polygon(self._ell(-9 * s, 0, 7.8 * s, 7.4 * s, k, zoff, 22), fill=base, outline=edge, width=2)
        if sp_ == 'peacock':
            for f, col in ((-6.5, '#e8453c'), (-9.2, '#f2c230'), (-11.9, '#3f6fe0')):
                c.create_polygon(self._ell(f * s, 0, 1.2 * s, 5.2 * s, k, zoff), fill=col, outline='')
        elif sp_ == 'widow':
            for sgn in (1, -1):
                pts = []
                for f, dd in ((-9 + sgn * 3.2, -2.6), (-9 + sgn * 3.2, 2.6), (-9, 0.0)):
                    x, y = self.loc(f * s, dd * s, k)
                    pts += [x, y + zoff]
                c.create_polygon(pts, fill=acc, outline='')
        elif sp_ == 'regius':
            for f, dd in ((-7, 3), (-7, -3), (-11, 0)):
                x, y = self.loc(f * s, dd * s, k)
                c.create_oval(x - 1.7 * s, y + zoff - 1.7 * s, x + 1.7 * s, y + zoff + 1.7 * s, fill=acc, outline='')
        elif sp_ == 'tarantula':
            c.create_polygon(self._ell(-12.5 * s, 0, 3.6 * s, 5 * s, k, zoff), fill=acc, outline='')
        elif sp_ == 'wolf':
            c.create_polygon(self._ell(-9 * s, 0, 5.8 * s, 1.7 * s, k, zoff), fill=edge, outline='')
        elif sp_ == 'pholcus':
            for f, dd in ((-6, 2.5), (-9, -2.8), (-11.5, 1.2)):
                x, y = self.loc(f * s, dd * s, k)
                c.create_oval(x - 1.3 * s, y + zoff - 1.3 * s, x + 1.3 * s, y + zoff + 1.3 * s, fill=acc, outline='')
        else:                                                # crabe : rayures corail sur les côtés
            for sd in (-1, 1):
                x1, y1 = self.loc(-13 * s, sd * 6.2 * s, k)
                x2, y2 = self.loc(-5 * s, sd * 7.2 * s, k)
                c.create_line(x1, y1 + zoff, x2, y2 + zoff, fill=acc, width=max(2, int(2.2 * s)), capstyle=tk.ROUND)
        c.create_polygon(self._ell(-11.5 * s, -3 * s, 3.2 * s, 2.2 * s, k, zoff), fill=light, outline='')
        # grosse tête ronde
        c.create_polygon(self._ell(4.5 * s, 0, 10 * s, 9.6 * s, k, zoff, 26), fill=base, outline=edge, width=2)
        c.create_polygon(self._ell(1.5 * s, -3.4 * s, 5 * s, 3.2 * s, k, zoff), fill=light, outline='')
        # accessoire
        if sp_ in ('regius', 'widow'):                       # petit nœud
            for sd in (-1, 1):
                x1, y1 = self.loc(-1.5 * s, sd * 0.6 * s, k)
                x2, y2 = self.loc(-3.5 * s, sd * 5.6 * s, k)
                x3, y3 = self.loc(1.5 * s, sd * 5.2 * s, k)
                c.create_polygon(x1, y1 + zoff, x2, y2 + zoff, x3, y3 + zoff, fill=acc, outline=edge)
            x, y = self.loc(-1.4 * s, 0, k)
            c.create_oval(x - 1.5 * s, y + zoff - 1.5 * s, x + 1.5 * s, y + zoff + 1.5 * s, fill=mix(acc, '#000000', 0.2), outline=edge)
        elif sp_ == 'peacock':                               # aigrette de plumes
            for f, dd, col in ((-3, -3, '#e8453c'), (-4.5, 0, '#f2c230'), (-3, 3, '#3f6fe0')):
                c.create_polygon(self._ell(f * s, dd * s, 3.4 * s, 1.5 * s, k, zoff), fill=col, outline=edge)
        elif sp_ == 'tarantula':                             # petite houppe
            for dd in (-1.5, 0, 1.5):
                x, y = self.loc(-2.5 * s, dd * s, k)
                c.create_oval(x - 1.4 * s, y + zoff - 1.4 * s, x + 1.4 * s, y + zoff + 1.4 * s, fill=acc, outline='')
        elif sp_ == 'wolf':                                  # petites oreilles rondes
            for sd in (-1, 1):
                x, y = self.loc(-1.5 * s, sd * 8 * s, k)
                c.create_oval(x - 2.4 * s, y + zoff - 2.4 * s, x + 2.4 * s, y + zoff + 2.4 * s, fill=base, outline=edge, width=2)
        elif sp_ == 'pholcus':                               # lunettes rondes
            for sd in (-1, 1):
                x, y = self.loc(7.4 * s, sd * 4.7 * s, k)
                c.create_oval(x - 6.4 * s, y + zoff - 6.4 * s, x + 6.4 * s, y + zoff + 6.4 * s, outline=acc, width=max(2, int(2 * s)))
        else:                                                # crabe : petite fleur
            x, y = self.loc(-1.5 * s, 6.5 * s, k)
            for a in range(5):
                px, py = x + math.cos(a * 1.2566) * 2.2 * s, y + zoff + math.sin(a * 1.2566) * 2.2 * s
                c.create_oval(px - 1.5 * s, py - 1.5 * s, px + 1.5 * s, py + 1.5 * s, fill=acc, outline='')
            c.create_oval(x - 1.1 * s, y + zoff - 1.1 * s, x + 1.1 * s, y + zoff + 1.1 * s, fill='#ffe066', outline='')
        # immenses yeux brillants
        er = 4.9 * s
        for dd in (-1, 1):
            x, y = self.loc(7.4 * s, dd * 4.7 * s, k)
            y += zoff
            c.create_oval(x - er, y - er, x + er, y + er, fill='#ffffff', outline='#2a1a30', width=2)
            self._iris(c, x, y, er * 0.95, angry)
            c.create_oval(x + er * 0.15, y + er * 0.2, x + er * 0.45, y + er * 0.5, fill='#ffffff', outline='')
        # joues roses + petit sourire
        for dd in (-1, 1):
            x, y = self.loc(3.4 * s, dd * 9.1 * s, k)
            y += zoff
            c.create_oval(x - 2.4 * s, y - 1.7 * s, x + 2.4 * s, y + 1.7 * s, fill='#ff9ab8', outline='')
        pts = []
        for f, dd in ((11.6, -1.7), (12.5, 0.0), (11.6, 1.7)):
            x, y = self.loc(f * s, dd * s, k)
            pts += [x, y + zoff]
        c.create_line(*pts, smooth=True, fill='#6a2a3a' if not angry else '#7a1010', width=max(2, int(1.8 * s)), capstyle=tk.ROUND)
        if angry:                                            # sourcils fâchés
            for dd in (-1, 1):
                x1, y1 = self.loc(12.4 * s, dd * 1.6 * s, k)
                x2, y2 = self.loc(10.6 * s, dd * 8.4 * s, k)
                c.create_line(x1, y1 + zoff, x2, y2 + zoff, fill=edge, width=max(2, int(2.6 * s)), capstyle=tk.ROUND)

    def _eye(self, c, f, dd, er, k, zoff, angry, ring='#1a1015'):
        s = self.s
        x, y = self.loc(f * s, dd * s, k)
        y += zoff
        c.create_oval(x - er * s, y - er * s, x + er * s, y + er * s, fill='#07070b',
                      outline='#e0102a' if angry else ring, width=max(1, int(1.4 * s)))
        self._iris(c, x, y, er * s, angry)

    def _body_widow(self, c, k, zoff, angry):
        """Veuve noire : abdomen rond et brillant, sablier rouge, petit céphalothorax."""
        s = self.s
        blk, shine = '#0b0b0e', '#3a3a46'
        c.create_polygon(self._ell(-10 * s, 0, 10.5 * s, 9.5 * s, k, zoff, 18), fill=blk, outline='#000000')
        c.create_polygon(self._ell(-12.5 * s, -3.2 * s, 5 * s, 3.2 * s, k, zoff), fill=shine, outline='')
        red = '#ff2a1a' if angry else '#d31f14'
        cf = -10 * s
        for sgn in (1, -1):                                  # sablier
            pts = []
            for f, dd in ((cf + sgn * 4 * s, -3 * s), (cf + sgn * 4 * s, 3 * s), (cf, 0.0)):
                x, y = self.loc(f, dd, k)
                pts += [x, y + zoff]
            c.create_polygon(pts, fill=red, outline='')
        c.create_polygon(self._ell(4 * s, 0, 6.8 * s, 5.8 * s, k, zoff), fill=blk, outline='#000000')
        c.create_polygon(self._ell(2.5 * s, -1.5 * s, 3 * s, 2 * s, k, zoff), fill=shine, outline='')
        for dd in (-1, 1):
            self._eye(c, 8.6, dd * 2.6, 3.0, k, zoff, angry, '#3a1010')

    def _body_tarantula(self, c, k, zoff, angry):
        """Mygale : grosse, velue, poils urticants roux, crocs qui s'ouvrent en menace."""
        s = self.s
        fur, dark, light = '#6a5038', '#3a2a1e', '#9a7a58'
        c.create_polygon(self._ell(-9 * s, 0, 11.8 * s, 10.4 * s, k, zoff, 18), fill='#8a6c4c', outline='')
        c.create_polygon(self._ell(-9 * s, 0, 10.4 * s, 9 * s, k, zoff, 18), fill=fur, outline=dark)
        c.create_polygon(self._ell(-13.5 * s, 0, 5 * s, 6.2 * s, k, zoff), fill='#c8501e', outline='')
        c.create_polygon(self._ell(-8 * s, -2.6 * s, 4.2 * s, 3.2 * s, k, zoff), fill=light, outline='')
        c.create_polygon(self._ell(4 * s, 0, 8.8 * s, 7.8 * s, k, zoff), fill='#7d6044', outline=dark)
        c.create_polygon(self._ell(3 * s, -1 * s, 4.5 * s, 4 * s, k, zoff), fill=light, outline='')
        th = self.threat
        for dd in (-1, 1):                                   # crocs
            x, y = self.loc(12.6 * s, dd * 2.4 * s, k)
            y += zoff
            r = 2.5 * s
            c.create_oval(x - r, y - r, x + r, y + r, fill=dark, outline='')
            if th > 0.3:
                x2, y2 = self.loc((17 + 3 * th) * s, dd * 1.4 * s, k)
                c.create_line(x, y, x2, y2 + zoff, fill='#f2e6d2', width=max(2, int(2.4 * s)), capstyle=tk.ROUND)
        for dd in (-1, 1):
            self._eye(c, 8.4, dd * 2.2, 2.7, k, zoff, angry or th > 0.3, '#2a1c14')

    def _body_wolf(self, c, k, zoff, angry):
        """Lycose : brun-gris rayé, gros yeux, porte ses bébés sur le dos."""
        s = self.s
        base, dark, light = '#8a7155', '#3d3024', '#cdb98e'
        c.create_polygon(self._ell(-10 * s, 0, 10.8 * s, 7.8 * s, k, zoff, 16), fill=base, outline=dark)
        c.create_polygon(self._ell(-10 * s, 0, 8.5 * s, 2.2 * s, k, zoff), fill=dark, outline='')
        for q in range(3):
            cf = (-6 - 4 * q) * s
            pts = []
            for f, dd in ((cf + 2 * s, 0.0), (cf - 1.6 * s, -4.2 * s), (cf - 0.4 * s, 0.0), (cf - 1.6 * s, 4.2 * s)):
                x, y = self.loc(f, dd, k)
                pts += [x, y + zoff]
            c.create_polygon(pts, fill='#5a4632', outline='')
        for i in range(self.carry):                          # bébés sur le dos
            col_, row = i % 4, i // 4
            x, y = self.loc((-5 - col_ * 3.2) * s, (-1 if row == 0 else 1) * 3.0 * s, k)
            y += zoff
            r = 1.8 * s
            c.create_oval(x - r, y - r, x + r, y + r, fill='#d8c9a4', outline='#4a3a2a')
        c.create_polygon(self._ell(4 * s, 0, 9 * s, 7.8 * s, k, zoff), fill=base, outline=dark)
        c.create_polygon(self._ell(2.5 * s, 0, 2.4 * s, 6.6 * s, k, zoff), fill=light, outline='')
        c.create_polygon(self._ell(4.5 * s, 0, 5 * s, 1.5 * s, k, zoff), fill=dark, outline='')
        for dd in (-1, 1):
            self._eye(c, 9.2, dd * 3.6, 3.8, k, zoff, angry, '#3d3024')

    def _body_pholcus(self, c, k, zoff, angry):
        """Pholque : minuscule corps pâle sur de très longues pattes, grands yeux ronds."""
        s = self.s
        c.create_polygon(self._ell(-6.5 * s, 0, 8 * s, 4.4 * s, k, zoff), fill='#d8cdb0', outline='#8a7a60')
        c.create_polygon(self._ell(-8 * s, -1.2 * s, 3.5 * s, 1.6 * s, k, zoff), fill='#efe7d2', outline='')
        c.create_polygon(self._ell(2 * s, 0, 4.8 * s, 4.2 * s, k, zoff), fill='#c9bb98', outline='#8a7a60')
        for dd in (-1, 1):
            self._eye(c, 5.2, dd * 2.2, 2.7, k, zoff, angry, '#5a4a30')

    def _body_crab(self, c, k, zoff, angry):
        """Araignée-crabe : corps large et plat qui prend la couleur du fond (camouflage)."""
        s = self.s
        col, dark, light = self.camo_hex(), self.camo_hex(0.65), self.camo_hex(1.12)
        c.create_polygon(self._ell(-9 * s, 0, 8 * s, 10.5 * s, k, zoff, 16), fill=col, outline=dark)
        for sd in (-1, 1):
            x1, y1 = self.loc(-14 * s, sd * 8 * s, k)
            x2, y2 = self.loc(-4 * s, sd * 9.8 * s, k)
            c.create_line(x1, y1 + zoff, x2, y2 + zoff, fill='#d9695a', width=max(2, int(2 * s)))
        c.create_polygon(self._ell(-8 * s, -2 * s, 4 * s, 4 * s, k, zoff), fill=light, outline='')
        c.create_polygon(self._ell(3 * s, 0, 7.4 * s, 9.6 * s, k, zoff), fill=col, outline=dark)
        c.create_polygon(self._ell(2 * s, -1 * s, 3.6 * s, 4.4 * s, k, zoff), fill=light, outline='')
        for dd in (-1, 1):
            self._eye(c, 8.6, dd * 2.2, 2.5, k, zoff, angry, dark)
            x, y = self.loc(6.5 * s, dd * 6.4 * s, k)
            y += zoff
            r = 1.5 * s
            c.create_oval(x - r, y - r, x + r, y + r, fill='#0a0a10', outline='')

    def draw(self, c, angry=False, alert=None):
        s = self.s
        k = 1 + (self.z + self.elev * 0.7) / (170 * s) + self.pulse
        if self.cute:                                       # rebondit en marchant, respire à l'arrêt
            mv = min(1.0, math.hypot(self.vx, self.vy) / (80 * s))
            k += 0.012 * math.sin(self.t_anim * 3) + 0.05 * mv * abs(math.sin(self.gphase * PI * 2))
        zoff = -(self.z + self.elev)
        if self.z > 1 or self.elev > 1:                                       # ombre
            c.create_polygon(self._ell(0, 0, 16 * s, 11 * s, 1.0, 0), fill='#000000',
                             stipple='gray50', outline='')
        w = max(3, int(round(3.2 * s)))
        for i in range(8):
            j = i % 4
            sd = -1 if i < 4 else 1
            hx, hy = self.loc(HIP_F[j] * s, sd * 3 * s, k)
            hy += zoff
            fx, fy = self.feet[i]
            fx = self.x + (fx - self.x) * k
            fy = self.y + (fy - self.y) * k + zoff
            lift = 0.0
            st_ = self.step[i]
            if st_ is not None and self.z <= 2:               # pied levé pendant le pas
                lift = math.sin(PI * clamp(st_[0] / st_[1], 0.0, 1.0))
                fy -= 5 * s * lift
            dancing = self.species == 'peacock' and self.dance > 0.02 and j == 2
            if dancing:                                  # 3e paire levée et agitée
                ph = self.dphase + (0.0 if sd < 0 else PI)
                tx, ty = self.loc((13 + 4 * math.sin(ph)) * s,
                                  sd * (19 + 4 * math.cos(ph * 0.5 + 1)) * s, k)
                ty += zoff - 6 * s * self.dance
                fx += (tx - fx) * self.dance
                fy += (ty - fy) * self.dance
            waving = self.species == 'regius' and self.wave > 0.02 and j == 0
            if waving:                                   # les deux pattes avant levées : coucou
                ph_ = self.dphase + (PI if sd < 0 else 0.0)
                tx, ty = self.loc(17 * s, sd * (9 + 12 * (0.5 + 0.5 * math.sin(ph_))) * s, k)
                ty += zoff - 9 * s * self.wave
                fx += (tx - fx) * self.wave
                fy += (ty - fy) * self.wave
            washing = self.wash > 0.02 and j == 0
            if washing:                                  # pattes avant qui frottent le visage
                ph_ = self.dphase + (0.0 if sd < 0 else PI * 0.5)
                tx, ty = self.loc((13 + 2 * math.cos(ph_)) * s, sd * (1.5 + 7.5 * (0.5 + 0.5 * math.sin(ph_))) * s, k)
                ty += zoff - 5 * s * self.wash
                fx += (tx - fx) * self.wash
                fy += (ty - fy) * self.wash
            if self.threat > 0.02 and j == 0:                # pattes avant levées et écartées (menace / affût)
                ph_ = self.dphase + (PI if sd < 0 else 0.0)
                tx, ty = self.loc(19 * s, sd * (11 + 3 * math.sin(ph_)) * s, k)
                ty += zoff - 9 * s * self.threat
                fx += (tx - fx) * self.threat
                fy += (ty - fy) * self.threat
            dx, dy = fx - hx, fy - hy
            d = max(1e-3, min(math.hypot(dx, dy), self.L1 + self.L2 - 0.01))
            dl = math.hypot(dx, dy)
            ux, uy = (dx / dl, dy / dl) if dl > 1e-3 else (1.0, 0.0)
            a = (self.L1 ** 2 - self.L2 ** 2 + d * d) / (2 * d)
            h = math.sqrt(max(self.L1 ** 2 - a * a, 0.0)) * (1 + 0.5 * lift)
            px, py = -uy, ux
            ea_ = self.ang + self.body_off
            ra, rb = -math.sin(ea_) * sd, math.cos(ea_) * sd   # direction "dehors"
            if px * ra + py * rb < 0:
                px, py = -px, -py
            kx, ky = hx + ux * a + px * h, hy + uy * a + py * h
            if self.cute:
                base_, edge_, acc_ = self._pal()
                lw_ = max(3, int(w * 1.35)) + (1 if j == 0 else 0)
                c.create_line(hx, hy, kx, ky, fx, fy, fill=edge_, width=lw_ + 2, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                c.create_line(hx, hy, kx, ky, fx, fy, fill=base_, width=lw_, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                pr = 1.9 * s
                c.create_oval(fx - pr, fy - pr, fx + pr, fy + pr, fill=mix(base_, '#ffffff', 0.4), outline=edge_)
                continue
            if self.species in LEGSTYLE:
                ol, mc, bc, tc, wm = LEGSTYLE[self.species]
                if self.species == 'crab':
                    mc, ol = self.camo_hex(1.05), self.camo_hex(0.6)
                lw_ = max(2, int(w * wm))
                c.create_line(hx, hy, kx, ky, fx, fy, fill=ol, width=lw_ + 2, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                c.create_line(hx, hy, kx, ky, fx, fy, fill=mc, width=lw_, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                if bc:
                    c.create_line(hx + (kx - hx) * 0.8, hy + (ky - hy) * 0.8, kx + (fx - kx) * 0.22,
                                  ky + (fy - ky) * 0.22, fill=bc, width=lw_)
                if tc:
                    c.create_line(kx + (fx - kx) * 0.65, ky + (fy - ky) * 0.65, fx, fy, fill=tc, width=lw_)
                continue
            if self.species == 'peacock':
                lw_ = w
                c.create_line(hx, hy, kx, ky, fx, fy, fill='#1b1417', width=lw_ + 2, capstyle=tk.ROUND,
                              joinstyle=tk.ROUND)
                c.create_line(hx, hy, kx, ky, fx, fy, fill='#5a4642', width=lw_, capstyle=tk.ROUND,
                              joinstyle=tk.ROUND)
                c.create_line(kx + (fx - kx) * 0.45, ky + (fy - ky) * 0.45, fx, fy, fill='#f6efe2',
                              width=lw_, capstyle=tk.ROUND)
                if dancing:
                    pr = 2.3 * s
                    c.create_oval(fx - pr, fy - pr, fx + pr, fy + pr, fill='#fffaf0', outline='#c9b99a')
                continue
            lw_ = w + (2 if j == 0 else 1)
            c.create_line(hx, hy, kx, ky, fx, fy, fill='#6b6670', width=lw_ + 2, capstyle=tk.ROUND,
                          joinstyle=tk.ROUND)
            c.create_line(hx, hy, kx, ky, fx, fy, fill='#d6d6dc', width=lw_, capstyle=tk.ROUND,
                          joinstyle=tk.ROUND)
            c.create_line(hx + (kx - hx) * 0.5, hy + (ky - hy) * 0.5, hx + (kx - hx) * 0.8,
                          hy + (ky - hy) * 0.8, fill='#9a8f84', width=lw_)
            c.create_line(kx + (fx - kx) * 0.45, ky + (fy - ky) * 0.45, kx + (fx - kx) * 0.75,
                          ky + (fy - ky) * 0.75, fill='#9a8f84', width=lw_)
            if waving:
                pr = 2.6 * s
                c.create_oval(fx - pr, fy - pr, fx + pr, fy + pr, fill='#ffffff', outline='#8f858b')
        (self._body_cute if self.cute else getattr(self, '_body_' + self.species))(c, k, zoff, angry)
        if self.happy > 0.3 or self.sleeping:
            self._happy_eyes(c, k, zoff)
        if alert:
            c.create_text(self.x, self.y - 40 * s - self.z, text='!', fill=alert,
                          font=('Segoe UI', -int(30 * s), 'bold'))



def rot_ell(x, y, ang, f0, d0, a, b, n=12):
    ca, sa = math.cos(ang), math.sin(ang)
    pts = []
    for q in range(n):
        t = 2 * PI * q / n
        f = f0 + a * math.cos(t)
        d = d0 + b * math.sin(t)
        pts += [x + f * ca - d * sa, y + f * sa + d * ca]
    return pts


class Basket:
    """Panier en osier posé sur le bureau : clic = une mouche, glisser = le déplacer."""

    def __init__(self, area, s):
        l, t, r, b = area
        self.s = s * 0.62                     # taille du panier
        self.x = r - 50 * s
        self.y = b - 40 * s
        self.bounce = 0.0

    def hit(self, px, py):
        s = self.s
        return abs(px - self.x) < 34 * s and -48 * s < py - self.y < 34 * s

    def update(self, dt):
        self.bounce = max(0.0, self.bounce - dt * 3.0)

    def draw(self, c, hover):
        """Panier de pique-nique en osier : couvercles, anse, tissu vichy rouge, dentelle, noeud."""
        s = self.s * (1.08 if hover else 1.0)
        x, y = self.x, self.y
        lift = 6 * s * math.sin(PI * self.bounce) * self.bounce      # couvercles qui se soulèvent
        dark, mid, light = '#8a6128', '#d6b36e', '#e9d19a'
        c.create_polygon(rot_ell(x + 2 * s, y + 38 * s, 0, 0, 0, 34 * s, 5 * s, 16), fill='#000000',
                         stipple='gray50', outline='')
        # anse (derrière les couvercles)
        c.create_arc(x - 9 * s, y - 46 * s, x + 9 * s, y + 14 * s, start=0, extent=180, style=tk.ARC,
                     outline='#a87c3a', width=max(4, int(5.5 * s)))
        c.create_arc(x - 9 * s, y - 46 * s, x + 9 * s, y + 14 * s, start=0, extent=180, style=tk.ARC,
                     outline='#e0c080', width=max(2, int(2.5 * s)))
        # corps tressé
        c.create_polygon(x - 32 * s, y + 4 * s, x + 32 * s, y + 4 * s, x + 32 * s, y + 29 * s, x + 29 * s, y + 33 * s,
                         x - 29 * s, y + 33 * s, x - 32 * s, y + 29 * s, fill=mid, outline=dark, width=2)
        row = 0
        yy = 8.0
        while yy < 32:
            c.create_line(x - 31 * s, y + yy * s, x + 31 * s, y + yy * s, fill='#b98e46', width=1)
            c.create_line(x - 31 * s, y + (yy + 1.3) * s, x + 31 * s, y + (yy + 1.3) * s, fill=light, width=1)
            xx = -29 + 4 * (row % 2)
            while xx < 30:
                c.create_line(x + xx * s, y + (yy - 1.5) * s, x + xx * s, y + (yy + 2.8) * s, fill='#a97c3b', width=1)
                xx += 8
            row += 1
            yy += 4.4
        # couvercles
        for sg in (-1, 1):
            pts = [x + sg * 3 * s, y - 17 * s - lift, x + sg * 31 * s, y - 16 * s - lift * 0.4,
                   x + sg * 33 * s, y - 6 * s, x + sg * 3 * s, y - 8 * s - lift * 0.5]
            c.create_polygon(pts, fill='#e3c78a', outline=dark, width=2)
            for q in (0.33, 0.66):
                ya = lerp(y - 17 * s - lift, y - 8 * s - lift * 0.5, q)
                yb = lerp(y - 16 * s - lift * 0.4, y - 6 * s, q)
                c.create_line(x + sg * 4 * s, ya, x + sg * 32 * s, yb, fill='#c9a65e', width=1)
        # tissu vichy
        x0, x1 = x - 32 * s, x + 32 * s
        c.create_rectangle(x0, y - 7 * s, x1, y + 5 * s, fill='#f7ecec', outline='')
        cw = 64 / 16.0
        for col in range(16):
            for rw in range(3):
                if (col + rw) % 2 == 0:
                    c.create_rectangle(x0 + col * cw * s, y + (-7 + rw * 4) * s,
                                       x0 + (col + 1) * cw * s, y + (-3 + rw * 4) * s,
                                       fill='#d93a3a', outline='')
        # dentelle blanche
        for q in range(17):
            lx = x0 + q * 4 * s
            c.create_oval(lx - 2.2 * s, y + 2.5 * s, lx + 2.2 * s, y + 7.5 * s, fill='#ffffff', outline='#cfcfcf')
        # noeud rouge
        for sg in (-1, 1):
            c.create_polygon(x, y - 0.5 * s, x + sg * 8 * s, y - 4 * s, x + sg * 8 * s, y + 4 * s,
                             fill='#d93a3a', outline='#8f1f1f')
        c.create_oval(x - 2.4 * s, y - 2.6 * s, x + 2.4 * s, y + 2.2 * s, fill='#b02a2a', outline='#8f1f1f')
        c.create_polygon(x - 1 * s, y + 2 * s, x - 5 * s, y + 10 * s, x - 1 * s, y + 8 * s,
                         fill='#d93a3a', outline='#8f1f1f')
        c.create_polygon(x + 1 * s, y + 2 * s, x + 5 * s, y + 10 * s, x + 1 * s, y + 8 * s,
                         fill='#d93a3a', outline='#8f1f1f')
        if hover:
            fs = -max(11, int(12 * self.s / 0.62))
            for q, txt in enumerate(('Clic : une proie', 'Clic droit : menu', 'Ctrl + glisser : nourrir')):
                yy = y - 52 * s - (2 - q) * (abs(fs) + 3)
                c.create_text(x + 1, yy + 1, text=txt, fill='#000000', font=('Segoe UI', fs, 'bold'))
                c.create_text(x, yy, text=txt, fill='#ffffff', font=('Segoe UI', fs, 'bold'))


class Fly:
    def __init__(self, x, y, ang, s, kind='fly'):
        self.s = s
        self.x, self.y, self.ang = x, y, ang
        self.state = 'fly'            # fly | stuck | fall | gone
        self.t = 0.0
        self.phase = random.uniform(0, 6)
        self.turn = 0.0
        self.speed = 170 * s
        self.seg = None
        self.stuck_t = 0.0
        self.wrap = 0.0
        self.size = 1.0
        self.vy = 0.0
        self.goal = None
        self.goal_t = 0.0
        self.jx = self.jy = 0.0
        self.leaving = False
        self.fall_t = 0.0
        self.kind = kind
        P = {'fly': (1.0, 170, 3.6, 4.5, 0.6, 70), 'mosquito': (0.7, 240, 2.2, 3.0, 0.35, 90),
             'butterfly': (1.5, 95, 8.0, 8.0, 0.95, 14)}[kind]
        self.sf, base, self.wrap_t, self.eat_t, self.feed, self.prate = P
        self.speed = base * s
        self.spin = ang

    def update(self, dt, pet):
        s = self.s
        self.t += dt
        self.phase += dt * (self.prate if self.state == 'fly' else self.prate * 0.65)
        if self.state == 'fly':
            self._fly(dt, pet)
        elif self.state == 'held':                          # tenue par le curseur
            amp = 1.2 * s
            self.jx = random.uniform(-amp, amp)
            self.jy = random.uniform(-amp, amp)
        elif self.state == 'stuck':
            self.stuck_t += dt
            if self.wrap < 1.0 and int(self.stuck_t * 0.6) != int((self.stuck_t - dt) * 0.6):
                pet.sound('buzz')
            if self.seg is not None and not self.seg.built:
                if self.wrap < 0.05:                       # la toile est coupée : elle se libère
                    self.state = 'fly'
                    self.seg = None
                    self.ang = random.uniform(-PI, PI)
                else:
                    self.state = 'fall'
                    self.vy = 0.0
            amp = 1.3 * s * max(0.0, 1.0 - self.wrap)
            self.jx = random.uniform(-amp, amp)
            self.jy = random.uniform(-amp, amp)
        elif self.state == 'fall':
            self.jx = self.jy = 0.0
            self.vy += 900 * s * dt
            self.y += self.vy * dt
            self.fall_t += dt
            if self.fall_t > 1.0:
                self.state = 'gone'

    def _fly(self, dt, pet):
        s = self.s
        web = pet.web
        l, t, r, b = pet.area
        built = [sg for sg in web.segs if sg.built]
        self.goal_t -= dt
        if built and (self.goal is None or self.goal_t <= 0 or
                      math.hypot(self.goal[0] - self.x, self.goal[1] - self.y) < 30 * s):
            sg = random.choice(built)
            self.goal = sg.point(random.random())
            self.goal_t = random.uniform(1.5, 3.0)
        if self.t > 60:
            self.leaving = True
        tj, tc = {'fly': (40, 6), 'mosquito': (60, 9), 'butterfly': (18, 3)}[self.kind]
        self.turn = clamp(self.turn + random.uniform(-1, 1) * dt * tj, -tc, tc)
        steer = self.turn
        if self.leaving:
            away = math.atan2(self.y - (t + b) / 2, self.x - (l + r) / 2)
            steer += clamp(angdiff(self.ang, away), -1, 1) * 6
        elif self.goal and built:
            diff = angdiff(self.ang, math.atan2(self.goal[1] - self.y, self.goal[0] - self.x))
            steer += clamp(diff, -1, 1) * 3.0
        cx, cy = pet.cur
        dcur = math.hypot(self.x - cx, self.y - cy)
        boost = 1.0
        if dcur < 110 * s:                                 # fuit le curseur
            steer += clamp(angdiff(self.ang, math.atan2(self.y - cy, self.x - cx)), -1, 1) * 10
            boost = 1.6
        if not self.leaving and (self.x < l + 30 or self.x > r - 30 or self.y < t + 30 or self.y > b - 30):
            steer += clamp(angdiff(self.ang, math.atan2((t + b) / 2 - self.y, (l + r) / 2 - self.x)), -1, 1) * 8
        self.ang += steer * dt
        sp_ = self.speed * boost * (0.8 + 0.4 * math.sin(self.t * 7))
        nx = self.x + math.cos(self.ang) * sp_ * dt
        ny = self.y + math.sin(self.ang) * sp_ * dt
        if not self.leaving or True:
            for sg in built:
                if sg.hit((self.x, self.y), (nx, ny), 2.5 * s):
                    self.x, self.y = sg.nearest(nx, ny)
                    self.state = 'stuck'
                    self.seg = sg
                    self.stuck_t = 0.0
                    self.spin = self.ang
                    pet.sound('buzz')
                    return
        self.x, self.y = nx, ny
        if self.leaving and (self.x < l - 80 or self.x > r + 80 or self.y < t - 80 or self.y > b + 80):
            self.state = 'gone'



def _wrap_stripes(c, f, x, y, ang, s):
    ca, sa = math.cos(ang), math.sin(ang)
    for i in range(int(f.wrap * 9)):
        fp = (-6 + i * 1.5) * s
        c.create_line(x + (fp - 1.0 * s) * ca + 4.4 * s * sa, y + (fp - 1.0 * s) * sa - 4.4 * s * ca,
                      x + (fp + 1.0 * s) * ca - 4.4 * s * sa, y + (fp + 1.0 * s) * sa + 4.4 * s * ca,
                      fill='#f4f4f1', width=max(2, int(1.7 * s)))


def _draw_mosquito(c, f, x, y, ang, s):
    ca, sa = math.cos(ang), math.sin(ang)
    if f.state == 'fly':
        c.create_polygon(rot_ell(x + 3 * s, y + 10 * s, ang, 0, 0, 5 * s, 1.6 * s), fill='#000000',
                         stipple='gray50', outline='')
    for sd in (-1, 1):                                                   # longues pattes
        for fp, spread in ((3.0, 7.5), (0.5, 9.0), (-2.0, 8.0)):
            x1, y1 = x + fp * s * ca - sd * 1.0 * s * sa, y + fp * s * sa + sd * 1.0 * s * ca
            kx, ky = x1 + (fp * 0.2 - 1.5) * s * ca - sd * spread * 0.55 * s * sa, y1 + (fp * 0.2 - 1.5) * s * sa + sd * spread * 0.55 * s * ca
            ex, ey = kx + (fp * 0.3 - 3.5) * s * ca - sd * spread * 0.5 * s * sa, ky + (fp * 0.3 - 3.5) * s * sa + sd * spread * 0.5 * s * ca
            c.create_line(x1, y1, kx, ky, ex, ey, fill='#3a332d')
    flap = 0.5 + 0.5 * abs(math.sin(f.phase))
    for sd in (-1, 1):                                                   # ailes fines
        wa = ang + PI - sd * (0.5 + 0.5 * flap)
        c.create_polygon(rot_ell(x, y, wa, 5.2 * s, 0, 5.5 * s, 1.3 * s), fill='#e8eef5', outline='#9aa8b8')
    c.create_polygon(rot_ell(x, y, ang, -4.2 * s, 0, 5.0 * s, 1.5 * s), fill='#6b5f55', outline='')
    c.create_polygon(rot_ell(x, y, ang, 0.8 * s, 0, 2.2 * s, 1.7 * s), fill='#4a4038', outline='')
    c.create_polygon(rot_ell(x, y, ang, 3.0 * s, 0, 1.4 * s, 1.3 * s), fill='#2d2823', outline='')
    c.create_line(x + 4 * s * ca, y + 4 * s * sa, x + 8.5 * s * ca, y + 8.5 * s * sa, fill='#2d2823', width=max(1, int(s * 0.8)))
    _wrap_stripes(c, f, x, y, ang, s)


def _draw_butterfly(c, f, x, y, ang, s):
    ca, sa = math.cos(ang), math.sin(ang)
    if f.state == 'fly':
        c.create_polygon(rot_ell(x + 3 * s, y + 10 * s, ang, 0, 0, 5 * s, 3 * s), fill='#000000',
                         stipple='gray50', outline='')
    w = 0.3 + 0.7 * abs(math.sin(f.phase * 0.5 if f.state == 'fly' else f.phase * 0.2))
    for sd in (-1, 1):
        cx_, cy_ = x - sd * 5.5 * s * w * sa, y + sd * 5.5 * s * w * ca        # ailes arrière
        c.create_polygon(rot_ell(cx_ - 4 * s * ca, cy_ - 4 * s * sa, ang, 0, 0, 5.8 * s, 5.0 * s * w + 0.6 * s),
                         fill='#e6a23c', outline='#2a1a10')
        cx_, cy_ = x - sd * 6.5 * s * w * sa, y + sd * 6.5 * s * w * ca        # ailes avant
        c.create_polygon(rot_ell(cx_ + 1.5 * s * ca, cy_ + 1.5 * s * sa, ang, 0, 0, 8.0 * s, 6.5 * s * w + 0.6 * s),
                         fill='#f08a24', outline='#2a1a10', width=2)
        for q in range(3):                                                  # points blancs
            px_ = x + (3 + q * 2.6) * s * ca - sd * (9.0 * s * w + 1) * sa
            py_ = y + (3 + q * 2.6) * s * sa + sd * (9.0 * s * w + 1) * ca
            c.create_oval(px_ - 0.9 * s, py_ - 0.9 * s, px_ + 0.9 * s, py_ + 0.9 * s, fill='#ffffff', outline='')
    c.create_polygon(rot_ell(x, y, ang, -1.0 * s, 0, 6.5 * s, 1.5 * s), fill='#2b2118', outline='')
    c.create_polygon(rot_ell(x, y, ang, 5.8 * s, 0, 1.6 * s, 1.5 * s), fill='#1a140e', outline='')
    for sd in (-1, 1):
        c.create_line(x + 6.5 * s * ca, y + 6.5 * s * sa,
                      x + 11 * s * ca - sd * 3.5 * s * sa, y + 11 * s * sa + sd * 3.5 * s * ca, fill='#2b2118')
    _wrap_stripes(c, f, x, y, ang, s * 0.7)


def draw_fly(c, f):
    s = f.s * f.size * f.sf
    if f.size <= 0.03:
        return
    x, y = f.x + f.jx, f.y + f.jy
    ang = f.ang
    cocoon = f.state != 'fly' and f.wrap >= 1.0
    if f.state == 'fly':
        c.create_polygon(rot_ell(x + 3 * s, y + 10 * s, ang, 0, 0, 5 * s, 2.5 * s), fill='#000000',
                         stipple='gray50', outline='')
    if cocoon:
        c.create_polygon(rot_ell(x, y, ang, 0, 0, 8.6 * s, 5.2 * s), fill='#f4f4f1', outline='#b3b3ab')
        ca, sa = math.cos(ang), math.sin(ang)
        for i in range(4):
            fp = (-5 + i * 3.3) * s
            for sgn in (-1, 1):
                pass
            c.create_line(x + (fp - 1.2 * s) * ca + 4.2 * s * sa, y + (fp - 1.2 * s) * sa - 4.2 * s * ca,
                          x + (fp + 1.2 * s) * ca - 4.2 * s * sa, y + (fp + 1.2 * s) * sa + 4.2 * s * ca,
                          fill='#c9c9c1')
        return
    if f.kind == 'butterfly':
        _draw_butterfly(c, f, x, y, ang, s)
        return
    if f.kind == 'mosquito':
        _draw_mosquito(c, f, x, y, ang, s)
        return
    flap = 0.5 + 0.5 * abs(math.sin(f.phase))
    tx, ty = x + math.cos(ang) * 0.6 * s, y + math.sin(ang) * 0.6 * s
    for sd in (-1, 1):                                                   # pattes
        for fp in (2.5, 0.2, -2.0):
            ca, sa = math.cos(ang), math.sin(ang)
            x1, y1 = x + fp * s * ca - sd * 1.5 * s * sa, y + fp * s * sa + sd * 1.5 * s * ca
            c.create_line(x1, y1, x1 + (fp * 0.3 - 0.5) * s * ca - sd * 3.8 * s * sa,
                          y1 + (fp * 0.3 - 0.5) * s * sa + sd * 3.8 * s * ca, fill='#111111')
    for sd in (-1, 1):                                                   # ailes
        wa = ang + PI - sd * (0.45 + 0.55 * flap)
        c.create_polygon(rot_ell(tx, ty, wa, 4.8 * s, 0, 5.2 * s, 2.3 * s), fill='#dbe8f4', outline='#8fa3b8')
    c.create_polygon(rot_ell(x, y, ang, -3.6 * s, 0, 3.8 * s, 2.7 * s), fill='#1d1c20', outline='')
    c.create_polygon(rot_ell(x, y, ang, 0.6 * s, 0, 2.9 * s, 2.5 * s), fill='#4a4a55', outline='')
    c.create_polygon(rot_ell(x, y, ang, 3.9 * s, 0, 1.9 * s, 1.8 * s), fill='#26252b', outline='')
    ca, sa = math.cos(ang), math.sin(ang)
    for sd in (-1, 1):
        ex, ey = x + 4.5 * s * ca - sd * 1.3 * s * sa, y + 4.5 * s * sa + sd * 1.3 * s * ca
        r = 1.15 * s
        c.create_oval(ex - r, ey - r, ex + r, ey + r, fill='#d9402d', outline='')
    n = int(f.wrap * 9)                                                  # fils de soie qui l'enveloppent
    for i in range(n):
        fp = (-6 + i * 1.5) * s
        c.create_line(x + (fp - 1.0 * s) * ca + 4.4 * s * sa, y + (fp - 1.0 * s) * sa - 4.4 * s * ca,
                      x + (fp + 1.0 * s) * ca - 4.4 * s * sa, y + (fp + 1.0 * s) * sa + 4.4 * s * ca,
                      fill='#f4f4f1', width=max(2, int(1.7 * s)))



class EggSac:
    def __init__(self, x, y, seg, hatch_at):
        self.x, self.y, self.seg = x, y, seg
        self.hatch_at = hatch_at
        self.state = 'hang'
        self.vy = 0.0
        self.t = 0.0


class Baby:
    def __init__(self, x, y, s):
        self.x, self.y = x, y
        self.s = s
        self.ang = random.uniform(-PI, PI)
        self.speed = random.uniform(35, 60) * s
        self.life = random.uniform(30, 50)
        self.t = 0.0
        self.turn = 0.0
        self.alive = True
        self.mother = False

    def update(self, dt, pet):
        s = self.s
        l, t, r, b = pet.area
        self.t += dt
        self.turn = clamp(self.turn + random.uniform(-1, 1) * dt * 20, -3, 3)
        steer = self.turn
        spd = self.speed
        d = math.hypot(self.x - pet.cur[0], self.y - pet.cur[1])
        leaving = self.t > self.life
        if d < 110 * s:                                            # fuit le curseur
            steer += clamp(angdiff(self.ang, math.atan2(self.y - pet.cur[1], self.x - pet.cur[0])), -1, 1) * 9
            spd *= 3.0
        elif leaving and self.mother and pet.sp.species == 'wolf':           # retourne sur le dos de sa mère
            steer += clamp(angdiff(self.ang, math.atan2(pet.sp.y - self.y, pet.sp.x - self.x)), -1, 1) * 6
            spd *= 2.0
            if math.hypot(pet.sp.x - self.x, pet.sp.y - self.y) < 20 * pet.sp.s:
                self.alive = False
                pet.carry = min(8, pet.carry + 1)
        elif leaving:
            away = math.atan2(self.y - (t + b) / 2, self.x - (l + r) / 2)
            steer += clamp(angdiff(self.ang, away), -1, 1) * 4
            spd *= 1.6
        elif self.x < l + 20 or self.x > r - 20 or self.y < t + 20 or self.y > b - 20:
            steer += clamp(angdiff(self.ang, math.atan2((t + b) / 2 - self.y, (l + r) / 2 - self.x)), -1, 1) * 6
        self.ang += steer * dt
        self.x += math.cos(self.ang) * spd * dt
        self.y += math.sin(self.ang) * spd * dt
        if leaving and not self.mother and (self.x < l - 20 or self.x > r + 20 or self.y < t - 20 or self.y > b + 20):
            self.alive = False


def draw_baby(c, bb):
    s = bb.s * 0.55
    x, y, a = bb.x, bb.y, bb.ang
    ca, sa = math.cos(a), math.sin(a)
    ph = bb.t * 14
    for q in range(4):
        for sd in (-1, 1):
            w = math.sin(ph + q * 1.3 + (PI if sd < 0 else 0)) * 1.2
            fx = x + (3 - q * 2.2) * s * ca - sd * 4.5 * s * sa
            fy = y + (3 - q * 2.2) * s * sa + sd * 4.5 * s * ca
            c.create_line(x + (2 - q * 1.6) * s * ca, y + (2 - q * 1.6) * s * sa, fx + w * s * ca, fy + w * s * sa,
                          fill='#3a2d2a')
    c.create_polygon(rot_ell(x, y, a, -3.2 * s, 0, 3.6 * s, 3.0 * s, 10), fill='#cdbd9e', outline='#4a3d36')
    c.create_polygon(rot_ell(x, y, a, 2.6 * s, 0, 2.4 * s, 2.2 * s, 10), fill='#3a2d2a', outline='')
    for sd in (-1, 1):
        c.create_oval(x + 4 * s * ca - sd * 0.9 * s * sa - 0.7 * s, y + 4 * s * sa + sd * 0.9 * s * ca - 0.7 * s,
                      x + 4 * s * ca - sd * 0.9 * s * sa + 0.7 * s, y + 4 * s * sa + sd * 0.9 * s * ca + 0.7 * s,
                      fill='#ffffff', outline='')


def draw_sac(c, sc, now, s, hatching):
    r = 6 * s * (1 + (0.06 * math.sin(now * 12) if hatching else 0))
    x, y = sc.x, sc.y
    c.create_oval(x - r, y - r, x + r, y + r, fill='#f7f7f2', outline='#b3b3ab', width=2)
    for q in range(3):
        a = q * PI / 3 + 0.4
        c.create_line(x - r * math.cos(a) * 0.9, y - r * math.sin(a) * 0.9, x + r * math.cos(a) * 0.9,
                      y + r * math.sin(a) * 0.9, fill='#d5d5cc')
    c.create_oval(x - r * 0.45, y - r * 0.7, x - r * 0.1, y - r * 0.35, fill='#ffffff', outline='')


def draw_exuvia(c, ex):
    x, y, ang, age, feet, s = ex
    ca, sa = math.cos(ang), math.sin(ang)

    def loc(f_, d_):
        return x + f_ * ca - d_ * sa, y + f_ * sa + d_ * ca

    for i in range(8):
        j = i % 4
        sd = -1 if i < 4 else 1
        hx, hy = loc(HIP_F[j] * s, sd * 3 * s)
        fx, fy = feet[i]
        mx, my = (hx + fx) / 2 - sd * sa * 7 * s, (hy + fy) / 2 + sd * ca * 7 * s
        c.create_line(hx, hy, mx, my, fx, fy, fill='#c9d0dd', width=max(2, int(2 * s)), capstyle=tk.ROUND,
                      joinstyle=tk.ROUND)
    c.create_polygon(rot_ell(x, y, ang, -9.5 * s, 0, 9.5 * s, 7.5 * s), fill='#e8edf5', outline='#aab2c0',
                     stipple='gray50')
    c.create_polygon(rot_ell(x, y, ang, 4 * s, 0, 9.3 * s, 8.2 * s), fill='#e8edf5', outline='#aab2c0',
                     stipple='gray50')



class Companion:
    """Seconde araignée (l'autre espèce) : se promène, évite le curseur, salue la première."""

    def __init__(self, area, scale, species, x, y):
        self.area = area
        self.s = scale
        self.sp = Spider(x, y, scale, species)
        self.state = 'idle'
        self.t = 0.0
        self.idle_for = 1.0
        self.target = (x, y)
        self.speed = 90 * scale
        self.jx0 = self.jy0 = 0.0
        self.leap_to = (x, y)
        self.flee_ang = 0.0
        self.flee_ok = 0.0

    def grab(self):
        self.set('held')

    def set(self, st):
        self.state = st
        self.t = 0.0
        if st != 'greet':
            self.sp.dance = 0.0
            self.sp.wave = 0.0

    def steer(self, tx, ty, speed, dt, turn=7.0):
        sp = self.sp
        dx, dy = tx - sp.x, ty - sp.y
        d = math.hypot(dx, dy)
        if d < 1e-3:
            return d
        diff = angdiff(sp.ang, math.atan2(dy, dx))
        sp.ang += clamp(diff, -turn * dt, turn * dt)
        f = max(0.15, math.cos(diff)) if abs(diff) < PI / 2 else 0.15
        step = min(d, speed * f * dt)
        sp.x += math.cos(sp.ang) * step
        sp.y += math.sin(sp.ang) * step
        return d

    def update(self, dt, pet):
        sp, s = self.sp, self.s
        l, t, r, b = self.area
        ox, oy = sp.x, sp.y
        self.t += dt
        if self.state == 'held':                                  # saisie a la main : elle pend au bout du curseur
            sp.x, sp.y = pet.cur[0], pet.cur[1]
            sp.z = 26 * s
            sp.vx = sp.vy = 0.0
            sp.gaze = (0.0, 0.6)
            if not pet.getbtn():
                sp.z = 0.0
                self.idle_for = 1.0
                self.set('idle')
            sp.update_legs(dt)
            return
        st = self.state
        cd = math.hypot(pet.cur[0] - sp.x, pet.cur[1] - sp.y)
        if st in ('idle', 'walk') and pet.now > self.flee_ok and pet.cspeed > 1100 and cd < 130 * s:
            self.flee_ang = math.atan2(sp.y - pet.cur[1], sp.x - pet.cur[0])
            self.flee_ok = pet.now + 4
            self.set('flee')
            st = 'flee'
        if st == 'idle':
            diff = angdiff(sp.ang, math.atan2(pet.cur[1] - sp.y, pet.cur[0] - sp.x))
            if cd < 450 * s and pet.cspeed < 900:
                sp.ang += clamp(diff, -1.8 * dt, 1.8 * dt)
            if self.t > self.idle_for:
                rr = random.random()
                if rr < 0.3:                                      # va voir l'autre araignée
                    self.target = (pet.sp.x + random.uniform(-160, 160) * s, pet.sp.y + random.uniform(-160, 160) * s)
                    self.speed = random.choice((70, 100, 130)) * s
                    self.set('walk')
                elif rr < 0.45:
                    a = sp.ang + random.uniform(-0.8, 0.8)
                    dist = random.uniform(130, 280) * s
                    self.leap_to = (clamp(sp.x + math.cos(a) * dist, l + 20, r - 20),
                                    clamp(sp.y + math.sin(a) * dist, t + 20, b - 20))
                    self.jx0, self.jy0 = sp.x, sp.y
                    self.set('leap')
                elif rr < 0.85:
                    self.target = (random.uniform(l + 60, r - 60), random.uniform(t + 60, b - 60))
                    self.speed = random.choice((70, 90, 110, 200)) * s
                    self.set('walk')
                else:
                    self.idle_for = random.uniform(2, 5)
                    self.t = 0.0
        elif st == 'walk':
            if self.steer(self.target[0], self.target[1], self.speed, dt) < 8 * s:
                self.idle_for = random.uniform(1, 4)
                self.set('idle')
        elif st == 'leap':
            u = self.t
            if u < 0.28:
                diff = angdiff(sp.ang, math.atan2(self.leap_to[1] - sp.y, self.leap_to[0] - sp.x))
                sp.ang += clamp(diff, -14 * dt, 14 * dt)
            else:
                k = clamp((u - 0.28) / 0.42, 0.0, 1.0)
                sp.x = lerp(self.jx0, self.leap_to[0], k)
                sp.y = lerp(self.jy0, self.leap_to[1], k)
                sp.z = 70 * s * math.sin(PI * k)
                if k >= 1.0:
                    sp.z = 0.0
                    self.idle_for = random.uniform(0.6, 2.0)
                    self.set('idle')
        elif st == 'flee':
            sp.ang += clamp(angdiff(sp.ang, self.flee_ang), -14 * dt, 14 * dt)
            sp.x += math.cos(sp.ang) * 480 * s * dt
            sp.y += math.sin(sp.ang) * 480 * s * dt
            if self.t > 0.6:
                self.idle_for = 1.5
                self.set('idle')
        elif st == 'greet':
            if sp.species == 'peacock':
                sp.dance = min(1.0, self.t / 0.6)
                sp.dphase += dt * 9
            else:
                sp.wave = min(1.0, self.t / 0.4)
                sp.dphase += dt * 14
            diff = angdiff(sp.ang, math.atan2(pet.sp.y - sp.y, pet.sp.x - sp.x))
            sp.ang += clamp(diff, -6 * dt, 6 * dt)
            if self.t > 4.2:
                self.idle_for = 2.0
                self.set('idle')
        if st != 'leap' and st != 'greet':
            sp.z = 0.0
        # ne se superpose pas à la première araignée
        dx, dy = sp.x - pet.sp.x, sp.y - pet.sp.y
        dd = math.hypot(dx, dy)
        if 0 < dd < 40 * s and st not in ('leap', 'greet'):
            sp.x += dx / dd * 120 * s * dt
            sp.y += dy / dd * 120 * s * dt
        if st not in ('leap',):
            sp.x = clamp(sp.x, l + 6, r - 6)
            sp.y = clamp(sp.y, t + 6, b - 6)
        if dt > 1e-4:
            sp.vx += ((sp.x - ox) / dt - sp.vx) * min(1.0, dt * 12)
            sp.vy += ((sp.y - oy) / dt - sp.vy) * min(1.0, dt * 12)
        # regard vers le curseur
        gdx, gdy = pet.cur[0] - sp.x, pet.cur[1] - (sp.y - sp.z)
        gd = math.hypot(gdx, gdy)
        gk = min(1.0, gd / 150) / gd if gd > 1 else 0.0
        gl = min(1.0, dt * 10)
        sp.gaze = (sp.gaze[0] + (gdx * gk - sp.gaze[0]) * gl, sp.gaze[1] + (gdy * gk - sp.gaze[1]) * gl)
        sp.update_legs(dt)


class ClipCanvas:
    """Ne dessine que ce qui est au-dessus de la ligne y = edge : le reste est « derriere la fenetre »."""

    def __init__(self, c, edge):
        self.c = c
        self.edge = edge

    def __getattr__(self, name):
        return getattr(self.c, name)

    @staticmethod
    def _pts(a):
        if len(a) == 1 and not isinstance(a[0], (int, float)):
            a = a[0]
        v = [float(q) for q in a]
        return [(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]

    @staticmethod
    def _chaikin(pts, closed, n=2):
        for _ in range(n):
            m = len(pts)
            out = [] if closed else [pts[0]]
            for i in (range(m) if closed else range(m - 1)):
                p, q = pts[i], pts[(i + 1) % m]
                out.append((0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]))
                out.append((0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1]))
            if not closed:
                out.append(pts[-1])
            pts = out
        return pts

    def _clip_poly(self, pts):
        e = self.edge
        out = []
        m = len(pts)
        for i in range(m):
            p, q = pts[i], pts[(i + 1) % m]
            pin, qin = p[1] <= e, q[1] <= e
            if pin:
                out.append(p)
            if pin != qin:
                t = (e - p[1]) / (q[1] - p[1])
                out.append((p[0] + (q[0] - p[0]) * t, e))
        return out

    def create_polygon(self, *args, **kw):
        pts = self._pts(args)
        if len(pts) < 3:
            return None
        if all(p[1] <= self.edge for p in pts):
            return self.c.create_polygon(*[v for p in pts for v in p], **kw)
        if all(p[1] > self.edge for p in pts):
            return None
        if kw.get('smooth'):
            pts = self._chaikin(pts, True)
        kw['smooth'] = False
        res = self._clip_poly(pts)
        if len(res) < 3:
            return None
        return self.c.create_polygon(*[v for p in res for v in p], **kw)

    def create_line(self, *args, **kw):
        pts = self._pts(args)
        if len(pts) < 2:
            return None
        e = self.edge
        if all(p[1] <= e for p in pts):
            return self.c.create_line(*[v for p in pts for v in p], **kw)
        if all(p[1] > e for p in pts):
            return None
        if kw.get('smooth'):
            pts = self._chaikin(pts, False)
        kw['smooth'] = False
        run = []
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            pin, qin = p[1] <= e, q[1] <= e
            if pin and not run:
                run = [p]
            if pin and qin:
                run.append(q)
            elif pin != qin:
                t = (e - p[1]) / (q[1] - p[1])
                x = (p[0] + (q[0] - p[0]) * t, e)
                if pin:
                    run.append(x)
                    self.c.create_line(*[v for z in run for v in z], **kw)
                    run = []
                else:
                    run = [x, q]
        if len(run) >= 2:
            self.c.create_line(*[v for z in run for v in z], **kw)
        return None

    def create_oval(self, x0, y0, x1, y1, **kw):
        if y1 <= self.edge:
            return self.c.create_oval(x0, y0, x1, y1, **kw)
        if y0 > self.edge:
            return None
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0) / 2, abs(y1 - y0) / 2
        pts = [(cx + rx * math.cos(2 * PI * q / 28), cy + ry * math.sin(2 * PI * q / 28)) for q in range(28)]
        res = self._clip_poly(pts)
        if len(res) < 3:
            return None
        kw.pop('smooth', None)
        return self.c.create_polygon(*[v for p in res for v in p], **kw)

    def create_arc(self, x0, y0, x1, y1, **kw):
        if (y0 + y1) / 2 <= self.edge:
            return self.c.create_arc(x0, y0, x1, y1, **kw)
        return None

    def create_text(self, x, y, **kw):
        if y <= self.edge:
            return self.c.create_text(x, y, **kw)
        return None


try:
    from PIL import Image as _PI, ImageDraw as _PD, ImageFont as _PF
except Exception:                                   # sans Pillow : dessin direct (bords en escalier)
    _PI = _PD = _PF = None

_RGB_CACHE = {}
_FONT_CACHE = {}


def _rgb(col):
    if not col:
        return None
    r = _RGB_CACHE.get(col)
    if r is None:
        if isinstance(col, str) and col.startswith('#') and len(col) == 7:
            r = (int(col[1:3], 16), int(col[3:5], 16), int(col[5:7], 16))
        else:
            try:
                v = tk._default_root.winfo_rgb(col)
                r = (v[0] >> 8, v[1] >> 8, v[2] >> 8)
            except Exception:
                r = (255, 255, 255)
        _RGB_CACHE[col] = r
    return r


class AACanvas:
    """Canvas « lisse » : meme interface que tk.Canvas (create_polygon / line / oval / arc / text), mais dessine en 3x
    avec Pillow puis reduit : plus de bords en escalier. Le resultat est pose sur le vrai canvas comme une image."""
    SS = 3

    def __init__(self, c, x0, y0, w, h, key=None):
        self.c = c
        self.x0, self.y0 = int(x0), int(y0)
        self.w, self.h = max(8, int(w)), max(8, int(h))
        S = self.SS
        self.img = _PI.new('RGBA', (self.w * S, self.h * S), (0, 0, 0, 0) if key is None else _rgb(key) + (255,))
        self.d = _PD.Draw(self.img)

    def _pts(self, a):
        if len(a) == 1 and not isinstance(a[0], (int, float)):
            a = a[0]
        v = [float(q) for q in a]
        S = self.SS
        return [((v[i] - self.x0) * S, (v[i + 1] - self.y0) * S) for i in range(0, len(v) - 1, 2)]

    def _stroke(self, pts, w, col, closed=False, caps=False):
        S = self.SS
        wi = max(1, int(round(w * S)))
        seq = pts + ([pts[0]] if closed else [])
        if len(seq) >= 2:
            self.d.line(seq, fill=col, width=wi, joint='curve')
        if caps and wi > 2:
            r = wi / 2.0
            for p in (pts[0], pts[-1]):
                self.d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=col)

    def create_polygon(self, *args, **kw):
        pts = self._pts(args)
        if len(pts) < 3:
            return None
        if kw.get('smooth'):
            pts = ClipCanvas._chaikin(pts, True)
        fill, outline = _rgb(kw.get('fill')), _rgb(kw.get('outline'))
        if fill:
            self.d.polygon(pts, fill=fill)
        if outline and kw.get('width', 1):
            self._stroke(pts, float(kw.get('width', 1)), outline, closed=True)
        return None

    def create_line(self, *args, **kw):
        pts = self._pts(args)
        if len(pts) < 2:
            return None
        if kw.get('smooth') and len(pts) > 2:
            pts = ClipCanvas._chaikin(pts, False)
        col = _rgb(kw.get('fill', '#000000'))
        self._stroke(pts, float(kw.get('width', 1)), col, caps=True)
        return None

    def create_oval(self, x0, y0, x1, y1, **kw):
        S = self.SS
        box = [(x0 - self.x0) * S, (y0 - self.y0) * S, (x1 - self.x0) * S, (y1 - self.y0) * S]
        fill, outline = _rgb(kw.get('fill')), _rgb(kw.get('outline'))
        wd = max(1, int(round(float(kw.get('width', 1)) * S)))
        self.d.ellipse(box, fill=fill, outline=outline, width=wd if outline else 0)
        return None

    def create_rectangle(self, x0, y0, x1, y1, **kw):
        S = self.SS
        box = [(x0 - self.x0) * S, (y0 - self.y0) * S, (x1 - self.x0) * S, (y1 - self.y0) * S]
        fill, outline = _rgb(kw.get('fill')), _rgb(kw.get('outline'))
        wd = max(1, int(round(float(kw.get('width', 1)) * S)))
        self.d.rectangle(box, fill=fill, outline=outline, width=wd if outline else 0)
        return None

    def create_arc(self, x0, y0, x1, y1, **kw):
        S = self.SS
        box = [(x0 - self.x0) * S, (y0 - self.y0) * S, (x1 - self.x0) * S, (y1 - self.y0) * S]
        st, ex = float(kw.get('start', 0)), float(kw.get('extent', 90))
        col = _rgb(kw.get('outline') or kw.get('fill') or '#000000')
        self.d.arc(box, -(st + ex), -st, fill=col, width=max(1, int(round(float(kw.get('width', 1)) * S))))
        return None

    def create_text(self, x, y, **kw):
        S = self.SS
        f = kw.get('font') or ('Segoe UI', -12)
        size = int(abs(f[1]) * S)
        key = (size, 'sym' if 'Symbol' in str(f[0]) else 'ui')
        font = _FONT_CACHE.get(key)
        if font is None:
            for name in (('seguisym.ttf', 'segoeui.ttf') if key[1] == 'sym' else ('segoeuib.ttf', 'segoeui.ttf')):
                try:
                    font = _PF.truetype(name, size)
                    break
                except Exception:
                    font = None
            _FONT_CACHE[key] = font or False
        if font:
            self.d.text(((x - self.x0) * S, (y - self.y0) * S), str(kw.get('text', '')), font=font, fill=_rgb(kw.get('fill', '#ffffff')), anchor='mm')
        return None

    def render(self):
        """Image finale (reduite) : les bords sont de vrais degrades de transparence."""
        return self.img.resize((self.w, self.h), _PI.LANCZOS)

    def flush(self):                                  # variante sans fenetre a part : posee sur le canvas (fond opaque)
        import base64
        buf = io.BytesIO()
        self.render().save(buf, 'PNG', compress_level=1)
        ph = tk.PhotoImage(data=base64.b64encode(buf.getvalue()).decode('ascii'))
        self.c.create_image(self.x0, self.y0, image=ph, anchor='nw')
        return ph


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', wintypes.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long), ('biPlanes', wintypes.WORD),
                ('biBitCount', wintypes.WORD), ('biCompression', wintypes.DWORD), ('biSizeImage', wintypes.DWORD),
                ('biXPelsPerMeter', ctypes.c_long), ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wintypes.DWORD), ('biClrImportant', wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [('BlendOp', ctypes.c_ubyte), ('BlendFlags', ctypes.c_ubyte), ('SourceConstantAlpha', ctypes.c_ubyte), ('AlphaFormat', ctypes.c_ubyte)]


class SpriteLayer:
    """Petite fenetre Windows a transparence par pixel (UpdateLayeredWindow) : l'animal y est affiche avec de vrais bords doux,
    sans liseré, par-dessus le bureau. Elle laisse passer les clics sauf quand la souris est sur l'animal."""

    def __init__(self):
        self.hwnd = None
        self.ok = True
        self.vis = False
        self.solid = False
        self.hdc = None
        self.bmp = None
        self.bits = ctypes.c_void_p()
        self.cap = (0, 0)

    def _setup(self):
        u32, g32 = ctypes.windll.user32, ctypes.windll.gdi32
        u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        u32.CreateWindowExW.restype = wintypes.HWND
        u32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE), wintypes.HDC,
                                            ctypes.POINTER(wintypes.POINT), wintypes.DWORD, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
        u32.UpdateLayeredWindow.restype = wintypes.BOOL
        u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.GetWindowLongW.restype = ctypes.c_long
        u32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        u32.DestroyWindow.argtypes = [wintypes.HWND]
        g32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g32.CreateCompatibleDC.restype = wintypes.HDC
        g32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        g32.CreateDIBSection.restype = wintypes.HBITMAP
        g32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g32.SelectObject.restype = wintypes.HGDIOBJ
        g32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g32.DeleteDC.argtypes = [wintypes.HDC]
        # LAYERED | TRANSPARENT | TOPMOST | TOOLWINDOW | NOACTIVATE
        self.hwnd = u32.CreateWindowExW(0x80000 | 0x20 | 0x8 | 0x80 | 0x08000000, 'STATIC', 'AraigneeSprite', 0x80000000, 0, 0, 1, 1, None, None, None, None)
        if not self.hwnd:
            self.ok = False
            return
        self.hdc = g32.CreateCompatibleDC(None)
        atexit.register(self.close)

    def _dib(self, w, h):
        g32 = ctypes.windll.gdi32
        if self.bmp:
            g32.SelectObject(self.hdc, self.old)
            g32.DeleteObject(self.bmp)
        bi = BITMAPINFOHEADER(40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        self.bmp = g32.CreateDIBSection(self.hdc, ctypes.byref(bi), 0, ctypes.byref(self.bits), None, 0)
        self.old = g32.SelectObject(self.hdc, self.bmp)
        self.cap = (w, h)

    def show(self, img, x, y, solid=False):
        """Affiche l'image RGBA (pixels en coordonnees ecran) ; False si ca ne marche pas (on retombe sur le dessin direct)."""
        try:
            if not self.ok:
                return False
            u32 = ctypes.windll.user32
            if self.hwnd is None:
                self._setup()
                if not self.ok:
                    return False
            w, h = img.size
            if (w, h) != self.cap:
                self._dib(w, h)
            data = img.tobytes('raw', 'BGRa')
            ctypes.memmove(self.bits, data, len(data))
            pt, sz, src, bf = wintypes.POINT(int(x), int(y)), wintypes.SIZE(w, h), wintypes.POINT(0, 0), BLENDFUNCTION(0, 0, 255, 1)
            if not u32.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(pt), ctypes.byref(sz), self.hdc, ctypes.byref(src), 0, ctypes.byref(bf), 2):
                self.ok = False
                return False
            if solid != self.solid:
                self.set_solid(solid)
            if not self.vis:
                u32.ShowWindow(self.hwnd, 4)
                u32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x13)
                self.vis = True
            return True
        except Exception:
            self.ok = False
            return False

    def set_solid(self, solid):
        """solid = la souris est sur l'animal : la fenetre capte les clics (sinon ils traversent jusqu'aux autres applications)."""
        self.solid = solid
        if self.hwnd:
            u32 = ctypes.windll.user32
            ex = u32.GetWindowLongW(self.hwnd, -20)
            u32.SetWindowLongW(self.hwnd, -20, (ex & ~0x20) if solid else (ex | 0x20))

    def hide(self):
        if self.hwnd and self.vis:
            ctypes.windll.user32.ShowWindow(self.hwnd, 0)
            self.vis = False

    def close(self):
        try:
            if self.hwnd:
                ctypes.windll.user32.DestroyWindow(self.hwnd)
                self.hwnd = None
            if self.bmp:
                ctypes.windll.gdi32.DeleteObject(self.bmp)
                self.bmp = None
        except Exception:
            pass


class TagCanvas:
    """Enveloppe d'un Canvas : tout ce qui est dessiné reçoit une étiquette (pour l'effacer par couche)."""

    def __init__(self, c, tag):
        self._c, self._tag = c, tag

    def __getattr__(self, name):
        f = getattr(self._c, name)
        if name.startswith('create_'):
            def g(*a, **k):
                k['tags'] = self._tag
                return f(*a, **k)
            return g
        return f


class Renderer:
    """La toile est redessinée seulement quand elle change ; tout le reste à chaque image."""

    def __init__(self, canvas):
        self.c = canvas
        self.dyn = TagCanvas(canvas, 'dyn')
        self.web = TagCanvas(canvas, 'web')
        self.sig = None

    def reset(self):
        self.sig = None
        self.c.delete('web')
        self.c.delete('dyn')

    def render(self, pet):
        self.c.delete('dyn')
        sig = pet.web_sig()
        if sig != self.sig:
            self.c.delete('web')
            pet.web.draw(self.web, pet.dew_on, pet.now, pet.web_jit(), 'static')
            self.sig = sig
        pet.draw(self.dyn, static=False)


# --------------------------------------------------------------------- cerveau
class Pet:
    def __init__(self, area, scale, corner, getcursor, log=None, species='peacock'):
        self.area = area
        self.s = scale
        self.getcur = getcursor
        self.log = log
        self.web = Web(area, corner, scale)
        l, t, r, b = area
        self.sp = Spider(random.uniform(l + 200, r - 200), random.uniform(t + 200, b - 200), scale, species)
        self.now = 0.0
        self.state = 'idle'
        self.state_t = 0.0
        self.idle_for = 0.5
        self.look = False
        self.sub = 'move'
        self.target = (self.sp.x, self.sp.y)
        self.walk_speed = 90 * scale
        self.cur = self.pcur = getcursor()
        self.cspeed = 0.0
        self.cut_times = []
        self.no_attack_until = 0.0
        self.flee_ok = 0.0
        self.weave_force = 0.0
        self.shake = 0.0
        self.cling_end = 10.0
        self.flinging = False
        self.fvx = self.fvy = 0.0
        self.fdur = 0.4
        self.flee_ang = 0.0
        self.jx0 = self.jy0 = 0.0
        self.icons = []
        self.route = []
        self.dance_ok = 6.0
        self.dance_dur = 8.0
        self.hearts = []
        self.heart_t = 0.0
        self.bk = Basket(area, scale)
        self.flies = []
        self.target_fly = None
        self.bk_press = None
        self.bk_drag = False
        self.bk_off = (0.0, 0.0)
        self.hover_bk = False
        self.no_cut_until = 0.0
        self.orb = 0.0
        self.getbtn2 = lambda: False
        self.btn2_prev = False
        self.pet_acc = 0.0
        self.pet_away = 0.0
        self.pet_ok = 0.0
        self.pet_heart_t = 0.0
        self.rj_n = 0
        self.rj_ang = 0.0
        self.rj_dir = 1
        self.leap_to = (0.0, 0.0)
        self.next_look = False
        self.next_idle = None
        self.cute = False
        self.cfg_save = None
        self.hunger = 0.5
        self.still_t = 0.0
        self.pounce_ok = 0.0
        self.zzz = []
        self.zzz_t = 0.0
        self.getbtn = lambda: False
        self.btn_prev = False
        self.interactive = False
        self.grab_off = (0.0, 0.0)
        self.drop_z0 = 0.0
        self.snd = Sound()
        self.paused = False
        self.menu_open = False
        self.menu_ctx = 'spider'
        self.menu_page = 'main'
        self.animal = 'spider'
        self.switch_animal_cb = None
        self.menu_pos = (0.0, 0.0)
        self.quit_cb = None
        self.dew_on = False
        self.comp_on = False
        self.click_t = -9.0
        self.grab_t = -9.0
        self.grab_cur = (0.0, 0.0)
        self.flip_a0 = 0.0
        self.flip_dir = 1
        self.wiggle = []
        self.last_wig = -9.0
        self.pvx = self.pvy = 0.0
        self.chase_ok = 0.0
        self.cp_phase = 0
        self.cp_t = 0.0
        self.hide_e = 'r'
        self.hide_pt = (0.0, 0.0)
        self.hide_out = (1.0, 0.0)
        self.hide_ang = PI
        self.duck_until = 0.0
        self.dg_x = 0.0
        self.dg_depth = 160.0
        self.dg_hang = 4.0
        self.hand_fly = None
        self.getctrl = lambda: False
        self.sac = None
        self.babies = []
        self.exuviae = []
        self.molt_ok = 240.0
        self.molted = False
        self.lay_pt = (0.0, 0.0)
        self.lay_seg = None
        self.hatch_delay = None
        self.windows = []
        self.win_by = {}
        self.perch_hwnd = None
        self.perch_dx = 0.0
        self.perch_v = 0.0
        self.perch_end = 0.0
        self.comp = None
        self.greet_ok = 20.0
        l0, t0, r0, b0 = area
        self.burrow_pt = (l0 + 220 * scale, b0 - 130 * scale)
        self.hang_pt = (0.0, 0.0)
        self.hang_end = 0.0
        self.burrow_end = 0.0
        self.amb_end = 0.0
        self.carry = 8
        self.unloaded = False
        self.camo_t = 0.0
        self.camo_target = (235.0, 225.0, 160.0)
        self.sample_cb = None
        self.whirl_c = (0.0, 0.0)
        self.sparks = []
        self.wash_ok = 15.0
        self.wash_pt = (0.0, 0.0)
        self.wash_seg = None
        self.wash_d = None

    # --- utilitaires
    def set_state(self, name):
        if self.log and name != self.state:
            self.log(f"[{self.now:6.1f}s] {self.state} -> {name}  (toile {self.web.built_ratio():.0%})")
        self.state = name
        self.state_t = 0.0
        if name not in ('dance', 'dance_end'):
            self.sp.dance = 0.0
        if name != 'rwave':
            self.sp.wave = 0.0
        if name != 'pet':
            self.sp.happy = 0.0
        if name != 'dangle':
            self.sp.splay = False
        if name != 'wash':
            self.sp.wash = 0.0
        if name not in ('threat', 'ambush', 'hang'):
            self.sp.threat = 0.0
        if name != 'burrow':
            self.sp.hidden = False
        if name not in ('lay', 'molt'):
            self.sp.pulse = 0.0 if name != 'sleep' else self.sp.pulse
        if name != 'sleep':
            self.sp.sleeping = False
            self.sp.pulse = 0.0

    def go_idle(self, secs, look=False):
        self.set_state('idle')
        self.idle_for = secs
        self.look = look
        self.sp.z = 0.0

    def steer(self, tx, ty, speed, dt, turn=7.0):
        sp = self.sp
        dx, dy = tx - sp.x, ty - sp.y
        d = math.hypot(dx, dy)
        if d < 1e-3:
            return d
        diff = angdiff(sp.ang, math.atan2(dy, dx))
        sp.ang += clamp(diff, -turn * dt, turn * dt)
        f = max(0.15, math.cos(diff)) if abs(diff) < PI / 2 else 0.15
        step = min(d, speed * f * dt)
        sp.x += math.cos(sp.ang) * step
        sp.y += math.sin(sp.ang) * step
        return d

    def face(self, tx, ty, dt, turn=6.0):
        sp = self.sp
        diff = angdiff(sp.ang, math.atan2(ty - sp.y, tx - sp.x) - sp.body_off)
        sp.ang += clamp(diff, -turn * dt, turn * dt)

    def cdist(self):
        return math.hypot(self.cur[0] - self.sp.x, self.cur[1] - self.sp.y)

    # --- boucle
    def update(self, dt):
        s = self.s
        sp = self.sp
        self.now += dt
        self.state_t += dt
        self.pcur = self.cur
        cx_, cy_ = self.getcur()
        l_, t_, r_, b_ = self.area
        self.cur = (clamp(cx_, l_, r_), clamp(cy_, t_, b_))   # curseur sur un 2e écran : collé au bord
        inst = math.hypot(self.cur[0] - self.pcur[0], self.cur[1] - self.pcur[1]) / max(dt, 1e-3)
        self.cspeed += (inst - self.cspeed) * min(1.0, dt * 8)
        self.hunger = min(1.0, self.hunger + dt * 0.004)
        self.still_t = self.still_t + dt if self.cspeed < 5 else 0.0
        gdx, gdy = self.cur[0] - sp.x, self.cur[1] - (sp.y - sp.z - sp.elev)
        gd = math.hypot(gdx, gdy)
        gk = min(1.0, gd / 150) / gd if gd > 1 else 0.0
        gl = min(1.0, dt * 10)
        sp.gaze = (sp.gaze[0] + (gdx * gk - sp.gaze[0]) * gl, sp.gaze[1] + (gdy * gk - sp.gaze[1]) * gl)

        spn = sp.species
        sp.carry = self.carry if spn == 'wolf' else 0
        if sp.cute and not sp.hidden and math.hypot(sp.vx, sp.vy) > 60 * s and random.random() < dt * 5:
            self.sparks.append([sp.x - sp.vx * 0.03, sp.y - sp.vy * 0.03, random.uniform(-6, 6) * s, -14 * s, 0.0, 'star'])
        if spn == 'crab':                                    # camouflage : prend la couleur du fond
            self.camo_t += dt
            if self.camo_t > 0.5 and self.sample_cb:
                self.camo_t = 0.0
                l_, t_, r_, b_ = self.area
                col_ = self.sample_cb(clamp(sp.x + 90 * sp.s, l_, r_ - 2), clamp(sp.y, t_, b_ - 2))
                if col_:
                    self.camo_target = col_
            for q_ in range(3):
                sp.camo[q_] += (self.camo_target[q_] - sp.camo[q_]) * min(1.0, dt * 1.2)
        vx_, vy_ = self.cur[0] - self.pcur[0], self.cur[1] - self.pcur[1]
        vl_ = math.hypot(vx_, vy_)
        if vl_ > 10 and math.hypot(self.pvx, self.pvy) > 10 and (vx_ * self.pvx + vy_ * self.pvy) < 0:
            self.wiggle.append(self.now)                    # le curseur change brusquement de sens
            self.last_wig = self.now
        if vl_ > 3:
            self.pvx, self.pvy = vx_, vy_
        self.wiggle = [t_ for t_ in self.wiggle if self.now - t_ < 1.6]
        btn = bool(self.getbtn())
        pressed = btn and not self.btn_prev
        self.btn_prev = btn
        hover = self.state not in ('cling', 'jump', 'attack', 'fling') and not sp.hidden and self.over_spider()
        self.hover_bk = (not hover) and self.bk.hit(self.cur[0], self.cur[1])
        cp_ = self.comp
        comp_hover = (cp_ is not None and not hover and not self.hover_bk
                      and (cp_.state == 'held' or math.hypot(self.cur[0] - cp_.sp.x, self.cur[1] - cp_.sp.y) < 42 * s))
        self.interactive = (hover or self.state == 'held' or self.hover_bk or self.bk_press is not None or comp_hover
                            or (self.menu_open and self.over_menu()) or self.hand_fly is not None)
        btn2 = bool(self.getbtn2())
        pressed2 = btn2 and not self.btn2_prev
        self.btn2_prev = btn2
        consumed = False
        if self.menu_open and pressed:                      # clic dans le menu (ou dehors : il se ferme)
            consumed = True
            idx = self.menu_row()
            items = self.menu_items()
            if idx is not None and str(items[idx][1]).startswith('slider:'):
                self.slider_start(items[idx][1][7:])            # curseur : on le fait glisser, le menu reste ouvert
                idx = None
            else:
                self.menu_open = False
            if idx is not None and items[idx][1]:
                self.sound('tap')
                self.menu_action(items[idx][1])
        self.slider_tick(btn)
        if pressed2:
            if self.hover_bk:
                self.open_menu('basket')
            elif hover and self.state != 'held':
                self.open_menu('spider')
            else:
                self.menu_open = False
        # caresses : le curseur glisse doucement sur elle
        if (self.state in ('idle', 'walk', 'weave', 'dance_go', 'dance_end') and hover and not btn
                and self.now >= self.pet_ok and 15 < self.cspeed < 1100):
            self.pet_acc += dt
            if self.pet_acc > 0.35:
                self.pet_acc = 0.0
                self.pet_away = 0.0
                self.pet_heart_t = 0.0
                self.set_state('pet')
        else:
            self.pet_acc = max(0.0, self.pet_acc - dt * 2)
        if (len(self.wiggle) >= 4 and self.state in ('idle', 'walk', 'tour', 'leap') and not hover
                and self.now >= self.chase_ok and self.cdist() > 60 * s and not self.paused):
            self.cp_phase, self.cp_t = 0, 0.0
            self.set_state('chase')
        if pressed and not consumed and hover and self.state != 'held':
            if self.now - self.click_t < 0.5:                # double-clic : saut périlleux
                self.start_flip()
            else:
                self.grab()
        elif pressed and not consumed and comp_hover and cp_.state != 'held':
            cp_.grab()                                           # la deuxieme araignee se deplace aussi
        elif pressed and not consumed and self.hover_bk and self.bk_press is None:
            if self.getctrl() and self.hand_fly is None and len(self.flies) < 4:
                self.hand_fly = self.new_fly(held=True)             # Ctrl + clic : proie tenue à la main
            else:
                self.bk_press = self.cur
                self.bk_drag = False
                self.bk_off = (self.bk.x - self.cur[0], self.bk.y - self.cur[1])
        if self.bk_press is not None:
            if btn:
                if self.bk_drag or math.hypot(self.cur[0] - self.bk_press[0], self.cur[1] - self.bk_press[1]) > 6 * s:
                    self.bk_drag = True
                    l, t, r, b = self.area
                    self.bk.x = clamp(self.cur[0] + self.bk_off[0], l + 30 * s, r - 30 * s)
                    self.bk.y = clamp(self.cur[1] + self.bk_off[1], t + 46 * s, b - 30 * s)
            else:
                if not self.bk_drag:
                    self.spawn_fly()
                else:
                    self.save_config()
                self.bk_press = None
                self.no_cut_until = self.now + 1.0
        if self.hand_fly is not None:
            f = self.hand_fly
            if btn:
                f.x, f.y = self.cur[0], self.cur[1] - 6 * s
                f.ang = -PI / 2 + math.sin(self.now * 9) * 0.5
            else:                                                   # lâchée : à l'araignée ou libre
                if math.hypot(f.x - sp.x, f.y - sp.y) < 160 * s and self.state in ('idle', 'walk', 'weave', 'tour', 'pet', 'dance_end'):
                    f.state = 'stuck'
                    f.seg = None
                    f.stuck_t = 1.1
                    f.wrap = 0.0
                    f.spin = f.ang
                    self.target_fly = f
                    self.set_state('hunt')
                else:
                    f.state = 'fly'
                    f.ang = random.uniform(-PI, PI)
                self.hand_fly = None
                self.no_cut_until = self.now + 1.0
        self.bk.update(dt)

        if self.paused:
            sp.vx = sp.vy = 0.0
            return
        # la toile ne casse pas quand on tient l'araignée / le panier
        if (self.state in ('held', 'drop') or self.bk_press is not None or self.now < self.no_cut_until
                or self.hand_fly is not None):
            cuts = []
        else:
            cuts = self.web.cut_path(self.pcur, self.cur, 5 * s)
        if cuts:
            self.on_cuts(len(cuts))

        ox, oy = sp.x, sp.y
        getattr(self, 'st_' + self.state)(dt)

        if self.state in ('idle', 'walk', 'tour', 'flee', 'startle', 'dance_go', 'dance', 'dance_end', 'rgo', 'rwave', 'rjump', 'pet'):
            tgt = 0.0
        else:
            tgt = 0.0
        sp.elev += clamp(tgt - sp.elev, -160 * s * dt, 90 * s * dt)
        if self.state in ('idle', 'walk', 'tour', 'flee', 'startle', 'dance_go', 'dance', 'dance_end', 'rgo', 'rwave', 'rjump', 'pet'):
            l, t, r, b = self.area
            sp.x = clamp(sp.x, l + 6, r - 6)
            sp.y = clamp(sp.y, t + 6, b - 6)
        if dt > 1e-4:
            sp.vx += ((sp.x - ox) / dt - sp.vx) * min(1.0, dt * 12)
            sp.vy += ((sp.y - oy) / dt - sp.vy) * min(1.0, dt * 12)
        self.web.update_debris(dt)
        for f in self.flies:
            f.update(dt, self)
        self.flies = [f for f in self.flies if f.state != 'gone']
        if self.state in ('idle', 'walk', 'weave', 'tour', 'flee', 'leap', 'perch', 'perch_go', 'wash_go', 'hang',
                          'hang_go', 'ambush', 'unload', 'burrow_go'):
            for f in self.flies:
                if f.state == 'stuck' and f.stuck_t > (0.4 if sp.species == 'widow' else 1.0):
                    self.target_fly = f
                    self.set_state('hunt')
                    break
        pg_, pr_, _pz, _pc = POUNCE.get(spn, POUNCE['default'])
        if self.hunger > pg_ and self.state in ('idle', 'walk', 'ambush') and self.now >= self.pounce_ok:
            for f in self.flies:
                if f.state == 'fly' and math.hypot(f.x - sp.x, f.y - sp.y) < pr_ * s:
                    self.start_pounce(f)
                    break
        if self.sac is not None:
            self.update_sac(dt)
        for bb in self.babies:
            bb.update(dt, self)
        self.babies = [bb for bb in self.babies if bb.alive]
        for ex in self.exuviae:
            ex[3] += dt
        self.exuviae = [ex for ex in self.exuviae if ex[3] < 50]
        if self.comp is not None:
            self.comp.update(dt, self)
            self.check_greet()
        for sk in self.sparks:
            sk[4] += dt
            if sk[4] > 0:
                if sk[5] == 'drop':
                    sk[3] += 260 * s * dt
                sk[0] += sk[2] * dt
                sk[1] += sk[3] * dt
        self.sparks = [sk for sk in self.sparks if sk[4] < {'drop': 0.75, 'hair': 0.9}.get(sk[5], 1.3)]
        for z in self.zzz:
            z[1] -= 22 * s * dt
            z[0] += 8 * s * dt
            z[2] += dt
        self.zzz = [z for z in self.zzz if z[2] < 2.4]
        for h in self.hearts:
            h[1] -= 45 * s * dt
            h[2] += dt
        self.hearts = [h for h in self.hearts if h[2] < 1.6]
        sp.update_legs(dt)

    def on_cuts(self, n):
        self.cut_times += [self.now] * n
        self.cut_times = [t for t in self.cut_times if self.now - t < 5]
        if self.state in ('attack', 'jump', 'cling', 'fling', 'held', 'drop'):
            return
        if len(self.cut_times) >= (1 if self.sp.species == 'widow' else 2) and self.now >= self.no_attack_until:
            self.cut_times = []
            self.set_state('attack')
        elif self.state != 'startle':
            self.set_state('startle')

    # --- décisions
    def pick_target(self):
        l, t, r, b = self.area
        m = 50 * self.s
        x = y = 0
        for _ in range(12):
            x = random.uniform(l + m, r - m)
            y = random.uniform(t + m, b - m)
            if 150 * self.s < math.hypot(x - self.sp.x, y - self.sp.y) < 800 * self.s:
                break
        return x, y

    def start_walk(self, target, speed=None):
        self.target = target
        self.walk_speed = (speed or random.choice((70, 90, 110, 130, 230))) * self.s * SPECIES[self.sp.species]['speed']
        self.set_state('walk')

    def start_weave(self):
        self.sub = 'move'
        self.set_state('weave')

    def decide_species(self):
        """Comportements propres à chaque espèce. Renvoie True si une action a été lancée."""
        spn, r = self.sp.species, random.random()
        if spn in ('widow', 'pholcus') and not self.web.missing() and r < 0.4:
            self.start_hang()
        elif spn == 'tarantula' and r < 0.25:
            self.start_burrow()
        elif spn == 'wolf' and self.carry >= 6 and not self.babies and r < 0.12:
            self.start_unload()
        elif spn == 'crab' and r < 0.4:
            self.start_ambush()
        else:
            return False
        return True

    def decide(self):
        r = random.random()
        s = self.s
        spn = self.sp.species
        if spn not in ('peacock', 'regius') and self.decide_species():
            return
        noweb = spn in ('tarantula', 'wolf', 'crab')
        if self.still_t > 60 and random.random() < 0.5:
            return self.start_sleep()
        if (self.web.built_ratio() > 0.99 and self.hunger < 0.45 and self.sac is None and not self.babies
                and random.random() < 0.08):
            return self.start_lay()
        if self.now >= self.molt_ok and self.hunger < 0.6 and random.random() < 0.05:
            return self.start_molt()
        if self.dew_on and self.now >= self.wash_ok and random.random() < 0.15 and self.start_wash():
            return
        if self.windows and spn != 'tarantula' and self.hunger < 0.7 and random.random() < 0.15:
            return self.start_perch()
        if self.hunger < 0.7 and random.random() < 0.08:
            return self.start_hide()
        if spn != 'tarantula' and self.hunger < 0.7 and random.random() < 0.06:
            return self.start_dangle()
        if spn in ('peacock', 'regius') and self.now >= self.dance_ok and self.hunger < 0.7 and random.random() < 0.2:
            return self.start_dance() if self.sp.species == 'peacock' else self.start_regius_show()
        if random.random() < 0.3:
            return self.start_leap()
        if self.web.missing() and not noweb:
            if r < 0.72 or self.now < self.weave_force:
                return self.start_weave()
            return self.start_walk(self.pick_target())
        if r < 0.45:
            self.start_walk(self.pick_target())
        elif r < 0.65:                                        # curieuse
            cx, cy = self.cur
            dx, dy = self.sp.x - cx, self.sp.y - cy
            d = max(1.0, math.hypot(dx, dy))
            tx, ty = cx + dx / d * 150 * s, cy + dy / d * 150 * s
            self.start_walk((tx, ty), 110)
            self.next_look = True
        elif r < 0.85:                                        # se pose près de sa toile
            hx, hy = self.web.hub
            self.start_walk((hx + self.web.sx * 70 * s, hy + self.web.sy * 70 * s), 90)
            self.next_idle = random.uniform(8, 15)
        else:
            self.go_idle(random.uniform(2, 5))

    def over_spider(self):
        sp, s = self.sp, self.s
        dx = self.cur[0] - sp.x
        dy = self.cur[1] + sp.z + sp.elev - sp.y
        ca, sa = math.cos(sp.ang + sp.body_off), math.sin(sp.ang + sp.body_off)
        f = dx * ca + dy * sa
        d = -dx * sa + dy * ca
        return -17 * s < f < 14 * s and abs(d) < 8.5 * s

    def grab(self):
        sp = self.sp
        self.grab_t = self.now
        self.grab_cur = self.cur
        self.grab_off = (sp.x - self.cur[0], sp.y - self.cur[1])
        sp.elev = 0.0
        self.route = []
        self.set_state('held')

    def st_held(self, dt):
        sp, s = self.sp, self.s
        k = min(1.0, dt * 6)
        ox, oy = self.grab_off
        self.grab_off = (ox * (1 - k), oy * (1 - k) + 4 * s * k)
        sp.z = min(22 * s, sp.z + 220 * s * dt)
        sp.x = self.cur[0] + self.grab_off[0]
        sp.y = self.cur[1] + self.grab_off[1] + sp.z
        sp.ang += 2.8 * math.sin(self.now * 16) * dt * 3
        if not self.getbtn():
            if self.now - self.grab_t < 0.28 and math.hypot(self.cur[0] - self.grab_cur[0],
                                                          self.cur[1] - self.grab_cur[1]) < 14 * s:
                self.click_t = self.now                       # simple clic (pour le double-clic)
            self.drop_z0 = sp.z
            self.set_state('drop')

    def st_drop(self, dt):
        sp = self.sp
        t = clamp(self.state_t / 0.28, 0.0, 1.0)
        sp.z = self.drop_z0 * (1 - t) ** 2
        if t >= 1.0:
            l, tp, r, b = self.area
            sp.x = clamp(sp.x, l + 6, r - 6)
            sp.y = clamp(sp.y, tp + 6, b - 6)
            self.no_attack_until = self.now + 4
            self.no_cut_until = self.now + 2.0
            self.go_idle(1.5)

    # --- mouche : panier, chasse, enroulage, repas
    def pick_kind(self):
        r = random.random()
        return 'fly' if r < 0.6 else ('mosquito' if r < 0.8 else 'butterfly')

    def new_fly(self, held=False, kind=None):
        s = self.s
        f = Fly(self.bk.x, self.bk.y - 16 * s, random.uniform(-PI / 2 - 0.6, -PI / 2 + 0.6), s, kind or self.pick_kind())
        if held:
            f.state = 'held'
        self.flies.append(f)
        self.bk.bounce = 1.0
        self.sound('pop')
        return f

    def spawn_fly(self):
        self.bk.bounce = 1.0
        if len(self.flies) >= 3:
            return
        self.new_fly()

    def fly_ok(self):
        f = self.target_fly
        return f is not None and f in self.flies and f.state == 'stuck'

    def st_hunt(self, dt):
        if not self.fly_ok():
            return self.go_idle(1.0)
        f, sp = self.target_fly, self.sp
        d = self.steer(f.x, f.y, 300 * self.s, dt, turn=14)
        if d < (50 if self.sp.species == 'pholcus' else 16) * self.s * math.sqrt(f.sf):
            self.orb = math.atan2(sp.y - f.y, sp.x - f.x)
            f.ang_cocoon = f.ang
            self.set_state('eat' if f.wrap >= 1 else 'wrap')

    def st_wrap(self, dt):
        if not self.fly_ok():
            return self.go_idle(1.0)
        f, sp, s = self.target_fly, self.sp, self.s
        if sp.species == 'pholcus':                          # lance sa soie de loin, sans s'approcher
            self.face(f.x, f.y, dt, 10)
            sp.pulse = 0.03 * math.sin(self.now * 20)
            f.wrap = min(1.0, f.wrap + dt / f.wrap_t)
            if f.wrap >= 1.0:
                sp.pulse = 0.0
                self.set_state('eat')
            return
        k_ = math.sqrt(f.sf)
        self.orb += dt * 6.0 / k_
        sp.x = f.x + math.cos(self.orb) * 16 * s * k_
        sp.y = f.y + math.sin(self.orb) * 16 * s * k_
        sp.ang = self.orb + PI / 2
        f.wrap = min(1.0, f.wrap + dt / (f.wrap_t * (0.6 if sp.species == 'widow' else 1.0)))
        if f.wrap >= 1.0:
            self.set_state('eat')

    def st_eat(self, dt):
        if not self.fly_ok():
            return self.go_idle(1.0)
        f, sp, s = self.target_fly, self.sp, self.s
        t = self.state_t
        f.size = max(0.0, 1.0 - t / f.eat_t)
        k_ = math.sqrt(f.sf)
        if int(t * 1.4) != int((t - dt) * 1.4):
            self.sound('crunch')
        tx_, ty_ = f.x + math.cos(self.orb) * 17 * s * k_, f.y + math.sin(self.orb) * 17 * s * k_
        if math.hypot(tx_ - sp.x, ty_ - sp.y) > 3 * s:                       # s'approche avant de manger
            self.steer(tx_, ty_, 170 * s, dt, turn=12)
        else:
            sp.x, sp.y = tx_, ty_
            sp.ang = math.atan2(f.y - sp.y, f.x - sp.x) + 0.25 * math.sin(self.now * 22)
        if t > f.eat_t:
            f.state = 'gone'
            self.hearts.append([sp.x, sp.y - 30 * s, 0.0])
            self.hearts.append([sp.x + 14 * s, sp.y - 38 * s, -0.2])
            self.hunger = max(0.0, self.hunger - f.feed)
            if self.hunger < 0.25 and random.random() < 0.5:
                self.start_sleep()                    # repue : sieste
            else:
                self.go_idle(2.5, True)

    # --- sieste
    def start_sleep(self):
        self.zzz_t = 0.0
        self.set_state('sleep')

    def st_sleep(self, dt):
        sp, s = self.sp, self.s
        sp.sleeping = True
        sp.pulse = 0.03 * math.sin(self.now * 2.2)
        self.zzz_t += dt
        if self.zzz_t > 1.3:
            self.zzz_t = 0.0
            self.zzz.append([sp.x + 12 * s, sp.y - 20 * s, 0.0])
            self.sound('snore')
        near = self.cdist() < 180 * s and self.cspeed > 150
        if (near or self.over_spider() or self.cspeed > 1200 or self.state_t > 150
                or (self.hunger > 0.85 and self.state_t > 30)):
            self.dance_ok = self.now + 10
            self.set_state('startle')

    # --- affamée : bondit sur une mouche en plein vol
    def start_pounce(self, f):
        sp, s = self.sp, self.s
        l, t, r, b = self.area
        tx = clamp(f.x + math.cos(f.ang) * f.speed * 0.45, l + 20, r - 20)
        ty = clamp(f.y + math.sin(f.ang) * f.speed * 0.45, t + 20, b - 20)
        self.jx0, self.jy0 = sp.x, sp.y
        self.leap_to = (tx, ty)
        self.set_state('pounce')

    def st_pounce(self, dt):
        sp, s = self.sp, self.s
        tx, ty = self.leap_to
        t = self.state_t
        if t < 0.25:                                  # s'accroupit, vise
            self.face(tx, ty, dt, 16)
            sp.x += random.uniform(-0.6, 0.6) * s
            sp.y += random.uniform(-0.6, 0.6) * s
            return
        u = (t - 0.25) / 0.35
        if u < 1.0:
            sp.x = lerp(self.jx0, tx, u)
            sp.y = lerp(self.jy0, ty, u)
            sp.z = POUNCE.get(sp.species, POUNCE['default'])[2] * s * math.sin(PI * u)
            return
        sp.z = 0.0
        sp.x, sp.y = tx, ty
        for f in self.flies:
            if f.state == 'fly' and math.hypot(f.x - sp.x, f.y - sp.y) < POUNCE.get(sp.species, POUNCE['default'])[3] * s:
                self.sound('ding')
                f.state = 'stuck'                     # attrapée !
                f.seg = None
                f.stuck_t = 1.1
                f.wrap = 0.0
                f.x = sp.x + math.cos(sp.ang) * 10 * s
                f.y = sp.y + math.sin(sp.ang) * 10 * s
                f.spin = sp.ang
                self.target_fly = f
                self.set_state('hunt')
                return
        self.pounce_ok = self.now + (3 if sp.species in ('wolf', 'crab') else 6)      # ratée
        self.go_idle(1.2, True)

    # --- toilette : elle va se laver dans une goutte de rosée de la toile
    def start_wash(self):
        self.web.ensure_dew()
        cands = [(sg, d) for sg in self.web.segs if sg.built and sg.dew for d in sg.dew]
        if not cands:
            return False
        sg, d = random.choice(cands)
        self.wash_seg, self.wash_d = sg, d
        self.wash_pt = sg.point(d[0])
        self.set_state('wash_go')
        return True

    def st_wash_go(self, dt):
        sg = self.wash_seg
        if not sg.built or not sg.dew or self.wash_d not in sg.dew:       # la goutte a disparu
            return self.go_idle(0.5)
        d = self.steer(self.wash_pt[0], self.wash_pt[1], 130 * self.s, dt)
        if d < 6 * self.s:
            sg.dew.remove(self.wash_d)
            self.sound('pop')
            self.set_state('wash')
        self.check_flee()

    def st_wash(self, dt):
        sp, s = self.sp, self.s
        t = self.state_t
        sp.wash = min(1.0, t / 0.4) if t < 3.2 else max(0.0, (3.8 - t) / 0.6)
        sp.dphase += dt * 16
        sp.x, sp.y = self.wash_pt
        sp.pulse = 0.02 * math.sin(t * 30)
        if random.random() < dt * 14 and t < 3.2:                           # éclaboussures
            hx, hy = sp.loc(14 * s, random.uniform(-6, 6) * s)
            a = random.uniform(0, 2 * PI)
            sp_ = random.uniform(30, 80) * s
            self.sparks.append([hx, hy, math.cos(a) * sp_, math.sin(a) * sp_ - 40 * s, 0.0, 'drop'])
        if int(t * 2) != int((t - dt) * 2) and t < 3.2:
            self.sound('tap')
        if t > 3.8:
            sp.pulse = 0.0
            for q in range(5):                                             # tout propre : étincelles
                a = random.uniform(0, 2 * PI)
                self.sparks.append([sp.x + math.cos(a) * 22 * s, sp.y + math.sin(a) * 22 * s - 6 * s,
                                    random.uniform(-6, 6) * s, -14 * s, -q * 0.12, 'star'])
            self.sound('chirp')
            self.wash_ok = self.now + 70
            self.go_idle(1.8, True)

    # --- veuve noire / pholque : suspendue au cœur de la toile
    def start_hang(self):
        hx, hy = self.web.hub
        R = self.web.R
        a = PI / 4
        self.hang_pt = (hx + self.web.sx * math.cos(a) * R * 0.45, hy + self.web.sy * math.sin(a) * R * 0.45)
        self.hang_end = 0.0
        self.set_state('hang_go')

    def st_hang_go(self, dt):
        if self.steer(self.hang_pt[0], self.hang_pt[1], 120 * self.s * SPECIES[self.sp.species]['speed'], dt) < 6 * self.s:
            self.hang_end = self.now + random.uniform(15, 35)
            self.set_state('hang')
        self.check_flee()

    def st_hang(self, dt):
        sp, s = self.sp, self.s
        sp.x = self.hang_pt[0] + math.sin(self.now * 1.3) * 1.5 * s
        sp.y = self.hang_pt[1] + math.sin(self.now * 2.1) * 2.0 * s
        sp.pulse = 0.015 * math.sin(self.now * 2.5)
        near = self.cdist() < 150 * s and self.cspeed > 150
        if sp.species == 'widow':                             # lève les pattes avant si on approche
            tgt = 0.8 if near else 0.0
            sp.threat += (tgt - sp.threat) * min(1.0, dt * 6)
            sp.dphase += dt * 6
        else:
            self.check_flee()
        if self.cdist() < 400 * s:
            self.face(self.cur[0], self.cur[1], dt, 1.5)
        if self.now > self.hang_end:
            self.go_idle(1.0, True)

    # --- pholque : tournoie très vite pour paraître plus grosse
    def start_whirl(self):
        self.whirl_c = (self.sp.x, self.sp.y)
        self.set_state('whirl')

    def st_whirl(self, dt):
        sp, s = self.sp, self.s
        t = self.state_t
        sp.x = self.whirl_c[0] + math.cos(t * 14) * 5 * s
        sp.y = self.whirl_c[1] + math.sin(t * 14) * 5 * s
        sp.ang += 22 * dt
        if t > 2.5:
            sp.x, sp.y = self.whirl_c
            self.go_idle(1.2, True)

    # --- mygale : menace (pattes levées, crocs), jets de poils urticants, terrier
    def start_threat(self):
        self.set_state('threat')

    def st_threat(self, dt):
        sp, s = self.sp, self.s
        t = self.state_t
        sp.threat = min(1.0, t / 0.3) if t < 2.8 else max(0.0, (3.3 - t) / 0.5)
        sp.dphase += dt * 8
        want = math.atan2(self.cur[1] - sp.y, self.cur[0] - sp.x)
        flick = 1.0 < t < 2.8
        diff = angdiff(sp.ang, want + (PI if flick else 0.0))
        sp.ang += clamp(diff, -7 * dt, 7 * dt)
        if flick and random.random() < dt * 14:               # lui tourne le dos et projette ses poils
            hx, hy = sp.loc(-14 * sp.s, random.uniform(-4, 4) * sp.s)
            a = want + random.uniform(-0.35, 0.35)
            v = random.uniform(150, 230) * s
            self.sparks.append([hx, hy, math.cos(a) * v, math.sin(a) * v, 0.0, 'hair'])
            if random.random() < 0.3:
                self.sound('tap')
        if t > 3.3:
            self.go_idle(2.0, True)

    def start_burrow(self):
        self.burrow_end = 0.0
        self.set_state('burrow_go')

    def st_burrow_go(self, dt):
        bx, by = self.burrow_pt
        if self.steer(bx, by, 110 * self.s * SPECIES[self.sp.species]['speed'], dt) < 8 * self.s:
            self.sp.x, self.sp.y = bx, by
            self.burrow_end = self.now + random.uniform(12, 35)
            self.set_state('burrow')
        self.check_flee()

    def st_burrow(self, dt):
        sp, s = self.sp, self.s
        sp.hidden = True
        sp.x, sp.y = self.burrow_pt
        if self.cdist() < 90 * s and self.cspeed > 800:     # on la dérange : elle sort en menaçant
            sp.hidden = False
            self.flee_ok = self.now + 5
            return self.start_threat()
        if self.now > self.burrow_end:
            sp.hidden = False
            self.go_idle(1.5, True)

    # --- lycose : dépose ses bébés puis les récupère
    def start_unload(self):
        self.unloaded = False
        self.set_state('unload')

    def st_unload(self, dt):
        sp, s = self.sp, self.s
        t = self.state_t
        if t < 1.0:
            sp.pulse = 0.04 * math.sin(t * 20)
        elif not self.unloaded:
            sp.pulse = 0.0
            self.unloaded = True
            for _ in range(max(self.carry, 1)):
                bb = Baby(sp.x + random.uniform(-6, 6) * s, sp.y + random.uniform(-6, 6) * s, s)
                bb.mother = True
                bb.life = random.uniform(18, 28)
                self.babies.append(bb)
            self.carry = 0
            self.sound('pop')
        if t > 2.0:
            self.unloaded = False
            self.go_idle(2.0, True)

    # --- araignée-crabe : immobile, pattes avant ouvertes, en embuscade
    def start_ambush(self):
        self.amb_end = self.now + random.uniform(12, 30)
        self.set_state('ambush')

    def st_ambush(self, dt):
        sp, s = self.sp, self.s
        sp.threat += (0.45 - sp.threat) * min(1.0, dt * 3)
        sp.dphase += dt * 1.5
        if self.cdist() < 450 * s:
            self.face(self.cur[0], self.cur[1], dt, 1.2)
        if self.now > self.amb_end:
            self.go_idle(1.0, True)

    # --- fenêtres : elle se perche sur le bord supérieur des fenêtres ouvertes
    def set_windows(self, lst):
        self.windows = lst
        self.win_by = {w[0]: w[1:] for w in lst}

    def start_perch(self):
        sp, s = self.sp, self.s
        t0 = self.area[1]
        cand = [w for w in self.windows if w[2] > t0 + 40 * s and w[3] - w[1] >= 250]
        if not cand:
            return self.start_walk(self.pick_target())
        w = random.choice(cand[:5])
        self.perch_hwnd = w[0]
        self.perch_dx = random.uniform(60, max(61, (w[3] - w[1]) - 60))
        self.perch_v = random.choice((-1, 1)) * random.uniform(25, 60) * s
        self.perch_end = self.now + random.uniform(10, 25)
        self.set_state('perch_go')

    def perch_point(self):
        w = self.win_by.get(self.perch_hwnd)
        if w is None:
            return None
        l, t, r, b = w
        return l + self.perch_dx, t - 8 * self.s

    def st_perch_go(self, dt):
        pt = self.perch_point()
        if pt is None:
            return self.go_idle(0.5)
        d = self.steer(pt[0], pt[1], 150 * self.s, dt)
        if d < 8 * self.s:
            self.set_state('perch')
        self.check_flee()

    def st_perch(self, dt):
        sp, s = self.sp, self.s
        w = self.win_by.get(self.perch_hwnd)
        if w is None:                                       # la fenêtre a disparu : elle saute
            return self.start_leap()
        l, t, r, b = w
        width = r - l
        if self.now > self.perch_end:
            return self.start_leap()                        # redescend d'un bond
        if random.random() < dt * 0.3:                      # change de sens / fait une pause
            self.perch_v = random.choice((-1, 0, 1)) * random.uniform(25, 60) * s
        self.perch_dx += self.perch_v * dt
        if self.perch_dx < 40 or self.perch_dx > width - 40:
            self.perch_v = -self.perch_v
            self.perch_dx = clamp(self.perch_dx, 40, width - 40)
        sp.x = l + self.perch_dx
        sp.y = t - 8 * s
        if abs(self.perch_v) > 1:
            sp.ang += clamp(angdiff(sp.ang, 0.0 if self.perch_v > 0 else PI), -6 * dt, 6 * dt)
        else:
            self.face(self.cur[0], self.cur[1], dt, 2.0)
        self.check_flee()

    # --- seconde araignée
    def ensure_comp(self):
        if self.comp is None:
            other = next_species(self.sp.species)
            l, t, r, b = self.area
            self.comp = Companion(self.area, self.s, other, random.uniform(l + 200, r - 200),
                                  random.uniform(t + 200, b - 200))
            if self.cute:
                self.comp.sp.cute = True
                self.comp.sp.apply_species(other, self.s)

    def toggle_companion(self):
        self.comp_on = not self.comp_on
        if self.comp_on:
            self.ensure_comp()
        else:
            self.comp = None
            if self.state == 'greet':
                self.go_idle(0.5)

    def check_greet(self):
        c = self.comp
        if (self.state in ('idle', 'walk') and c.state in ('idle', 'walk') and self.now >= self.greet_ok
                and math.hypot(c.sp.x - self.sp.x, c.sp.y - self.sp.y) < 260 * self.s
                and not self.paused and random.random() < 0.02):
            self.greet_ok = self.now + 60
            self.set_state('greet')
            c.set('greet')

    def st_greet(self, dt):
        sp, s = self.sp, self.s
        c = self.comp
        if c is None:
            return self.go_idle(0.5)
        t = self.state_t
        if sp.species == 'peacock':
            sp.dance = min(1.0, t / 0.6)
            sp.dphase += dt * 9
        else:
            sp.wave = min(1.0, t / 0.4)
            sp.dphase += dt * 14
        self.face(c.sp.x, c.sp.y, dt, 6)
        if int(t * 1.2) != int((t - dt) * 1.2):
            self.hearts.append([(sp.x + c.sp.x) / 2 + random.uniform(-10, 10) * s,
                                (sp.y + c.sp.y) / 2 - 26 * s, 0.0])
            self.sound('chirp')
        if t > 4.2:
            self.dance_ok = self.now + 20
            self.go_idle(2.0, True)

    # --- ponte d'un cocon d'œufs dans la toile
    def start_lay(self):
        rings = [sg for sg in self.web.segs if sg.built and sg.kind == 'ring']
        if not rings:
            return self.go_idle(2.0)
        self.lay_seg = random.choice(rings)
        self.lay_pt = self.lay_seg.point(0.5)
        self.set_state('lay_go')

    def st_lay_go(self, dt):
        d = self.steer(self.lay_pt[0], self.lay_pt[1], 130 * self.s, dt)
        if d < 8 * self.s:
            self.set_state('lay')

    def st_lay(self, dt):
        sp, s = self.sp, self.s
        t = self.state_t
        sp.pulse = 0.07 * math.sin(t * 9) * min(1.0, t)
        if t > 3.5:
            sp.pulse = 0.0
            x, y = self.lay_seg.nearest(sp.x, sp.y)
            delay = self.hatch_delay if self.hatch_delay is not None else random.uniform(45, 90)
            self.sac = EggSac(x, y, self.lay_seg, self.now + delay)
            self.hearts.append([sp.x, sp.y - 30 * s, 0.0])
            self.sound('ding')
            self.go_idle(2.0, True)

    def update_sac(self, dt):
        sc, s = self.sac, self.s
        if sc.state == 'hang':
            if sc.seg is not None and not sc.seg.built:
                sc.state = 'fall'
                sc.vy = 0.0
            elif self.now >= sc.hatch_at:                           # éclosion !
                for _ in range(random.randint(8, 12)):
                    self.babies.append(Baby(sc.x + random.uniform(-6, 6), sc.y + random.uniform(-6, 6), s))
                self.sound('pop')
                self.sac = None
        else:
            sc.t += dt
            sc.vy += 900 * s * dt
            sc.y += sc.vy * dt
            if sc.t > 1.0:
                self.sac = None

    # --- mue : laisse une vieille peau accrochée
    def start_molt(self):
        self.molt_ok = self.now + 500
        self.molted = False
        self.set_state('molt')

    def st_molt(self, dt):
        sp, s = self.sp, self.s
        t = self.state_t
        sp.pulse = 0.05 * math.sin(t * 22) * min(1.0, t)
        sp.ang += math.cos(t * 30) * 0.12 * 30 * dt
        if t > 2.6 and not self.molted:
            self.molted = True
            self.exuviae.append([sp.x, sp.y, sp.ang, 0.0, [tuple(f_) for f_ in sp.feet], s])
            self.exuviae = self.exuviae[-3:]
            for q in range(3):
                self.hearts.append([sp.x + (q - 1) * 14 * s, sp.y - 30 * s - q * 6 * s, -q * 0.12])
            self.sound('ding')
        if t > 3.6:
            sp.pulse = 0.0
            self.molted = False
            self.go_idle(2.0, True)

    # --- sons
    def sound(self, name):
        self.snd.play(name)

    # --- menu du clic droit
    def menu_items(self):
        if self.menu_page == 'race':                         # onglet « Race » : choix de l'animal
            rows = [('Race (animal)', None)]
            for key, name in ANIMALS.items():
                if key in ANIMALS_READY:
                    rows.append((name + ('   (actuel)' if key == self.animal else ''), 'race:' + key))
                else:
                    rows.append((name + '   (en preparation)', None))
            rows.append(('<  Retour', 'back'))
            return rows
        top = []
        if self.menu_ctx == 'basket':                       # menu du panier : choisir la proie à sortir
            top = [('Sortir : une mouche', 'prey:fly'),
                   ('Sortir : un moustique', 'prey:mosquito'),
                   ('Sortir : un papillon', 'prey:butterfly')]
        return paged_menu(self.menu_page, self.animal, top + [
            ('Faim : %d%%' % int(self.hunger * 100), None),
            ('Race : ' + ANIMALS[self.animal] + '   >', 'race'),
            ('Espece : ' + SPECIES[self.sp.species]['name'], 'species'),
            ('Style mignon : ' + ('oui' if self.cute else 'non'), 'cute'),
            ('Faire la parade', 'show'),
            ('Dormir', 'sleep'),
            ('Se pendre au fil', 'dangle'),
            ('Se cacher', 'hide'),
            ('Se laver (rosee)', 'wash'),
            ('Taille +', 'size+'),
            ('Taille -', 'size-'),
            ('Son : ' + ('oui' if self.snd.on else 'coupe'), 'sound'),
            ('Volume + (%d %%)' % int(round(self.snd.volume * 100)), 'vol+'),
            ('Volume -', 'vol-'),
            ('Rosee : ' + ('oui' if self.dew_on else 'non'), 'dew'),
            ('2e araignee : ' + ('oui' if self.comp_on else 'non'), 'comp'),
            ('Reprendre' if self.paused else 'Pause', 'pause'),
            ('Quitter', 'quit'),
        ], self)

    def menu_geom(self):
        m = getattr(self, 'menu_m_lock', None) or clamp(self.s / 1.4, 0.9, 1.5)   # fige pendant qu'on regle la taille
        items = self.menu_items()
        w, rh = (290 if hasattr(self, 'life') else 250) * m, 26 * m
        h = rh * len(items) + 8 * m
        l, t, r, b = self.area
        x = clamp(self.menu_pos[0], l + 4, r - w - 4)
        y = clamp(self.menu_pos[1], t + 4, b - h - 4)
        return x, y, w, h, rh, m, items

    def over_menu(self):
        x, y, w, h, rh, m, items = self.menu_geom()
        return x <= self.cur[0] <= x + w and y <= self.cur[1] <= y + h

    def menu_row(self):
        x, y, w, h, rh, m, items = self.menu_geom()
        if not (x <= self.cur[0] <= x + w and y + 4 * m <= self.cur[1] <= y + h - 4 * m):
            return None
        return int((self.cur[1] - y - 4 * m) // rh)

    def open_menu(self, ctx='spider'):
        self.menu_ctx = ctx
        self.menu_page = 'out' if ctx == 'basket' else 'main'
        self.menu_pos = (self.cur[0] + 8, self.cur[1] + 8)
        self.menu_open = True
        self.sound('tap')

    def menu_action(self, act):
        sp = self.sp
        if act == 'tabclick':
            self.click_tab()
        elif act == 'bug':
            if getattr(self, 'bug_cb', None):
                self.bug_cb()
        elif act == 'launcher':
            PREFS['launcher'] = not PREFS.get('launcher', True)
            if self.cfg_save:
                self.cfg_save({'show_launcher': PREFS['launcher']})
            self.menu_page, self.menu_open = 'settings', True
        elif act == 'monitor':
            n = monitor_count()
            if n > 1 and self.cfg_save:
                if hasattr(self, 'life_save'):
                    self.life_save()
                self.cfg_save({'monitor': MON.get('index', 1) % n + 1})
                restart_soon()
                if self.quit_cb:
                    self.quit_cb()
        elif act == 'quality':
            self.aa_on = not self.aa_on
            if self.cfg_save:
                self.cfg_save({'aa': self.aa_on})
            self.menu_page, self.menu_open = 'settings', True
        elif act == 'update':
            UPDATER.start()
            self.menu_page, self.menu_open = 'settings', True
        elif act == 'show':
            self.dance_ok = 0.0
            {'peacock': self.start_dance, 'regius': self.start_regius_show, 'widow': self.start_hang,
             'tarantula': self.start_threat, 'wolf': self.start_unload, 'pholcus': self.start_whirl,
             'crab': self.start_ambush}[sp.species]()
        elif act == 'race':
            self.menu_page = 'race'
            self.menu_open = True                           # reste ouvert : on affiche l'onglet Race
        elif act in ('actions', 'out'):
            self.menu_page = act
            self.menu_open = True
        elif act == 'back':
            self.menu_page = 'animal' if self.menu_page in ('race', 'coat') else 'main'
            self.menu_open = True
        elif act.startswith('race:'):
            self.menu_page = 'main'
            if act[5:] != self.animal and self.switch_animal_cb:
                self.switch_animal_cb(act[5:])
                return
        elif act.startswith('prey:'):
            if len(self.flies) < 4:
                self.new_fly(kind=act[5:])
            else:
                self.bk.bounce = 1.0
        elif act == 'species':
            self.switch_species()
        elif act == 'cute':
            self.set_cute(not self.cute)
        elif act == 'sleep':
            self.start_sleep()
        elif act == 'dangle':
            self.start_dangle()
        elif act == 'hide':
            self.start_hide()
        elif act == 'wash':
            self.dew_on = True
            self.wash_ok = 0.0
            self.start_wash()
        elif act == 'size+':
            self.set_scale(self.s * 1.15)
        elif act == 'size-':
            self.set_scale(self.s / 1.15)
        elif act == 'sound':
            self.snd.on = not self.snd.on
            if self.snd.on:
                self.snd.play('ding')
        elif act in ('vol+', 'vol-'):
            self.snd.set_volume(self.snd.volume + (0.1 if act == 'vol+' else -0.1))
            if winsound is not None:
                self.snd.on = True
            self.snd.last = 0.0
            self.snd.play('ding')                       # aperçu du nouveau volume
            self.menu_open = True                       # le menu reste ouvert pour régler
        elif act == 'dew':
            self.dew_on = not self.dew_on
        elif act == 'comp':
            self.toggle_companion()
        elif act == 'pause':
            self.paused = not self.paused
        elif act == 'quit':
            if self.quit_cb:
                self.quit_cb()
        self.save_config()

    def set_cute(self, flag):
        self.cute = bool(flag)
        sp = self.sp
        sp.cute = self.cute
        sp.apply_species(sp.species, self.s)
        if self.comp is not None:
            self.comp.sp.cute = self.cute
            self.comp.sp.apply_species(self.comp.sp.species, self.s)
        if self.cute:
            for q in range(4):
                a = random.uniform(0, 2 * PI)
                self.sparks.append([sp.x + math.cos(a) * 20 * self.s, sp.y + math.sin(a) * 20 * self.s - 6 * self.s,
                                    random.uniform(-6, 6) * self.s, -16 * self.s, -q * 0.1, 'star'])

    def set_scale(self, new):
        new = clamp(new, 0.8, 3.2)
        sp = self.sp
        self.s = new
        sp.apply_species(sp.species, new)
        self.bk.s = new * 0.62
        if self.comp is not None:
            self.comp.s = new
            self.comp.sp.apply_species(self.comp.sp.species, new)

    # --- double-clic : saut périlleux
    def start_flip(self):
        self.flip_a0 = self.sp.ang
        self.flip_dir = random.choice((-1, 1))
        self.sound('boing')
        self.set_state('flip')

    def st_flip(self, dt):
        sp, s = self.sp, self.s
        u = clamp(self.state_t / 0.7, 0.0, 1.0)
        sp.z = 90 * s * math.sin(PI * u)
        sp.ang = self.flip_a0 + self.flip_dir * 2 * PI * (u * u * (3 - 2 * u))
        if u >= 1.0:
            sp.z = 0.0
            sp.ang = self.flip_a0
            self.hearts.append([sp.x, sp.y - 30 * s, 0.0])
            self.go_idle(1.0, True)

    # --- pointeur laser : le curseur s'agite, elle le poursuit et lui saute dessus
    def st_chase(self, dt):
        sp, s = self.sp, self.s
        if self.now - self.last_wig > 1.8:
            self.chase_ok = self.now + 4
            sp.z = 0.0
            return self.go_idle(1.0, True)
        cx, cy = self.cur
        if self.cp_phase == 0:
            d = self.steer(cx, cy, 340 * s, dt, turn=12)
            if d < 120 * s:
                self.cp_phase, self.cp_t = 1, 0.0
                self.jx0, self.jy0 = sp.x, sp.y
        elif self.cp_phase == 1:
            self.cp_t += dt
            if self.cp_t < 0.15:
                self.face(cx, cy, dt, 16)
                self.leap_to = (cx, cy)
                sp.x += random.uniform(-0.5, 0.5) * s
                return
            u = clamp((self.cp_t - 0.15) / 0.3, 0.0, 1.0)
            sp.x = lerp(self.jx0, self.leap_to[0], u)
            sp.y = lerp(self.jy0, self.leap_to[1], u)
            sp.z = 40 * s * math.sin(PI * u)
            if u >= 1.0:
                sp.z = 0.0
                self.cp_phase, self.cp_t = 2, 0.0
                self.sound('tap')
                if random.random() < 0.3:
                    self.hearts.append([sp.x, sp.y - 28 * s, 0.0])
        else:
            self.cp_t += dt
            if self.cp_t > 0.25:
                self.cp_phase = 0

    # --- cache-cache : elle se glisse hors de l'écran et ne montre que ses yeux
    def start_hide(self):
        sp, s = self.sp, self.s
        l, t, r, b = self.area
        cands = [('l', sp.x - l), ('r', r - sp.x), ('t', sp.y - t)]
        cands.sort(key=lambda c_: c_[1])
        e = random.choice(cands[:2])[0]
        if e == 'l':
            pt, out, ang = (l, random.uniform(t + 150, b - 150)), (-1.0, 0.0), 0.0
        elif e == 'r':
            pt, out, ang = (r, random.uniform(t + 150, b - 150)), (1.0, 0.0), PI
        else:
            pt, out, ang = (random.uniform(l + 150, r - 150), t), (0.0, -1.0), PI / 2
        self.hide_e, self.hide_pt, self.hide_out, self.hide_ang = e, pt, out, ang
        self.duck_until = 0.0
        self.set_state('hide_go')

    def st_hide_go(self, dt):
        s = self.s
        px, py = self.hide_pt
        ox, oy = self.hide_out
        d = self.steer(px - ox * 40 * s, py - oy * 40 * s, 170 * s, dt)
        if d < 8 * s:
            self.set_state('hide')

    def st_hide(self, dt):
        sp, s = self.sp, self.s
        px, py = self.hide_pt
        ox, oy = self.hide_out
        if self.now > self.duck_until and self.cdist() < 260 * s and self.cspeed > 80 and random.random() < dt * 1.2:
            self.duck_until = self.now + 1.6               # se baisse quand on approche
        if self.cdist() < 90 * s and self.cspeed > 500:    # Bouh !
            self.set_state('startle')
            return
        o = 30 * s if self.now < self.duck_until else 2.5 * s
        tx, ty = px + ox * o, py + oy * o
        k = min(1.0, dt * 7)
        sp.x += (tx - sp.x) * k
        sp.y += (ty - sp.y) * k
        sp.ang += clamp(angdiff(sp.ang, self.hide_ang), -8 * dt, 8 * dt)
        if self.state_t > 18 or self.paused:
            sp.x, sp.y = px - ox * 40 * s, py - oy * 40 * s
            self.go_idle(1.0, True)

    # --- se laisse pendre au bout d'un fil de soie
    def start_dangle(self):
        sp, s = self.sp, self.s
        l, t, r, b = self.area
        self.dg_x = clamp(sp.x + random.uniform(-200, 200), l + 80, r - 80)
        self.dg_depth = random.uniform(150, 270) * s
        self.dg_hang = random.uniform(3.5, 6.5)
        self.set_state('dg_go')

    def st_dg_go(self, dt):
        s = self.s
        t = self.area[1]
        d = self.steer(self.dg_x, t + 8 * s, 190 * s, dt)
        if d < 8 * s:
            self.sp.x, self.sp.y = self.dg_x, t + 8 * s
            self.set_state('dangle')

    def st_dangle(self, dt):
        sp, s = self.sp, self.s
        t0 = self.state_t
        D = self.dg_depth
        top = self.area[1] + 8 * s
        ease = lambda u_: u_ * u_ * (3 - 2 * u_)
        if t0 < 1.8:
            depth = D * ease(t0 / 1.8)
            head = PI / 2
        elif t0 < 1.8 + self.dg_hang:
            depth = D + 6 * s * math.sin((t0 - 1.8) * 3)
            head = PI / 2
        elif t0 < 3.6 + self.dg_hang:
            depth = D * (1 - ease((t0 - 1.8 - self.dg_hang) / 1.8))
            head = -PI / 2
        else:
            sp.x, sp.y = self.dg_x, top
            return self.go_idle(1.0, True)
        sway = 10 * s * math.sin(t0 * 1.7) * (depth / max(D, 1.0))
        sp.x = self.dg_x + sway
        sp.y = top + depth
        sp.ang = head + 0.25 * math.sin(t0 * 1.7)
        sp.splay = head > 0

    # --- changement d'espèce (clic droit sur le panier) + sauvegarde
    def switch_species(self):
        sp, s = self.sp, self.s
        new = next_species(sp.species)
        sp.apply_species(new, s)
        sp.threat = 0.0
        sp.hidden = False
        self.bk.bounce = 1.0
        if self.comp is not None:
            self.comp.sp.apply_species(next_species(new), s)
        for q in range(3):
            self.hearts.append([sp.x + (q - 1) * 16 * s, sp.y - 30 * s - q * 6 * s, -q * 0.12])
        if self.state in ('dance_go', 'dance', 'dance_end', 'rgo', 'rwave', 'rjump', 'pet', 'hang', 'threat', 'burrow',
                          'burrow_go', 'whirl', 'ambush', 'unload'):
            self.go_idle(0.5)
        self.dance_ok = self.now + 8
        if self.log:
            self.log('espece -> ' + new)
        self.save_config()

    def save_config(self):
        if self.cfg_save:
            try:
                self.cfg_save({'species': self.sp.species, 'bx': self.bk.x, 'by': self.bk.y, 'scale': self.s,
                               'sound': self.snd.on, 'volume': self.snd.volume, 'dew': self.dew_on,
                               'comp': self.comp_on, 'cute': self.cute, 'animal': 'spider'})
            except Exception:
                pass

    # --- caresses
    def st_pet(self, dt):
        sp, s = self.sp, self.s
        sp.happy = min(1.0, sp.happy + dt * 4)
        self.face(self.cur[0], self.cur[1], dt, 3)
        sp.ang += math.cos(self.now * 13) * 0.12 * 13 * dt         # frétille
        self.pet_heart_t += dt
        if self.pet_heart_t > 0.6:
            self.pet_heart_t = 0.0
            self.hearts.append([sp.x + random.uniform(-8, 8) * s, sp.y - 26 * s, 0.0])
            self.sound('chirp')
        self.pet_away = 0.0 if self.over_spider() else self.pet_away + dt
        if self.pet_away > 0.7:
            self.pet_ok = self.now + 1.0
            self.go_idle(1.0, True)

    # --- parade de la Phidippus regius : coucou de la patte, puis sauts autour du curseur
    def start_regius_show(self):
        s = self.s
        cx, cy = self.cur
        dx, dy = self.sp.x - cx, self.sp.y - cy
        d = max(1.0, math.hypot(dx, dy))
        l, t, r, b = self.area
        self.target = (clamp(cx + dx / d * 170 * s, l + 80 * s, r - 80 * s),
                       clamp(cy + dy / d * 170 * s, t + 80 * s, b - 80 * s))
        self.walk_speed = 130 * s
        self.set_state('rgo')

    def show_abort(self):
        self.dance_abort()

    def st_rgo(self, dt):
        d = self.steer(self.target[0], self.target[1], self.walk_speed, dt)
        if d < 10 * self.s or self.state_t > 6:
            self.set_state('rwave')
        elif self.cspeed > 1600 and self.cdist() < 250 * self.s:
            self.show_abort()

    def st_rwave(self, dt):
        sp, s = self.sp, self.s
        t = self.state_t
        sp.wave = min(1.0, t / 0.4)
        sp.dphase += dt * 14
        self.face(self.cur[0], self.cur[1], dt, 5)
        if self.cspeed > 1600 and self.cdist() < 250 * s:
            return self.show_abort()
        if t > 3.2:                                   # le coucou est fini
            self.hearts.append([sp.x, sp.y - 30 * s, 0.0])
            self.dance_ok = self.now + 35
            self.go_idle(2.0, True)

    def start_rjump(self):
        sp, s = self.sp, self.s
        l, t, r, b = self.area
        self.rj_ang += self.rj_dir * random.uniform(0.9, 1.4)
        rad = random.uniform(110, 150) * s
        tx = clamp(self.cur[0] + math.cos(self.rj_ang) * rad, l + 30, r - 30)
        ty = clamp(self.cur[1] + math.sin(self.rj_ang) * rad, t + 30, b - 30)
        self.jx0, self.jy0 = sp.x, sp.y
        self.leap_to = (tx, ty)
        self.rj_n -= 1
        self.set_state('rjump')

    def st_rjump(self, dt):
        sp, s = self.sp, self.s
        tx, ty = self.leap_to
        t = self.state_t
        if t < 0.2:                                   # s'accroupit
            self.face(tx, ty, dt, 14)
            sp.x += (self.jx0 - sp.x) * 0.5
            sp.y += (self.jy0 - sp.y) * 0.5
            return
        if t < 0.58:
            u = (t - 0.2) / 0.38
            sp.x = lerp(self.jx0, tx, u)
            sp.y = lerp(self.jy0, ty, u)
            sp.z = 55 * s * math.sin(PI * u)
            return
        sp.z = 0.0
        sp.x, sp.y = tx, ty
        self.face(self.cur[0], self.cur[1], dt, 12)
        if t > 0.72:
            if self.rj_n > 0:
                self.start_rjump()
            else:
                for q in range(3):
                    self.hearts.append([sp.x + (q - 1) * 14 * s, sp.y - 30 * s - q * 7 * s, -q * 0.15])
                self.dance_ok = self.now + 35
                self.go_idle(2.0, True)

    # --- la parade nuptiale du paon : la souris joue le rôle de la femelle
    def start_dance(self):
        s = self.s
        cx, cy = self.cur
        dx, dy = self.sp.x - cx, self.sp.y - cy
        d = max(1.0, math.hypot(dx, dy))
        l, t, r, b = self.area
        tx = clamp(cx + dx / d * 170 * s, l + 80 * s, r - 80 * s)
        ty = clamp(cy + dy / d * 170 * s, t + 80 * s, b - 80 * s)
        self.target = (tx, ty)
        self.walk_speed = 130 * s
        self.dance_dur = random.uniform(7, 10)
        self.set_state('dance_go')

    def dance_abort(self):
        self.dance_ok = self.now + 25
        self.sp.dance = 0.0
        self.flee_ang = math.atan2(self.sp.y - self.cur[1], self.sp.x - self.cur[0])
        self.flee_ok = self.now + 4
        self.set_state('flee')

    def st_dance_go(self, dt):
        d = self.steer(self.target[0], self.target[1], self.walk_speed, dt)
        if d < 10 * self.s or self.state_t > 6:
            self.set_state('dance')
        elif self.cspeed > 1600 and self.cdist() < 250 * self.s:
            self.dance_abort()

    def st_dance(self, dt):
        sp, s = self.sp, self.s
        t = self.state_t
        sp.dance = min(1.0, t / 0.6)
        sp.dphase += dt * 9
        self.face(self.cur[0], self.cur[1], dt, 5)
        px, py = -math.sin(sp.ang), math.cos(sp.ang)
        side = math.sin(t * 2.6)                      # petits pas de côté, façon crabe
        sp.x += px * side * 42 * s * dt + random.uniform(-0.5, 0.5) * s
        sp.y += py * side * 42 * s * dt + random.uniform(-0.5, 0.5) * s
        if self.cdist() > 120 * s and (t * 1.3) % 1.0 < 0.35:      # bonds vers la "femelle"
            sp.x += math.cos(sp.ang) * 70 * s * dt
            sp.y += math.sin(sp.ang) * 70 * s * dt
        self.heart_t += dt
        if self.heart_t > 0.8:
            self.heart_t = 0.0
            self.hearts.append([sp.x + random.uniform(-10, 10) * s, sp.y - 30 * s, 0.0])
        if self.cspeed > 1600 and self.cdist() < 250 * s:           # la femelle s'en va : vexée
            self.dance_abort()
        elif t > self.dance_dur:
            for q in range(4):
                self.hearts.append([sp.x + (q - 1.5) * 14 * s, sp.y - 30 * s - q * 8 * s, -q * 0.15])
            self.set_state('dance_end')

    def st_dance_end(self, dt):
        sp = self.sp
        sp.dance = max(0.0, sp.dance - dt * 2.0)
        sp.dphase += dt * 6
        if self.state_t > 0.7:
            self.dance_ok = self.now + 35
            self.go_idle(2.0, True)

    # --- saut de côté (araignée sauteuse) : accroupie, puis bond en arc
    def start_leap(self):
        sp, s = self.sp, self.s
        if sp.species == 'tarantula':                        # trop lourde pour sauter
            return self.start_walk(self.pick_target(), 70)
        l, t, r, b = self.area
        for _ in range(10):
            a = sp.ang + random.uniform(-0.8, 0.8)
            dist = random.uniform(130, 300) * s
            tx, ty = sp.x + math.cos(a) * dist, sp.y + math.sin(a) * dist
            if l + 20 < tx < r - 20 and t + 20 < ty < b - 20:
                break
        else:
            tx, ty = clamp(tx, l + 20, r - 20), clamp(ty, t + 20, b - 20)
        self.jx0, self.jy0 = sp.x, sp.y
        self.leap_to = (tx, ty)
        self.set_state('leap')

    def st_leap(self, dt):
        sp, s = self.sp, self.s
        tx, ty = self.leap_to
        t = self.state_t
        if t < 0.28:                                  # s'accroupit, vise
            self.face(tx, ty, dt, 14)
            sp.x += (self.jx0 - sp.x) * 0.5 + random.uniform(-0.5, 0.5) * s
            sp.y += (self.jy0 - sp.y) * 0.5 + random.uniform(-0.5, 0.5) * s
            return
        u = clamp((t - 0.28) / 0.42, 0.0, 1.0)
        sp.x = lerp(self.jx0, tx, u)
        sp.y = lerp(self.jy0, ty, u)
        sp.z = 70 * s * math.sin(PI * u)
        if u >= 1.0:
            sp.z = 0.0
            self.go_idle(random.uniform(0.6, 2.0))

    def check_flee(self):
        s = self.s
        spn = self.sp.species
        if spn == 'tarantula':                                # elle ne fuit pas : elle menace
            if self.now > self.flee_ok and self.cspeed > 600 and self.cdist() < 170 * s:
                self.flee_ok = self.now + 5
                self.start_threat()
            return
        if spn == 'pholcus':                                  # tournoie sur elle-même
            if self.now > self.flee_ok and self.cspeed > 1000 and self.cdist() < 150 * s:
                self.flee_ok = self.now + 4
                self.start_whirl()
            return
        if spn in ('widow', 'crab'):                          # tient bon
            return
        if self.now > self.flee_ok and self.cspeed > 1400 and self.cdist() < 130 * s:
            self.flee_ang = math.atan2(self.sp.y - self.cur[1], self.sp.x - self.cur[0])
            self.flee_ok = self.now + 4
            self.set_state('flee')

    # --- états
    def st_idle(self, dt):
        if self.look:
            self.face(self.cur[0], self.cur[1], dt)
        elif self.cdist() < 450 * self.s and self.cspeed < 900:   # suit le curseur du regard
            self.face(self.cur[0], self.cur[1], dt, 1.8)
        if self.state_t > self.idle_for:
            self.decide()
        self.check_flee()

    def st_walk(self, dt):
        d = self.steer(self.target[0], self.target[1], self.walk_speed, dt)
        if d > 220 * self.s and random.random() < dt * 0.25:
            return self.start_leap()
        if d < 8 * self.s:
            look, idle = self.next_look, self.next_idle
            self.next_look, self.next_idle = False, None
            self.go_idle(idle or random.uniform(1, 4) if not look else random.uniform(3, 7), look)
        self.check_flee()

    def st_weave(self, dt):
        sp = self.sp
        s = self.s
        seg = self.web.next_unbuilt()
        if seg is None:
            self.go_idle(random.uniform(3, 6))
            return
        if self.sub == 'move':
            d = self.steer(seg.a[0], seg.a[1], 160 * s, dt, turn=10)
            if d < 5 * s:
                sp.x, sp.y = seg.a
                self.sub = 'draw'
                seg.prog = 0.0
        else:
            seg.prog = min(1.0, seg.prog + 150 * s * dt / seg.len)
            nx, ny = seg.point(seg.prog)
            if math.hypot(nx - sp.x, ny - sp.y) > 0.01:
                want = math.atan2(ny - sp.y, nx - sp.x)
                sp.ang += clamp(angdiff(sp.ang, want), -12 * dt, 12 * dt)
            sp.x, sp.y = nx, ny
            if seg.prog >= 1.0:
                seg.built = True
                self.sub = 'move'
        self.check_flee()

    def st_flee(self, dt):
        sp = self.sp
        sp.ang += clamp(angdiff(sp.ang, self.flee_ang), -14 * dt, 14 * dt)
        sp.x += math.cos(sp.ang) * 500 * self.s * dt
        sp.y += math.sin(sp.ang) * 500 * self.s * dt
        if self.state_t > 0.6:
            self.go_idle(1.5)

    def st_startle(self, dt):
        sp = self.sp
        t = self.state_t
        sp.z = 16 * self.s * math.sin(PI * min(1.0, t / 0.35))
        self.face(self.cur[0], self.cur[1], dt, 12)
        if t > 0.55:
            sp.z = 0
            if self.web.missing():
                self.weave_force = self.now + 20
                self.start_weave()
            else:
                self.go_idle(1.0, True)

    def st_attack(self, dt):
        s = self.s
        sp = self.sp
        cx, cy = self.cur
        self.steer(cx, cy, 760 * s, dt, turn=16)
        if self.cdist() < 200 * s or self.state_t > 2.2:
            self.jx0, self.jy0 = sp.x, sp.y
            sp.elev = 0.0
            self.set_state('jump')

    def cling_pos(self):
        s = self.s
        return (self.cur[0] + 9 * s + 1.6 * s * math.sin(self.now * 37),
                self.cur[1] + 13 * s + 1.6 * s * math.cos(self.now * 41))

    def st_jump(self, dt):
        s = self.s
        sp = self.sp
        t = clamp(self.state_t / 0.42, 0.0, 1.0)
        tx, ty = self.cling_pos()
        sp.x = lerp(self.jx0, tx, t)
        sp.y = lerp(self.jy0, ty, t)
        sp.z = 110 * s * math.sin(PI * t)
        sp.ang = math.atan2(ty - self.jy0, tx - self.jx0)
        if t >= 1.0:
            sp.z = 0
            self.shake = 0.0
            self.cling_end = random.uniform(*((14, 22) if self.sp.species == 'widow' else (9, 14)))
            self.set_state('cling')

    def st_cling(self, dt):
        sp = self.sp
        sp.x, sp.y = self.cling_pos()
        sp.ang = math.atan2(-13, -9) + 0.18 * math.sin(self.now * 18)
        if self.cspeed > 1700:
            self.shake += dt * self.cspeed / 1700
        else:
            self.shake = max(0.0, self.shake - dt * 0.6)
        forced = self.shake > 1.0
        if forced or self.state_t > self.cling_end:
            a = random.uniform(0, 2 * PI)
            v = 650 if forced else 300
            self.fvx, self.fvy = math.cos(a) * v * self.s, math.sin(a) * v * self.s
            self.fdur = 0.5 if forced else 0.38
            self.flinging = forced
            self.no_attack_until = self.now + (10 if forced else 6)
            self.weave_force = self.now + 40
            self.cut_times = []
            self.set_state('fling')

    def st_fling(self, dt):
        sp = self.sp
        t = clamp(self.state_t / self.fdur, 0.0, 1.0)
        sp.x += self.fvx * dt * (1 - t)
        sp.y += self.fvy * dt * (1 - t)
        sp.z = 70 * self.s * math.sin(PI * t)
        if self.flinging:
            sp.ang += 16 * dt
        l, tp, r, b = self.area
        sp.x = clamp(sp.x, l + 10, r - 10)
        sp.y = clamp(sp.y, tp + 10, b - 10)
        if t >= 1.0:
            sp.z = 0
            self.go_idle(2.5 if self.flinging else 1.2)

    # --- rendu
    def web_jit(self):
        return any(f.state == 'stuck' and f.wrap < 1.0 for f in self.flies)

    def web_sig(self):
        """Change seulement quand la toile (ou sa rosée) doit être redessinée."""
        jit = self.web_jit()
        return (tuple(sg.built for sg in self.web.segs), self.dew_on,
                int(self.now * 4) if self.dew_on else 0, int(self.now * 40) if jit else -1)

    def slider_start(self, key):
        self.slider_key = key
        self.menu_m_lock = self.menu_geom()[5]
        self.slider_set()

    def slider_track(self):
        x, y, w, h, rh, m, items = self.menu_geom()
        return x + w * 0.30, x + w - 58 * m

    def slider_set(self):
        a, b = self.slider_track()
        f = clamp((self.cur[0] - a) / max(1.0, b - a), 0.0, 1.0)
        if self.slider_key == 'vol':
            self.snd.set_volume(0.1 + 0.9 * f)
            if winsound is not None:
                self.snd.on = True
        else:
            self.set_scale(0.8 + 2.4 * f)

    def slider_tick(self, btn):
        key = getattr(self, 'slider_key', None)
        if not key:
            return
        if btn and self.menu_open:
            self.slider_set()
            return
        self.slider_key, self.menu_m_lock = None, None           # bouton relache : on garde la valeur
        if key == 'vol':
            self.snd.play('pop', force=True)                     # apercu du nouveau volume
        self.save_config()

    def click_tab(self):
        keys = [k for k, _ in menu_tabs(self.animal)]
        x, y, w, h, rh, m, items = self.menu_geom()
        i = int((self.cur[0] - x - 3) // ((w - 6) / len(keys)))
        self.menu_page = keys[int(clamp(i, 0, len(keys) - 1))]
        self.menu_open = True

    def draw_menu(self, c):
        if not self.menu_open:
            return
        x, y, w, h, rh, m, items = self.menu_geom()
        c.create_rectangle(x + 3, y + 3, x + w + 3, y + h + 3, fill='#000000', stipple='gray50', outline='')
        c.create_rectangle(x, y, x + w, y + h, fill='#26232b', outline='#8f858b', width=2)
        hov = self.menu_row()
        for i, (label, act) in enumerate(items):
            ry = y + 4 * m + i * rh
            if label == '\x00tabs':                                  # bande d'onglets
                tabs = menu_tabs(self.animal)
                cur_key = menu_active(self.menu_page, self.animal)
                cw = (w - 6) / len(tabs)
                for k, (key, name) in enumerate(tabs):
                    tx0 = x + 3 + k * cw
                    hot = (i == hov and tx0 <= self.cur[0] < tx0 + cw)
                    fill = '#7a62a8' if key == cur_key else ('#4a3f5e' if hot else '#322e3a')
                    c.create_rectangle(tx0 + 1, ry + 1, tx0 + cw - 1, ry + rh - 1, fill=fill, outline='')
                    c.create_text(tx0 + cw / 2, ry + rh / 2, text=name, fill='#ffffff' if (key == cur_key or hot) else '#b9b2c2',
                                  font=('Segoe UI', -int(12 * m), 'bold'))
                continue
            if label.startswith('G:'):                                # jauge : G:nom:valeur:inverse
                _, name, val, inv = label.split(':')
                v = clamp(float(val), 0.0, 1.0)
                good = 1.0 - v if inv == '1' else v
                col = '#6bcf7f' if good > 0.6 else ('#f0c24a' if good > 0.3 else '#ee5a5a')
                cy = ry + rh / 2
                c.create_text(x + 12 * m, cy, text=name, anchor='w', fill='#e6e0ee', font=('Segoe UI', -int(13 * m)))
                bx0, bx1 = x + w * 0.36, x + w - 14 * m
                c.create_rectangle(bx0, cy - 6 * m, bx1, cy + 6 * m, fill='#151318', outline='#6a6475')
                if v > 0.01:
                    c.create_rectangle(bx0 + 1, cy - 5 * m, bx0 + 1 + (bx1 - bx0 - 2) * v, cy + 5 * m, fill=col, outline='')
                continue
            if label.startswith('S:'):                                # curseur : S:nom:valeur:texte
                _, name, val, txt = label.split(':', 3)
                v = clamp(float(val), 0.0, 1.0)
                cy = ry + rh / 2
                drag = getattr(self, 'slider_key', None) == act[7:]
                if i == hov or drag:
                    c.create_rectangle(x + 3, ry, x + w - 3, ry + rh, fill='#3a3346', outline='')
                c.create_text(x + 12 * m, cy, text=name, anchor='w', fill='#ffffff', font=('Segoe UI', -int(14 * m), 'bold'))
                bx0, bx1 = self.slider_track()
                kx = bx0 + (bx1 - bx0) * v
                c.create_rectangle(bx0, cy - 2.5 * m, bx1, cy + 2.5 * m, fill='#151318', outline='#6a6475')
                c.create_rectangle(bx0, cy - 2.5 * m, kx, cy + 2.5 * m, fill='#9d84d0', outline='')
                kr = (8 if drag else 7) * m
                c.create_oval(kx - kr, cy - kr, kx + kr, cy + kr, fill='#ffffff', outline='#7a62a8', width=2)
                c.create_text(x + w - 10 * m, cy, text=txt, anchor='e', fill='#e6e0ee', font=('Segoe UI', -int(12 * m), 'bold'))
                continue
            if act and i == hov:
                c.create_rectangle(x + 3, ry, x + w - 3, ry + rh, fill='#5a4a72', outline='')
            c.create_text(x + 12 * m, ry + rh / 2, text=label, anchor='w',
                          fill='#ffffff' if act else '#b9b2c2', font=('Segoe UI', -int(14 * m), 'bold' if act else 'normal'))

    def draw(self, c, static=True):
        if static:
            self.web.draw(c, self.dew_on, self.now, self.web_jit(), 'static')
        self.web.draw(c, False, self.now, False, 'dyn')
        for ex in self.exuviae:
            draw_exuvia(c, ex)
        if self.sac is not None:
            draw_sac(c, self.sac, self.now, self.s, self.sac.state == 'hang' and self.sac.hatch_at - self.now < 8)
        for bb in self.babies:
            draw_baby(c, bb)
        self.bk.draw(c, self.hover_bk or self.bk_drag)
        for f in self.flies:
            draw_fly(c, f)
        st = self.state
        sp = self.sp
        if st == 'wrap' and self.fly_ok():                    # fil de soie vers la proie
            f = self.target_fly
            if sp.species == 'pholcus':                       # jets de soie
                rx, ry = sp.loc(22 * self.s, 0)
                for _ in range(3):
                    jx, jy = random.uniform(-4, 4) * self.s, random.uniform(-4, 4) * self.s
                    c.create_line(rx + 1, ry + 1, f.x + jx + 1, f.y + jy + 1, fill=WEB_SHADOW, width=1)
                    c.create_line(rx, ry, f.x + jx, f.y + jy, fill=WEB_LIGHT, width=1)
            else:
                rx, ry = sp.loc(-20 * self.s, 0)
                for off, col in ((1, WEB_SHADOW), (0, WEB_LIGHT)):
                    c.create_line(rx + off, ry + off, f.x + off, f.y + off, fill=col, width=1)
        if sp.species == 'tarantula':                         # le terrier
            bx, by = self.burrow_pt
            r_ = 14 * sp.s
            c.create_oval(bx - r_ * 1.3, by - r_ * 0.85, bx + r_ * 1.3, by + r_ * 0.85, fill='#4b3b2c', outline='#2a1f16', width=2)
            c.create_oval(bx - r_, by - r_ * 0.62, bx + r_, by + r_ * 0.62, fill='#120c08', outline='')
        if self.comp is not None:
            self.comp.sp.draw(c, False, None)
        angry = st in ('attack', 'jump', 'cling', 'fling')
        alert = '#ff3030' if angry and st != 'fling' else ('#ffb020' if st == 'startle' else None)
        if st == 'dangle' or (st == 'dg_go' and False):       # fil de soie du haut de l'écran
            top = self.area[1] + 8 * self.s
            rx, ry = sp.loc(-20 * self.s, 0)
            for off, col in ((1, WEB_SHADOW), (0, WEB_LIGHT)):
                c.create_line(self.dg_x + off, top + off, rx + off, ry + off, fill=col, width=1)
        if not sp.hidden:
            sp.draw(c, angry, alert)
        for h in self.hearts:
            if h[2] >= 0:
                c.create_text(h[0], h[1], text='\u2665', fill='#ff5c93',
                              font=('Segoe UI Symbol', -int(20 * self.s), 'bold'))
        for z in self.zzz:
            fs = -int((9 + z[2] * 7) * self.s)
            c.create_text(z[0] + 1, z[1] + 1, text='Z', fill='#000000', font=('Segoe UI', fs, 'bold'))
            c.create_text(z[0], z[1], text='Z', fill='#ffffff', font=('Segoe UI', fs, 'bold'))
        if self.hunger > 0.7 and st in ('idle', 'walk', 'weave') and (self.now % 9) < 2.5:
            s_ = self.s
            bx, by = sp.x + 28 * s_, sp.y - 36 * s_
            c.create_oval(sp.x + 9 * s_, sp.y - 14 * s_, sp.x + 13 * s_, sp.y - 10 * s_, fill='#ffffff', outline='#777777')
            c.create_oval(sp.x + 14 * s_, sp.y - 22 * s_, sp.x + 20 * s_, sp.y - 16 * s_, fill='#ffffff', outline='#777777')
            c.create_oval(bx - 16 * s_, by - 12 * s_, bx + 16 * s_, by + 12 * s_, fill='#ffffff', outline='#777777', width=2)
            ghost = Fly(bx, by, -0.6, s_ * 0.9)
            ghost.phase = 0.8
            draw_fly(c, ghost)
        if st == 'wash':                                     # la goutte qui rétrécit
            r_ = max(2.0, 1.1 * self.s) * 1.6 * max(0.0, 1.0 - self.state_t / 1.2)
            if r_ > 0.5:
                c.create_oval(self.wash_pt[0] - r_, self.wash_pt[1] - r_, self.wash_pt[0] + r_, self.wash_pt[1] + r_,
                              fill='#d7ecff', outline='#6f9fc6')
        for sk in self.sparks:
            if sk[4] < 0:
                continue
            if sk[5] == 'drop':
                r_ = 1.5 * self.s
                c.create_oval(sk[0] - r_, sk[1] - r_, sk[0] + r_, sk[1] + r_, fill='#cfe9ff', outline='#6fa0c8')
            elif sk[5] == 'hair':
                r_ = 1.3 * self.s
                c.create_oval(sk[0] - r_, sk[1] - r_, sk[0] + r_, sk[1] + r_, fill='#c8501e', outline='')
            else:
                c.create_text(sk[0], sk[1], text='\u2726', fill='#ffe066',
                              font=('Segoe UI Symbol', -int(18 * self.s * (1.2 - sk[4] * 0.5)), 'bold'))
        if self.paused:
            c.create_text(sp.x + 1, sp.y - 38 * self.s + 1, text='Pause', fill='#000000', font=('Segoe UI', -int(14 * self.s), 'bold'))
            c.create_text(sp.x, sp.y - 38 * self.s, text='Pause', fill='#ffffff', font=('Segoe UI', -int(14 * self.s), 'bold'))
        self.draw_menu(c)



# ============================================================================ LE CHAT (vue de profil)
COATS = {
    'tabby': dict(name='Tigre roux', base='#f2a650', dark='#c7772b', belly='#ffe9c8', paw='#fff1da', muzzle='#fff1da',
                  ol='#6b3510', eye='#6cc26a', pat='tabby', inner='#ffb3c1'),
    'black': dict(name='Noir', base='#3c3c48', dark='#2a2a34', belly='#4c4c5a', paw=None, muzzle=None,
                  ol='#0d0d12', eye='#f5d442', pat=None, inner='#a86a7a'),
    'white': dict(name='Blanc', base='#fbf9f6', dark='#d8cfc9', belly='#ffffff', paw=None, muzzle=None,
                  ol='#8a7e78', eye='#6fb0ee', pat=None, inner='#ffb3c1'),
    'siamese': dict(name='Siamois', base='#f3e6d0', dark='#6a4a3a', belly='#fbf2e2', paw=None, muzzle=None,
                    ol='#4a3226', eye='#5aa8f2', pat='points', inner='#8a6a5a'),
    'tuxedo': dict(name='Smoking', base='#2e2e38', dark='#16161e', belly='#ffffff', paw='#ffffff', muzzle='#ffffff',
                   ol='#0d0d12', eye='#f5d442', pat='tux', inner='#ffb3c1'),
    'calico': dict(name='Ecaille', base='#fbf5ee', dark='#d8c9b8', belly='#ffffff', paw=None, muzzle=None,
                   ol='#6a5a50', eye='#62bd72', pat='calico', inner='#ffb3c1', p1='#ee9a3e', p2='#34343e'),
}
COAT_ORDER = list(COATS)
DOG_COATS = {
    'golden': dict(name='Golden', base='#eab45e', dark='#c98a34', ear='#cf9440', belly='#f7d99c', paw='#f3cb88', muzzle='#f7d99c',
                   ol='#5e3a12', eye='#8a5a2a', pat=None, inner='#ffb3c1'),
    'beagle': dict(name='Beagle', base='#f7f0e4', dark='#9a5a26', ear='#9a5a26', belly='#ffffff', paw='#ffffff', muzzle='#ffffff',
                   ol='#4a2a12', eye='#8a5a2a', pat='saddle', inner='#ffb3c1'),
    'dalmatian': dict(name='Dalmatien', base='#fbfaf8', dark='#2a2a30', ear='#2e2e34', belly='#ffffff', paw='#ffffff', muzzle='#ffffff',
                      ol='#44444e', eye='#8a5a2a', pat='spots', inner='#ffb3c1'),
    'husky': dict(name='Husky', base='#9aa3b0', dark='#4f5866', ear='#5a6372', belly='#ffffff', paw='#ffffff', muzzle='#ffffff',
                  ol='#2e3440', eye='#6fb0ee', pat='saddle', inner='#ffb3c1'),
    'chocolate': dict(name='Chocolat', base='#7a5238', dark='#4a2e1e', ear='#5a3a26', belly='#8c6244', paw=None, muzzle='#9a7050',
                      ol='#24140a', eye='#a8743a', pat=None, inner='#ffb3c1'),
}
DOG_ORDER = list(DOG_COATS)
GOAT_COATS = {
    'caramel': dict(name='Caramel', base='#c58a4a', dark='#6b4222', ear='#b07a3f', belly='#e6c79a', paw='#2d2326', muzzle='#e3c18f',
                    ol='#4a2a12', eye='#e8b832', pat='stripe', inner='#ffb3c1', beard='#6b4222', horn='#e0d5b8', socks=True),
    'blanche': dict(name='Blanche', base='#f6f3ec', dark='#cfc7b8', ear='#efe8dc', belly='#ffffff', paw='#7a7078', muzzle='#ffffff',
                    ol='#6a6258', eye='#e8c040', pat=None, inner='#ffb3c1', beard='#ece6da', horn='#d9cdb0', socks=False),
    'noire': dict(name='Noire', base='#34323a', dark='#1a191e', ear='#2a282f', belly='#4a4852', paw='#17161a', muzzle='#55525c',
                  ol='#0c0c10', eye='#e0b030', pat=None, inner='#ffb3c1', beard='#1a191e', horn='#9a9484', socks=False),
    'pie': dict(name='Pie', base='#f6f3ec', dark='#8a5630', ear='#8a5630', belly='#ffffff', paw='#3a2e30', muzzle='#ffffff',
                ol='#4a3a2c', eye='#e8b832', pat='patch', inner='#ffb3c1', beard='#fbf7ef', horn='#d9cdb0', socks=False),
    'grise': dict(name='Grise', base='#a79e90', dark='#403c38', ear='#8f8678', belly='#d6cfc2', paw='#26201f', muzzle='#cfc7b8',
                  ol='#2e2a28', eye='#d8a830', pat='stripe', inner='#ffb3c1', beard='#403c38', horn='#cfc4a8', socks=True),
}
GOAT_ORDER = list(GOAT_COATS)
FERRET_COATS = {
    'sable': dict(name='Sable', base='#8a6238', dark='#3b2a1e', head='#cdb089', ear='#6a4a2c', belly='#c9ac80', paw='#3b2a1e', muzzle='#e9d9b8',
                  mask='#3b2a1e', tail='#4a3322', nose='#b4707a', ol='#2e1e12', eye='#140c0a', pat=None, inner='#ffb3c1', socks=True),
    'albinos': dict(name='Albinos', base='#f6eee4', dark='#e0d2c4', head='#fbf5ec', ear='#f2d4cc', belly='#fff8ee', paw='#f0e4da', muzzle='#ffffff',
                    mask=None, tail='#f6eee4', nose='#f09aa8', ol='#9a8478', eye='#c4384c', pat=None, inner='#ffb3c1', socks=False),
    'panda': dict(name='Panda', base='#5c4230', dark='#2e2018', head='#f6f0e6', ear='#f2e8dc', belly='#e8dcc6', paw='#f4ece0', muzzle='#ffffff',
                  mask=None, tail='#5c4230', nose='#e29aa0', ol='#2e2018', eye='#140c0a', pat=None, inner='#ffb3c1', socks=False),
    'argente': dict(name='Argente', base='#9c9aa2', dark='#4a4850', head='#cfccd2', ear='#8a8890', belly='#d9d6dc', paw='#4a4850', muzzle='#eceaee',
                    mask='#5a5860', tail='#74727a', nose='#b88a94', ol='#34323a', eye='#140c0a', pat=None, inner='#ffb3c1', socks=True),
    'cannelle': dict(name='Cannelle', base='#b87a44', dark='#6a3c1e', head='#e0c08e', ear='#a06a38', belly='#e6c898', paw='#8a5428', muzzle='#f1e0bc',
                     mask='#8a5428', tail='#9a5e30', nose='#c47c82', ol='#4a2a12', eye='#1a0e0a', pat=None, inner='#ffb3c1', socks=False),
}
FERRET_ORDER = list(FERRET_COATS)

# poses (unités u, y vers le haut = négatif) : épaule, hanche, tête, queue, corps, cambrure, pas, pieds fixes
POSES = {
    'stand': dict(sx=9, sy=-19, hx=-8, hy=-19, hdx=19, hdy=-33, ta=-2.2, curl=-0.12, amp=0.16, bl=1.0, bt=1.0, arc=0.0,
                  gait=1.0, feet=((8, 0), (6, 0), (-9, 0), (-11, 0))),
    'sit': dict(sx=5, sy=-27, hx=-9, hy=-12, hdx=7, hdy=-43, ta=3.0, curl=0.3, amp=0.07, bl=0.95, bt=1.0, arc=0.0,
                gait=0.0, feet=((9, 0), (13, 0), (0, 0), (4, 0))),
    'loaf': dict(sx=8, sy=-14, hx=-11, hy=-10, hdx=19, hdy=-22, ta=3.1, curl=0.35, amp=0.05, bl=1.0, bt=1.12, arc=0.0,
                 gait=0.0, feet=((17, 0), (20, 0), (-3, 0), (1, 0))),
    'sleep': dict(sx=4, sy=-11, hx=-7, hy=-10, hdx=12, hdy=-10, ta=3.1, curl=0.5, amp=0.03, bl=0.8, bt=1.28, arc=0.0,
                  gait=0.0, feet=((11, 0), (14, 0), (-3, 0), (0, 0))),
    'crouch': dict(sx=11, sy=-12, hx=-9, hy=-21, hdx=24, hdy=-17, ta=3.0, curl=0.0, amp=0.4, bl=1.0, bt=1.0, arc=0.0,
                   gait=0.0, feet=((19, 0), (22, 0), (-11, 0), (-7, 0))),
    'pounce': dict(sx=11, sy=-19, hx=-12, hy=-19, hdx=26, hdy=-24, ta=3.4, curl=0.05, amp=0.1, bl=1.1, bt=0.92, arc=0.0,
                   gait=0.0, feet=((31, -14), (27, -9), (-31, -12), (-27, -8))),
    'air': dict(sx=9, sy=-19, hx=-8, hy=-19, hdx=19, hdy=-33, ta=-1.9, curl=-0.1, amp=0.2, bl=1.0, bt=1.0, arc=0.0,
                gait=0.0, feet=((17, -8), (13, -4), (-16, -8), (-12, -4))),
    'arch': dict(sx=7, sy=-25, hx=-7, hy=-25, hdx=17, hdy=-30, ta=-1.57, curl=0.0, amp=0.05, bl=1.0, bt=1.08, arc=6.0,
                 gait=0.0, feet=((8, 0), (6, 0), (-8, 0), (-10, 0))),
    'stretch': dict(sx=15, sy=-9, hx=-10, hy=-27, hdx=26, hdy=-8, ta=-2.4, curl=-0.1, amp=0.1, bl=1.05, bt=1.0, arc=0.0,
                    gait=0.0, feet=((25, 0), (29, 0), (-10, 0), (-14, 0))),
    'hang': dict(sx=2, sy=-27, hx=-2, hy=-13, hdx=3, hdy=-42, ta=1.75, curl=0.0, amp=0.12, bl=0.9, bt=1.0, arc=0.0,
                 gait=0.0, feet=((6, -3), (9, -6), (-4, -1), (-7, -4))),
    'scratch': dict(sx=4, sy=-41, hx=-5, hy=-14, hdx=9, hdy=-53, ta=2.9, curl=0.2, amp=0.2, bl=0.95, bt=0.95, arc=0.0,
                    gait=0.0, feet=((18, -36), (16, -31), (-4, 0), (0, 0))),
    'eat_low': dict(sx=14, sy=-16, hx=-10, hy=-22, hdx=27, hdy=-9, ta=3.0, curl=0.15, amp=0.12, bl=1.0, bt=1.0, arc=0.0,
                    gait=0.0, feet=((19, 0), (22, 0), (-9, 0), (-5, 0))),
    'rub': dict(sx=9, sy=-19, hx=-8, hy=-19, hdx=21, hdy=-30, ta=-1.57, curl=0.2, amp=0.1, bl=1.0, bt=1.0, arc=0.0,
                gait=0.0, feet=((10, 0), (8, 0), (-10, 0), (-12, 0))),
    'edge_sleep': dict(sx=5, sy=-12, hx=-9, hy=-10, hdx=14, hdy=-12, ta=3.1, curl=0.45, amp=0.04, bl=0.9, bt=1.22, arc=0.0,
                       gait=0.0, feet=((20, 11), (17, 9), (-4, 0), (0, 0))),
    'peek': dict(sx=8, sy=-17, hx=-10, hy=-15, hdx=22, hdy=-11, ta=3.0, curl=0.3, amp=0.2, bl=1.0, bt=1.0, arc=0.0,
                 gait=0.0, feet=((24, 12), (21, 10), (-9, 0), (-5, 0))),
    'knead': dict(sx=9, sy=-15, hx=-11, hy=-10, hdx=20, hdy=-19, ta=3.0, curl=0.3, amp=0.12, bl=1.0, bt=1.12, arc=0.0,
                  gait=0.0, feet=((16, 0), (19, 0), (-3, 0), (1, 0))),
}


POSES['rim_hide'] = dict(sx=2, sy=-27, hx=-2, hy=-14, hdx=3, hdy=-14, ta=1.75, curl=0.0, amp=0.1, bl=0.9, bt=1.0, arc=0.0,
                          gait=0.0, feet=((4, -34.5), (7, -34.5), (-4, -1), (-7, -1)))
POSES['rim_peek'] = dict(POSES['rim_hide'], hdy=-46)
POSES['beg'] = dict(sx=4, sy=-32, hx=-9, hy=-12, hdx=7, hdy=-49, ta=3.0, curl=0.3, amp=0.1, bl=0.95, bt=1.0, arc=0.0,
                    gait=0.0, feet=((13, -22), (16, -24), (0, 0), (4, 0)))


def _dp(base, **kw):
    d = {k: (v if k != 'feet' else tuple(tuple(f) for f in v)) for k, v in POSES[base].items()}
    d.update(kw)
    return d


DOG_POSES = dict(POSES)
DOG_POSES.update({
    'stand': _dp('stand', sx=10, sy=-20, hx=-9, hy=-20, hdx=22, hdy=-34, ta=-2.45, curl=0.2, amp=0.18, bl=1.08),
    'sit': _dp('sit', sy=-30, hdx=8, hdy=-47, ta=2.95, curl=0.08, amp=0.1),
    'loaf': _dp('loaf', sy=-17, hdx=22, hdy=-27, ta=3.0, curl=0.1, amp=0.1, feet=((21, 0), (25, 0), (-3, 0), (1, 0))),
    'sleep': _dp('sleep', hdx=18, hdy=-9, ta=3.05, curl=0.2, bl=0.85, bt=1.2, feet=((19, 0), (23, 0), (-2, 0), (2, 0))),
    'beg': dict(sx=4, sy=-33, hx=-10, hy=-12, hdx=7, hdy=-51, ta=2.9, curl=0.1, amp=0.1, bl=0.95, bt=1.0, arc=0.0,
                gait=0.0, feet=((14, -24), (17, -26), (0, 0), (4, 0))),
    'bark': _dp('stand', sx=11, sy=-21, hdx=24, hdy=-39, ta=-2.3, curl=0.2, amp=0.25),
    'bow': _dp('stretch', ta=-2.15, curl=0.25, amp=0.3),
    'dig': _dp('eat_low', hdx=25, hdy=-14, ta=-2.4, curl=0.2, amp=0.25, feet=((19, 0), (22, 0), (-9, 0), (-5, 0))),
    'sniff': _dp('stand', sx=11, sy=-19, hdx=28, hdy=-20, ta=-2.4, curl=0.2, amp=0.18),
})

GOAT_POSES = dict(DOG_POSES)
GOAT_POSES.update({
    'stand': _dp('stand', sx=9, sy=-16, hx=-9, hy=-16, hdx=21, hdy=-29, ta=-1.85, curl=0.0, amp=0.1, bl=1.0, bt=1.12),
    'sit': _dp('sit', sy=-24, hdx=9, hdy=-40, ta=-1.7, curl=0.0, amp=0.06, bt=1.1),
    'loaf': _dp('loaf', sy=-13, hy=-9, hdx=21, hdy=-25, ta=-1.7, curl=0.0, amp=0.05, bt=1.12,
                feet=((18, 0), (21, 0), (-3, 0), (1, 0))),
    'sleep': _dp('sleep', hdx=17, hdy=-9, ta=-1.6, curl=0.0, bl=0.85, bt=1.22, feet=((17, 0), (20, 0), (-3, 0), (0, 0))),
    'beg': dict(DOG_POSES['beg'], sy=-31, hdy=-47, ta=-1.5, curl=0.0, bt=1.1),
    'bark': _dp('stand', sx=10, sy=-17, hdx=24, hdy=-35, ta=-1.9, curl=0.0, amp=0.1, bt=1.12),
    'bow': _dp('stretch', ta=-1.7, curl=0.0, amp=0.1, bt=1.1),
    'dig': _dp('eat_low', sx=12, sy=-13, hy=-16, hdx=26, hdy=-9, ta=-1.85, curl=0.0, amp=0.06, bt=1.12,
               feet=((17, 0), (20, 0), (-9, 0), (-5, 0))),
    'sniff': _dp('stand', sx=10, sy=-16, hdx=27, hdy=-19, ta=-1.85, curl=0.0, amp=0.1, bt=1.12),
    'butt': _dp('stand', sx=14, sy=-12, hx=-9, hy=-18, hdx=29, hdy=-14, ta=-1.5, curl=0.0, amp=0.05, bt=1.12, gait=0.0,
                feet=((14, 0), (11, 0), (-9, 0), (-11, 0))),
    'pronk': _dp('air', sx=10, sy=-20, hx=-9, hy=-22, hdx=22, hdy=-38, ta=-1.5, curl=0.0, amp=0.2, bt=1.12, arc=5.0,
                 feet=((16, -9), (9, -14), (-15, -8), (-8, -13))),
})
for _k in ('crouch', 'pounce', 'air', 'arch', 'stretch', 'eat_low', 'rub', 'knead', 'peek', 'edge_sleep'):
    GOAT_POSES[_k] = dict(GOAT_POSES[_k], ta=-1.8, curl=0.0)

# furet : meme squelette que le chien, mais long, bas sur pattes, tete petite, queue trainante
FERRET_POSES = {}
for _k, _v in DOG_POSES.items():
    if _k in ('rim_hide', 'rim_peek', 'hang', 'scratch'):
        FERRET_POSES[_k] = _v
        continue
    _d = dict(_v)
    _d['sx'] = _v['sx'] * 1.75
    _d['hx'] = _v['hx'] * 1.75
    _d['hdx'] = _v['hdx'] + _v['sx'] * 0.75 + 2
    _d['sy'] = _v['sy'] * 0.58
    _d['hy'] = _v['hy'] * 0.58
    _d['hdy'] = _v['hdy'] * 0.64
    _d['bt'] = _v['bt'] * 0.55
    _d['feet'] = tuple((fx * 1.7, fy * 0.65) for fx, fy in _v['feet'])
    _d['ta'] = 2.9
    _d['curl'] = 0.0
    FERRET_POSES[_k] = _d
def _belly(st, kick=0.0):
    """Pose sur le dos, decrite a l'endroit : corps bas, tete au niveau du corps, pattes courtes repliees
    (une fois l'animal retourne, elles pointent vers le ciel). kick : pattes qui pedalent."""
    sx, sy, hx, hy = st['sx'], st['sy'] * 0.85, st['hx'], st['hy'] * 0.85
    k = kick
    return dict(st, sy=sy, hy=hy, hdx=st['hdx'] * 0.95, hdy=sy - 1, ta=2.6, curl=0.25, amp=0.25, arc=-2.0, gait=0.0,
                feet=((sx + 5 + 4 * k, sy + 15 - 3 * k), (sx + 10 - 4 * k, sy + 17 + 2 * k),
                      (hx + 4 - 4 * k, hy + 16 + 2 * k), (hx - 3 + 4 * k, hy + 18 - 3 * k)))


FERRET_POSES['beg'] = dict(FERRET_POSES['beg'], sx=3, sy=-35, hx=-6, hy=-7, hdx=7, hdy=-47, ta=2.7,   # furet dresse : le corps a la verticale
                           feet=((9, -25), (11, -27), (0, 0), (5, 0)))
FERRET_POSES['war'] = dict(sx=14, sy=-11, hx=-14, hy=-10, hdx=25, hdy=-10, ta=-2.3, curl=0.15, amp=0.2, bl=1.0, bt=0.62, arc=6.0,
                           gait=0.0, feet=((12, 0), (9, 0), (-15, 0), (-17, 0)))


for _P in (POSES, DOG_POSES, GOAT_POSES, FERRET_POSES):
    _P['belly'] = _belly(_P['stand'])
    _P['belly2'] = _belly(_P['stand'], 1.0)
for _k in ('belly', 'belly2'):                       # chevre : tete un peu relevee (les cornes ne rentrent pas dans le sol)
    GOAT_POSES[_k] = dict(GOAT_POSES[_k], hdy=GOAT_POSES[_k]['sy'] + 8, ta=-1.85)


class Cat:
    """Chat de dessin animé en pseudo-3D : de profil, de face, de dos ou de trois quarts, tête qui se tourne seule."""

    def __init__(self, x, y, u, coat='tabby'):
        self.x, self.y, self.u = x, y, u
        self.coat = coat
        self.dir = 1
        self.pkey = None
        self.px0 = 0.0
        self.target = 'stand'
        self.rate = 9.0
        self.P = {k: (v if k != 'feet' else [list(f) for f in v]) for k, v in POSES['stand'].items()}
        self.gp = 0.0
        self.sl = 10.0
        self.tail = [-2.2] * 7
        self.tp = 0.0
        self.blink = 0.0
        self.blink_t = random.uniform(2, 5)
        self.eyes = 'open'
        self.look = (0.0, 0.0)
        self.ear = 0.0
        self.ear_t = random.uniform(2, 6)
        self.cute = False
        self.squash = 0.0
        self.spin = 0.0
        self.paw = 0.0
        self.paw_to = None        # cible de la patte avant (x, y locaux) pour le coup de patte
        self.paw_ph = 0.0
        self.yawn = 0.0
        self.puff = 0.0
        self.wag = 0.0
        self.mouth = None
        self.speed = 0.0
        self.yaw = 0.0            # 0 = profil droit, pi/2 = de face, pi = profil gauche, -pi/2 = de dos
        self.hyaw = 0.0
        self.view = 'side'        # side | front | back | 3q
        self.hlook = False        # la tête se tourne vers l'écran / le curseur
        self.cur_rel = 0.0
        self.hshift = (0.0, 0.0)
        self.earback = 0.0
        self.scratching = False
        self.scr_w = 0.0
        self.knead = False
        self.knead_w = 0.0
        self.vib = 0.0
        self.vib_off = 0.0
        self.vib_t = 0.0
        self.twitch = 0.0
        self.free_spin = 0.0
        self.spin_yaw = 0.0
        self._fs_on = False
        self.yoff = 0.0
        self.climbing = False
        self.cph = 0.0
        self.clw = 0.0
        self.expr = None          # expression drole : wide, derp, wink, smug, sad, heart, dizzy
        self.blep = 0.0           # langue tiree
        self.kid = 0.0            # 1 = bebe, 0.45 = jeune, 0 = adulte : corps court, grosse tete
        self._cl_on = False
        self.cl = []              # pattes en escalade : [x, y, posee, t, x0]
        self.plant_n = 0
        self.pull = 0.0
        self.climb_ph = 0.0       # phase du cycle d'escalade (0 = ramasse, 0.05-0.5 = poussee, 0.5-1 = les pattes arriere remontent)
        self.climb_scr = 0.0      # > 0 : il se hisse au sommet en pedalant des pattes arriere
        self._ly = None
        self.gal = 0.0            # poids du galop (0 = marche, 1 = galop complet)
        self.gph = 0.0            # phase du galop
        self.goat = coat in GOAT_COATS
        self.ferret = coat in FERRET_COATS
        self.dog = coat in DOG_COATS or self.goat or self.ferret
        self.poses = GOAT_POSES if self.goat else (FERRET_POSES if self.ferret else (DOG_POSES if self.dog else POSES))
        self.tng = 0.0            # langue pendante (chien)
        self.digging = False
        self.dig_w = 0.0
        self.fz = 1.0             # ecartement lateral des pattes avant (agrippe un rebord)
        self.E = {k: (v if k != 'feet' else [tuple(f) for f in v]) for k, v in self.P.items()}

    @staticmethod
    def _kf(frames, t):
        t %= 1.0
        for i in range(len(frames) - 1):
            t0, p0 = frames[i]
            t1, p1 = frames[i + 1]
            if t0 <= t <= t1:
                k = (t - t0) / max(1e-6, t1 - t0)
                k = k * k * (3 - 2 * k)
                return (p0[0] + (p1[0] - p0[0]) * k, p0[1] + (p1[1] - p0[1]) * k)
        return frames[-1][1]

    FRONT_KF = [(0.00, (25, -6)), (0.12, (19, 0)), (0.42, (1, 0)), (0.54, (0, -9)), (0.76, (13, -11)), (1.0, (25, -6))]
    HIND_KF = [(0.00, (-27, -5)), (0.28, (-14, -12)), (0.52, (-3, -1)), (0.58, (-3, 0)), (0.92, (-25, 0)), (1.0, (-27, -5))]

    CLIMB_STEP = 22.0             # ce que le corps monte a chaque bond (unites locales)

    @staticmethod
    def climb_rise(ph):
        """Avancee du corps dans le cycle : il ne monte que pendant la poussee (0.05 -> 0.5)."""
        k = clamp((ph - 0.05) / 0.45, 0.0, 1.0)
        return k * k * (3 - 2 * k)

    def climb_params(self, dt):
        """Grimpe comme un chat dans un arbre, par bonds :
        - poussee : les deux pattes arriere, plantees, poussent ensemble ; le corps s'etire vers le haut
          et les pattes avant lachent pour aller s'accrocher plus haut ;
        - ramasse : les griffes avant tiennent, les pattes arriere remontent sous le ventre, le dos s'arrondit ;
        - la queue balance pour l'equilibre ; au sommet, les pattes arriere pedalent pour se hisser."""
        S = self.poses['stand']
        sxc, hxc = S['sx'], S['hx']
        St = self.CLIMB_STEP
        F0, H0 = sxc + 11, hxc + 9                     # ou se plantent les pattes avant / arriere (coordonnees locales)
        ph = self.climb_ph % 1.0
        feet = []
        planted = []
        for i in range(4):
            q = (ph - (0.04 if i % 2 else 0.0)) % 1.0   # une patte de chaque paire suit l'autre de pres
            Y = St * self.climb_rise(q)
            if i < 2:                                   # pattes avant : volent pendant la poussee
                if 0.05 <= q < 0.5:
                    k = (q - 0.05) / 0.45
                    e = k * k * (3 - 2 * k)
                    wx = F0 + St * e + 7 * math.sin(PI * k)        # va chercher plus haut (un peu au-dela)
                    lx, ly = wx - Y, -8.0 * math.sin(PI * k)
                    planted.append(0)
                else:
                    lx, ly = F0, 0.0
                    planted.append(1)
            else:                                       # pattes arriere : plantees pendant la poussee, puis remontent
                if q < 0.5:
                    lx, ly = H0 - Y, 0.0
                    planted.append(1)
                elif q < 0.9:
                    k = (q - 0.5) / 0.4
                    e = k * k * (3 - 2 * k)
                    lx, ly = H0 - St + St * e, -6.0 * math.sin(PI * k)
                    planted.append(0)
                else:
                    lx, ly = H0, 0.0
                    planted.append(1)
            feet.append([lx, ly])
        if self.climb_scr > 0:                          # en haut : les pattes avant tiennent le rebord, l'arriere pedale
            w = self.climb_scr
            for i in (2, 3):
                a = self.paw_ph * 2.6 + (0 if i == 2 else PI)
                feet[i][0] += (H0 - 6 + 7 * math.sin(a) - feet[i][0]) * w
                feet[i][1] += (-4 + 4 * math.cos(a) - feet[i][1]) * w
            for i in (0, 1):
                feet[i][0] += (F0 + 5 - feet[i][0]) * w
                feet[i][1] += (-3 - feet[i][1]) * w
        # griffes qui s'agrippent : compte les pattes qui se reposent
        pl = getattr(self, '_cl_planted', None)
        if pl is not None:
            for a, b in zip(pl, planted):
                if b and not a:
                    self.plant_n += 1
        self._cl_planted = planted
        self.pull = (planted[0] + planted[1]) / 2.0
        # etirement : maximal en fin de poussee, ramasse (dos rond) quand les pattes arriere sont remontees
        if ph < 0.5:
            ext = self.climb_rise(ph)
        else:
            k = (ph - 0.5) / 0.5
            ext = 1 - k * k * (3 - 2 * k)
        syc = min(S['sy'], -15.0) - 2.0
        C = dict(sx=sxc + 3 + 2 * ext, sy=syc, hx=hxc + 5 - 7 * ext, hy=syc + 1.5 * (1 - ext),
                 hdx=S['hdx'] + 4 + 2 * ext, hdy=S['hdy'] - 2, ta=3.05 + 0.32 * math.sin(2 * PI * ph), curl=0.15,
                 amp=0.25, bl=1.0 + 0.13 * ext, bt=S['bt'] * 0.95, arc=5.5 * (1 - ext) - 1.0 * ext, gait=0.0)
        C['feet'] = [tuple(f) for f in feet]
        return C

    def gallop_params(self, phi):
        """Galop de dessin animé : le corps s'étire en vol, se ramasse, les pattes se tendent puis se replient."""
        e = 0.5 + 0.5 * math.cos(2 * PI * phi)
        yb = -5.0 * math.cos(2 * PI * phi) ** 2
        G = dict(sx=8 + 7 * e, sy=-19 + yb, hx=-5 - 7 * e, hy=-24 + 5 * e + yb, hdx=20 + 9 * e, hdy=-29 + yb * 0.8,
                 ta=-3.0, curl=-0.05, amp=0.22, bl=1.0 + 0.22 * e, bt=0.93, arc=6.0 * (1 - e), gait=0.0)
        G['feet'] = [self._kf(self.FRONT_KF, phi), self._kf(self.FRONT_KF, phi + 0.05),
                     self._kf(self.HIND_KF, phi), self._kf(self.HIND_KF, phi + 0.05)]
        if self.ferret:
            # galop du furet : le corps s'etire tres long en vol, puis se replie en arche (dos rond) quand les pattes se rassemblent
            sx0 = G['sx']
            G['sx'] = sx0 * 1.45 + 6 * e
            G['hx'] = G['hx'] * 1.45 - 6 * e
            G['hdx'] = G['hdx'] + (G['sx'] - sx0) + 2
            G['sy'] *= 0.62
            G['hy'] *= 0.62
            G['hdy'] *= 0.62
            G['bl'] = 1.0 + 0.3 * e
            G['bt'] = 0.58
            G['arc'] = 7.0 * (1 - e)
            G['ta'] = 2.95
            G['feet'] = [(fx * (1.45 + 0.35 * e), fy * 0.7) for fx, fy in G['feet']]
        return G

    def set_pose(self, name, rate=9.0):
        self.target = name
        self.rate = rate

    def update(self, dt, vx_abs, grounded):
        T = self.poses[self.target]
        k = min(1.0, dt * self.rate)
        for key, val in T.items():
            if key == 'feet':
                for i in range(4):
                    self.P['feet'][i][0] += (val[i][0] - self.P['feet'][i][0]) * k
                    self.P['feet'][i][1] += (val[i][1] - self.P['feet'][i][1]) * k
            else:
                self.P[key] += (val - self.P[key]) * k
        self.sl = clamp(9 + vx_abs / (self.u * 20), 9, 20)
        self.fz += ((2.4 if self.target in ('rim_hide', 'rim_peek') else 1.0) - self.fz) * min(1.0, dt * 10)
        if self.P['gait'] > 0.3 and grounded and vx_abs > 3:
            self.gp += dt * 0.6 * vx_abs / (self.sl * self.u)
        self.speed = vx_abs
        thr = 215 * (self.u / 1.75)
        self.gal += ((1.0 if (grounded and vx_abs > thr) else 0.0) - self.gal) * min(1.0, dt * 8)
        if self.gal > 0.01:
            self.gph = (self.gph + dt * max(vx_abs, thr * 0.6) / (55 * self.u)) % 1.0
        gw = clamp(self.gal, 0.0, 1.0)
        self.earback = 0.85 * gw
        if gw > 0.01:
            G = self.gallop_params(self.gph)
            self.E = {}
            for key, val in self.P.items():
                if key == 'feet':
                    self.E['feet'] = [(val[i][0] + (G['feet'][i][0] - val[i][0]) * gw, val[i][1] + (G['feet'][i][1] - val[i][1]) * gw) for i in range(4)]
                else:
                    self.E[key] = val + (G[key] - val) * gw
        else:
            self.E = {k: (v if k != 'feet' else [tuple(f) for f in v]) for k, v in self.P.items()}
        self.clw += ((1.0 if self.climbing else 0.0) - self.clw) * min(1.0, dt * 10)
        if self.clw > 0.01:
            self.cph = (self.cph + dt * 2.3) % 1.0
            C = self.climb_params(dt)
            cw = clamp(self.clw, 0.0, 1.0)
            for key, val in list(self.E.items()):
                if key == 'feet':
                    self.E['feet'] = [(val[i][0] + (C['feet'][i][0] - val[i][0]) * cw, val[i][1] + (C['feet'][i][1] - val[i][1]) * cw) for i in range(4)]
                else:
                    self.E[key] = val + (C[key] - val) * cw
        else:
            self._cl_on = False
        if self.kid > 0.01:                                  # bebe / jeune : corps court, pattes courtes
            E, k_ = self.E, self.kid
            f_, g_ = 1 - 0.28 * k_, 1 - 0.2 * k_
            sx0 = E['sx']
            E['sx'] *= f_
            E['hx'] *= f_
            E['hdx'] -= sx0 * (1 - f_)
            E['sy'] *= g_
            E['hy'] *= g_
            E['hdy'] *= 1 - 0.1 * k_
            E['feet'] = [(fx * f_, fy * g_) for fx, fy in E['feet']]
        if self.dog and self.P['gait'] > 0.3 and grounded and vx_abs > 3 and self.gal < 0.5:
            up = 1.1 * math.sin(4 * PI * self.gp) * clamp(vx_abs / (60 * self.u / 1.75), 0.0, 1.0)   # le corps monte au passage des pattes
            self.E['sy'] -= up
            self.E['hy'] -= up
            self.E['hdy'] -= up * 1.3
        self.tp += dt * (2.2 + vx_abs / (self.u * 40) + self.wag * (12 if self.dog else 6))
        P = self.E
        for i in range(7):
            tgt = P['ta'] + P['curl'] * i + (P['amp'] + self.wag * 0.5) * math.sin(self.tp - i * 0.55) * (0.4 + i * 0.25)
            self.tail[i] += (tgt - self.tail[i]) * min(1.0, dt * (16 - i * 1.5))
        self.blink_t -= dt
        if self.blink_t <= 0:
            self.blink = 0.14
            self.blink_t = random.uniform(2, 6)
        self.blink = max(0.0, self.blink - dt)
        self.ear_t -= dt
        if self.ear_t <= 0:
            self.ear = 1.0
            self.ear_t = random.uniform(2.5, 7)
        self.ear = max(0.0, self.ear - dt * 5)
        self.squash = max(0.0, self.squash - dt * 4)
        self.paw_ph += dt * 9
        self.scr_w += ((1.0 if self.scratching else 0.0) - self.scr_w) * min(1.0, dt * 10)
        self.knead_w += ((1.0 if self.knead else 0.0) - self.knead_w) * min(1.0, dt * 10)
        self.dig_w += ((1.0 if self.digging else 0.0) - self.dig_w) * min(1.0, dt * 10)
        self.vib_t += dt * 50
        self.vib_off = self.vib * 0.5 * math.sin(self.vib_t)
        self.twitch = max(0.0, self.twitch - dt * 2)
        # --- orientation du corps (le demi-tour passe par l'avant : le chat se retourne vers toi)
        base = 0.0 if self.dir > 0 else PI
        tgt = base
        if self.view == 'front':
            tgt = PI / 2
        elif self.view == 'back':
            tgt = -PI / 2
        elif self.view == '3q':
            tgt = base + (PI / 4 if self.dir > 0 else -PI / 4)
        d = (tgt - self.yaw + PI) % (2 * PI) - PI
        if abs(abs(d) - PI) < 0.06:
            yw = (self.yaw + PI) % (2 * PI) - PI
            d = PI if abs(yw) < PI / 2 else -PI
        self.yaw = (self.yaw + d * min(1.0, dt * 9) + PI) % (2 * PI) - PI
        if self.free_spin:
            if not self._fs_on:
                self._fs_on = True
                self.spin_yaw = self.yaw
            self.spin_yaw = (self.spin_yaw + self.free_spin * dt + PI) % (2 * PI) - PI
            self.yaw = self.spin_yaw
        else:
            self._fs_on = False
        # --- la tête peut se tourner vers l'écran, dans la limite du cou
        if self.hlook:
            want = PI / 2 - clamp(self.cur_rel / 520.0, -1.0, 1.0) * 1.05
            delta = clamp(angdiff(self.yaw, want), -1.4, 1.4)
            htgt = self.yaw + delta
        elif math.sin(self.yaw) > -0.3:
            htgt = self.yaw + clamp(angdiff(self.yaw, PI / 2), -0.75, 0.75)
        else:
            htgt = self.yaw
        dh = (htgt - self.hyaw + PI) % (2 * PI) - PI
        self.hyaw = (self.hyaw + dh * min(1.0, dt * 10) + PI) % (2 * PI) - PI
        if self.free_spin:
            self.hyaw = (self.yaw + 0.9 + PI) % (2 * PI) - PI

    # ------------------------------------------------------------------ projection pseudo-3D
    def V(self, v):
        """Vecteur local (x avant, y bas, z côté) -> écran (dx, dy) en pixels + profondeur."""
        x, y, z = v
        c, s_ = math.cos(self.yaw), math.sin(self.yaw)
        xr = x * c - z * s_
        zr = x * s_ + z * c
        if self.spin:
            a = self.spin * (1 if c >= 0 else -1)
            xr, y = xr * math.cos(a) - y * math.sin(a), xr * math.sin(a) + y * math.cos(a)
        y *= 1 - self.squash * 0.2
        xr *= 1 + self.squash * 0.12
        u = self.u
        return xr * u, y * u, zr * u

    def P3(self, x, y, z, head=False):
        dx, dy, dz = self.V((x, y + 18, z))
        sx, sy = self.hshift if head else (0.0, 0.0)
        return self.x + dx + sx, self.y + dy - 18 * self.u + sy + (self.vib_off + self.yoff) * self.u, dz

    def T(self, lx, ly):
        x, y, _ = self.P3(lx, ly, 0.0)
        return x, y

    def ell3(self, c3, axes, n=22, head=False):
        """Projection d'un ellipsoïde (centre + 3 demi-axes locaux) : une ellipse à l'écran."""
        cx, cy, _ = self.P3(c3[0], c3[1], c3[2], head)
        s00 = s01 = s11 = 0.0
        for ax in axes:
            vx, vy, _ = self.V(ax)
            s00 += vx * vx
            s01 += vx * vy
            s11 += vy * vy
        tr, det = s00 + s11, s00 * s11 - s01 * s01
        disc = math.sqrt(max(tr * tr / 4 - det, 0.0))
        r1, r2 = math.sqrt(max(tr / 2 + disc, 0.0)), math.sqrt(max(tr / 2 - disc, 0.0))
        th = 0.5 * math.atan2(2 * s01, s00 - s11)
        ct_, st_ = math.cos(th), math.sin(th)
        out = []
        for q in range(n):
            t = 2 * PI * q / n
            ex, ey = r1 * math.cos(t), r2 * math.sin(t)
            out += [cx + ex * ct_ - ey * st_, cy + ex * st_ + ey * ct_]
        return out

    @staticmethod
    def capsule2(p0, p1, r0, r1, n=6):
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        res = []
        for i in range(n + 1):
            a = ang - PI / 2 + PI * i / n
            res += [p1[0] + math.cos(a) * r1, p1[1] + math.sin(a) * r1]
        for i in range(n + 1):
            a = ang + PI / 2 + PI * i / n
            res += [p0[0] + math.cos(a) * r0, p0[1] + math.sin(a) * r0]
        return res

    def feet_pos(self):
        P = self.E
        gw = clamp(P['gait'], 0.0, 1.0)
        out = []
        # chien : marche en sequence laterale (arriere gauche, avant gauche, arriere droite, avant droite), 3 pattes au sol
        phs = ((8, 0.25), (6, 0.75), (-9, 0.0), (-11, 0.5)) if self.dog else ((8, 0.0), (6, 0.5), (-9, 0.5), (-11, 0.0))
        duty = 0.7 if self.dog else 0.6
        kf = 1 - 0.28 * self.kid
        for i, (xc, ph0) in enumerate(phs):
            ph = (self.gp + ph0) % 1.0
            sl = self.sl * (1 - 0.25 * self.kid)
            if ph < duty:
                gx, gy = xc * kf + sl * (0.5 - ph / duty), 0.0
            else:
                t = (ph - duty) / (1 - duty)
                gx, gy = xc * kf - sl * 0.5 + sl * t, -(6 if self.dog else 5) * math.sin(PI * t) * (sl / 10)
            fx, fy = P['feet'][i]
            out.append([fx + (gx - fx) * gw, fy + (gy - fy) * gw])
        if self.paw > 0.01:                                  # patte avant levée vers le visage (toilette, coup de patte)
            hx, hy = P['hdx'], P['hdy']
            if self.paw_to is not None:
                tx, ty = self.paw_to
            else:
                tx, ty = hx + 6 + 2 * math.sin(self.paw_ph), hy + 10 + 2 * math.cos(self.paw_ph * 1.3)
            out[0][0] += (tx - out[0][0]) * self.paw
            out[0][1] += (ty - out[0][1]) * self.paw
        if self.knead_w > 0.01:                              # pétrissage : les pattes avant poussent à tour de rôle
            a = math.sin(self.paw_ph * 1.1)
            out[0][1] += -4.5 * self.knead_w * max(0.0, a)
            out[0][0] += 3.0 * self.knead_w * a
            b = math.sin(self.paw_ph * 1.1 + PI)
            out[1][1] += -4.5 * self.knead_w * max(0.0, b)
            out[1][0] += 3.0 * self.knead_w * b
        if self.twitch > 0.01:                               # il rêve : les pattes frémissent
            out[2][1] += -3.0 * self.twitch * math.sin(self.paw_ph * 5)
            out[3][1] += -3.0 * self.twitch * math.sin(self.paw_ph * 5 + 1.3)
            out[0][0] += 1.5 * self.twitch * math.sin(self.paw_ph * 6)
        if self.dig_w > 0.01:                                # il creuse : les pattes avant grattent vers l'arriere
            a = max(0.0, math.sin(self.paw_ph * 1.6))
            b = max(0.0, math.sin(self.paw_ph * 1.6 + PI))
            out[0][1] += -7 * self.dig_w * a
            out[0][0] += -9 * self.dig_w * a
            out[1][1] += -7 * self.dig_w * b
            out[1][0] += -9 * self.dig_w * b
        if self.scr_w > 0.01:                                # griffes : les deux pattes avant grattent à tour de rôle
            out[0][1] += 8 * self.scr_w * math.sin(self.paw_ph * 1.5)
            out[1][1] += 8 * self.scr_w * math.sin(self.paw_ph * 1.5 + PI)
        return out

    def paws_col(self, co):
        if co['pat'] == 'points':
            return co['dark']
        return co['paw'] or co['base']

    # ------------------------------------------------------------------ dessin
    def draw(self, c, angry=False):
        u = self.u
        P = self.E
        co = DOG_COATS.get(self.coat) or GOAT_COATS.get(self.coat) or FERRET_COATS.get(self.coat) or COATS[self.coat]
        dog = self.dog
        goat = self.goat
        ferret = self.ferret
        lk = 1.0 if goat else (0.68 if ferret else (1.12 if dog else 1.0))
        base, dark, ol = co['base'], co['dark'], co['ol']
        if self.kid > 0.01:
            base = mix(base, '#ffffff', 0.22 * self.kid)           # pelage de bebe plus clair, duveteux
        ow = max(2, int(round(1.35 * u)))
        feet = self.feet_pos()
        pawc = self.paws_col(co)
        legc = dark if (co['pat'] == 'points' or co.get('socks')) else base
        s_y = math.sin(self.yaw)
        cute = self.cute or self.kid > 0.5                          # un bebe a toujours les joues roses
        dim = lambda col: mix(col, '#000000', 0.2)
        items = []

        def sticker(shapes):
            for kind, data, fill, extra in shapes:
                if kind == 'poly':
                    c.create_polygon(*data, fill=ol, outline=ol, width=ow * 2, joinstyle=tk.ROUND, smooth=extra)
                else:
                    c.create_line(*data, fill=ol, width=extra + 2 * ow, capstyle=tk.ROUND, joinstyle=tk.ROUND)
            for kind, data, fill, extra in shapes:
                if kind == 'poly':
                    c.create_polygon(*data, fill=fill, outline='', smooth=extra)
                else:
                    c.create_line(*data, fill=fill, width=extra, capstyle=tk.ROUND, joinstyle=tk.ROUND)

        # ---- pattes (4) : triées par profondeur avec le reste
        fh = (P['sx'] - 1, P['sy'] + 7)
        bh = (P['hx'] + 1, P['hy'] + 7)
        for li, (hip, foot, zz) in enumerate(((fh, feet[0], 5.4 * self.fz), (fh, feet[1], -5.4 * self.fz), (bh, feet[2], 5.6), (bh, feet[3], -5.6))):
            ph = self.P3(hip[0], hip[1], zz)
            pf = self.P3(foot[0], foot[1], zz)
            dep = (ph[2] + pf[2]) / 2
            far = dep < -1.5 * u
            cw_ = clamp(self.clw, 0.0, 1.0)
            pk = None
            if cw_ > 0.05:                                        # grimpe : coude / genou plie vers l'exterieur
                pk = self.P3((hip[0] + foot[0]) / 2 + (-1.5 if li < 2 else 3.0) * cw_, (hip[1] + foot[1]) / 2 - (4.5 if li < 2 else 6.0) * cw_, zz)

            def f(ph=ph, pf=pf, pk=pk, foot=foot, zz=zz, far=far):
                lc, pc = (dim(legc), dim(pawc)) if far else (legc, pawc)
                w0, w1 = (3.8 if goat else 3.5) * u * lk, (2.8 if goat else 3.0) * u * lk
                if pk is None:
                    legs = [('poly', self.capsule2(ph, pf, w0, w1), lc, False)]
                else:
                    wm = (w0 + w1) / 2
                    legs = [('poly', self.capsule2(ph, pk, w0, wm), lc, False), ('poly', self.capsule2(pk, pf, wm, w1), lc, False)]
                sticker(legs + [
                         ('poly', (self.ell3((foot[0] + 1.0, foot[1] - 2.0, zz), ((3.6, 0, 0), (0, 3.0, 0), (0, 0, 3.3)), 16) if goat else
                                   self.ell3((foot[0] + 1.6, foot[1] - 1.5, zz), ((4.7 * lk, 0, 0), (0, 3.1 * lk, 0), (0, 0, 3.8 * lk)), 16)), pc, False)])
            items.append((dep, f))

        # ---- queue (fine, effilée) : balaie aussi sur le côté
        tx0, ty0 = (P['hx'] - 8, P['hy'] - 8) if goat else (P['hx'] - 6, P['hy'] - 2)
        sw = 0.25 + self.wag * 1.2 + self.puff * 0.2
        tp3 = [(tx0, ty0, 0.0)]
        for i in range(7):
            a = self.tail[i]
            zq = math.sin(self.tp * 1.3 - i * 0.7) * sw * (0.4 + i * 0.35) * 2.4
            tp3.append((tp3[-1][0] + math.cos(a) * (1.5 if goat else (3.4 if ferret else 5.4)) * (1 - 0.3 * self.kid), tp3[-1][1] + math.sin(a) * (1.5 if goat else (3.4 if ferret else 5.4)) * (1 - 0.3 * self.kid), zq))
        tp2 = [self.P3(*q) for q in tp3]
        tail_col = dark if co['pat'] == 'points' else base
        if co.get('tail'):
            tail_col = co['tail']

        def tail_f():
            shapes = []
            for i in range(7):
                wd = max(3, int(((((5.0 - i * 0.35) if goat else ((4.4 - i * 0.38) if ferret else (6.4 - i * 0.5))) if dog else (5.0 - i * 0.38)) + self.puff * 3) * u))
                col = dark if (co['pat'] == 'tabby' and i % 2 == 1) else tail_col
                if dog and co['pat'] == 'saddle' and i >= 5:
                    col = '#ffffff'
                shapes.append(('line', [tp2[i][0], tp2[i][1], tp2[i + 1][0], tp2[i + 1][1]], col, wd))
            sticker(shapes)
        items.append((tp2[0][2] - 0.5 * u, tail_f))

        # ---- corps
        mx, my = (P['sx'] + P['hx']) / 2, (P['sy'] + P['hy']) / 2 - P['arc']
        ang = math.atan2(P['sy'] - P['hy'], P['sx'] - P['hx'])
        ln = math.hypot(P['sx'] - P['hx'], P['sy'] - P['hy']) / 2 * P['bl'] + (9.8 if goat else (9.5 if ferret else (10.5 if dog else 9.0)))
        bt = (11.2 if goat else 10.4) * P['bt'] * (1.0 + 0.15 * self.kid)
        rz = (9.4 if goat else 8.6) * P['bt'] * (1.0 + 0.15 * self.kid)
        ca_, sa_ = math.cos(ang), math.sin(ang)
        nx_, ny_ = -sa_, ca_

        def torso_f():
            sticker([('poly', self.ell3((mx, my, 0), ((ca_ * ln, sa_ * ln, 0), (nx_ * bt, ny_ * bt, 0), (0, 0, rz)), 30), base, False),
                     ('poly', self.ell3((P['hx'] + 1, P['hy'] + 1.5, 0), ((8.6 * P['bt'], 0, 0), (0, 9.2 * P['bt'], 0), (0, 0, rz + 0.4)), 22), base, False)])
            if s_y > -0.35:                                      # ventre / poitrail (caché vu de dos)
                c.create_polygon(self.ell3((mx + nx_ * bt * 0.45, my + ny_ * bt * 0.45, 0),
                                           ((ca_ * ln * 0.78, sa_ * ln * 0.78, 0), (nx_ * bt * 0.5, ny_ * bt * 0.5, 0), (0, 0, rz * 0.72)), 20),
                                 fill=co['belly'], outline='')
            if co['pat'] == 'tabby':                             # rayures qui font le tour du dos
                for q in range(4):
                    tt = -0.6 + q * 0.4
                    cx_, cy_ = mx + ca_ * ln * tt, my + sa_ * ln * tt
                    for sg in (-1, 1):
                        line = []
                        for k_ in range(7):
                            a = k_ * 0.19
                            loc = (cx_ - nx_ * bt * math.cos(a), cy_ - ny_ * bt * math.cos(a), sg * rz * math.sin(a))
                            nrm = (-nx_ * math.cos(a) / bt, -ny_ * math.cos(a) / bt, sg * math.sin(a) / rz)
                            if self.V(nrm)[2] > -0.0005:
                                px_, py_, _ = self.P3(*loc)
                                line += [px_, py_]
                        if len(line) >= 4:
                            c.create_line(*line, fill=dark, width=max(2, int(1.9 * u)), capstyle=tk.ROUND, smooth=True)
            elif co['pat'] == 'calico':                          # (taches posees le long du dos, elles suivent le corps)
                c.create_polygon(self.ell3((mx - 4 * ca_ - nx_ * bt * 0.55, my - 4 * sa_ - ny_ * bt * 0.55, 0),
                                           ((7.5 * ca_, 7.5 * sa_, 0), (4.0 * nx_, 4.0 * ny_, 0), (0, 0, rz * 0.7)), 16), fill=co['p1'], outline='')
                c.create_polygon(self.ell3((mx + 7 * ca_ - nx_ * bt * 0.45, my + 7 * sa_ - ny_ * bt * 0.45, 0),
                                           ((5.5 * ca_, 5.5 * sa_, 0), (3.4 * nx_, 3.4 * ny_, 0), (0, 0, rz * 0.7)), 16), fill=co['p2'], outline='')
            elif co['pat'] == 'tux' and s_y > -0.35:
                c.create_polygon(self.ell3((P['sx'] + 1, P['sy'] + 6, 1.5), ((6.2, 0, 0), (0, 8.8, 0), (0, 0, 5.0)), 18), fill='#ffffff', outline='')
            elif co['pat'] == 'saddle':                          # selle sombre sur le dos (beagle, husky)
                c.create_polygon(self.ell3((mx - ca_ - nx_ * bt * 0.52, my - sa_ - ny_ * bt * 0.52, 0),
                                           ((ca_ * ln * 0.74, sa_ * ln * 0.74, 0), (nx_ * bt * 0.45, ny_ * bt * 0.45, 0), (0, 0, rz * 0.98)), 26),
                                 fill=dark, outline='')
            elif co['pat'] == 'spots':                           # taches de dalmatien
                sgn = 1 if self.V((0, 0, 1))[2] >= 0 else -1
                for tt, vv, rr in ((-0.62, -0.35, 2.1), (-0.2, 0.05, 2.7), (0.28, -0.42, 2.0), (0.6, 0.02, 2.3), (-0.75, 0.3, 1.8),
                                   (0.02, 0.5, 1.7), (0.42, 0.45, 1.8), (-0.4, -0.7, 1.6), (0.15, -0.72, 1.5)):
                    c.create_polygon(self.ell3((mx + ca_ * ln * tt + nx_ * bt * vv, my + sa_ * ln * tt + ny_ * bt * vv, sgn * rz * 0.8),
                                               ((rr, 0, 0), (0, rr, 0), (0, 0, rr * 0.5)), 10), fill=dark, outline='')
            elif co['pat'] == 'stripe':                          # raie dorsale sombre (chevre caramel / grise)
                c.create_polygon(self.ell3((mx - ca_ - nx_ * bt * 0.76, my - sa_ - ny_ * bt * 0.76, 0),
                                           ((ca_ * ln * 0.86, sa_ * ln * 0.86, 0), (nx_ * bt * 0.20, ny_ * bt * 0.20, 0), (0, 0, rz * 0.72)), 24),
                                 fill=dark, outline='')
            elif co['pat'] == 'patch':                           # grandes taches (chevre pie)
                sgn = 1 if self.V((0, 0, 1))[2] >= 0 else -1
                for tt, vv, rr in ((-0.5, -0.25, 5.2), (0.32, -0.1, 4.4), (0.74, 0.4, 3.0)):
                    c.create_polygon(self.ell3((mx + ca_ * ln * tt + nx_ * bt * vv, my + sa_ * ln * tt + ny_ * bt * vv, sgn * rz * 0.72),
                                               ((rr * 1.3, 0, 0), (0, rr, 0), (0, 0, rr * 0.5)), 14), fill=dark, outline='')
        items.append((0.0, torso_f))

        # ---- tête (sphère aplatie) : peut se tourner indépendamment du corps
        hx0, hy0 = P['hdx'], P['hdy']
        R = (12.0 if goat else (8.8 if ferret else (12.6 if dog else 12.4))) * (1.12 if cute else 1.0) * (1.0 + 0.3 * self.kid)
        self.hshift = (self.look[0] * 1.5 * u, self.look[1] * 1.2 * u)
        dl = self.hyaw - self.yaw
        cd, sd = math.cos(dl), math.sin(dl)
        f_ = (cd, 0.0, sd)
        l_ = (-sd, 0.0, cd)
        Rx, Ry, Rz = R * 1.0, R * 0.98, R * 1.12

        def surf(al, be, k=1.0):
            ca, sa = math.cos(al), math.sin(al)
            cb, sb = math.cos(be), math.sin(be)
            return (hx0 + (f_[0] * Rx * cb * ca + l_[0] * Rz * cb * sa) * k,
                    hy0 + Ry * sb * k,
                    (f_[2] * Rx * cb * ca + l_[2] * Rz * cb * sa) * k)

        def vis(al, be):
            cb = math.cos(be)
            n = (f_[0] * cb * math.cos(al) + l_[0] * cb * math.sin(al), math.sin(be), f_[2] * cb * math.cos(al) + l_[2] * cb * math.sin(al))
            return self.V(n)[2] / u

        def head_pt(p):
            return self.P3(p[0], p[1], p[2], True)

        def HP(fw, lat, dn):                                     # point de la tete : avant, cote, vers le bas (en rayons)
            return head_pt((hx0 + (f_[0] * fw + l_[0] * lat) * R, hy0 + dn * R, (f_[2] * fw + l_[2] * lat) * R))

        head_dep = self.P3(hx0, hy0, 0.0)[2] + 0.01
        er_ = self.ear * 1.8
        earc = dark if co['pat'] == 'points' else base

        def ear_pts(sd_, k=1.0):
            lift = er_ if sd_ < 0 else 0.0
            eb = self.earback
            tip = (hx0 + (f_[0] * (0.04 * sd_ - 0.5 * eb) + l_[0] * 0.64 * sd_) * R, hy0 - (1.40 - 0.3 * eb) * R - lift,
                   (f_[2] * (0.04 * sd_ - 0.5 * eb) + l_[2] * 0.64 * sd_) * R)
            def bp(fw, lat, up):
                return (hx0 + (f_[0] * fw + l_[0] * lat * sd_) * R, hy0 - up * R, (f_[2] * fw + l_[2] * lat * sd_) * R)
            fo, fi, bi, bo = bp(0.32, 0.96, 0.70), bp(0.30, 0.16, 0.98), bp(-0.30, 0.16, 0.98), bp(-0.32, 0.96, 0.70)
            res = []
            for q in (fo, tip, fi, bi, bo):
                q = (tip[0] + (q[0] - tip[0]) * k, tip[1] + (q[1] - tip[1]) * k, tip[2] + (q[2] - tip[2]) * k) if k != 1.0 else q
                res += list(head_pt(q)[:2])
            return res

        dog_earc = co.get('ear') or earc

        def dog_ear(sd_):
            eb = self.earback
            fl = self.ear * 0.35

            def bp(fw, lat, up):
                return head_pt((hx0 + (f_[0] * fw + l_[0] * lat * sd_) * R, hy0 - up * R, (f_[2] * fw + l_[2] * lat * sd_) * R))[:2]
            pts = [bp(0.30, 0.62, 0.96), bp(0.38, 1.12, 0.40 + 0.7 * eb), bp(-0.05 - 0.4 * eb, 1.22, -0.9 + 1.2 * eb + fl),
                   bp(-0.55 - 0.5 * eb, 1.14, -0.25 + 0.9 * eb), bp(-0.42, 0.62, 0.96)]
            return [v for q in pts for v in q]

        def dog_face(fx):
            def Pp(fw, lat, dn):
                return head_pt((hx0 + (f_[0] * fw + l_[0] * lat) * R, hy0 + dn * R, (f_[2] * fw + l_[2] * lat) * R))
            lw_ = max(1, int(1.3 * u))
            opn = self.yawn
            fxx = max(0.5, fx)

            def blob(p, rx, ry, fill, outline=ol, n=14):
                c.create_polygon([v for q in range(n) for v in (p[0] + rx * math.cos(2 * PI * q / n), p[1] + ry * math.sin(2 * PI * q / n))],
                                 fill=fill, outline=outline, width=max(1, int(0.9 * u)))
            nose = Pp(1.72, 0.0, 0.17)
            c.create_line(nose[0], nose[1], *Pp(1.64, 0.0, 0.40)[:2], fill=ol, width=lw_, capstyle=tk.ROUND)
            for sd_ in (-1, 1):                                  # sourire de chaque cote
                pts = [Pp(1.64, 0.0, 0.40), Pp(1.42, sd_ * 0.13, 0.52), Pp(1.06, sd_ * 0.3, 0.52), Pp(0.82, sd_ * 0.38, 0.40)]
                c.create_line(*[v for q in pts for v in q[:2]], fill=ol, width=lw_, smooth=True, capstyle=tk.ROUND)
            if opn > 0.2:                                        # gueule ouverte
                m = Pp(1.30, 0.0, 0.58 + 0.10 * opn)
                blob(m, 0.34 * R * u * fxx, (0.10 + 0.24 * opn) * R * u, '#8a2a3c')
                blob((m[0], m[1] + 0.10 * R * u * opn), 0.2 * R * u * fxx, 0.1 * R * u * opn, '#ff7f96', '')
            elif max(self.tng, self.blep) > 0.25:                # langue qui pend
                ry_ = 0.26 * R * u * max(self.tng, self.blep)
                tp_ = Pp(1.30, 0.0, 0.60)
                tc = (tp_[0], tp_[1] + ry_ * 0.7)
                blob(tc, 0.17 * R * u * fxx, ry_, '#ff7f96')
                c.create_line(tc[0], tc[1] - ry_ * 0.5, tc[0], tc[1] + ry_ * 0.7, fill='#d8506e', width=1)
            blob(nose, 0.26 * R * u * fxx, 0.18 * R * u, '#1c1418')
            blob((nose[0] - 0.05 * R * u, nose[1] - 0.05 * R * u), 0.06 * R * u, 0.04 * R * u, '#8a7a88', '', 8)
            if cute or self.eyes == 'happy':                      # joues roses
                for sd_ in (-1, 1):
                    if vis(sd_ * 1.1, 0.25) > 0.05:
                        bq = Pp(0.5, sd_ * 0.86, 0.26)
                        blob(bq, 0.16 * R * u * max(0.3, vis(sd_ * 1.1, 0.25)), 0.1 * R * u, '#ff9ab8', '', 12)
            if self.mouth is not None:                           # balle / proie dans la gueule
                tq = Pp(1.5, 0.0, 0.5)
                self.mouth(c, tq[0] + 2 * u * (1 if math.cos(self.hyaw) >= 0 else -1), tq[1] + 4 * u)

        def goat_ear(sd_):                                       # oreille en feuille, horizontale, qui part vers l'arriere
            fl = self.ear * 0.5
            eb = self.earback
            pts = [HP(0.30, sd_ * 0.82, -0.58), HP(0.05, sd_ * 1.30, -0.66 - 0.2 * fl), HP(-0.50 - 0.4 * eb, sd_ * 1.78, -0.34 - 0.3 * fl + 0.3 * eb),
                   HP(-0.30, sd_ * 1.30, -0.16), HP(-0.36, sd_ * 0.82, -0.40)]
            return [v for q in pts for v in q[:2]]

        def goat_horn(sd_):                                      # petites cornes courbees vers l'arriere
            a, b, d = HP(0.12, sd_ * 0.42, -0.95), HP(-0.20, sd_ * 0.50, -1.38), HP(-0.80, sd_ * 0.50, -1.50)
            hc = co.get('horn', '#d8cdb2')
            return [('line', [a[0], a[1], b[0], b[1]], hc, max(3, int(4.2 * u))), ('line', [b[0], b[1], d[0], d[1]], hc, max(2, int(2.6 * u)))]

        def goat_face(fx):
            lw_ = max(1, int(1.3 * u))
            opn = self.yawn
            fxx = max(0.5, fx)

            def blob(p, rx, ry, fill, outline=ol, n=14):
                c.create_polygon([v for q in range(n) for v in (p[0] + rx * math.cos(2 * PI * q / n), p[1] + ry * math.sin(2 * PI * q / n))],
                                 fill=fill, outline=outline, width=max(1, int(0.9 * u)))
            nose = HP(1.50, 0.0, 0.24)
            c.create_line(nose[0], nose[1], *HP(1.46, 0.0, 0.42)[:2], fill=ol, width=lw_, capstyle=tk.ROUND)
            for sd_ in (-1, 1):                                  # bouche : petit sourire de chaque cote
                pts = [HP(1.46, 0.0, 0.42), HP(1.30, sd_ * 0.10, 0.52), HP(0.98, sd_ * 0.26, 0.50), HP(0.78, sd_ * 0.32, 0.42)]
                c.create_line(*[v for q in pts for v in q[:2]], fill=ol, width=lw_, smooth=True, capstyle=tk.ROUND)
            if opn > 0.2:                                        # bouche ouverte : bele / machonne
                m = HP(1.16, 0.0, 0.58 + 0.08 * opn)
                blob(m, 0.30 * R * u * fxx, (0.08 + 0.22 * opn) * R * u, '#8a2a3c')
                blob((m[0], m[1] + 0.08 * R * u * opn), 0.17 * R * u * fxx, 0.08 * R * u * opn, '#ff7f96', '')
            if self.blep > 0.3 and opn <= 0.2:                   # langue tiree
                tp_ = HP(1.12, 0.0, 0.60)
                blob((tp_[0], tp_[1] + 0.12 * R * u * self.blep), 0.12 * R * u * fxx, 0.15 * R * u * self.blep, '#ff7f96')
            blob(nose, 0.24 * R * u * fxx, 0.17 * R * u, '#4a3a40')
            for sd_ in (-1, 1):
                blob(HP(1.50, sd_ * 0.11, 0.22), 0.05 * R * u * fxx, 0.04 * R * u, '#150f12', '', 8)
            if cute or self.eyes == 'happy':                      # joues roses
                for sd_ in (-1, 1):
                    if vis(sd_ * 1.1, 0.25) > 0.05:
                        bq = HP(0.5, sd_ * 0.86, 0.26)
                        blob(bq, 0.16 * R * u * max(0.3, vis(sd_ * 1.1, 0.25)), 0.1 * R * u, '#ff9ab8', '', 12)
            if self.mouth is not None:                           # balle dans la bouche
                tq = HP(1.4, 0.0, 0.5)
                self.mouth(c, tq[0] + 2 * u * (1 if math.cos(self.hyaw) >= 0 else -1), tq[1] + 4 * u)

        def ferret_ear(sd_):                                     # petite oreille ronde, basse sur le cote de la tete
            pts = []
            for q in range(10):
                a = 2 * PI * q / 10
                pts.append(HP(-0.05 + 0.10 * math.cos(a), sd_ * (0.80 + 0.26 * math.cos(a)), -(0.80 + 0.28 * math.sin(a) + 0.15 * self.ear)))
            return [v for p_ in pts for v in p_[:2]]

        def ferret_face(fx):
            lw_ = max(1, int(1.2 * u))
            opn = self.yawn
            fxx = max(0.5, fx)

            def blob(p, rx, ry, fill, outline=ol, n=12):
                c.create_polygon([v for q in range(n) for v in (p[0] + rx * math.cos(2 * PI * q / n), p[1] + ry * math.sin(2 * PI * q / n))],
                                 fill=fill, outline=outline, width=max(1, int(0.8 * u)))
            nose = HP(1.30, 0.0, 0.20)
            c.create_line(nose[0], nose[1], *HP(1.24, 0.0, 0.40)[:2], fill=ol, width=lw_, capstyle=tk.ROUND)
            for sd_ in (-1, 1):
                pts = [HP(1.24, 0.0, 0.40), HP(1.10, sd_ * 0.08, 0.50), HP(0.84, sd_ * 0.20, 0.48)]
                c.create_line(*[v for q in pts for v in q[:2]], fill=ol, width=lw_, smooth=True, capstyle=tk.ROUND)
                if vis(sd_ * 0.9, 0.3) > 0.0:                    # moustaches
                    for k_ in range(3):
                        a_, b_ = HP(0.98, sd_ * 0.30, 0.30 + k_ * 0.05), HP(0.86, sd_ * 1.10, 0.16 + k_ * 0.14)
                        c.create_line(a_[0], a_[1], b_[0], b_[1], fill=ol, width=1)
            if opn > 0.2:                                        # bouche ouverte : il dooke
                m = HP(1.0, 0.0, 0.56 + 0.06 * opn)
                blob(m, 0.24 * R * u * fxx, (0.06 + 0.20 * opn) * R * u, '#8a2a3c')
                blob((m[0], m[1] + 0.07 * R * u * opn), 0.14 * R * u * fxx, 0.07 * R * u * opn, '#ff7f96', '', 8)
            if self.blep > 0.3 and opn <= 0.2:                   # langue tiree
                tp_ = HP(1.0, 0.0, 0.56)
                blob((tp_[0], tp_[1] + 0.12 * R * u * self.blep), 0.1 * R * u * fxx, 0.14 * R * u * self.blep, '#ff7f96')
            blob(nose, 0.17 * R * u * fxx, 0.12 * R * u, co.get('nose', '#c27a84'))
            if cute or self.eyes == 'happy':                      # joues roses
                for sd_ in (-1, 1):
                    if vis(sd_ * 1.1, 0.25) > 0.05:
                        bq = HP(0.5, sd_ * 0.86, 0.30)
                        blob(bq, 0.14 * R * u * max(0.3, vis(sd_ * 1.1, 0.25)), 0.09 * R * u, '#ff9ab8', '', 12)
            if self.mouth is not None:                           # balle dans la gueule
                tq = HP(1.2, 0.0, 0.5)
                self.mouth(c, tq[0] + 2 * u * (1 if math.cos(self.hyaw) >= 0 else -1), tq[1] + 4 * u)

        def head_f():
            shapes = []
            late = []
            for sd_ in (-1, 1):
                if goat:
                    near = self.V((l_[0] * sd_, 0.0, l_[2] * sd_))[2] >= 0
                    tgt = late if near else shapes
                    tgt.extend(goat_horn(sd_))
                    tgt.append(('poly', goat_ear(sd_), dog_earc, True))
                elif ferret:
                    near = self.V((l_[0] * sd_, 0.0, l_[2] * sd_))[2] >= 0
                    (late if near else shapes).append(('poly', ferret_ear(sd_), dog_earc, True))
                elif dog:
                    near = self.V((l_[0] * sd_, 0.0, l_[2] * sd_))[2] >= 0
                    (late if near else shapes).append(('poly', dog_ear(sd_), dog_earc, True))
                else:
                    shapes.append(('poly', ear_pts(sd_), earc, False))
            shapes.append(('poly', self.ell3((hx0, hy0, 0), ((f_[0] * Rx, 0, f_[2] * Rx), (0, Ry, 0), (l_[0] * Rz, 0, l_[2] * Rz)), 32, True), co.get('head') or base, False))
            if dog and vis(0.0, 0.1) > -0.05:                    # museau allonge
                mz = (0.95, 0.58, 0.40, 0.46) if goat else ((0.85, 0.52, 0.34, 0.40) if ferret else (1.08, 0.68, 0.40, 0.50))
                shapes.append(('poly', self.ell3((hx0 + f_[0] * R * mz[0], hy0 + 0.32 * R, f_[2] * R * mz[0]),
                                                 ((f_[0] * R * mz[1], 0, f_[2] * R * mz[1]), (0, R * mz[2], 0), (l_[0] * R * mz[3], 0, l_[2] * R * mz[3])), 24, True),
                               co['muzzle'] or base, False))
                if goat:                                         # barbiche
                    bp_ = [HP(1.38, -0.15, 0.60), HP(1.34, -0.20, 1.02), HP(1.14, 0.0, 1.68), HP(1.00, 0.20, 1.02), HP(0.98, 0.15, 0.60)]
                    shapes.append(('poly', [v for q in bp_ for v in q[:2]], co.get('beard') or dark, True))
            shapes.extend(late)
            for sd_ in (-1, 1):                                  # touffes de joues
                if (not dog) and vis(sd_ * 1.25, 0.3) > -0.2:
                    shapes.append(('poly', [v for q in (surf(sd_ * 1.30, 0.12, 1.02), surf(sd_ * 1.38, 0.52, 1.30), surf(sd_ * 0.95, 0.68, 0.96)) for v in head_pt(q)[:2]], base, True))
            sticker(shapes)
            vf = vis(0.0, 0.1)                                   # l'avant du visage regarde-t-il le spectateur ?
            if vf > 0.03 and not dog:
                for sd_ in (-1, 1):                              # intérieur des oreilles
                    c.create_polygon(*ear_pts(sd_, 0.58), fill=co['inner'], outline='')
            if co['pat'] == 'tabby':                             # rayures du front (ou de la nuque vue de dos)
                for dx_ in (-0.2, 0.0, 0.2):
                    for off in (0.0, PI):
                        if vis(off + dx_, -0.9) > 0.05:
                            p1, p2 = head_pt(surf(off + dx_, -1.22)), head_pt(surf(off + dx_ * 0.9, -0.78))
                            c.create_line(p1[0], p1[1], p2[0], p2[1], fill=dark, width=max(2, int(1.7 * u)), capstyle=tk.ROUND)
            if vf > 0.03:
                fx = max(0.22, vf)
                mzx, mzy, _ = head_pt(surf(0.0, 0.42))
                if ferret and co.get('mask'):                    # masque de bandit autour des yeux
                    c.create_polygon(self.ell3(surf(0.0, 0.04), ((l_[0] * R * 0.98, 0, l_[2] * R * 0.98), (0, R * 0.30, 0), (f_[0] * 2, 0, f_[2] * 2)), 20, True),
                                     fill=co['mask'], outline='')
                if dog:
                    pass
                elif co['pat'] == 'points':
                    c.create_polygon(self.ell3(surf(0.0, 0.42), ((l_[0] * R * 0.5, 0, l_[2] * R * 0.5), (0, R * 0.42, 0), (f_[0] * 2, 0, f_[2] * 2)), 18, True), fill=dark, outline='')
                elif co['muzzle']:
                    c.create_polygon(self.ell3(surf(0.0, 0.42), ((l_[0] * R * 0.46, 0, l_[2] * R * 0.46), (0, R * 0.36, 0), (f_[0] * 2, 0, f_[2] * 2)), 18, True), fill=co['muzzle'], outline='')
                elif co['pat'] == 'calico':
                    c.create_polygon(self.ell3(surf(-0.8, -0.45), ((l_[0] * R * 0.42, 0, l_[2] * R * 0.42), (0, R * 0.34, 0), (f_[0] * 2, 0, f_[2] * 2)), 14, True), fill=co['p1'], outline='')
                # yeux
                er = (3.5 if ferret else (4.4 if dog else 4.7)) * (1.2 if cute else 1.0) * (1.0 + 0.3 * self.kid)
                mode = self.expr if self.expr else (self.eyes if self.blink <= 0 else 'closed')
                er0 = er
                for sd_ in (-1, 1):
                    al = sd_ * (0.66 if goat else (0.52 if ferret else (0.5 if dog else 0.56)))
                    ve = vis(al, 0.1)
                    if ve < 0.12:
                        continue
                    ex, ey, _ = head_pt(surf(al, 0.1))
                    fxe = max(0.25, ve)
                    if mode in ('heart', 'dizzy'):                       # yeux en coeur / spirales
                        txt, col = ('♥', '#ff4f86') if mode == 'heart' else ('@', '#3a2a44')
                        sz = er0 * (2.7 + (0.5 * abs(math.sin(self.tp * 2)) if mode == 'heart' else 0.0)) * u
                        c.create_text(ex, ey, text=txt, fill=col, font=('Segoe UI Symbol', -int(sz), 'bold'))
                        continue
                    me = 'happy' if (mode == 'wink' and sd_ == 1) else mode
                    er = er0 * (1.3 if mode == 'wide' else (1.25 if (mode == 'derp' and sd_ == -1) else (0.85 if mode == 'derp' else 1.0)))
                    if me == 'closed':
                        c.create_line(ex - er * 0.9 * fxe, ey, ex, ey + 1.4 * u, ex + er * 0.9 * fxe, ey, fill=ol, width=max(2, int(1.9 * u)), smooth=True, capstyle=tk.ROUND)
                    elif me == 'happy':
                        c.create_arc(ex - er * 0.9 * fxe * u, ey - er * 0.2 * u, ex + er * 0.9 * fxe * u, ey + er * 1.7 * u, start=15, extent=150, style=tk.ARC, outline=ol, width=max(2, int(2.1 * u)))
                    else:
                        def el(cx, cy, a, b, n=16):
                            return [v for q in range(n) for v in (cx + a * math.cos(2 * PI * q / n), cy + b * math.sin(2 * PI * q / n))]
                        c.create_polygon(el(ex, ey, er * 0.98 * fxe * u, er * 1.18 * u), fill=ol, outline='')
                        c.create_polygon(el(ex, ey, er * 0.82 * fxe * u, er * 1.02 * u), fill=co['eye'] if not angry else '#f2c230', outline='')
                        gx, gy = self.look[0] * er * 0.4 * fxe * u, self.look[1] * er * 0.4 * u
                        if mode == 'derp':                           # yeux qui louchent
                            gx, gy = -sd_ * er * 0.55 * fxe * u, 0.0
                        pk = 0.5 if mode in ('wide', 'derp') else 1.0
                        pw = 0.6 if mode == 'angry' else 0.95
                        if goat:                                         # pupille rectangulaire horizontale
                            c.create_polygon(ex + gx - er * 0.95 * fxe * u, ey + gy - er * 0.24 * u, ex + gx + er * 0.95 * fxe * u, ey + gy - er * 0.24 * u,
                                             ex + gx + er * 0.95 * fxe * u, ey + gy + er * 0.24 * u, ex + gx - er * 0.95 * fxe * u, ey + gy + er * 0.24 * u,
                                             fill='#0a0a0e', outline='')
                        else:
                            c.create_polygon(el(ex + gx, ey + gy, pw * fxe * u * pk, er * 0.9 * u * pk), fill='#0a0a0e', outline='')
                        c.create_polygon(el(ex + gx - er * 0.32 * fxe * u, ey + gy - er * 0.45 * u, er * 0.34 * fxe * u, er * 0.34 * u, 10), fill='#ffffff', outline='')
                        c.create_polygon(el(ex + gx + er * 0.3 * fxe * u, ey + gy + er * 0.35 * u, er * 0.17 * fxe * u, er * 0.17 * u, 8), fill='#ffffff', outline='')
                        if mode == 'angry':
                            c.create_line(ex - sd_ * er * 1.2 * fxe * u, ey - er * 1.5 * u, ex + sd_ * er * 1.2 * fxe * u, ey - er * 0.35 * u, fill=ol, width=max(2, int(2.4 * u)), capstyle=tk.ROUND)
                        elif mode == 'smug':                             # paupiere mi-close : l'air blase
                            c.create_polygon(ex - er * 1.15 * fxe * u, ey - er * 1.4 * u, ex + er * 1.15 * fxe * u, ey - er * 1.4 * u,
                                             ex + er * 1.15 * fxe * u, ey - er * 0.05 * u, ex - er * 1.15 * fxe * u, ey - er * 0.05 * u,
                                             fill=base, outline=ol, width=max(1, int(1.2 * u)))
                        elif mode == 'sad':                              # sourcils tristes et une larme
                            c.create_line(ex - sd_ * er * 1.2 * fxe * u, ey - er * 1.3 * u, ex + sd_ * er * 1.2 * fxe * u, ey - er * 2.1 * u,
                                          fill=ol, width=max(2, int(2.0 * u)), capstyle=tk.ROUND)
                            ty_ = ey + er * 1.3 * u + ((self.tp * 0.6) % 1.0) * er * 1.8 * u
                            c.create_oval(ex - 0.28 * er * u * fxe, ty_ - 0.45 * er * u, ex + 0.28 * er * u * fxe, ty_ + 0.45 * er * u, fill='#8ad0ff', outline='')
                if goat:
                    goat_face(max(0.22, vf))
                elif ferret:
                    ferret_face(max(0.22, vf))
                elif dog:
                    dog_face(max(0.22, vf))
                else:
                    # museau
                    nx0, ny0, _ = head_pt(surf(0.0, 0.40))
                    c.create_polygon(nx0 - 1.5 * fx * u, ny0 - 1.0 * u, nx0 + 1.5 * fx * u, ny0 - 1.0 * u, nx0, ny0 + 0.9 * u, fill='#f0788c', outline=ol, smooth=True)
                    if self.yawn > 0.2:
                        my_ = ny0 + 3.4 * u
                        c.create_polygon([v for q in range(14) for v in (nx0 + 2.9 * fx * u * math.cos(2 * PI * q / 14), my_ + (2.0 + self.yawn * 2.8) * u * math.sin(2 * PI * q / 14))],
                                         fill='#8a2a3c', outline=ol)
                    else:
                        c.create_line(nx0, ny0 + 0.9 * u, nx0, ny0 + 2.4 * u, fill=ol, width=max(1, int(1.1 * u)))
                        c.create_line(nx0 - 3.4 * fx * u, ny0 + 2.6 * u, nx0 - 1.7 * fx * u, ny0 + 3.9 * u, nx0, ny0 + 2.4 * u, nx0 + 1.7 * fx * u, ny0 + 3.9 * u, nx0 + 3.4 * fx * u, ny0 + 2.6 * u,
                                      fill=ol, width=max(1, int(1.1 * u)), smooth=True, capstyle=tk.ROUND)
                    if self.blep > 0.3 and self.yawn <= 0.2:           # langue tiree
                        c.create_polygon([v for q in range(12) for v in (nx0 + 1.0 * u + 1.7 * fx * u * math.cos(2 * PI * q / 12), ny0 + 4.6 * u + 2.0 * u * self.blep * math.sin(2 * PI * q / 12))],
                                         fill='#ff7f96', outline=ol)
                    for sd_ in (-1, 1):                              # moustaches
                        al = sd_ * 0.78
                        if vis(al, 0.42) > 0.0:
                            st = surf(al, 0.42)
                            sx0, sy0, _ = head_pt(st)
                            for k_ in range(3):
                                en = (st[0] + l_[0] * sd_ * 9.0 + f_[0] * 1.2, st[1] - 1.4 + k_ * 3.0, st[2] + l_[2] * sd_ * 9.0 + f_[2] * 1.2)
                                ex2, ey2, _ = head_pt(en)
                                c.create_line(sx0, sy0 + (k_ * 1.5 - 1.0) * u, ex2, ey2, fill=ol, width=1)
                    if cute or mode == 'happy':                      # joues roses
                        for sd_ in (-1, 1):
                            al = sd_ * 0.98
                            if vis(al, 0.5) > 0.05:
                                bx_, by_, _ = head_pt(surf(al, 0.5))
                                c.create_polygon([v for q in range(12) for v in (bx_ + 2.8 * u * max(0.3, vis(al, 0.5)) * math.cos(2 * PI * q / 12), by_ + 1.8 * u * math.sin(2 * PI * q / 12))],
                                                 fill='#ff9ab8', outline='')
                    if self.mouth is not None:                       # proie dans la gueule
                        self.mouth(c, nx0 + 5 * u * (1 if math.cos(self.hyaw) >= 0 else -1), ny0 + 3.5 * u)
        items.append((head_dep, head_f))

        for _, fn in sorted(items, key=lambda it: it[0]):
            fn()

    def box(self):
        """Rectangle (écran) occupé par le chat, pour le survol."""
        u = self.u
        P = self.P
        if abs(self.spin) > 0.6:                              # à la verticale (escalade)
            return self.x - 24 * u, self.y - 18 * u - 40 * u, self.x + 24 * u, self.y - 18 * u + 40 * u
        ext = max(abs(P['hdx']) + 16, abs(P['hx']) + 22) * max(abs(math.cos(self.yaw)), 0.55)
        top = self.y + (min(P['hdy'], P['sy']) - 20) * u
        return self.x - ext * u, top, self.x + ext * u, self.y + 3 * u


class NullWeb:
    """Le chat n'a pas de toile : même interface, sans rien dessiner."""
    segs = []
    debris = []
    hub = (0, 0)
    R = 0.0
    sx = sy = 1
    s = 1.0

    def draw(self, *a, **k):
        pass

    def update_debris(self, dt):
        pass

    def built_ratio(self):
        return 0.0

    def missing(self):
        return 0

    def cut_path(self, *a):
        return []

    def next_unbuilt(self):
        return None

    def ensure_dew(self):
        pass



class Toy:
    """Souris en peluche, pelote de laine ou tasse : objets qui vivent sur les plateformes."""

    def __init__(self, kind, x, y, u):
        self.kind = kind
        self.x, self.y, self.u = x, y, u
        self.vx = self.vy = 0.0
        self.pkey = None
        self.px0 = 0.0
        self.state = 'live'                    # live | held | carried | broken | gone
        self.t = 0.0
        self.dir = random.choice((-1, 1))
        self.rot = 0.0
        self.life = 150.0 if kind == 'yarn' else 100.0
        self.pause = 0.0
        self.landed_t = 0.0
        self.fell = False
        self.feed = 0.45
        self.transit = False

    def update(self, dt, pet):
        self.t += dt
        if self.state in ('held', 'carried'):
            return
        if self.kind in ('bowl', 'box'):
            pet.toy_phys(self, dt)
            return
        if self.state == 'broken':
            if self.t - self.landed_t > 0.9:
                self.state = 'gone'
            return
        if self.t > self.life:
            self.state = 'gone'
            return
        if self.transit and self.t > 2.0 and (self.x < pet.area[0] + 10 or self.x > pet.area[2] - 10):
            self.state = 'gone'                                  # elle a traversé l'écran
            return
        u = self.u
        k = u / 1.75
        if self.kind == 'mouse' and self.pkey is not None:
            cat = pet.cat
            dcat = abs(cat.x - self.x) if abs(cat.y - self.y) < 60 * u else 1e9
            danger = pet.state in ('stalk', 'chase') and dcat < 160 * u
            dcur = math.hypot(pet.cur[0] - self.x, pet.cur[1] - (self.y - 8 * u))
            if dcur < 110 * u and pet.cspeed > 200:              # fuit le curseur
                self.dir = 1 if self.x > pet.cur[0] else -1
                sp_ = 210
            elif danger:                                         # fuit le chat
                self.dir = 1 if self.x > cat.x else -1
                sp_ = 170
            elif self.transit:
                sp_ = 125
            else:
                self.pause -= dt
                if self.pause > 0:
                    sp_ = 0
                else:
                    sp_ = 95
                    if random.random() < dt * 0.4:
                        self.pause = random.uniform(0.4, 1.8)
                    if random.random() < dt * 0.3:
                        self.dir = -self.dir
            self.vx = self.dir * sp_ * k
        elif self.kind == 'yarn':
            dx, dy = self.x - pet.cur[0], (self.y - 6 * u) - pet.cur[1]
            if abs(dx) < 26 * u and abs(dy) < 26 * u and pet.cspeed > 200:      # poussée par le curseur
                self.vx = clamp(self.vx + (1 if dx >= 0 else -1) * pet.cspeed * 0.35, -700, 700)
                if self.pkey is not None:
                    self.vy = -260 * k
                    self.pkey = None
            self.rot += self.vx * dt / (8 * u)
        pet.toy_phys(self, dt)


def draw_mouse(c, x, y, u, d, ph=0.0, carried=False):
    s = u * 0.9
    c.create_line(x - d * 8 * s, y - 4 * s, x - d * 13 * s, y - 2 * s, x - d * 17 * s, y - 8 * s, smooth=True, fill='#d99aa8', width=max(2, int(1.6 * s)))
    for q, off in enumerate((-4, 3)):                                             # petites pattes
        dy_ = abs(math.sin(ph + q * 2.1)) * 1.6 * s
        c.create_oval(x + off * s - 1.6 * s, y - 1.6 * s - dy_, x + off * s + 1.6 * s, y + 0.2 * s - dy_, fill='#7a768a', outline='')
    c.create_polygon(rot_ell(x, y - 4.6 * s, 0, 0, 0, 8 * s, 4.6 * s), fill='#aaa6b2', outline='#5a566a')
    c.create_polygon(rot_ell(x + d * 7 * s, y - 5 * s, 0, 0, 0, 4.4 * s, 3.5 * s), fill='#b8b4c0', outline='#5a566a')
    c.create_oval(x + d * 5 * s - 2.3 * s, y - 10.5 * s, x + d * 5 * s + 2.3 * s, y - 6.5 * s, fill='#f0a8b8', outline='#5a566a')
    c.create_oval(x + d * 11 * s - 1.1 * s, y - 5.8 * s, x + d * 11 * s + 1.1 * s, y - 3.8 * s, fill='#e8607f', outline='')
    c.create_oval(x + d * 8 * s - 0.8 * s, y - 6.6 * s, x + d * 8 * s + 0.8 * s, y - 5.0 * s, fill='#101018', outline='')


def draw_yarn(c, x, y, u, rot):
    r = 7 * u
    cy = y - r
    c.create_line(x + r * 0.9, cy + r * 0.4, x + r * 1.7, y - 1, x + r * 2.6, y - 2, smooth=True, fill='#e8607f', width=max(2, int(1.4 * u)))
    c.create_oval(x - r, cy - r, x + r, cy + r, fill='#e8607f', outline='#a02848', width=2)
    for k_ in range(3):
        a = rot + k_ * PI / 3
        ca, sa = math.cos(a), math.sin(a)
        c.create_line(x - ca * r * 0.92, cy - sa * r * 0.5, x + ca * r * 0.92, cy + sa * r * 0.5, fill='#ff9ab0', width=max(1, int(1.2 * u)))
    c.create_oval(x - r * 0.55, cy - r * 0.7, x - r * 0.1, cy - r * 0.25, fill='#ffd0da', outline='')


def draw_bone(c, x, y, u):
    w = 9 * u
    c.create_line(x - w, y, x + w, y, fill='#8a7a5a', width=max(4, int(7 * u)), capstyle=tk.ROUND)
    for sx in (-1, 1):
        for dy in (-1, 1):
            c.create_oval(x + sx * w - 3.4 * u, y + dy * 2.8 * u - 3.4 * u, x + sx * w + 3.4 * u, y + dy * 2.8 * u + 3.4 * u,
                          fill='#f6efdc', outline='#8a7a5a', width=2)
    c.create_line(x - w, y, x + w, y, fill='#f6efdc', width=max(3, int(5 * u)), capstyle=tk.ROUND)


def draw_carrot(c, x, y, u):
    c.create_polygon(x - 9 * u, y - 4 * u, x + 8 * u, y, x - 9 * u, y + 4 * u, fill='#f08a2e', outline='#a85a14', width=2)
    for dy in (-1.5, 1.5):
        c.create_line(x - 9 * u, y + dy * u, x - 14 * u, y + (dy * 2.4) * u, fill='#4aa64a', width=max(2, int(2.4 * u)), capstyle=tk.ROUND)
    c.create_line(x - 9 * u, y, x - 15 * u, y, fill='#4aa64a', width=max(2, int(2.4 * u)), capstyle=tk.ROUND)
    c.create_line(x - 3 * u, y - 2 * u, x - 1 * u, y - 0.5 * u, fill='#c26a1c', width=1)
    c.create_line(x + 1 * u, y + 0.5 * u, x + 3 * u, y + 2 * u, fill='#c26a1c', width=1)


def draw_bowl(c, x, y, u, food):
    s = u * 0.95
    c.create_polygon(x - 12 * s, y - 8 * s, x + 12 * s, y - 8 * s, x + 9 * s, y, x - 9 * s, y, fill='#e8607f', outline='#8a2a44', width=2, smooth=False)
    c.create_oval(x - 12 * s, y - 10.5 * s, x + 12 * s, y - 5.5 * s, fill='#3a1a24' if food <= 0 else '#c9854a', outline='#8a2a44', width=2)
    if food > 0:                                                  # croquettes + un petit poisson
        for q, (dx_, dy_) in enumerate(((-6, -9.5), (-2, -10.5), (3, -9.8), (7, -9.2), (0, -8.2), (-4, -8.4))):
            c.create_oval(x + dx_ * s - 1.5 * s, y + dy_ * s - 1.1 * s, x + dx_ * s + 1.5 * s, y + dy_ * s + 1.1 * s, fill='#8a5a2a', outline='')
        c.create_polygon(x - 3 * s, y - 12 * s, x + 4 * s, y - 14.5 * s, x + 9 * s, y - 12 * s, x + 4 * s, y - 10.5 * s, fill='#7ab8e8', outline='#3a78a8')
    c.create_rectangle(x - 6 * s, y - 4.5 * s, x + 6 * s, y - 2.5 * s, fill='#ffd0da', outline='')


def draw_box_back(c, x, y, u):
    w, h = 25 * u, 22 * u
    c.create_polygon(x - w - 1, y - h - 4 * u, x + w + 1, y - h - 4 * u, x + w, y, x - w, y, fill='#8a6030', outline='#5a3c18', width=2)
    for sd in (-1, 1):                                            # rabats du dessus, ouverts vers l'extérieur
        c.create_polygon(x + sd * w, y - h - 3 * u, x + sd * (w + 10 * u), y - h - 12 * u, x + sd * (w + 8 * u), y - h + 1 * u,
                         x + sd * w, y - h, fill='#b98846', outline='#5a3c18', width=2)


def draw_box_front(c, x, y, u):
    w, h = 25 * u, 22 * u
    c.create_polygon(x - w, y - h, x + w, y - h, x + w, y, x - w, y, fill='#c99a5b', outline='#5a3c18', width=2)
    c.create_rectangle(x - 5 * u, y - h, x + 5 * u, y - h + 8 * u, fill='#e8d2a0', outline='')
    c.create_line(x - w + 4 * u, y - 5 * u, x + w - 4 * u, y - 5 * u, fill='#a8793a', width=max(1, int(1.2 * u)))
    c.create_line(x - w + 4 * u, y - 10 * u, x + w - 4 * u, y - 10 * u, fill='#a8793a', width=max(1, int(1.2 * u)))
    c.create_polygon(x - w, y - h, x - w - 8 * u, y - h - 6 * u, x - w - 6 * u, y - h + 3 * u, fill='#b98846', outline='#5a3c18', width=2)
    c.create_polygon(x + w, y - h, x + w + 8 * u, y - h - 6 * u, x + w + 6 * u, y - h + 3 * u, fill='#b98846', outline='#5a3c18', width=2)


def draw_cup(c, x, y, u):
    s = u * 0.9
    c.create_arc(x + 4 * s, y - 10 * s, x + 11 * s, y - 2.5 * s, start=-90, extent=180, style=tk.ARC, outline='#6a6a7a', width=max(2, int(2 * s)))
    c.create_rectangle(x - 6 * s, y - 12 * s, x + 6 * s, y, fill='#f4f4f6', outline='#6a6a7a', width=2)
    c.create_rectangle(x - 6 * s, y - 7 * s, x + 6 * s, y - 5 * s, fill='#6aa8e8', outline='')
    c.create_oval(x - 5 * s, y - 13.5 * s, x + 5 * s, y - 10.5 * s, fill='#6a3a1a', outline='#6a6a7a')


class Buddy:
    """Deuxième chat : vit sa vie (marche, saute, dort) et partage des moments avec le premier (toilette, sieste, jeux)."""

    def __init__(self, pet, coat):
        self.pet = pet
        l, t, r, b = pet.area
        self.cat = Cat(random.uniform(l + 200, r - 200), b, pet.u, coat)
        self.cat.cute = pet.cute
        self.vx = self.vy = 0.0
        self.edge = 0
        self.state = 'idle'
        self.sub = 'a'
        self.t = 0.0
        self.idle_for = 1.0
        self.idle_pose = 'sit'
        self.view = 'side'
        self.tx = self.cat.x
        self.jump_to = (0.0, 0.0)
        self.nap_with = False
        self.zoom_end = 0.0
        self.zzz_t = 0.0

    def set(self, st, sub='a'):
        self.state, self.t, self.sub = st, 0.0, sub
        ct = self.cat
        ct.eyes = 'open'
        ct.yoff = 0.0
        ct.knead = False
        ct.vib = 0.0
        ct.wag = 0.0
        ct.paw = 0.0
        if st != 'sleep':
            self.nap_with = False

    def idle(self, secs, pose=None):
        self.set('idle')
        self.idle_for = secs
        self.idle_pose = pose or random.choice(('sit', 'sit', 'stand', 'loaf'))
        self.view = random.choice(('side', 'front', '3q'))
        self.vx = 0.0

    def update(self, dt):
        pet, ct = self.pet, self.cat
        u = pet.u
        self.t += dt
        ct.u = u
        ct.cute = pet.cute
        getattr(self, 'st_' + self.state)(dt)
        if self.state != 'held' and pet.phys_actor(ct, self, dt):
            self.on_land()
        grounded = ct.pkey is not None
        ct.update(dt, abs(self.vx) if grounded else 0.0, grounded)
        hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
        dx, dy = pet.cur[0] - hx, pet.cur[1] - hy
        d = math.hypot(dx, dy)
        k = min(1.0, d / 160.0) / d if d > 1 else 0.0
        ct.look = (dx * k, dy * k)
        ct.cur_rel = pet.cur[0] - ct.x
        ct.view = self.view if self.state in ('idle', 'groom_other') else ('3q' if self.state == 'sleep' else 'side')
        if self.state == 'held':
            ct.view = 'front'
        ct.hlook = self.state in ('idle', 'wash', 'groom_other', 'held') and ct.view != 'back'

    def on_land(self):
        pet = self.pet
        pet.sound('tap')
        self.cat.spin = 0.0
        if self.state in ('jump', 'fall'):
            self.idle(random.uniform(0.5, 1.5))

    # --- saisie a la main
    def grab(self):
        self.set('held')
        self.cat.pkey = None
        self.vx = self.vy = 0.0

    def st_held(self, dt):
        pet, ct = self.pet, self.cat
        ct.set_pose('hang', 8)
        ct.pkey = None
        self.vx = self.vy = 0.0
        ct.x = pet.cur[0]
        ct.y = min(pet.cur[1] + 58 * pet.u, pet.area[3])
        ct.spin = 0.0
        if not pet.getbtn():
            self.vx = clamp((pet.cur[0] - pet.pcur[0]) * 20, -500, 500)
            self.vy = clamp((pet.cur[1] - pet.pcur[1]) * 20, -600, 300)
            self.set('fall')

    def st_fall(self, dt):
        self.cat.set_pose('air', 12)

    # --- états
    def st_idle(self, dt):
        pet, ct = self.pet, self.cat
        u = pet.u
        self.vx = 0.0
        ct.set_pose(self.idle_pose)
        if abs(pet.cur[0] - ct.x) > 30 * u and pet.cspeed < 900:
            ct.dir = 1 if pet.cur[0] > ct.x else -1
        if self.t > self.idle_for:
            self.decide()

    def decide(self):
        pet, ct = self.pet, self.cat
        u = pet.u
        r = random.random()
        p = pet.plat(ct.pkey) if ct.pkey else None
        c1 = pet.cat
        if pet.still_t > 70 and r < 0.4:
            return self.set('sleep')
        if r < 0.30 and p:
            self.tx = random.uniform(p['x0'] + 30 * u, p['x1'] - 30 * u)
            return self.set('walk')
        if r < 0.50:
            return self.start_jump(random_target=True)
        if r < 0.68:                                                    # va retrouver le premier chat
            if c1.pkey == ct.pkey and p:
                self.tx = clamp(c1.x + random.choice((-1, 1)) * 70 * u, p['x0'] + 20 * u, p['x1'] - 20 * u)
                return self.set('walk')
            tp = pet.plat(c1.pkey) if c1.pkey else None
            if tp is not None:
                ok, tx = pet.reachable(tp, c1.x, ct)
                if ok:
                    self.jump_to = (tx, tp['y'])
                    return self.set('jump')
        if r < 0.78:
            return self.set('wash')
        self.idle(random.uniform(2, 5))

    def start_jump(self, random_target=False):
        pet, ct = self.pet, self.cat
        u = pet.u
        cands = []
        for p in pet.plats:
            if p['key'] == ct.pkey:
                continue
            ok, tx = pet.reachable(p, random.uniform(p['x0'] + 20 * u, p['x1'] - 20 * u), ct)
            if ok:
                cands.append((tx, p['y']))
        if not cands:
            return self.idle(1.0)
        self.jump_to = random.choice(cands)
        self.set('jump')

    def st_walk(self, dt):
        pet, ct = self.pet, self.cat
        u = pet.u
        ct.set_pose('stand')
        d = self.tx - ct.x
        ct.dir = 1 if d >= 0 else -1
        self.vx = ct.dir * 100 * (u / 1.75) if abs(d) > 6 * u else 0.0
        if abs(d) <= 6 * u or self.edge:
            self.idle(random.uniform(1, 4))

    def st_jump(self, dt):
        pet, ct = self.pet, self.cat
        tx, ty = self.jump_to
        if self.sub == 'a':
            ct.set_pose('crouch', 14)
            self.vx = 0.0
            ct.dir = 1 if tx >= ct.x else -1
            ct.wag = 0.4
            if self.t > 0.28:
                pet.plan_jump(tx, ty, ct, self)
                self.sub = 'b'
                ct.set_pose('pounce', 16)
        else:
            ct.set_pose('pounce' if self.vy < 200 else 'air', 12)
            if self.t > 3.0:
                self.idle(0.5)

    def st_sleep(self, dt):
        pet, ct = self.pet, self.cat
        u = pet.u
        self.vx = 0.0
        ct.set_pose('sleep', 4)
        ct.eyes = 'closed'
        ct.vib = 0.35
        self.zzz_t += dt
        if self.zzz_t > 1.7:
            self.zzz_t = 0.0
            hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
            pet.zzz.append([hx + 6 * u, hy - 8 * u, 0.0])
        if self.nap_with and pet.state != 'sleep' and self.t > 4:
            return self.idle(1.0)
        if pet.cspeed > 1200 or self.t > 140 or (abs(pet.cur[0] - ct.x) < 150 * u and pet.cspeed > 200 and self.t > 3):
            self.idle(1.0)

    def st_wash(self, dt):
        pet, ct = self.pet, self.cat
        self.vx = 0.0
        ct.set_pose('sit', 7)
        ct.paw = min(1.0, self.t / 0.5) if self.t < 3.0 else max(0.0, (3.6 - self.t) / 0.6)
        ct.eyes = 'closed' if ct.paw > 0.6 else 'open'
        if self.t > 3.6:
            self.idle(random.uniform(1, 3), 'sit')

    # --- moments à deux avec le premier chat
    def st_groom_other(self, dt):
        pet, ct = self.pet, self.cat
        u = pet.u
        c1 = pet.cat
        side = -1 if ct.x <= c1.x else 1
        tx = c1.x + side * 32 * u
        if self.sub == 'a':                                             # vient se placer contre lui
            d = tx - ct.x
            ct.set_pose('stand')
            ct.dir = 1 if d >= 0 else -1
            self.vx = ct.dir * 120 * (u / 1.75) if abs(d) > 5 * u else 0.0
            if abs(d) <= 5 * u or self.edge or self.t > 10:
                self.vx = 0.0
                self.set('groom_other', 'b')
        else:                                                           # lui lèche la tête
            self.vx = 0.0
            ct.dir = -side
            ct.set_pose('sit', 8)
            ct.yoff = -1.6 * max(0.0, math.sin(self.t * 7))
            ct.eyes = 'closed' if int(self.t * 2) % 2 else 'open'
            if int(self.t * 1.2) != int((self.t - dt) * 1.2):
                pet.hearts.append([(ct.x + c1.x) / 2, ct.y - 68 * u, 0.0])
                pet.sound('purr')
            if self.t > 5.0:
                ct.yoff = 0.0
                self.idle(random.uniform(2, 4), 'sit')

    def st_nap_go(self, dt):
        pet, ct = self.pet, self.cat
        u = pet.u
        c1 = pet.cat
        side = -1 if ct.x <= c1.x else 1
        tx = c1.x + side * 38 * u
        d = tx - ct.x
        ct.set_pose('stand')
        ct.dir = 1 if d >= 0 else -1
        self.vx = ct.dir * 110 * (u / 1.75) if abs(d) > 5 * u else 0.0
        if abs(d) <= 5 * u or self.edge or self.t > 10:
            self.vx = 0.0
            self.set('sleep')
            self.nap_with = True
            ct.dir = -side

    def st_zoom(self, dt):
        pet, ct = self.pet, self.cat
        u = pet.u
        p = pet.plat(ct.pkey) if ct.pkey else None
        if pet.now > self.zoom_end or p is None:
            return self.idle(1.5)
        ct.set_pose('stand', 12)
        ct.wag = 0.5
        c1 = pet.cat
        if self.sub == 'a' or abs(self.tx - ct.x) < 12 * u or self.edge:
            self.sub = 'b'
            self.tx = clamp(c1.x + random.uniform(-260, 260) * u / 1.75, p['x0'] + 20 * u, p['x1'] - 20 * u)
        ct.dir = 1 if self.tx >= ct.x else -1
        self.vx = ct.dir * 560 * (u / 1.75)


TRAITS = {'gourmand': 'Gourmand', 'joueur': 'Joueur', 'timide': 'Timide', 'calin': 'Calin', 'paresseux': 'Paresseux',
          'curieux': 'Curieux', 'colerique': 'Colerique', 'aventurier': 'Aventurier', 'farceur': 'Farceur', 'propre': 'Propre', 'cochon': 'Cochon'}
TRAIT_EXCLUS = (('propre', 'cochon'), ('joueur', 'paresseux'), ('timide', 'aventurier'), ('calin', 'colerique'))


def random_traits(n=2):
    """Deux traits de caractere au hasard (jamais deux traits qui se contredisent)."""
    out = []
    pool = list(TRAITS)
    random.shuffle(pool)
    for t in pool:
        if len(out) >= n:
            break
        if any((t in p and (set(p) - {t}) & set(out)) for p in TRAIT_EXCLUS):
            continue
        out.append(t)
    return out


class Life:
    """Vie de l'animal facon Tamagotchi : besoins, humeur, age, sante. Sauvegardee dans la config (il continue de vivre, doucement, hors-ligne)."""
    EGG_TIME = 120.0            # secondes avant l'eclosion
    HUNGER = 0.0001             # par seconde : le ventre se vide en pres de 3 heures
    ENERGY_DOWN = 0.00015
    ENERGY_UP = 0.002           # endormi, il recupere vite
    CLEAN_DOWN = 0.00006
    JOY_DOWN = 0.00018
    GROWTH = {'bebe': 0.62, 'jeune': 0.8, 'adulte': 1.0, 'senior': 0.95}
    NAMES = {'oeuf': 'Oeuf', 'bebe': 'Bebe', 'jeune': 'Jeune', 'adulte': 'Adulte', 'senior': 'Senior'}
    KEYS = ('hunger', 'energy', 'joy', 'clean', 'health', 'born', 'last')

    def __init__(self):
        now = time.time()
        self.born, self.last = now - 10 * 86400, now        # par defaut : un adulte en forme (utile pour les tests)
        self.hunger, self.energy, self.joy, self.clean, self.health = 0.4, 0.9, 0.8, 0.9, 1.0
        self.egg_t = None
        self.sick = False
        self.traits = []
        self.name = ''
        self.save_t = 0.0
        self.need_t = 15.0
        self.size_t = 0.0
        self.stage_prev = None

    @classmethod
    def new_egg(cls):
        L = cls()
        L.egg_t = cls.EGG_TIME
        L.born = L.last = time.time()
        L.hunger, L.energy, L.joy, L.clean = 0.3, 1.0, 0.9, 1.0
        L.traits = random_traits()
        return L

    @classmethod
    def load(cls, d):
        if not isinstance(d, dict):
            return cls.new_egg()
        L = cls()
        ok = 0
        for k in cls.KEYS:                                       # champ manquant ou abime : valeur par defaut, le reste est garde
            try:
                v = float(d[k])
                if v != v:
                    continue
                setattr(L, k, clamp(v, 0.0, 1.0) if k not in ('born', 'last') else v)
                ok += 1
            except Exception:
                pass
        if ok == 0:
            return cls.new_egg()
        try:
            e = d.get('egg_t')
            L.egg_t = None if e is None else clamp(float(e), 0.0, cls.EGG_TIME)
        except Exception:
            L.egg_t = None
        L.sick = bool(d.get('sick', False))
        L.name = ' '.join(str(d.get('name') or '').split())[:18]
        tr = d.get('traits')
        L.traits = [t for t in tr if t in TRAITS] if isinstance(tr, list) else random_traits()   # ancienne sauvegarde : on lui en donne
        if L.born > time.time():
            L.born = time.time()
        if L.last > time.time():
            L.last = time.time()
        el = clamp(time.time() - L.last, 0.0, 6 * 3600.0)       # temps passe programme ferme (plafonne, et adouci)
        if L.egg_t is None and el > 30:
            L.hunger = max(L.hunger, min(0.9, L.hunger + cls.HUNGER * el * 0.5))
            L.energy = min(1.0, L.energy + 0.0004 * el)
            L.clean = min(L.clean, max(0.25, L.clean - cls.CLEAN_DOWN * el * 0.4))
            L.joy = min(L.joy, max(0.25, L.joy - 0.00008 * el))
        L.last = time.time()
        return L

    def dump(self):
        d = {k: round(float(getattr(self, k)), 4) for k in ('hunger', 'energy', 'joy', 'clean', 'health')}
        d['born'] = self.born
        d['last'] = time.time()
        d['egg_t'] = self.egg_t
        d['sick'] = self.sick
        d['traits'] = list(self.traits)
        d['name'] = self.name
        d['v'] = 2
        return d

    def has(self, t):
        return t in self.traits

    def traits_txt(self):
        return ', '.join(TRAITS[t] for t in self.traits) or 'Aucun'

    def age_days(self):
        return max(0.0, (time.time() - self.born) / 86400.0)

    def stage(self):
        if self.egg_t is not None:
            return 'oeuf'
        d = self.age_days()
        return 'bebe' if d < 1 else 'jeune' if d < 3 else 'adulte' if d < 14 else 'senior'

    def growth(self):
        return self.GROWTH.get(self.stage(), 1.0)

    def age_txt(self):
        d = self.age_days()
        return '%d h' % int(d * 24) if d < 1 else '%d j' % int(d)

    def mood(self):
        if self.sick:
            return 'Malade'
        if self.hunger > 0.8:
            return 'Affame'
        if self.energy < 0.2:
            return 'Epuise'
        if self.clean < 0.2:
            return 'Sale'
        if self.joy > 0.75:
            return 'Heureux'
        if self.joy > 0.45:
            return 'Content'
        return 'Triste' if self.joy > 0.25 else 'Deprime'


VERSION = '1.1.3'
GITHUB_REPO = 'ethilbalde/desktop-pet'


def ver_tuple(v):
    out = []
    for p in str(v).lstrip('vV').split('.'):
        try:
            out.append(int(''.join(ch for ch in p if ch.isdigit()) or 0))
        except Exception:
            out.append(0)
    return tuple(out)


class Updater:
    """Mise a jour depuis GitHub (clic sur « Mise a jour » dans Reglages) : cherche la derniere release,
    telecharge le nouvel exe a cote de l'ancien, puis un petit script le remplace et relance le programme."""
    API = 'https://api.github.com/repos/%s/releases/latest' % GITHUB_REPO
    TRUSTED = 'https://github.com/%s/releases/' % GITHUB_REPO
    MIN_SIZE = 1000000

    def __init__(self):
        self.msg = ''
        self.busy = False
        self.ready = None
        self.frozen = bool(getattr(sys, 'frozen', False))
        self.exe_path = sys.executable if self.frozen else ''

    def start(self):
        if self.busy:
            return
        import threading
        self.busy = True
        self.msg = 'Recherche...'
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            import json
            import urllib.request
            hdr = {'User-Agent': 'desktop-pet-updater', 'Accept': 'application/vnd.github+json'}
            with urllib.request.urlopen(urllib.request.Request(self.API, headers=hdr), timeout=12) as r:
                data = json.loads(r.read().decode('utf-8'))
            tag = str(data.get('tag_name', ''))
            if ver_tuple(tag) <= ver_tuple(VERSION):
                self.msg = 'Deja a jour (v%s)' % VERSION
                return
            if not self.frozen:
                self.msg = 'v%s disponible (version sources : rien remplace)' % tag.lstrip('vV')
                return
            asset = next((a for a in data.get('assets', []) if str(a.get('name', '')).lower().endswith('.exe')), None)
            url = str((asset or {}).get('browser_download_url', ''))
            if not url.startswith(self.TRUSTED):
                self.msg = 'Aucun exe dans la release %s' % tag
                return
            self.msg = 'Telechargement de v%s...' % tag.lstrip('vV')
            dest = self.exe_path + '.new'
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=60) as r, open(dest, 'wb') as f:
                shutil.copyfileobj(r, f)
            if os.path.getsize(dest) < self.MIN_SIZE:
                os.remove(dest)
                self.msg = 'Telechargement incomplet'
                return
            self.msg = 'v%s prete : redemarrage...' % tag.lstrip('vV')
            self.ready = dest
        except Exception as e:
            code = getattr(e, 'code', None)
            if code == 404:
                self.msg = 'GitHub injoignable (page introuvable)'
            elif code in (403, 429):
                self.msg = 'GitHub limite les demandes, reessaie plus tard'
            elif isinstance(e, (OSError, getattr(__import__('urllib.error').error, 'URLError', OSError))):
                self.msg = 'Pas de connexion a GitHub'
            else:
                self.msg = 'Echec : %s' % str(e)[:40]
            try:
                if self.exe_path and not self.ready and os.path.exists(self.exe_path + '.new'):
                    os.remove(self.exe_path + '.new')           # telechargement coupe : on ne garde pas un exe a moitie
            except Exception:
                pass
        finally:
            self.busy = False


UPDATER = Updater()


def relaunch_cmd(skip=('--monitor', '--animal', '--autre-ecran')):
    """Ligne de commande pour relancer le programme (sans les options qui ecraseraient les reglages)."""
    args, it = [], iter(sys.argv[1:])
    for a in it:
        if a == '--direct':
            continue
        if a in skip:
            if a != '--autre-ecran':
                next(it, None)
            continue
        args.append(a)
    if getattr(sys, 'frozen', False):
        base = [sys.executable]
    else:
        exe = sys.executable
        if exe.lower().endswith('python.exe'):
            exe = exe[:-len('python.exe')] + 'pythonw.exe'
        base = [exe, os.path.abspath(sys.argv[0])]
    return base + args


def spawn_script(text, name='araignee_relance.bat'):
    import subprocess
    path = os.path.join(tempfile.gettempdir(), name)
    with open(path, 'w', encoding='mbcs', errors='replace') as f:
        f.write(text)
    subprocess.Popen(['cmd', '/c', path], creationflags=0x08000000 | 0x00000008, close_fds=True)


def restart_soon():
    """Relance le programme apres quelques secondes (le temps que celui-ci se ferme)."""
    cmd = ' '.join('"%s"' % c for c in relaunch_cmd() + ['--direct'])
    spawn_script('@echo off\r\nping -n 3 127.0.0.1 >nul\r\nstart "" %s\r\ndel "%%~f0"\r\n' % cmd)


def apply_update(new_exe, old_exe, args=()):
    """Remplace l'exe (impossible tant qu'il tourne : on reessaie jusqu'a ce qu'il soit ferme) puis le relance."""
    a = ' '.join('"%s"' % x for x in args)
    spawn_script('@echo off\r\ncopy /y "%s" "%s.old" >nul 2>&1\r\nset n=0\r\n:w\r\nmove /y "%s" "%s" >nul 2>&1\r\nif errorlevel 1 (\r\n  set /a n+=1\r\n'
                 '  if %%n%% gtr 60 exit /b 1\r\n  ping -n 2 127.0.0.1 >nul\r\n  goto w\r\n)\r\nstart "" "%s" %s\r\ndel "%%~f0"\r\n'
                 % (old_exe, old_exe, new_exe, old_exe, old_exe, a), 'araignee_maj.bat')


_MON_COUNT = [0.0, 1]


def monitor_count():
    if time.time() - _MON_COUNT[0] > 5:
        _MON_COUNT[0] = time.time()
        try:
            _MON_COUNT[1] = max(1, len(list_monitors()))
        except Exception:
            _MON_COUNT[1] = 1
    return _MON_COUNT[1]


class CatPet:
    """Cerveau du chat : physique de plateformes (barre des tâches, fenêtres, panier), états, souris, menu."""
    UK = 1.45
    ANGRY_STATES = ('defend',)
    LOOK_STATES = ('idle', 'loaf', 'groom', 'pet', 'held', 'stretch', 'eat', 'carry', 'greet', 'knead', 'box', 'found', 'dizzy', 'rim')
    menu_geom = Pet.menu_geom
    over_menu = Pet.over_menu
    menu_row = Pet.menu_row
    open_menu = Pet.open_menu
    sound = Pet.sound
    set_windows = Pet.set_windows
    draw_menu = Pet.draw_menu
    click_tab = Pet.click_tab
    slider_start = Pet.slider_start
    slider_track = Pet.slider_track
    slider_set = Pet.slider_set
    slider_tick = Pet.slider_tick

    def __init__(self, area, scale, getcursor, log=None, coat='tabby'):
        self.life = Life()
        self.name_asked = False
        self.ask_name_cb = self.reset_cb = self.load_cb = None
        self.layers, self.lay_used, self.sprite_solid = {}, set(), False
        self.face, self.face_until, self.face_t = None, 0.0, random.uniform(12, 25)
        self.found_ok = 0.0
        self.growth = 1.0
        self.auto_sleep_ok = 0.0
        self.treat_ok = 0.0
        self.area = area
        self.s = scale
        self.u = scale * self.UK
        self.getcur = getcursor
        self.log = log
        self.web = NullWeb()
        self.dew_on = False
        self.comp_on = False
        self.comp = None
        self.icons = []
        l, t, r, b = area
        self.cat = Cat(random.uniform(l + 300, r - 300), b, self.u, coat)
        self.g = 1400 * self.u
        self.vx = self.vy = 0.0
        self.now = 0.0
        self.state = 'idle'
        self.state_t = 0.0
        self.idle_for = 1.0
        self.idle_pose = 'sit'
        self.idle_view = 'side'
        self.cur = self.pcur = getcursor()
        self.cspeed = 0.0
        self.hunger = 0.5
        self.still_t = 0.0
        self.snd = Sound()
        self.snd_last = 0.0
        self.bk = Basket(area, scale)
        self.bk.y = b - 34 * self.bk.s
        self.bk_press = None
        self.bk_drag = False
        self.bk_off = (0.0, 0.0)
        self.hover_bk = False
        self.windows = []
        self.win_by = {}
        self.plats = []
        self.interactive = False
        self.paused = False
        self.menu_open = False
        self.menu_ctx = 'cat'
        self.menu_page = 'main'
        self.menu_pos = (0.0, 0.0)
        self.animal = 'cat'
        self.switch_animal_cb = None
        self.cfg_save = None
        self.quit_cb = None
        self.getbtn = lambda: False
        self.getbtn2 = lambda: False
        self.getctrl = lambda: False
        self.btn_prev = False
        self.btn2_prev = False
        self.hearts = []
        self.zzz = []
        self.zzz_t = 0.0
        self.sparks = []
        self.flies = []
        self.toys = []
        self.hand_toy = None
        self.cute = False
        self.click_t = -9.0
        self.grab_t = -9.0
        self.grab_cur = (0.0, 0.0)
        self.grab_off = (0.0, 0.0)
        self.wiggle = []
        self.last_wig = -9.0
        self.pvx = self.pvy = 0.0
        self.pet_acc = 0.0
        self.pet_away = 0.0
        self.pet_ok = 0.0
        self.pet_heart_t = 0.0
        self.tx = self.cat.x
        self.wspeed = 90.0
        self.sub = 'a'
        self.edge = 0
        self.jump_to = None
        self.chase_ok = 0.0
        self.no_cut_until = 0.0
        self.then = None
        self.state_t_sub = 0.0
        self.prey = None
        self.hunt_ok = 6.0
        self.def_ok = 0.0
        self.zoom_end = 0.0
        self.zjump = 0.0
        self.cup = None
        self.carry = None
        self.eat_feed = 0.0
        self.knock_dir = 1
        self.bats = 0
        self.sub_t = 0.0
        self.climb = None
        self.then_climb = None
        self.climb_v = 0.0
        self.scr = None
        self.ambient = True
        self.amb_t = random.uniform(10, 18)
        self.bowl = None
        self.feed_ok = 0.0
        self.eat_t0 = 0.0
        self.box_obj = None
        self.buddy = None
        self.buddy_on = False
        self.social = None
        self.social_ok = 25.0
        self.knead_then = None
        self.knead_dur = 4.0
        self.edge_pose = False
        self.edge_target = 0.0
        self.edge_next = 'sleep'
        self.rub_dir = 1
        self.dream_t = 0.0
        self.words = []
        self.rim = None
        self.hover_toy = None
        self.hand_hist = []
        self.snap_basket()

    # ------------------------------------------------------------------ utilitaires
    def web_sig(self):
        return 0

    def web_jit(self):
        return False

    def snap_basket(self):
        l, t, r, b = self.area
        bs = self.bk.s
        if abs(self.bk.y + 33 * bs - b) < 80 * self.s:
            self.bk.y = b - 33 * bs

    def set_state(self, name):
        if self.log and name != self.state:
            self.log(f"[{self.now:6.1f}s] {self.state} -> {name}")
        self.state = name
        self.state_t = 0.0
        self.sub = 'a'
        ct = self.cat
        if name != 'pet':
            ct.eyes = 'open'
        if name not in ('groom', 'bat'):
            ct.paw = 0.0
        if name != 'swat':
            ct.paw_to = None
        ct.yawn = 0.0
        ct.wag = 0.0
        ct.puff = 0.0
        if name != 'sleep':
            self.zzz_t = 0.0
        if name != 'carry':
            ct.mouth = None
        if name not in ('climb', 'flip', 'belly'):
            ct.spin = 0.0
        ct.knead = (name == 'knead')
        ct.vib = {'knead': 1.0, 'pet': 0.8, 'rub': 0.8, 'sleep': 0.35, 'box': 0.0}.get(name, 0.0)
        if name != 'tailchase':
            ct.free_spin = 0.0
        if name != 'box':
            ct.yoff = 0.0
        if name not in ('sleep', 'edge_go'):
            self.edge_pose = False
        if name != 'climb':
            ct.climbing = False
            ct.climb_scr = 0.0
        if name not in ('rim', 'rim_go', 'jump', 'climb_go', 'climb', 'fall'):
            self.rim = None
        ct.scratching = (name == 'scratch')

    def view_for_state(self):
        st = self.state
        if st in ('pet', 'held', 'defend', 'eat', 'greet', 'dizzy', 'box', 'found', 'rim'):
            return 'front'
        if st == 'idle':
            return self.idle_view
        if st in ('loaf', 'groom', 'sleep', 'knead', 'rub', 'groomed'):
            return '3q'
        return 'side'

    def go_idle(self, secs, pose=None):
        self.then = None
        self.cat.paw = 0.0
        self.cat.paw_to = None
        self.idle_view = random.choices(['side', 'front', '3q', 'back'], [0.38, 0.32, 0.2, 0.1])[0]
        self.set_state('idle')
        self.idle_for = secs
        self.idle_pose = pose or random.choice(('sit', 'sit', 'stand'))
        self.vx = 0.0

    def grounded(self):
        return self.cat.pkey is not None

    def cursor_look(self):
        ct = self.cat
        hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
        dx, dy = self.cur[0] - hx, self.cur[1] - hy
        d = math.hypot(dx, dy)
        k = min(1.0, d / 160.0) / d if d > 1 else 0.0
        return dx * k, dy * k

    def over_cat(self):
        if self.state == 'rim' and self.rim:                       # seule la partie visible au-dessus du rebord compte
            w = self.win_by.get(self.rim['hw'])
            if w:
                u, ct = self.u, self.cat
                up = 34 * u if self.sub == 'p' else 8 * u
                return abs(self.cur[0] - ct.x) < 17 * u and w[1] - up <= self.cur[1] <= w[1] + 5 * u
            return False
        l, t, r, b = self.cat.box()
        return l <= self.cur[0] <= r and t <= self.cur[1] <= b

    # ------------------------------------------------------------------ plateformes
    def build_platforms(self):
        l, t, r, b = self.area
        u = self.u
        pl = [dict(key=('ground', 0), x0=l + 4, x1=r - 4, y=b)]
        for hw, wl, wt, wr, wb in self.windows:
            if wt > t + 100 * u and wr - wl >= 250:
                pl.append(dict(key=('win', hw), x0=wl + 8, x1=wr - 8, y=wt))
        bk = self.bk
        pl.append(dict(key=('basket', 0), x0=bk.x - 24 * bk.s, x1=bk.x + 24 * bk.s, y=bk.y - 17 * bk.s))
        self.plats = pl

    def plat(self, key):
        for p in self.plats:
            if p['key'] == key:
                return p
        return None

    def cur_plat(self):
        return self.plat(self.cat.pkey) if self.cat.pkey else None

    def plan_jump(self, tx, ty, ct=None, a=None):
        """Lance un chat en vol vers (tx, ty) : trajectoire balistique."""
        ct = ct or self.cat
        a = a or self
        g = self.g
        k_ = self.u / 1.75
        dx = clamp(tx - ct.x, -560 * k_, 560 * k_)                  # un chat ne saute pas plus loin que ça
        dy = max(ty - ct.y, -820 * k_)
        dist = math.hypot(dx, dy)
        if dy < 0:
            T = max(0.4, math.sqrt(2 * abs(dy) / g) * 1.3) + dist * 0.0003
        else:
            T = 0.45 + dist * 0.0004
        a.vx = dx / T
        a.vy = (dy - 0.5 * g * T * T) / T
        ct.pkey = None
        ct.dir = 1 if dx >= 0 else -1

    def reachable(self, p, x, ct=None):
        """Peut-on sauter de la position actuelle vers la plateforme p (point x) ?"""
        ct = ct or self.cat
        u = self.u
        tx = clamp(x, p['x0'] + 20 * u, p['x1'] - 20 * u)
        dy = p['y'] - ct.y
        return (dy > -800 * (u / 1.75) and abs(tx - ct.x) < 540 * (u / 1.75) + max(0, dy) * 0.5), tx

    def phys_actor(self, ct, a, dt):
        """Gravité, plateformes, atterrissage pour le chat ct dont l'état de mouvement est dans a (vx, vy, edge, state, sub).
        Renvoie True si le chat vient d'atterrir."""
        u = self.u
        l, t, r, b = self.area
        a.edge = 0
        if ct.pkey is not None:
            p = self.plat(ct.pkey)
            if p is None:                                     # la plateforme a disparu : chute
                ct.pkey = None
                a.vy = 0.0
            else:
                ct.x += p['x0'] - ct.px0
                ct.px0 = p['x0']
                ct.y = p['y']
                nx = ct.x + a.vx * dt
                lo, hi = p['x0'] + 6 * u, p['x1'] - 6 * u
                if nx < lo or nx > hi:
                    if a.state in ('walk', 'zoom') and a.sub == 'drop':       # il saute volontairement dans le vide
                        ct.x = nx
                        ct.pkey = None
                        a.vy = -200 * (u / 1.75)
                    else:
                        ct.x = clamp(nx, lo, hi)
                        a.edge = -1 if nx < lo else 1
                else:
                    ct.x = nx
                if ct.pkey is not None:
                    return False
        # en l'air
        py = ct.y
        a.vy += self.g * dt
        ct.x += a.vx * dt
        ct.y += a.vy * dt
        if ct.y < t + 70 * u:                                   # plafond : le haut de l'écran
            ct.y = t + 70 * u
            a.vy = max(a.vy, 0.0)
        if ct.x < l + 8 * u or ct.x > r - 8 * u:
            ct.x = clamp(ct.x, l + 8 * u, r - 8 * u)
            a.vx = -a.vx * 0.3
        if a.vy >= 0:
            best = None
            for p in self.plats:
                if py <= p['y'] + 3 and ct.y >= p['y'] and p['x0'] - 4 * u <= ct.x <= p['x1'] + 4 * u:
                    if best is None or p['y'] < best['y']:
                        best = p
            if best is None and ct.y > b:                         # sous le sol (lâché trop bas) : retombe sur le sol
                best = self.plats[0]
                ct.x = clamp(ct.x, best['x0'], best['x1'])
            if best is not None:
                ct.pkey = best['key']
                ct.px0 = best['x0']
                ct.y = best['y']
                ct.squash = clamp(a.vy / (1500 * (u / 1.75)), 0.15, 1.0)
                a.vy = 0.0
                a.vx = 0.0
                return True
        return False

    def physics(self, dt):
        if self.life.sick and self.cat.pkey is not None:
            self.vx *= 0.55                                      # malade : il se traine
        if self.phys_actor(self.cat, self, dt):
            self.on_land()

    def on_land(self):
        self.sound('tap')
        ct = self.cat
        ct.spin = 0.0
        if self.state == 'jump' and self.then:
            nxt, self.then = self.then, None
            if nxt == 'rim' and self.rim is not None:
                if self.cat.pkey == ('win', self.rim['hw']):
                    return self.set_state('rim_go')
                if self.cat.pkey == ('ground', 0) and self.start_climb(then='rim', only=self.rim['hw']):
                    return
                self.rim = None
                return self.go_idle(0.5)
            if nxt == 'sleep':
                return self.go_sleep()
            if nxt == 'stalk' and self.prey_alive(self.prey):
                return self.set_state('stalk')
            if nxt == 'feed' and self.bowl is not None and self.bowl.food > 0:
                return self.set_state('feed_go')
            if nxt == 'box' and self.box_obj is not None:
                return self.set_state('box_go')
            if nxt == 'zoom' and self.now < self.zoom_end:
                return self.set_state('zoom')
            return self.go_idle(0.5)
        if self.state == 'stalk' and self.sub == 'c':                    # bond manqué
            self.hunt_ok = self.now + 3
            return self.go_idle(random.uniform(0.8, 1.8), 'sit')
        if self.state in ('jump', 'fall', 'flip', 'pounce'):
            self.go_idle(random.uniform(0.4, 1.5))

    # ------------------------------------------------------------------ boucle
    def update(self, dt):
        s, u, ct = self.s, self.u, self.cat
        if self.life.egg_t is not None:
            return self.update_egg(dt)
        self.now += dt
        self.state_t += dt
        self.pcur = self.cur
        cx_, cy_ = self.getcur()
        l_, t_, r_, b_ = self.area
        self.cur = (clamp(cx_, l_, r_), clamp(cy_, t_, b_))
        inst = math.hypot(self.cur[0] - self.pcur[0], self.cur[1] - self.pcur[1]) / max(dt, 1e-3)
        self.cspeed += (inst - self.cspeed) * min(1.0, dt * 8)
        self.hunger = min(1.0, self.hunger + dt / getattr(self, 'SPEED', 1.0) * self.life.HUNGER * (1.35 if self.life.has('gourmand') else 1.0))
        self.still_t = self.still_t + dt if self.cspeed < 5 else 0.0
        ct.look = self.cursor_look()
        ct.cur_rel = self.cur[0] - ct.x
        ct.view = self.view_for_state()
        ct.hlook = self.state in self.LOOK_STATES and ct.view != 'back'
        self.build_platforms()
        self.life_tick(dt)

        vx_, vy_ = self.cur[0] - self.pcur[0], self.cur[1] - self.pcur[1]
        vl_ = math.hypot(vx_, vy_)
        if vl_ > 10 and math.hypot(self.pvx, self.pvy) > 10 and (vx_ * self.pvx + vy_ * self.pvy) < 0:
            self.wiggle.append(self.now)
            self.last_wig = self.now
        if vl_ > 3:
            self.pvx, self.pvy = vx_, vy_
        self.wiggle = [t_ for t_ in self.wiggle if self.now - t_ < 1.6]

        btn = bool(self.getbtn())
        pressed = btn and not self.btn_prev
        self.btn_prev = btn
        hover = self.state not in ('held',) and self.over_cat()
        self.hover_bk = (not hover) and self.bk.hit(self.cur[0], self.cur[1])
        self.hover_toy = None if (hover or self.hover_bk or self.hand_toy is not None) else self.toy_at(self.cur[0], self.cur[1])
        bud = self.buddy
        bud_hover = False
        if bud is not None and not hover and self.hand_toy is None:
            bl_, bt_, br_, bb_ = bud.cat.box()
            bud_hover = bud.state == 'held' or (bl_ <= self.cur[0] <= br_ and bt_ <= self.cur[1] <= bb_)
        if bud_hover:
            self.hover_toy = None
        self.interactive = (hover or self.state == 'held' or self.hover_bk or self.bk_press is not None
                            or self.hover_toy is not None or bud_hover
                            or (self.menu_open and self.over_menu()) or self.hand_toy is not None)
        btn2 = bool(self.getbtn2())
        pressed2 = btn2 and not self.btn2_prev
        self.btn2_prev = btn2
        consumed = False
        if self.menu_open and pressed:
            consumed = True
            idx = self.menu_row()
            items = self.menu_items()
            if idx is not None and str(items[idx][1]).startswith('slider:'):
                self.slider_start(items[idx][1][7:])            # curseur : on le fait glisser, le menu reste ouvert
                idx = None
            else:
                self.menu_open = False
            if idx is not None and items[idx][1]:
                self.sound('tap')
                self.menu_action(items[idx][1])
        self.slider_tick(btn)
        if pressed2:
            if self.hover_bk:
                self.open_menu('basket')
            elif hover and self.state != 'held':
                self.open_menu('cat')
            else:
                self.menu_open = False
        # caresses
        if (self.state in ('idle', 'walk', 'loaf', 'groom', 'stretch') and hover and not btn
                and self.now >= self.pet_ok and 15 < self.cspeed < 1100):
            self.pet_acc += dt
            if self.pet_acc > 0.35:
                self.pet_acc = 0.0
                self.pet_away = 0.0
                self.pet_heart_t = 0.0
                self.set_state('pet')
        else:
            self.pet_acc = max(0.0, self.pet_acc - dt * 2)
        if (len(self.wiggle) >= 4 and self.state in ('idle', 'walk', 'loaf') and not hover
                and self.now >= self.chase_ok and not self.paused and self.can_chase()):
            self.set_state('chase')
        if pressed and not consumed and hover and self.state != 'held' and not self.life.name and not self.name_asked and self.ask_name_cb:
            self.name_asked = True                               # il vient d'eclore (ou n'a pas de nom) : on lui en donne un
            self.ask_name_cb()
        elif pressed and not consumed and hover and self.state != 'held':
            if self.now - self.click_t < 0.5:
                self.start_flip()
            else:
                self.grab()
        elif pressed and not consumed and bud_hover and bud.state != 'held':
            bud.grab()                                           # le deuxieme chat se deplace aussi
        elif pressed and not consumed and self.hover_toy is not None and self.hand_toy is None:
            o = self.hover_toy                                   # on attrape la pelote (ou la souris) a la main
            if self.carry is o:
                self.carry = None
                self.cat.mouth = None
            o.state = 'held'
            o.pkey = None
            self.hand_toy = o
            self.hand_hist = []
        elif pressed and not consumed and self.hover_bk and self.bk_press is None:
            if self.getctrl() and self.hand_toy is None:
                self.hand_toy = self.new_toy(held=True)
            else:
                self.bk_press = self.cur
                self.bk_drag = False
                self.bk_off = (self.bk.x - self.cur[0], self.bk.y - self.cur[1])
        if self.bk_press is not None:
            if btn:
                if self.bk_drag or math.hypot(self.cur[0] - self.bk_press[0], self.cur[1] - self.bk_press[1]) > 6 * s:
                    self.bk_drag = True
                    l, t, r, b = self.area
                    self.bk.x = clamp(self.cur[0] + self.bk_off[0], l + 30 * s, r - 30 * s)
                    self.bk.y = clamp(self.cur[1] + self.bk_off[1], t + 46 * s, b - 30 * s)
            else:
                if not self.bk_drag:
                    self.spawn_toy()
                else:
                    self.snap_basket()
                    self.save_config()
                self.bk_press = None
        self.update_hand_toy(btn)
        self.pointer_sense(dt, pressed and not consumed and not hover and not self.hover_bk and self.hover_toy is None)
        self.bk.update(dt)
        if self.paused:
            self.vx = 0.0
            return

        getattr(self, 'st_' + self.state)(dt)
        self.face_update(dt)
        if self.state not in ('held', 'climb', 'rim'):
            self.physics(dt)
        grounded = self.grounded()
        spd = abs(self.vx) if grounded else 0.0
        if self.state == 'tailchase':
            spd, grounded = 70 * (u / 1.75), True
        if self.state == 'climb':
            spd, grounded = (self.climb_v if self.sub == 'b' else 0.0), True
        ct.update(dt, spd, grounded)
        self.update_world(dt)
        for h in self.hearts:
            h[1] -= 45 * s * dt
            h[2] += dt
        self.hearts = [h for h in self.hearts if h[2] < 1.6]
        for w in self.words:
            w[3] += dt
            w[2] -= 16 * s * dt
        self.words = [w for w in self.words if w[3] < 1.3]
        for z in self.zzz:
            z[1] -= 22 * s * dt
            z[0] += 8 * s * dt
            z[2] += dt
        self.zzz = [z for z in self.zzz if z[2] < 2.4]
        for sk in self.sparks:
            sk[4] += dt
            if sk[4] > 0:
                if sk[5] == 'chip':
                    sk[3] += 700 * dt
                sk[0] += sk[2] * dt
                sk[1] += sk[3] * dt
        self.sparks = [sk for sk in self.sparks if sk[4] < (0.8 if sk[5] == 'chip' else 1.3)]
        if ct.cute and grounded and abs(self.vx) > 60 * s and random.random() < dt * 5:
            self.sparks.append([ct.x - ct.dir * 20 * u, ct.y - 18 * u, random.uniform(-6, 6) * s, -14 * s, 0.0, 'star'])

    def update_world(self, dt):
        for f in self.flies:
            f.update(dt, self)
        self.flies = [f for f in self.flies if f.state != 'gone']
        for o in self.toys:
            o.update(dt, self)
        self.toys = [o for o in self.toys if o.state != 'gone']
        if self.cup is not None:
            self.cup.update(dt, self)
            if self.cup.state == 'gone':
                self.cup = None
        b_ = self.bowl
        if b_ is not None:
            if b_.food <= 0 and self.now - b_.empty_t > 15:
                self.bowl = None
                self.toys = [o for o in self.toys if o is not b_]
            elif (b_.food > 0 and self.hunger > 0.2 and self.now >= self.feed_ok
                  and self.state in ('idle', 'loaf', 'groom', 'stretch', 'walk') and random.random() < dt * 1.5):
                if not self.start_feed():
                    self.feed_ok = self.now + 4
        if self.buddy is not None:
            self.buddy.update(dt)
            self.social_tick(dt)
        self.amb_t -= dt
        if self.amb_t <= 0:
            self.amb_t = random.uniform(22, 50)
            if self.ambient and len(self.flies) + len(self.toys) < 2 and self.state not in ('sleep', 'held'):
                self.spawn_ambient()
        if (self.state in ('idle', 'loaf', 'groom', 'stretch', 'walk') and self.now >= self.hunt_ok
                and self.prey_list() and random.random() < dt * 1.5):
            if not self.start_hunt():
                self.hunt_ok = self.now + 3


    def can_chase(self):
        return True

    # ------------------------------------------------------------------ décisions
    def decide(self):
        ct, u, s = self.cat, self.u, self.s
        r = random.random()
        p = self.cur_plat()
        if self.still_t > 50 and random.random() < 0.5:
            return self.start_sleep()
        if self.still_t > 2 and self.cspeed < 80 and abs(self.cur[0] - ct.x) < 700 * (u / 1.75) and random.random() < 0.10:
            return self.set_state('greet')
        if random.random() < 0.08 and self.start_rub():
            return
        if random.random() < 0.05:
            return self.start_tailchase()
        if random.random() < 0.05 and self.start_rim():
            return
        if self.box_obj is not None and random.random() < 0.10 and self.start_box():
            return
        if p and p['key'][0] == 'win' and random.random() < 0.07 and self.start_peek():
            return
        if (self.hunger > 0.5 or random.random() < 0.5) and self.prey_list() and self.start_hunt():
            return
        if r < 0.04:
            return self.start_zoom()
        if 0.07 <= r < 0.12 and self.start_climb():
            return
        if 0.12 <= r < 0.17 and self.start_scratch():
            return
        if r < 0.07 and p and p['key'][0] in ('win', 'basket') and self.start_knock():
            return
        if r < 0.22 and p:
            return self.start_walk(random.uniform(p['x0'] + 30 * u, p['x1'] - 30 * u))
        if r < 0.40:
            return self.start_jump_random()
        if r < 0.52:
            return self.set_state('groom')
        if r < 0.60:
            return self.set_state('stretch')
        if r < 0.70:
            return self.set_state('loaf')
        if r < 0.82:
            return self.start_curious()
        return self.go_idle(random.uniform(2, 5))

    def start_walk(self, tx, speed=None):
        self.tx = tx
        self.wspeed = (speed or random.choice((70, 90, 110, 150))) * (self.u / 1.75)
        self.set_state('walk')

    def start_curious(self):
        """Va s'asseoir près du curseur (saute vers sa plateforme si besoin)."""
        ct, u = self.cat, self.u
        cx, cy = self.cur
        best = None
        for p in self.plats:
            if p['x0'] - 60 <= cx <= p['x1'] + 60 and p['y'] >= cy - 20:
                if best is None or p['y'] < best['y']:
                    best = p
        if best is None:
            return self.go_idle(2.0)
        tx = clamp(cx - ct.dir * 70 * u, best['x0'] + 20 * u, best['x1'] - 20 * u)
        if best['key'] == ct.pkey:
            return self.start_walk(tx, 120)
        ok, tx = self.reachable(best, tx)
        if ok:
            self.jump_to = (tx, best['y'])
            self.set_state('jump')
        else:
            self.go_idle(2.0)

    def start_jump_random(self, prefer_win=False):
        ct, u = self.cat, self.u
        cands = []
        for p in self.plats:
            if p['key'] == ct.pkey:
                continue
            x = random.uniform(p['x0'] + 20 * u, p['x1'] - 20 * u)
            ok, tx = self.reachable(p, x)
            if ok:
                cands.append((p, tx))
        if not cands:
            if self.state == 'zoom':
                return
            return self.start_walk(ct.x + random.choice((-1, 1)) * 150 * u)
        if prefer_win:
            wc = [c_ for c_ in cands if c_[0]['key'][0] == 'win']
            if wc:
                cands = wc
        p, tx = random.choice(cands)
        self.jump_to = (tx, p['y'])
        self.set_state('jump')

    # ------------------------------------------------------------------ états
    def st_idle(self, dt):
        ct = self.cat
        self.vx = 0.0
        ct.set_pose(self.idle_pose)
        ct.eyes = 'open'
        if self.hunger > 0.75 and random.random() < dt * 0.06:
            self.sound('meow')
        hx = ct.T(ct.P['hdx'], 0)[0]
        if abs(self.cur[0] - ct.x) > 30 * self.u and self.cspeed < 900:
            ct.dir = 1 if self.cur[0] > ct.x else -1                 # se tourne vers le curseur
        if self.state_t > self.idle_for:
            self.decide_trait()
        self.check_defend()

    CALM = ('idle', 'walk', 'loaf', 'groom', 'stretch', 'follow')

    def pointer_sense(self, dt, click_near):
        """Ce que fait le pointeur, et comment il reagit :
        - clic pres de lui (pas dessus) : il bondit sur l'endroit du clic ;
        - pointeur qui tourne en rond autour de lui : il le suit des yeux... et a le tournis ;
        - pointeur qui passe vite tout pres : il sursaute (le timide s'enfuit, le colerique se fache) ;
        - pointeur immobile juste au-dessus de sa tete : il tente de l'attraper d'un coup de patte ;
        - longue caresse : il s'endort de bonheur.
        Son caractere change la frequence (joueur, curieux, timide, paresseux...)."""
        ct, u, L = self.cat, self.u, self.life
        st = self.state
        if self.paused or self.menu_open or L.egg_t is not None:
            return
        has = L.has
        hx, hy = ct.x, ct.y - 30 * u
        dx, dy = self.cur[0] - hx, self.cur[1] - hy
        dist = math.hypot(dx, dy)
        calm = st in self.CALM and ct.pkey is not None and self.now > getattr(self, 'ptr_ok', 0.0)

        # 1) le pointeur tourne autour de lui
        cdx, cdy = self.cur[0] - ct.x, self.cur[1] - (ct.y - 70 * u)      # centre un peu au-dessus de lui (il est souvent au ras du sol)
        cd = math.hypot(cdx, cdy)
        a = math.atan2(cdy, cdx)
        pa = getattr(self, 'ptr_ang', a)
        da = (a - pa + PI) % (2 * PI) - PI
        self.ptr_ang = a
        acc = getattr(self, "ptr_acc", 0.0) * math.exp(-dt * 0.2)
        if 30 * u < cd < 260 * u and self.cspeed > 120:
            acc += da
        self.ptr_acc = acc
        if calm and abs(acc) > 2 * PI * 1.3:
            self.ptr_acc, self.ptr_ok = 0.0, self.now + 6
            self.say('Ouh la la...')
            return self.set_state('dizzy')

        # 2) clic tout pres (sur le bureau ou une fenetre) : il bondit dessus
        if click_near and calm and abs(dx) < 420 * u and -60 * u < (ct.y - self.cur[1]) < 160 * u:
            p_ = 0.85 if has('joueur') else (0.25 if has('paresseux') else 0.55)
            pl = self.cur_plat()
            self.ptr_ok = self.now + 5
            if pl is not None and random.random() < p_:
                tx = clamp(self.cur[0], pl['x0'] + 15 * u, pl['x1'] - 15 * u)
                if abs(tx - ct.x) > 25 * u:
                    self.jump_to = (tx, pl['y'])
                    self.sound('meow')
                    return self.set_state('jump')

        # 3) passage rapide tout pres : sursaut
        k_ = u / 1.75                                             # (vitesses a l'echelle de l'animal)
        if (calm and 650 * k_ < self.cspeed < 1400 * k_ and dist < 120 * u and abs(acc) < PI):
            self.ptr_ok = self.now + 9
            ct.dir = 1 if dx >= 0 else -1
            if has('colerique'):
                return self.set_state('defend')
            self.set_face('wide', 1.4)
            ct.squash = 0.5
            self.words.append(['!', ct.x, ct.y - 80 * u, 0.0])
            if has('timide') or random.random() < 0.25:
                self.start_jump_random()                          # il prefere s'eloigner
            return

        # 4) pointeur immobile juste au-dessus de sa tete : coup de patte
        over = abs(dx) < 70 * u and 8 * u < (hy - self.cur[1]) < 110 * u
        self.ptr_hover = getattr(self, 'ptr_hover', 0.0) + dt if (over and self.cspeed < 25) else 0.0
        if calm and self.ptr_hover > (0.7 if has('curieux') else 1.3):
            self.ptr_hover, self.ptr_ok = 0.0, self.now + 4
            return self.set_state('swat')

        # 5) gratouilles : allers-retours rapides du pointeur sur lui -> il se met sur le dos
        vxc = self.cur[0] - getattr(self, 'ptr_px', self.cur[0])
        self.ptr_px = self.cur[0]
        sc = [t_ for t_ in getattr(self, 'scr_rev', []) if self.now - t_ < 1.3]
        if self.over_cat() and abs(vxc) > 2.5:
            sg = 1 if vxc > 0 else -1
            if sg != getattr(self, 'scr_sg', sg):
                sc.append(self.now)                              # le pointeur vient de changer de sens
            self.scr_sg = sg
        self.scr_rev = sc
        if (len(sc) >= 4 and (st in self.CALM or st in ('pet', 'fchase', 'chase')) and ct.pkey is not None
                and self.now > getattr(self, 'belly_ok', 0.0)):
            self.scr_rev = []
            return self.set_state('belly')

        # 6) longue caresse : il s'endort de bonheur
        if st == 'pet' and self.state_t > 8 and L.energy < 0.8 and ct.pkey is not None:
            self.say('Ronron...')
            self.start_sleep()

    def st_belly(self, dt):
        """Sur le dos, pattes en l'air : on lui gratouille le ventre. Il ronronne et pedale ;
        des qu'on arrete, il se remet sur ses pattes."""
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        sp = ct.poses['stand']
        lift = 36 + sp['sy'] * 0.85 - 8.5 * sp['bt']              # ce qu'il faut descendre pour poser le dos au sol
        if self.sub == 'a':                                       # il roule sur le cote puis sur le dos
            k = clamp(t / 0.45, 0.0, 1.0)
            e = k * k * (3 - 2 * k)
            ct.set_pose('belly', 10)
            ct.spin = -ct.dir * PI * e
            ct.yoff = lift * e - 6 * math.sin(PI * k)
            ct.squash = 0.15 * math.sin(PI * k)
            if k >= 1.0:
                self.sub, self.belly_away = 'b', 0.0
                self.sound('purr')
        elif self.sub == 'b':                                     # pattes en l'air, il se tortille
            ct.spin = -ct.dir * PI + 0.07 * math.sin(t * 5)
            ct.yoff = lift
            scratch = self.over_cat() and self.cspeed > 60
            ct.set_pose('belly2' if (scratch and int(t * 6) % 2) else 'belly', 12 if scratch else 5)
            ct.eyes = 'happy' if scratch else 'open'
            ct.wag = 0.5 if scratch else 0.15
            ct.vib = 0.8 if scratch else 0.3
            self.pet_heart_t = getattr(self, 'pet_heart_t', 0.0) + dt
            if scratch and self.pet_heart_t > 0.6:
                self.pet_heart_t = 0.0
                self.hearts.append([ct.x + random.uniform(-15, 15) * u, ct.y - 40 * u, 0.0])
                if random.random() < 0.4:
                    self.sound('purr')
            if hasattr(self, 'life'):
                self.life.joy = min(1.0, self.life.joy + dt * 0.01)
            self.belly_away = 0.0 if scratch else self.belly_away + dt
            if self.belly_away > (2.5 if self.life.has('paresseux') else 1.4) or t > 25:
                self.sub, self.state_t = 'c', 0.0
        else:                                                     # il se remet sur ses pattes
            k = clamp(t / 0.4, 0.0, 1.0)
            e = k * k * (3 - 2 * k)
            ct.set_pose('stand', 12)
            ct.spin = -ct.dir * PI * (1 - e)
            ct.yoff = lift * (1 - e)
            if k >= 1.0:
                ct.spin, ct.yoff = 0.0, 0.0
                self.belly_ok = self.now + 4
                self.pet_ok = self.now + 1.0
                self.go_idle(random.uniform(1.0, 2.5), 'sit')

    def st_swat(self, dt):
        """Coup de patte sur le pointeur : il suit le curseur, se place a bonne distance,
        se dresse sur ses pattes arriere si le pointeur est haut, s'aplatit s'il est au ras du sol,
        et sa patte avant va toucher le pointeur."""
        ct, u = self.cat, self.u
        t = self.state_t
        cx, cy = self.cur
        ry = (ct.y - cy) / u                                      # hauteur du pointeur au-dessus du sol (unites)
        # posture selon la hauteur du pointeur (avec un peu d'hysteresis)
        pose = getattr(self, 'swat_pose', 'stand')
        if ry > (24 if pose == 'beg' else 29):                    # pointeur un peu haut : il se dresse sur 2 pattes
            pose = 'beg'
        elif ry < (16 if pose == 'crouch' else 11):
            pose = 'crouch'
        else:
            pose = 'stand'
        self.swat_pose = pose
        ct.set_pose(pose, 9)
        Pp = ct.poses[pose]
        # il se tourne vers le pointeur (pas de demi-tour nerveux quand il est juste au-dessus)
        if abs(cx - ct.x) > 12 * u:
            ct.dir = 1 if cx >= ct.x else -1
        # point d'epaule et allonge de la patte
        shx, shy = Pp['sx'], Pp['sy']
        reach = {'beg': 27.0, 'crouch': 24.0}.get(pose, 22.0)
        ty = clamp(-ry, shy - reach, 0.0)
        hx_ = math.sqrt(max(0.0, reach * reach - (ty - shy) ** 2)) * 0.85
        off = shx + max(6.0, hx_)
        if pose == 'beg' or abs(ty - Pp['hdy']) < 14:            # pointeur a hauteur de tete : on le garde devant le museau
            off = max(off, Pp['hdx'] + (13 if pose == 'beg' else 9))
        want_x = cx - ct.dir * off * u                            # ou se placer pour que la patte arrive au pointeur
        p = self.cur_plat()
        if p is not None:
            want_x = clamp(want_x, p['x0'] + 10 * u, p['x1'] - 10 * u)
        d = want_x - ct.x
        k_ = u / 1.75
        self.vx = clamp(d * 7, -330 * k_, 330 * k_) if abs(d) > 3 * u else 0.0
        if abs(self.vx) > 40 * k_ and pose != 'beg':
            ct.set_pose('crouch' if pose == 'crouch' else 'stand', 9)
        # la patte : petits coups secs vers le pointeur
        c = math.cos(ct.yaw)
        strike = max(0.0, math.sin(t * 8.5)) ** 0.6
        if abs(c) > 0.35:
            lx = (cx - ct.x) / (u * c)                           # cible en coordonnees locales
            ly = clamp((cy - ct.y) / u, shy - reach - 4, 2.0)
            dx_, dy_ = lx - shx, ly - shy
            dd = math.hypot(dx_, dy_)
            if dd > reach + 4:                                   # trop loin : la patte se tend au maximum
                lx, ly = shx + dx_ / dd * (reach + 4), shy + dy_ / dd * (reach + 4)
            rx, ry_ = shx + 6, shy - (8 if pose != 'crouch' else 3)   # patte armee, repliee contre le poitrail
            ct.paw_to = (rx + (lx - rx) * strike, ry_ + (ly - ry_) * strike)
            ct.paw = 1.0
        else:
            ct.paw_to = None
            ct.paw = strike
        ct.wag = 0.6
        ct.eyes = 'open'
        # touche !
        if strike > 0.97 and not getattr(self, 'swat_hit', False):
            self.swat_hit = True
            fx, fy = ct.T(*ct.paw_to) if ct.paw_to is not None else (ct.x, ct.y)
            if math.hypot(fx - cx, fy - cy) < 9 * u:
                self.sound('tap')
                self.sparks.append([cx, cy, random.uniform(-30, 30), -random.uniform(10, 40), 0.0, 'star'])
        elif strike < 0.3:
            self.swat_hit = False
        hx, hy = ct.x, ct.y - 30 * u
        top = -ct.poses['beg']['sy'] + 27 + 14                    # au-dela, meme dresse il n'y arrive pas
        gone = abs(cx - ct.x) > 260 * u or ry > top or cy > ct.y + 10 * u
        if t > 6.0 or gone or self.cspeed > 900:
            if self.cspeed > 900 and not gone:
                self.say('Rate !')
            elif ry > top:
                self.say('Trop haut !')
            self.end_swat()

    def end_swat(self):
        ct = self.cat
        ct.paw, ct.paw_to = 0.0, None
        self.swat_pose = 'stand'
        self.vx = 0.0
        self.go_idle(random.uniform(1.0, 2.5), 'sit')

    def check_defend(self):
        ct, u = self.cat, self.u
        if (self.now > self.def_ok and self.cspeed > 1400 and abs(self.cur[0] - ct.x) < 170 * u
                and len(getattr(self, 'scr_rev', ())) < 2 and self.state != 'belly'      # des gratouilles, pas une attaque
                and abs(self.cur[1] - (ct.y - 25 * u)) < 150 * u):
            self.def_ok = self.now + 7
            self.set_state('defend')

    def st_walk(self, dt):
        ct = self.cat
        ct.set_pose('stand')
        d = self.tx - ct.x
        ct.dir = 1 if d >= 0 else -1
        self.vx = ct.dir * self.wspeed
        if abs(d) < 8 * self.u or self.edge:
            self.go_idle(random.uniform(1, 4))
        self.check_defend()

    def st_jump(self, dt):
        ct, u = self.cat, self.u
        tx, ty = self.jump_to
        if self.sub == 'a':                                          # s'accroupit en visant
            ct.set_pose('crouch', 14)
            self.vx = 0.0
            ct.dir = 1 if tx >= ct.x else -1
            ct.wag = 0.4
            if self.state_t > 0.28:
                self.plan_jump(tx, ty)
                self.sub = 'b'
                ct.set_pose('pounce', 16)
        else:
            ct.set_pose('pounce' if self.vy < 200 else 'air', 12)
            if self.state_t > 3.0:
                self.go_idle(0.5)

    def st_fall(self, dt):
        self.cat.set_pose('air', 12)

    def start_sleep(self):
        ct, u = self.cat, self.u
        here = self.cur_plat()
        if here and here['key'][0] == 'win' and random.random() < 0.85:
            return self.go_sleep()                       # il dort là, en haut de la fenêtre
        wins = [p for p in self.plats if p['key'][0] == 'win' and p['key'] != ct.pkey]
        random.shuffle(wins)
        if wins and random.random() < 0.75:
            for p in wins:
                ok, tx = self.reachable(p, random.uniform(p['x0'] + 40 * u, max(p['x0'] + 41 * u, p['x1'] - 40 * u)))
                if ok:
                    self.jump_to = (tx, p['y'])
                    self.then = 'sleep'
                    return self.set_state('jump')
            if ct.pkey == ('ground', 0) and self.start_climb(then='sleep'):   # trop haut pour sauter : il grimpe
                return
        bkp = self.plat(('basket', 0))                         # sinon sur le panier
        if bkp and ct.pkey != bkp['key'] and random.random() < 0.6:
            ok, tx = self.reachable(bkp, self.bk.x)
            if ok:
                self.jump_to = (tx, bkp['y'])
                self.then = 'sleep'
                return self.set_state('jump')
        self.go_sleep()

    def st_sleep(self, dt):
        ct, u = self.cat, self.u
        self.vx = 0.0
        ct.set_pose('edge_sleep' if self.edge_pose else 'sleep', 4)
        ct.eyes = 'closed'
        if self.state_t > 6 and random.random() < dt * 0.5:
            ct.twitch = 1.0                                       # il rêve : les pattes frémissent
        self.zzz_t += dt
        if self.zzz_t > 1.4:
            self.zzz_t = 0.0
            hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
            self.zzz.append([hx + 6 * u, hy - 8 * u, 0.0])
            self.sound('purr')
        near = abs(self.cur[0] - ct.x) < 160 * u and abs(self.cur[1] - ct.y) < 160 * u and self.cspeed > 150
        if near or self.over_cat() or self.cspeed > 1200 or self.state_t > 150:
            self.set_state('stretch')

    def st_stretch(self, dt):
        ct = self.cat
        self.vx = 0.0
        t = self.state_t
        ct.set_pose('stretch', 6)
        ct.eyes = 'closed' if t < 1.6 else 'open'
        ct.yawn = clamp((t - 0.6) / 0.4, 0, 1) if 0.6 < t < 1.8 else 0.0
        if t > 2.4:
            self.go_idle(random.uniform(1, 3), 'stand')

    def st_loaf(self, dt):
        ct = self.cat
        self.vx = 0.0
        ct.set_pose('loaf', 5)
        ct.eyes = 'closed' if int(self.now * 0.7) % 4 == 3 else 'open'
        if abs(self.cur[0] - ct.x) > 30 * self.u and self.cspeed < 900:
            ct.dir = 1 if self.cur[0] > ct.x else -1
        if self.state_t > random.uniform(5, 12) or self.over_cat() and self.cspeed > 300:
            self.go_idle(1.0, 'stand')

    def st_groom(self, dt):
        ct = self.cat
        self.vx = 0.0
        t = self.state_t
        ct.set_pose('sit', 7)
        ct.paw = min(1.0, t / 0.5) if t < 3.2 else max(0.0, (3.8 - t) / 0.6)
        ct.eyes = 'closed' if ct.paw > 0.6 else 'open'
        if t > 3.8:
            self.go_idle(random.uniform(1, 3), 'sit')

    def st_pet(self, dt):
        ct, u = self.cat, self.u
        self.vx = 0.0
        ct.set_pose('sit', 8)
        ct.eyes = 'happy'
        ct.wag = 0.35
        self.pet_heart_t += dt
        if self.pet_heart_t > 0.7:
            self.pet_heart_t = 0.0
            self.hearts.append([ct.x + ct.dir * 10 * u, ct.y - 60 * u, 0.0])
            self.sound('purr')
        if self.state_t > 3.2 and self.over_cat():
            self.knead_then = None
            return self.set_state('knead')
        self.pet_away = 0.0 if self.over_cat() else self.pet_away + dt
        if self.pet_away > 0.7:
            self.pet_ok = self.now + 1.0
            self.go_idle(1.5, 'sit')

    # --- saisie à la main
    def grab(self):
        ct = self.cat
        self.grab_t = self.now
        self.grab_cur = self.cur
        self.set_state('held')

    def st_held(self, dt):
        ct, u = self.cat, self.u
        ct.set_pose('hang', 8)
        ct.eyes = 'open'
        chomp = getattr(self, 'held_chomp', 0.0)
        if chomp > 0:                                            # il mache ce qu'il vient d'attraper
            self.held_chomp = chomp - dt
            ct.yawn = 0.3 + 0.3 * math.sin(chomp * 30)
            ct.eyes = 'happy'
        else:
            hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
            for o in self.prey_list():                           # on l'approche d'une mouche, d'un papillon... : hop !
                if isinstance(o, Toy) and o.kind not in ('fly', 'butterfly', 'mosquito', 'mouse'):
                    continue
                px, py = self.prey_pos(o)
                if math.hypot(px - hx, py - hy) < 40 * u:
                    self.held_eat(o)
                    break
        ct.pkey = None
        self.vx = self.vy = 0.0
        ct.x = self.cur[0]
        ct.y = min(self.cur[1] + 58 * u, self.area[3])
        ct.spin = 0.0
        if not self.getbtn():
            if self.now - self.grab_t < 0.28 and math.hypot(self.cur[0] - self.grab_cur[0], self.cur[1] - self.grab_cur[1]) < 14 * self.s:
                self.click_t = self.now
            self.vx = clamp((self.cur[0] - self.pcur[0]) * 20, -500, 500)
            self.vy = clamp((self.cur[1] - self.pcur[1]) * 20, -600, 300)
            self.set_state('fall')

    def held_eat(self, o):
        ct, u = self.cat, self.u
        if isinstance(o, Fly):
            o.state = 'gone'
            feed = o.feed * 0.9
        else:
            o.state = 'gone'
            self.toys = [x for x in self.toys if x is not o]
            feed = 0.18 if o.kind == 'mouse' else 0.08
        self.hunger = max(0.0, self.hunger - feed)
        if hasattr(self, 'life'):
            self.life.joy = min(1.0, self.life.joy + 0.06)
        self.held_chomp = 0.9
        ct.squash = 0.4
        hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
        for _ in range(5):
            self.sparks.append([hx + random.uniform(-10, 10) * u, hy + random.uniform(-8, 8) * u,
                                random.uniform(-40, 40), -random.uniform(20, 60), 0.0, 'star'])
        self.hearts.append([hx, hy - 20 * u, 0.0])
        self.sound('crunch')
        self.say(random.choice(('Miam !', 'Chope !', 'Hop, avale !')))

    def start_flip(self):
        ct = self.cat
        self.click_t = -9.0
        ct.pkey = None
        self.vx = 0.0
        self.vy = -820 * (self.u / 1.75)
        self.sound('meow')
        self.set_state('flip')

    def st_flip(self, dt):
        ct = self.cat
        ct.set_pose('air', 14)
        ct.spin = ct.dir * 2 * PI * clamp(self.state_t / 0.75, 0.0, 1.0)

    # --- poursuite du pointeur (curseur agité)
    def st_chase(self, dt):
        ct, u = self.cat, self.u
        if self.now - self.last_wig > 1.8:
            self.chase_ok = self.now + 4
            return self.go_idle(1.0, 'sit')
        ct.set_pose('crouch' if abs(self.cur[0] - ct.x) < 90 * u else 'stand', 10)
        d = self.cur[0] - ct.x
        ct.dir = 1 if d >= 0 else -1
        ct.wag = 0.4
        if self.sub == 'a':
            self.vx = ct.dir * 260 * (u / 1.75) if abs(d) > 60 * u else 0.0
            if abs(d) <= 90 * u:
                self.sub = 'b'
                self.state_t_sub = self.now
        elif self.sub == 'b':                                      # (en l'air, on ne recalcule plus le saut)
            self.vx = 0.0
            if self.now - self.state_t_sub > 0.25:
                # bond de chasse : il saute vers le pointeur mais retombe sur son support,
                # sans monter plus haut qu'un vrai saut (il ne s'envole pas vers un curseur en l'air)
                g, k_ = self.g, u / 1.75
                h = clamp(ct.y - self.cur[1], 30 * u, 150 * k_ + 40 * u)
                vy0 = math.sqrt(2 * g * h)
                T = 2 * vy0 / g
                dx = clamp(self.cur[0] - ct.x, -320 * k_, 320 * k_)
                self.vx, self.vy = dx / T, -vy0
                self.jump_to = (ct.x + dx, ct.y)
                ct.pkey = None
                ct.dir = 1 if dx >= 0 else -1
                self.sub = 'c'
        if self.sub == 'c':
            ct.set_pose('pounce', 14)
            if self.grounded():
                self.sub = 'a'

    # ------------------------------------------------------------------ jouets (étape suivante)
    def new_toy(self, held=False, kind=None):
        kind = kind or random.choices(['fly', 'butterfly', 'mouse', 'yarn'], [0.35, 0.15, 0.25, 0.25])[0]
        bk, u = self.bk, self.u
        x, y = bk.x, bk.y - 17 * bk.s
        if kind in ('fly', 'butterfly'):
            obj = Fly(x, y - 10 * u, random.uniform(-PI / 2 - 0.6, -PI / 2 + 0.6), self.s, kind)
            if held:
                obj.state = 'held'
            self.flies.append(obj)
        else:
            obj = Toy(kind, x, y, u)
            obj.vy = -420 * (u / 1.75)
            obj.vx = random.uniform(-120, 120)
            if held:
                obj.state = 'held'
            self.toys.append(obj)
        bk.bounce = 1.0
        self.sound('pop')
        return obj

    def spawn_toy(self, kind=None):
        self.bk.bounce = 1.0
        if len(self.flies) + len(self.toys) >= 4:
            return
        self.new_toy(kind=kind)

    def toy_at(self, x, y):
        for o in self.toys:
            if o.kind in ('yarn', 'mouse') and o.state == 'live':
                if abs(x - o.x) < 24 * self.u and -6 * self.u < (o.y - y) < 26 * self.u:
                    return o
            elif o.kind == 'bowl' and o.state == 'live':                 # la gamelle se prend et se deplace aussi
                if abs(x - o.x) < 24 * self.u and -4 * self.u < (o.y - y) < 18 * self.u:
                    return o
            elif o.kind == 'box' and o.state == 'live':                  # la boite en carton aussi
                if abs(x - o.x) < 27 * self.u and -4 * self.u < (o.y - y) < 27 * self.u:
                    return o
        return None

    def update_hand_toy(self, btn):
        o = self.hand_toy
        if o is None:
            return
        if btn:
            h = self.hand_hist
            h.append((self.now, self.cur[0], self.cur[1]))
            while len(h) > 2 and self.now - h[0][0] > 0.15:
                h.pop(0)
            if isinstance(o, Fly):
                o.x, o.y = self.cur[0], self.cur[1] - 6 * self.s
                o.ang = -PI / 2 + math.sin(self.now * 9) * 0.5
            else:
                o.x, o.y = self.cur[0], self.cur[1] + 8 * self.u
                o.vx = o.vy = 0.0
                o.pkey = None
        else:
            if isinstance(o, Fly):
                o.state = 'fly'
                o.ang = random.uniform(-PI, PI)
            else:
                o.state = 'live'
                h = self.hand_hist
                if o.kind not in ('bowl', 'box') and len(h) >= 2 and h[-1][0] - h[0][0] > 0.02:     # lancer : la pelote part a la vitesse de la main
                    dtw = h[-1][0] - h[0][0]
                    o.vx = clamp((h[-1][1] - h[0][1]) / dtw, -1300, 1300)
                    o.vy = clamp((h[-1][2] - h[0][2]) / dtw, -1300, 700)
                    o.pkey = None
            self.hand_toy = None

    # ------------------------------------------------------------------ physique des jouets
    def toy_phys(self, o, dt):
        l, t, r, b = self.area
        u = self.u
        if o.pkey is not None:
            p = self.plat(o.pkey)
            if p is None:
                o.pkey = None
            else:
                o.x += p['x0'] - o.px0
                o.px0 = p['x0']
                o.y = p['y']
                nx = o.x + o.vx * dt
                if nx < p['x0'] or nx > p['x1']:
                    if o.kind == 'mouse':
                        o.dir = -o.dir
                        nx = clamp(nx, p['x0'], p['x1'])
                        o.vx = -o.vx
                    else:                                         # roule / glisse dans le vide
                        o.pkey = None
                        o.fell = True
                o.x = nx
                if o.pkey is not None:
                    if o.kind == 'yarn':
                        o.vx *= (1 - dt * 0.7)
                    return
        py = o.y
        o.vy += self.g * dt
        o.x += o.vx * dt
        o.y += o.vy * dt
        if o.x < l + 8 * u or o.x > r - 8 * u:
            o.x = clamp(o.x, l + 8 * u, r - 8 * u)
            o.vx = -o.vx * 0.5
        if o.vy >= 0:
            best = None
            for p in self.plats:
                if py <= p['y'] + 3 and o.y >= p['y'] and p['x0'] - 4 * u <= o.x <= p['x1'] + 4 * u:
                    if best is None or p['y'] < best['y']:
                        best = p
            if best is None and o.y > b:
                best = self.plats[0]
            if best is not None:
                o.y = best['y']
                if o.kind == 'cup' and o.fell:                   # la tasse se brise
                    o.state = 'broken'
                    o.landed_t = o.t
                    o.vx = o.vy = 0.0
                    self.sound('clink')
                    for q in range(4):
                        self.sparks.append([o.x + random.uniform(-8, 8), o.y - 8, random.uniform(-50, 50), -random.uniform(40, 120), -q * 0.05, 'star'])
                    return
                if o.kind == 'yarn' and o.vy > 320:              # rebondit
                    o.vy = -o.vy * 0.45
                    o.vx *= 0.8
                    self.sound('tap')
                    return
                o.pkey = best['key']
                o.px0 = best['x0']
                o.vy = 0.0
                if o.kind != 'yarn':
                    o.vx = 0.0

    # ------------------------------------------------------------------ chasse
    def prey_list(self):
        return [f for f in self.flies if f.state == 'fly'] + [o for o in self.toys if o.state == 'live' and o.kind not in ('bowl', 'box')]

    def prey_alive(self, o):
        if o is None:
            return False
        if isinstance(o, Fly):
            return o in self.flies and o.state == 'fly'
        return o in self.toys and o.state == 'live'

    def prey_pos(self, o):
        if isinstance(o, Fly):
            return o.x, o.y
        return o.x, o.y - 7 * self.u

    def plat_under(self, x, y):
        best = None
        for p in self.plats:
            if p['x0'] - 10 <= x <= p['x1'] + 10 and p['y'] >= y - 15 * self.u:
                if best is None or p['y'] < best['y']:
                    best = p
        return best

    def start_hunt(self):
        ct, u = self.cat, self.u
        cands = []
        for o in self.prey_list():
            px, py = self.prey_pos(o)
            pl = self.plat_under(px, py)
            if pl is None:
                continue
            if pl['key'] != ct.pkey:
                ok, tx = self.reachable(pl, px)
                if not ok:
                    continue
            elif ct.y - py > 360 * (u / 1.75):                     # trop haut pour sauter d'ici
                continue
            cands.append((abs(px - ct.x), o, pl))
        if not cands:
            return False
        cands.sort(key=lambda c_: c_[0])
        _, o, pl = cands[0]
        self.prey = o
        self.bats = 0
        px, py = self.prey_pos(o)
        if pl['key'] != ct.pkey:
            self.jump_to = (clamp(px, pl['x0'] + 20 * u, pl['x1'] - 20 * u), pl['y'])
            self.then = 'stalk'
            self.set_state('jump')
        else:
            self.set_state('stalk')
        return True

    def give_up(self, secs=5.0):
        self.hunt_ok = self.now + secs
        self.go_idle(random.uniform(0.6, 1.5), 'sit')

    def st_stalk(self, dt):
        ct, u = self.cat, self.u
        o = self.prey
        if not self.prey_alive(o):
            return self.give_up(2.0)
        px, py = self.prey_pos(o)
        d = px - ct.x
        k = u / 1.75
        if self.sub == 'a':
            ct.set_pose('stand', 10)
            ct.dir = 1 if d >= 0 else -1
            ct.wag = 0.25
            isyarn = isinstance(o, Toy) and o.kind == 'yarn'
            if isyarn and abs(d) < 44 * u and abs(ct.y - o.y) < 40 * u:
                return self.set_state('bat')
            near = abs(d) <= (120 if not isyarn else 60) * u
            sp_ = 235 if (isinstance(o, Toy) and o.kind == 'mouse') else 170
            self.vx = ct.dir * (sp_ if not near else 110) * k if abs(d) > (110 if not isyarn else 40) * u else 0.0
            if not isyarn and abs(d) <= 135 * u and ct.y - py < 340 * k and py - ct.y < 60 * u:
                self.sub, self.sub_t = 'b', self.now
            if self.state_t > 14 or (self.edge and abs(d) > 60 * u):
                return self.give_up(5.0)
        elif self.sub == 'b':                                          # à l'affût : fesses qui frétillent
            ct.set_pose('crouch', 14)
            ct.dir = 1 if d >= 0 else -1
            ct.wag = 0.7
            self.vx = 0.0
            if self.now - self.sub_t > 0.9:
                vx_, vy_ = (o.vx, o.vy) if isinstance(o, Toy) else (math.cos(o.ang) * o.speed, math.sin(o.ang) * o.speed)
                self.plan_jump(px + vx_ * 0.35, py + vy_ * 0.35)
                self.sub = 'c'
                ct.set_pose('pounce', 16)
        else:                                                         # en vol
            ct.set_pose('pounce' if self.vy < 150 else 'air', 12)
            hx, hy = ct.T(ct.P['hdx'] + 6, ct.P['hdy'] + 3)
            if math.hypot(hx - px, hy - py) < 30 * u:
                self.caught(o)

    def caught(self, o):
        ct, u = self.cat, self.u
        self.vx = 0.0
        if isinstance(o, Fly):
            o.state = 'gone'
            self.eat_feed = o.feed * 0.9
            self.sound('crunch')
            self.set_state('eat')
        elif o.kind == 'mouse':
            o.state = 'carried'
            self.carry = o
            self.set_state('carry')
            ct.mouth = lambda c, x, y: draw_mouse(c, x, y + 2 * self.u, self.u, ct.dir, 0.0, True)
        else:
            self.give_up(2.0)

    def st_eat(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('sit', 8)
        ct.eyes = 'closed'
        ct.yawn = 0.35 + 0.3 * math.sin(t * 14)
        ct.look = (ct.look[0], ct.look[1] + 0.4 * math.sin(t * 10))
        if t > 1.7:
            self.hunger = max(0.0, self.hunger - self.eat_feed)
            self.hearts.append([ct.x + ct.dir * 12 * u, ct.y - 62 * u, 0.0])
            self.sound('chirp')
            self.go_idle(random.uniform(1.5, 3), 'sit')

    def st_carry(self, dt):
        ct, u = self.cat, self.u
        o = self.carry
        t = self.state_t
        ct.set_pose('stand', 8)
        ct.eyes = 'open'
        p = self.cur_plat()
        if self.sub == 'a':
            self.tx = (p['x0'] + p['x1']) / 2 if p else ct.x
            self.sub = 'b'
        d = self.tx - ct.x
        ct.dir = 1 if d >= 0 else -1
        self.vx = ct.dir * 85 * (u / 1.75) if abs(d) > 20 * u else 0.0
        if self.edge:
            self.tx = ct.x - ct.dir * 200 * u
        if t > 3.8 and o is not None:                                  # dépose sa « prise » devant l'écran
            hx, hy = ct.T(ct.P['hdx'] + 8, ct.P['hdy'] + 6)
            o.x, o.y = hx, self.cat.y
            o.vx, o.vy = ct.dir * 60, -240 * (u / 1.75)
            o.pkey = None
            o.state = 'live'
            o.t = 0.0
            self.carry = None
            self.hunger = max(0.0, self.hunger - o.feed)
            self.hearts.append([ct.x, ct.y - 62 * u, 0.0])
            self.sound('meow')
            self.hunt_ok = self.now + 6
            self.go_idle(random.uniform(2, 4), 'sit')

    def st_bat(self, dt):
        ct, u = self.cat, self.u
        o = self.prey
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('stand', 10)
        if not self.prey_alive(o):
            return self.give_up(2.0)
        ct.dir = 1 if o.x >= ct.x else -1
        ct.paw = clamp(t / 0.25, 0, 1) if t < 0.5 else max(0.0, (0.75 - t) / 0.25)
        if t > 0.28 and self.sub == 'a':
            self.sub = 'b'
            o.vx = ct.dir * 520 * (u / 1.75)
            o.vy = -300 * (u / 1.75)
            o.pkey = None
            self.sound('tap')
            self.bats += 1
        if t > 0.75:
            if self.bats >= 6:
                return self.give_up(8.0)
            self.set_state('stalk')

    def st_defend(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        if t < 1.5:
            ct.set_pose('arch', 12)
            ct.puff = 1.0
            ct.eyes = 'angry'
            ct.dir = 1 if self.cur[0] >= ct.x else -1
            if self.sub == 'a':
                self.sub = 'b'
                self.sound('hiss')
        else:
            ct.set_pose('stand', 12)
            ct.dir = -1 if self.cur[0] >= ct.x else 1              # s'éloigne du curseur
            self.vx = ct.dir * 300 * (u / 1.75)
            if t > 2.4 or self.edge:
                self.go_idle(random.uniform(1.5, 3), 'sit')

    # ------------------------------------------------------------------ course folle
    def start_zoom(self):
        self.zoom_end = self.now + random.uniform(10, 16)
        self.zjump = self.now
        self.sound('meow')
        self.set_state('zoom')

    def st_zoom(self, dt):
        ct, u = self.cat, self.u
        p = self.cur_plat()
        if self.now > self.zoom_end:
            return self.go_idle(2.0, 'sit')
        if p is None:
            return
        ct.set_pose('stand', 12)
        ct.wag = 0.5
        if self.sub == 'a' or abs(self.tx - ct.x) < 12 * u or self.edge:
            self.sub = 'b'
            for _ in range(8):
                self.tx = random.uniform(p['x0'] + 20 * u, p['x1'] - 20 * u)
                if abs(self.tx - ct.x) > 200 * u:
                    break
        ct.dir = 1 if self.tx >= ct.x else -1
        self.vx = ct.dir * 650 * (u / 1.75)                       # course folle : vraiment vite
        if self.now - self.zjump > 0.9 and random.random() < dt * 1.3:
            self.zjump = self.now
            if ct.pkey == ('ground', 0) and random.random() < 0.55 and self.start_climb(then='zoom'):
                return                                              # il grimpe a une fenetre en pleine course
            self.then = 'zoom'
            self.start_jump_random(prefer_win=True)                 # ou saute d'une fenetre a l'autre

    # ------------------------------------------------------------------ se cache derriere la fenetre du dessus
    def rim_window(self):
        for hw, wl, wt, wr, wb in self.windows:                  # de la plus haute a la plus basse
            if wr - wl >= 250 and wt > self.area[1] + 75 * self.u:
                return (hw, wl, wt, wr, wb)
        return None

    def start_rim(self):
        w = self.rim_window()
        ct, u = self.cat, self.u
        if w is None:
            return False
        hw, wl, wt, wr, wb = w
        self.rim = dict(hw=hw, x=random.uniform(wl + 70 * u, wr - 70 * u), n=random.randint(2, 4), k=0, dur=3.0)
        if ct.pkey == ('win', hw):
            self.set_state('rim_go')
            return True
        p = self.plat(('win', hw))
        if p is not None:
            ok, tx = self.reachable(p, self.rim['x'])
            if ok:
                self.jump_to = (tx, p['y'])
                self.then = 'rim'
                self.set_state('jump')
                return True
        if ct.pkey == ('ground', 0):
            if self.start_climb(then='rim', only=hw):
                return True
        elif ct.pkey is not None:                                # trop haut pour sauter : il redescend d'abord au sol
            self.jump_to = (ct.x, self.area[3])
            self.then = 'rim'
            self.set_state('jump')
            return True
        self.rim = None
        return False

    def st_rim_go(self, dt):
        ct, u = self.cat, self.u
        r = self.rim
        p = self.cur_plat()
        if r is None or r['hw'] not in self.win_by or p is None or p['key'] != ('win', r['hw']):
            return self.go_idle(0.5)
        d = r['x'] - ct.x
        ct.set_pose('stand')
        ct.dir = 1 if d >= 0 else -1
        self.vx = ct.dir * 130 * (u / 1.75) if abs(d) > 6 * u else 0.0
        if abs(d) <= 6 * u or self.edge:
            self.vx = 0.0
            self.set_state('rim')

    def rim_leave(self):
        """Remonte sur le dessus de la fenetre (ou tombe si elle a disparu)."""
        ct, u = self.cat, self.u
        r = self.rim
        self.rim = None
        p = self.plat(('win', r['hw'])) if r else None
        if p is not None:
            ct.pkey = p['key']
            ct.px0 = p['x0']
            ct.y = p['y']
            ct.x = clamp(ct.x, p['x0'] + 6 * u, p['x1'] - 6 * u)
            ct.squash = 0.25
            self.go_idle(random.uniform(1.5, 3), 'sit')
        else:
            self.vx = self.vy = 0.0
            self.set_state('fall')

    def st_rim(self, dt):
        ct, u = self.cat, self.u
        r = self.rim
        w = self.win_by.get(r['hw']) if r else None
        rw = self.rim_window()
        if w is None or rw is None or rw[0] != r['hw']:          # la fenetre a bouge, disparu ou n'est plus au-dessus
            return self.rim_leave()
        wl, wt, wr, wb = w
        ct.pkey = None
        self.vx = self.vy = 0.0
        ct.x = clamp(r['x'], wl + 30 * u, wr - 30 * u)
        ct.dir = 1
        t = self.now - self.sub_t
        if self.sub == 'a':                                      # il passe de l'autre cote du rebord
            k = clamp(self.state_t / 0.5, 0.0, 1.0)
            ct.y = wt + 34 * u * k
            ct.set_pose('rim_hide', 10)
            if k >= 1.0:
                self.sub, self.sub_t = 'h', self.now
                r['dur'] = random.uniform(2.0, 4.5)
        elif self.sub == 'h':                                    # seules les pattes avant tiennent le rebord
            ct.y = wt + 34 * u
            ct.set_pose('rim_hide', 10)
            if t > r['dur']:
                if r['k'] >= r['n']:
                    self.sub, self.sub_t = 'o', self.now
                else:
                    r['k'] += 1
                    self.sub, self.sub_t = 'p', self.now
                    r['dur'] = random.uniform(2.5, 5.0)
        elif self.sub == 'p':                                    # la tete apparait, regarde autour
            ct.y = wt + 34 * u
            ct.set_pose('rim_peek', 9)
            if int(t * 0.7) != int((t - dt) * 0.7):
                ct.ear = 1.0
            if t > r['dur'] or (self.cspeed > 1600 and abs(self.cur[0] - ct.x) < 260 * u):
                self.sub, self.sub_t = 'h', self.now
                r['dur'] = random.uniform(1.5, 4.0)
        else:                                                    # fin : il remonte sur la fenetre
            k = clamp(t / 0.45, 0.0, 1.0)
            ct.y = wt + 34 * u * (1 - k)
            ct.set_pose('rim_peek', 12)
            if k >= 1.0:
                self.rim_leave()

    # ------------------------------------------------------------------ escalade du bord d'une fenêtre
    def start_climb(self, then=None, only=None):
        ct, u = self.cat, self.u
        if ct.pkey != ('ground', 0):
            return False
        l, t, r, b = self.area
        opts = []
        for hw, wl, wt, wr, wb in self.windows:
            if wr - wl < 250 or wt < t + 70 * u or (only is None and (wt < t + 120 * u or wb < b - 100 * u)) or (only is not None and hw != only):
                continue
            if wl - 18 * u > l + 10 * u:
                opts.append((hw, -1))                              # bord gauche
            if wr + 18 * u < r - 10 * u:
                opts.append((hw, 1))                               # bord droit
        if not opts:
            return False
        hw, side = random.choice(opts)
        self.climb = dict(hw=hw, side=side)
        self.then_climb = then
        self.set_state('climb_go')
        return True

    def chips(self, n=3):
        ct = self.cat
        fx, fy = ct.feet_pos()[0]
        px, py = ct.T(fx, fy)
        for _ in range(n):
            self.sparks.append([px, py, random.uniform(-40, 40), random.uniform(-90, -20), 0.0, 'chip'])

    def st_climb_go(self, dt):
        ct, u = self.cat, self.u
        c = self.climb
        w = self.win_by.get(c['hw'])
        if w is None:
            return self.go_idle(0.5)
        wl, wt, wr, wb = w
        side = c['side']
        tx = wl - 73 * u if side < 0 else wr + 73 * u              # prend son élan à quelques pas du bord
        d = tx - ct.x
        ct.set_pose('stand')
        ct.dir = 1 if d >= 0 else -1
        self.vx = ct.dir * (480 if self.then_climb == 'zoom' else 170) * (u / 1.75) if abs(d) > 6 * u else 0.0
        if abs(d) <= 6 * u:
            self.vx = 0.0
            ct.dir = 1 if side < 0 else -1
            self.set_state('climb')
        elif self.edge:
            self.go_idle(0.5)

    def st_climb(self, dt):
        """Grimpe a la fenetre comme un chat grimpe a un arbre : s'accroupit, bondit haut sur le bord,
        monte par bonds (les pattes arriere poussent, les pattes avant vont s'agripper plus haut),
        glisse parfois un peu, puis se hisse par-dessus le rebord en pedalant des pattes arriere."""
        ct, u = self.cat, self.u
        c = self.climb
        w = self.win_by.get(c['hw'])
        if w is None:                                              # la fenetre a disparu : il tombe
            ct.spin = 0.0
            ct.climbing = False
            ct.climb_scr = 0.0
            ct.pkey = None
            self.vx = self.vy = 0.0
            return self.set_state('fall')
        wl, wt, wr, wb = w
        side = c['side']
        wd = 1 if side < 0 else -1
        wall_x = wl if side < 0 else wr
        xw = wall_x - wd * 18 * u
        ct.dir = wd
        ct.pkey = None
        self.vx = self.vy = 0.0
        t = self.state_t
        zoom = self.then_climb == 'zoom'
        if self.sub == 'a':                                        # s'accroupit face a l'« arbre », l'arriere-train qui frétille
            ct.set_pose('crouch', 14)
            ct.wag = 0.7
            ct.x += math.sin(t * 40) * 0.25 * u * (t > 0.25)
            if t > (0.25 if zoom else 0.5):
                self.sub, self.sub_t = 'a2', self.now
                c['x0'], c['y0'] = ct.x, ct.y
        elif self.sub == 'a2':                                     # grand bond : il atterrit haut sur le bord, toutes griffes dehors
            k = clamp((self.now - self.sub_t) / 0.38, 0.0, 1.0)
            e = k * k * (3 - 2 * k)
            ct.set_pose('pounce', 16)
            hj = min(70 * u, max(20 * u, c['y0'] - (wt + 60 * u)))   # hauteur du bond (jamais au-dessus du sommet)
            ct.x = c['x0'] + (xw - c['x0']) * e
            ct.y = c['y0'] - hj * e - 26 * u * math.sin(PI * k)
            ct.spin = -PI / 2 * e
            if k >= 1.0:
                self.sub = 'b'
                ct.climb_ph = 0.5                                  # griffes avant plantees, l'arriere remonte
                ct.climb_scr = 0.0
                c['yb'] = ct.y                                     # position du corps au debut du cycle
                c['slip'] = 0.0
                ct.squash = 0.35
                self.sound('tap')
                self.chips(5)
        elif self.sub == 'b':                                      # montee par bonds
            ct.set_pose('stand', 10)
            ct.climbing = True
            ct.x = xw
            ct.spin = -PI / 2 + 0.05 * math.sin(ct.climb_ph * 2 * PI)   # le corps tangue un peu a chaque bond
            period = 0.42 if zoom else 0.68
            if getattr(self, 'life', None) is not None and self.life.has('paresseux'):
                period *= 1.25
            ph0 = ct.climb_ph
            ct.climb_ph += dt / period
            if int(ct.climb_ph) != int(ph0):                       # nouveau cycle : le corps repart de plus haut
                c['yb'] -= ct.CLIMB_STEP * u
                if not zoom and random.random() < 0.12:            # petite glissade : les griffes lachent un instant
                    c['slip'] = 1.0
                    self.sound('tap')
                    self.chips(6)
                    if random.random() < 0.5:
                        self.say(random.choice(('Oups !', 'Hop hop !')))
            ph = ct.climb_ph % 1.0
            c['slip'] = max(0.0, c.get('slip', 0.0) - dt * 2.2)
            sl = c['slip']
            drop = 9 * u * math.sin(PI * sl) if sl > 0 else 0.0   # il glisse, puis se rattrape
            ct.y = c['yb'] - ct.CLIMB_STEP * u * ct.climb_rise(ph) + drop
            if ct.plant_n != getattr(self, 'prev_plant', 0):       # les griffes s'agrippent : eclats
                self.chips(2)
            self.prev_plant = ct.plant_n
            ct.wag = 0.3
            if ct.y <= wt + 34 * u and ph >= 0.5:                  # les pattes avant atteignent le rebord
                self.sub, self.sub_t = 'c', self.now
                c['x0'], c['y0'] = ct.x, ct.y
        elif self.sub == 'c':                                      # se hisse : pattes avant sur le rebord, l'arriere pedale
            k = clamp((self.now - self.sub_t) / 0.45, 0.0, 1.0)
            ct.climbing = True
            ct.climb_scr = min(1.0, k * 4)
            ct.x = xw
            ct.spin = -PI / 2
            ct.y = c['y0'] - 12 * u * k + math.sin(k * 30) * 0.6 * u
            if int(k * 6) != int(clamp((self.now - dt - self.sub_t) / 0.45, 0.0, 1.0) * 6):
                self.chips(1)
            if k >= 1.0:
                self.sub, self.sub_t = 'd', self.now
                c['x0'], c['y0'] = ct.x, ct.y
                ct.climbing = False
                ct.climb_scr = 0.0
        else:                                                      # bascule par-dessus le rebord
            k = clamp((self.now - self.sub_t) / 0.4, 0.0, 1.0)
            tx = wl + 34 * u if side < 0 else wr - 34 * u
            ct.set_pose('air', 12)
            ct.x = c['x0'] + (tx - c['x0']) * k
            ct.y = c['y0'] + (wt - c['y0']) * k - 12 * u * math.sin(PI * k)
            ct.spin = -PI / 2 * (1 - k * k * (3 - 2 * k))
            if k >= 1.0:
                ct.spin = 0.0
                p = self.plat(('win', c['hw']))
                nxt, self.then_climb = self.then_climb, None
                if p:
                    ct.pkey = p['key']
                    ct.px0 = p['x0']
                    ct.y = p['y']
                    ct.x = clamp(ct.x, p['x0'] + 6 * u, p['x1'] - 6 * u)
                    ct.squash = 0.3
                    self.sound('tap')
                    if nxt == 'sleep':
                        return self.go_sleep()
                    if nxt == 'rim' and self.rim is not None:
                        return self.set_state('rim_go')
                    if nxt == 'zoom' and self.now < self.zoom_end:
                        self.zjump = self.now
                        return self.set_state('zoom')               # la course folle continue en haut
                    if random.random() < 0.5:
                        self.say(random.choice(('Ta-da !', 'Facile.', 'Je suis le roi !')))
                    return self.go_idle(random.uniform(2, 4), 'sit')
                self.vy = 0.0
                self.set_state('fall')

    # ------------------------------------------------------------------ fait ses griffes dans un coin
    def start_scratch(self):
        ct, u = self.cat, self.u
        if ct.pkey != ('ground', 0):
            return False
        l, t, r, b = self.area
        opts = [(l + 20 * u, -1), (r - 20 * u, 1)]                 # coins de l'écran
        for hw, wl, wt, wr, wb in self.windows:
            if wb >= b - 100 * u and wr - wl >= 250:               # pied d'une fenêtre
                if wl - 20 * u > l + 30 * u:
                    opts.append((wl - 20 * u, 1))
                if wr + 20 * u < r - 30 * u:
                    opts.append((wr + 20 * u, -1))
        self.scr = random.choice(opts)
        self.set_state('scratch_go')
        return True

    def st_scratch_go(self, dt):
        ct, u = self.cat, self.u
        x, dr = self.scr
        d = x - ct.x
        ct.set_pose('stand')
        ct.dir = 1 if d >= 0 else -1
        self.vx = ct.dir * 170 * (u / 1.75) if abs(d) > 6 * u else 0.0
        if abs(d) <= 6 * u or self.edge:
            self.vx = 0.0
            self.set_state('scratch')

    def st_scratch(self, dt):
        ct, u = self.cat, self.u
        x, dr = self.scr
        t = self.state_t
        ct.dir = dr
        self.vx = 0.0
        ct.set_pose('scratch', 8)
        ct.eyes = 'closed' if int(t * 1.3) % 3 == 2 else 'open'
        if int(t * 5.5) != int((t - dt) * 5.5):
            self.sound('crunch')
            hx, hy = ct.T(ct.P['hdx'] + 14, ct.P['hdy'] + 14)
            self.sparks.append([hx, hy, ct.dir * 30, 20, 0.0, 'star'])
        if t > 6.5:
            self.set_state('stretch')

    # ------------------------------------------------------------------ sommeil : pétrissage, puis dodo (parfois au bord d'une fenêtre)
    def go_sleep(self):
        ct, u = self.cat, self.u
        p = self.cur_plat()
        if p and p['key'][0] == 'win' and p['x1'] - p['x0'] > 140 * u and random.random() < 0.5:
            self.edge_pose = True
            self.edge_next = 'sleep'
            self.edge_target = (p['x1'] - 24 * u) if random.random() < 0.5 else (p['x0'] + 24 * u)
            return self.set_state('edge_go')
        self.edge_pose = False
        if random.random() < 0.75:
            return self.start_knead('sleep')
        self.set_state('sleep')

    def start_knead(self, then=None):
        self.knead_then = then
        self.knead_dur = random.uniform(3.2, 5.0)
        self.set_state('knead')

    def st_knead(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('knead', 8)
        ct.eyes = 'closed' if t > 0.8 else 'open'
        ct.wag = 0.1
        if int(t * 1.1) != int((t - dt) * 1.1):
            self.sound('purr')
            self.hearts.append([ct.x + ct.dir * 10 * u, ct.y - 55 * u, 0.0])
        if t > self.knead_dur:
            nxt, self.knead_then = self.knead_then, None
            if nxt == 'sleep':
                self.edge_pose = False
                return self.set_state('sleep')
            self.go_idle(random.uniform(1.5, 3), 'sit')

    def st_edge_go(self, dt):
        ct, u = self.cat, self.u
        p = self.cur_plat()
        if p is None:
            return self.go_idle(0.5)
        d = self.edge_target - ct.x
        ct.set_pose('stand')
        ct.dir = 1 if d >= 0 else -1
        self.vx = ct.dir * 110 * (u / 1.75) if abs(d) > 5 * u else 0.0
        if abs(d) <= 5 * u or self.edge:
            self.vx = 0.0
            ct.dir = 1 if self.edge_target > (p['x0'] + p['x1']) / 2 else -1     # face au vide
            if self.edge_next == 'peek':
                return self.set_state('peek')
            self.edge_pose = True
            self.set_state('sleep')
            self.edge_pose = True

    def start_peek(self):
        ct, u = self.cat, self.u
        p = self.cur_plat()
        if not p or p['x1'] - p['x0'] < 140 * u:
            return False
        self.edge_next = 'peek'
        self.edge_target = (p['x1'] - 22 * u) if random.random() < 0.5 else (p['x0'] + 22 * u)
        self.set_state('edge_go')
        return True

    def st_peek(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('peek', 8)
        ct.look = (0.2, 0.95)
        ct.wag = 0.3
        if t > 4.5:
            self.go_idle(random.uniform(1.5, 3), 'sit')

    # ------------------------------------------------------------------ salut : clignement lent vers l'écran
    def st_greet(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('sit', 8)
        ct.eyes = 'closed' if (0.9 < t < 1.5 or 2.7 < t < 3.3) else 'open'
        ct.wag = 0.2
        if self.sub == 'a' and t > 0.5:
            self.sub = 'b'
            self.sound('meow')
        if t > 4.2:
            self.hearts.append([ct.x, ct.y - 70 * u, 0.0])
            self.go_idle(random.uniform(2, 4), 'sit')

    # ------------------------------------------------------------------ se frotte contre le curseur
    def start_rub(self):
        ct, u = self.cat, self.u
        p = self.cur_plat()
        if not p or self.cspeed > 80:
            return False
        cx, cy = self.cur
        if abs(cx - ct.x) > 320 * (u / 1.75) or abs(cy - (ct.y - 22 * u)) > 75 * u:
            return False
        if not (p['x0'] + 30 * u < cx < p['x1'] - 30 * u):
            return False
        self.rub_dir = 1 if cx >= ct.x else -1
        self.set_state('rub_go')
        return True

    def st_rub_go(self, dt):
        ct, u = self.cat, self.u
        cx = self.cur[0]
        tx = cx - self.rub_dir * 22 * u
        d = tx - ct.x
        ct.set_pose('stand')
        ct.dir = 1 if d >= 0 else -1
        self.vx = ct.dir * 130 * (u / 1.75) if abs(d) > 5 * u else 0.0
        if self.cspeed > 400 or abs(self.cur[1] - (ct.y - 22 * u)) > 110 * u or self.edge:
            return self.go_idle(1.0, 'sit')
        if abs(d) <= 5 * u:
            self.vx = 0.0
            ct.dir = self.rub_dir
            self.set_state('rub')

    def st_rub(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        p = self.cur_plat()
        ct.dir = self.rub_dir
        ct.set_pose('rub', 8)
        ct.eyes = 'happy' if int(t * 0.8) % 2 else 'closed'
        ct.wag = 0.2
        self.vx = 0.0
        if p is not None:                                         # la tête vient se coller au curseur et le pousse
            ct.x = clamp(self.cur[0] - ct.dir * (21 * u) + ct.dir * 5 * u * math.sin(t * 4.5), p['x0'] + 8 * u, p['x1'] - 8 * u)
        if int(t * 1.3) != int((t - dt) * 1.3):
            self.hearts.append([self.cur[0], ct.y - 65 * u, 0.0])
            self.sound('purr')
        if self.cspeed > 500 or abs(self.cur[1] - (ct.y - 22 * u)) > 110 * u or t > 5.5:
            self.go_idle(random.uniform(1.5, 3), 'sit')

    # ------------------------------------------------------------------ court après sa queue, puis a le tournis
    def start_tailchase(self):
        self.set_state('tailchase')

    def st_tailchase(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('stand', 10)
        ct.eyes = 'open'
        ct.free_spin = 7.5
        ct.wag = 0.6
        if t > 4.6:
            self.set_state('dizzy')

    def st_dizzy(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('sit', 8)
        ct.eyes = 'closed' if int(t * 3) % 2 else 'open'
        ct.look = (math.sin(t * 6) * 0.8, 0.2)
        if int(t * 4) != int((t - dt) * 4):
            hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'] - 14)
            a = t * 6
            self.sparks.append([hx + math.cos(a) * 14 * u, hy + math.sin(a) * 4 * u, 0, -8, 0.0, 'star'])
        if t > 2.4:
            self.go_idle(random.uniform(1.5, 3), 'sit')

    # ------------------------------------------------------------------ deuxième chat
    def toggle_buddy(self):
        self.buddy_on = not self.buddy_on
        self.ensure_buddy()

    def ensure_buddy(self):
        if self.buddy_on and self.buddy is None:
            i = COAT_ORDER.index(self.cat.coat) if self.cat.coat in COAT_ORDER else 0
            self.buddy = Buddy(self, COAT_ORDER[(i + 3) % len(COAT_ORDER)])
        elif not self.buddy_on:
            self.buddy = None
            self.social = None

    def social_tick(self, dt):
        b = self.buddy
        ct, u = self.cat, self.u
        if self.social is None:
            if (self.now >= self.social_ok and self.state in ('idle', 'loaf', 'stretch') and b.state in ('idle', 'walk')
                    and ct.pkey is not None and ct.pkey == b.cat.pkey
                    and abs(b.cat.x - ct.x) < 500 * (u / 1.75) and random.random() < dt * 0.15):
                self.start_social()
            return
        kind, t_end = self.social
        done = self.now >= t_end
        if kind == 'groom' and self.state == 'groomed' and b.state not in ('groom_other',):
            done = True
        if kind == 'nap' and self.state != 'sleep' and self.now > t_end - 117:
            done = True
        if done:
            self.end_social()

    def start_social(self):
        b, ct = self.buddy, self.cat
        kind = random.choice(('groom', 'groom', 'nap', 'play'))
        if kind == 'groom':
            self.social = ('groom', self.now + 14)
            self.set_state('groomed')
            b.set('groom_other')
        elif kind == 'nap':
            self.social = ('nap', self.now + 120)
            self.set_state('sleep')
            b.set('nap_go')
        else:
            self.social = ('play', self.now + 9)
            self.start_zoom()
            self.zoom_end = self.now + 8
            b.zoom_end = self.now + 8
            b.set('zoom')

    def end_social(self):
        b = self.buddy
        self.social = None
        self.social_ok = self.now + random.uniform(45, 90)
        if b is not None and b.state in ('groom_other', 'nap_go', 'zoom'):
            b.idle(1.0)
        if self.state == 'groomed':
            self.go_idle(1.5, 'sit')

    def st_groomed(self, dt):
        ct, u = self.cat, self.u
        b = self.buddy
        self.vx = 0.0
        ct.set_pose('sit', 8)
        ct.eyes = 'closed'
        if b is not None:
            ct.dir = 1 if b.cat.x >= ct.x else -1
        if self.state_t > 12:
            self.go_idle(1.5, 'sit')

    # ------------------------------------------------------------------ boîte en carton
    def place_box(self):
        l, t, r, b = self.area
        u = self.u
        if self.box_obj is not None:
            self.toys = [o for o in self.toys if o is not self.box_obj]
        cx = clamp(self.cur[0], l + 60, r - 60)
        pl = self.plat_under(cx, self.cur[1]) or self.plats[0]
        o = Toy('box', clamp(cx, pl['x0'] + 40, pl['x1'] - 40), min(self.cur[1], pl['y'] - 40 * u), u)
        o.life = 1e9
        self.toys.append(o)
        self.box_obj = o
        self.sound('pop')

    def start_box(self):
        ct, u = self.cat, self.u
        o = self.box_obj
        pl = self.plat_under(o.x, o.y - 5)
        if pl is None:
            return False
        if pl['key'] != ct.pkey:
            ok, tx = self.reachable(pl, o.x)
            if not ok:
                return False
            self.jump_to = (clamp(o.x - 40 * u, pl['x0'] + 20 * u, pl['x1'] - 20 * u), pl['y'])
            self.then = 'box'
            self.set_state('jump')
            return True
        self.set_state('box_go')
        return True

    def st_box_go(self, dt):
        ct, u = self.cat, self.u
        o = self.box_obj
        if o is None:
            return self.go_idle(0.5)
        d = o.x - ct.x
        ct.set_pose('stand')
        ct.dir = 1 if d >= 0 else -1
        if o.state != 'live':
            return self.go_idle(0.5)
        self.vx = ct.dir * 150 * (u / 1.75) if abs(d) > 5 * u else 0.0
        if abs(d) <= 5 * u or self.edge or self.state_t > 12:
            self.vx = 0.0
            self.set_state('box')

    def st_box(self, dt):
        ct, u = self.cat, self.u
        o = self.box_obj
        t = self.state_t
        self.vx = 0.0
        if o is None or o.state != 'live':                        # on lui deplace la boite : il en sort
            ct.yoff = 0.0
            return self.go_idle(0.5)
        ct.x = o.x
        ct.yoff = -6.0
        ct.set_pose('loaf', 8)
        sleepy = self.sub == 'z'
        ct.eyes = 'closed' if sleepy else 'open'
        if not sleepy and t > 6 and random.random() < dt * 0.15:
            self.sub = 'z'                                       # il s'endort dans la boîte
        if sleepy:
            self.zzz_t += dt
            if self.zzz_t > 1.5:
                self.zzz_t = 0.0
                hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
                self.zzz.append([hx + 6 * u, hy - 8 * u, 0.0])
                self.sound('purr')
        prey = self.prey_list()
        if prey and not sleepy:                                    # embuscade : il bondit de la boîte sur une proie
            for q in prey:
                if abs(q.x - ct.x) < 450 * (u / 1.75) and random.random() < dt * 1.5:
                    ct.yoff = 0.0
                    self.hunt_ok = 0.0
                    if self.start_hunt():
                        return
        if self.now > self.found_ok and self.cspeed < 500 and (self.over_cat() or self.hover_toy is o):
            return self.set_state('found')                         # on l'a decouvert !
        if t > 16 or (self.over_cat() and self.cspeed > 600):
            ct.yoff = 0.0
            self.go_idle(random.uniform(1.5, 3), 'sit')

    # ------------------------------------------------------------------ gamelle : « Donner à manger »
    def place_bowl(self):
        l, t, r, b = self.area
        u = self.u
        if self.bowl is not None:
            self.toys = [o for o in self.toys if o is not self.bowl]
        cx = clamp(self.cur[0], l + 40, r - 40)
        pl = self.plat_under(cx, self.cur[1]) or self.plats[0]
        o = Toy('bowl', clamp(cx, pl['x0'] + 20, pl['x1'] - 20), min(self.cur[1], pl['y'] - 30 * u), u)
        o.life = 1e9
        o.food = 1.0
        o.empty_t = 0.0
        self.toys.append(o)
        self.bowl = o
        self.feed_ok = 0.0
        self.sound('pop')

    def start_feed(self):
        ct, u = self.cat, self.u
        o = self.bowl
        pl = self.plat_under(o.x, o.y - 5)
        if pl is None:
            return False
        if pl['key'] != ct.pkey:
            ok, tx = self.reachable(pl, o.x)
            if not ok:
                return False
            self.jump_to = (clamp(o.x - 40 * u, pl['x0'] + 20 * u, pl['x1'] - 20 * u), pl['y'])
            self.then = 'feed'
            self.set_state('jump')
            return True
        self.set_state('feed_go')
        return True

    def st_feed_go(self, dt):
        ct, u = self.cat, self.u
        o = self.bowl
        if o is None or o.food <= 0 or o.state != 'live':
            return self.go_idle(0.5)
        d = (o.x - 22 * u * (1 if o.x >= ct.x else -1)) - ct.x
        ct.set_pose('stand')
        ct.dir = 1 if o.x >= ct.x else -1
        self.vx = ct.dir * 170 * (u / 1.75) if abs(d) > 6 * u else 0.0
        if abs(d) <= 6 * u or self.edge or self.state_t > 12:
            self.vx = 0.0
            self.eat_t0 = self.now
            self.set_state('feed')

    def st_feed(self, dt):
        ct, u = self.cat, self.u
        o = self.bowl
        t = self.state_t
        self.vx = 0.0
        if o is None or o.state != 'live':                        # on lui a pris la gamelle
            return self.go_idle(0.5)
        ct.dir = 1 if o.x >= ct.x else -1
        ct.set_pose('eat_low', 8)
        ct.eyes = 'closed' if int(t * 2) % 2 else 'open'
        ct.yawn = 0.25 + 0.25 * math.sin(t * 16)
        ct.wag = 0.15
        if int(t * 2.5) != int((t - dt) * 2.5):
            self.sound('crunch')
        o.food = max(0.0, 1.0 - t / 5.0)
        if t > 5.0:
            o.food = 0.0
            o.empty_t = self.now
            self.hunger = max(0.0, self.hunger - 0.85)
            self.hearts.append([ct.x + ct.dir * 14 * u, ct.y - 62 * u, 0.0])
            self.sound('meow')
            self.go_idle(random.uniform(2, 4), 'sit')

    # ------------------------------------------------------------------ proies spontanées (mouches, souris qui traversent l'écran)
    def spawn_ambient(self):
        l, t, r, b = self.area
        u = self.u
        kind = random.choices(['fly', 'mouse', 'butterfly', 'mosquito'], [0.38, 0.40, 0.12, 0.10])[0]
        side = random.choice((-1, 1))
        if kind == 'mouse':
            o = Toy('mouse', l + 12 if side < 0 else r - 12, b, u)
            o.transit = True
            o.dir = -side
            o.pkey = ('ground', 0)
            o.px0 = l + 4
            o.life = 70
            self.toys.append(o)
        else:
            y = random.uniform(max(t + 100, b - 520 * (u / 1.75)), b - 90)
            self.flies.append(Fly(l + 6 if side < 0 else r - 6, y, 0.0 if side < 0 else PI, self.s, kind))

    # ------------------------------------------------------------------ gag : fait tomber une tasse
    def start_knock(self):
        ct, u = self.cat, self.u
        p = self.cur_plat()
        if not p:
            return False
        for dirn in (ct.dir, -ct.dir):
            cx = ct.x + dirn * 70 * u
            if p['x0'] + 30 * u < cx < p['x1'] - 30 * u:
                self.cup = Toy('cup', cx, p['y'], u)
                self.cup.pkey = p['key']
                self.cup.px0 = p['x0']
                self.cup.life = 1e9
                self.knock_dir = dirn
                self.set_state('knock')
                return True
        return False

    def st_knock(self, dt):
        ct, u = self.cat, self.u
        cup = self.cup
        t = self.state_t
        if cup is None:
            return self.go_idle(1.0, 'sit')
        ct.dir = self.knock_dir
        k = u / 1.75
        if self.sub == 'a':                                             # s'approche de la tasse
            ct.set_pose('stand', 10)
            d = cup.x - ct.x
            self.vx = ct.dir * 90 * k if abs(d) > 38 * u else 0.0
            if abs(d) <= 38 * u:
                self.sub, self.sub_t = 'b', self.now
        elif self.sub == 'b':                                           # la fixe, puis te regarde
            self.vx = 0.0
            ct.set_pose('sit', 8)
            if self.now - self.sub_t > 1.2:
                self.sub, self.sub_t = 'c', self.now
        elif self.sub == 'c':                                           # petit coup de patte
            ct.set_pose('sit', 8)
            ct.paw = clamp((self.now - self.sub_t) / 0.3, 0, 1)
            if self.now - self.sub_t > 0.35:
                cup.vx = self.knock_dir * 150 * k
                self.sound('tap')
                self.sub, self.sub_t = 'd', self.now
        else:
            ct.set_pose('sit', 8)
            ct.paw = max(0.0, 1 - (self.now - self.sub_t) / 0.4)
            ct.eyes = 'happy' if cup.state == 'broken' else 'open'
            if cup.state in ('broken', 'gone') or self.cup is None:
                if self.now - self.sub_t > 1.0:
                    self.sound('meow')
                    self.go_idle(random.uniform(2, 4), 'sit')
            elif self.now - self.sub_t > 6:
                self.go_idle(1.0, 'sit')

    # ------------------------------------------------------------------ menu
    def menu_items(self):
        if self.menu_page == 'race':
            rows = [('Race (animal)', None)]
            for key, name in ANIMALS.items():
                if key in ANIMALS_READY:
                    rows.append((name + ('   (actuel)' if key == self.animal else ''), 'race:' + key))
                else:
                    rows.append((name + '   (en preparation)', None))
            rows.append(('<  Retour', 'back'))
            return rows
        if self.menu_page == 'coat':
            rows = [('Pelage', None)]
            for k in COAT_ORDER:
                rows.append((COATS[k]['name'] + ('   (actuel)' if k == self.cat.coat else ''), 'coat:' + k))
            rows.append(('<  Retour', 'back'))
            return rows
        top = []
        if self.menu_ctx == 'basket':
            top = [('Sortir : une mouche', 'prey:fly'), ('Sortir : un papillon', 'prey:butterfly'),
                   ('Sortir : une souris', 'prey:mouse'), ('Sortir : une pelote', 'prey:yarn')]
        return paged_menu(self.menu_page, self.animal, top + [
            ('Faim : %d%%' % int(self.hunger * 100), None),
            ('Race : ' + ANIMALS[self.animal] + '   >', 'race'),
            ('Pelage : ' + COATS[self.cat.coat]['name'] + '   >', 'coat'),
            ('Style mignon : ' + ('oui' if self.cute else 'non'), 'cute'),
            ('Dormir', 'sleep'),
            ('Toilette', 'groom'),
            ('S etirer', 'stretch'),
            ('Course folle', 'zoom'),
            ('Grimper a une fenetre', 'climb'),
            ('Faire ses griffes', 'scratch'),
            ('Se cacher derriere la fenetre', 'rim'),
            ('Donner a manger (gamelle)', 'feed'),
            ('Poser une boite en carton', 'box'),
            ('Deuxieme chat : ' + ('oui' if self.buddy_on else 'non'), 'buddy'),
            ('Proies spontanees : ' + ('oui' if self.ambient else 'non'), 'ambient'),
            ('Taille +', 'size+'),
            ('Taille -', 'size-'),
            ('Son : ' + ('oui' if self.snd.on else 'coupe'), 'sound'),
            ('Volume + (%d %%)' % int(round(self.snd.volume * 100)), 'vol+'),
            ('Volume -', 'vol-'),
            ('Reprendre' if self.paused else 'Pause', 'pause'),
            ('Quitter', 'quit'),
        ], self)

    def menu_action(self, act):
        if act == 'tabclick':
            self.click_tab()
        elif act == 'bug':
            if getattr(self, 'bug_cb', None):
                self.bug_cb()
        elif act == 'monitor':
            n = monitor_count()
            if n > 1 and self.cfg_save:
                if hasattr(self, 'life_save'):
                    self.life_save()
                self.cfg_save({'monitor': MON.get('index', 1) % n + 1})
                restart_soon()
                if self.quit_cb:
                    self.quit_cb()
        elif act == 'quality':
            self.aa_on = not self.aa_on
            if self.cfg_save:
                self.cfg_save({'aa': self.aa_on})
            self.menu_page, self.menu_open = 'settings', True
        elif act == 'update':
            UPDATER.start()
            self.menu_page, self.menu_open = 'settings', True
        elif act == 'race':
            self.menu_page = 'race'
            self.menu_open = True
        elif act in ('actions', 'out', 'state'):
            self.menu_page = act
            self.menu_open = True
        elif act == 'rename':
            if self.ask_name_cb:
                self.ask_name_cb()
        elif act == 'reset':
            if self.reset_cb:
                self.reset_cb()
        elif act == 'load':
            if self.load_cb:
                self.load_cb()
        elif act == 'launcher':
            PREFS['launcher'] = not PREFS.get('launcher', True)
            if self.cfg_save:
                self.cfg_save({'show_launcher': PREFS['launcher']})
            self.menu_page, self.menu_open = 'settings', True
        elif act == 'bath':
            if not self.start_bath():
                self.say('Pas ici...')
            self.menu_page, self.menu_open = 'state', True
        elif act == 'heal':
            self.start_heal()
            self.menu_page, self.menu_open = 'state', True
        elif act == 'treat':
            self.give_treat()
            self.menu_page, self.menu_open = 'state', True
        elif act == 'coat':
            self.menu_page = 'coat'
            self.menu_open = True
        elif act == 'back':
            self.menu_page = 'animal' if self.menu_page in ('race', 'coat') else 'main'
            self.menu_open = True
        elif act.startswith('race:'):
            self.menu_page = 'main'
            if act[5:] != self.animal and self.switch_animal_cb:
                self.switch_animal_cb(act[5:])
                return
        elif act.startswith('coat:'):
            self.cat.coat = act[5:]
            self.menu_page = 'main'
            self.hearts.append([self.cat.x, self.cat.y - 70 * self.u, 0.0])
        elif act.startswith('prey:'):
            self.spawn_toy(act[5:])
        elif act == 'cute':
            self.set_cute(not self.cute)
        elif act == 'sleep':
            self.start_sleep()
        elif act == 'groom':
            self.set_state('groom')
        elif act == 'stretch':
            self.set_state('stretch')
        elif act == 'zoom':
            self.start_zoom()
        elif act == 'climb':
            self.start_climb()
        elif act == 'scratch':
            self.start_scratch()
        elif act == 'rim':
            if not self.start_rim():
                self.words.append(['Aucune fenetre...', self.cat.x, self.cat.y - 80 * self.u, 0.0])
        elif act == 'feed':
            self.place_bowl()
        elif act == 'box':
            self.place_box()
        elif act == 'buddy':
            self.toggle_buddy()
        elif act == 'ambient':
            self.ambient = not self.ambient
        elif act == 'size+':
            self.set_scale(self.s * 1.15)
        elif act == 'size-':
            self.set_scale(self.s / 1.15)
        elif act == 'sound':
            self.snd.on = not self.snd.on
            if self.snd.on:
                self.snd.play('ding')
        elif act in ('vol+', 'vol-'):
            self.snd.set_volume(self.snd.volume + (0.1 if act == 'vol+' else -0.1))
            if winsound is not None:
                self.snd.on = True
            self.snd.last = 0.0
            self.snd.play('ding')
            self.menu_open = True
        elif act == 'pause':
            self.paused = not self.paused
        elif act == 'quit':
            self.life_save()
            if self.quit_cb:
                self.quit_cb()
        self.save_config()

    # ------------------------------------------------------------------ vie de l'animal (facon Tamagotchi)
    @property
    def hunger(self):
        return self._hunger

    @hunger.setter
    def hunger(self, v):
        old = getattr(self, '_hunger', v)
        self._hunger = v
        if v < old - 0.001:                                      # il vient de manger : ca rend heureux
            self.life.joy = min(1.0, self.life.joy + (old - v) * 0.3)

    FUNNY = (('derp', 'Hein ?'), ('wink', 'Wink !'), ('smug', 'Hmm...'), ('blep', 'Blep !'), ('wide', 'Oh !'))

    def set_face(self, name, secs):
        self.face, self.face_until = name, self.now + secs

    def face_update(self, dt):
        """Expressions rigolotes : yeux en coeur quand on le caresse, surpris quand on l'attrape, grimaces au hasard, triste s'il va mal."""
        ct, st, L = self.cat, self.state, self.life
        if st in ('sleep', 'eat', 'feed', 'bath', 'heal', 'box') or (st == 'idle' and self.paused):
            ct.expr = None
            ct.blep += (0.0 - ct.blep) * min(1.0, dt * 10)
            return
        if st == 'pet':
            self.set_face('heart', 0.4)
        elif st == 'held':
            self.set_face('wide', 0.3)
        elif st == 'dizzy':
            self.set_face('dizzy', 0.3)
        self.face_t -= dt
        if self.face_t <= 0:
            self.face_t = random.uniform(10, 25) if L.has('farceur') else random.uniform(20, 45)
            if st in ('idle', 'loaf', 'walk', 'follow', 'stretch'):
                f, w = random.choice(self.FUNNY)
                self.set_face(f, 2.4)
                self.say(w)
        face = self.face if self.now < self.face_until else None
        if face is None and st in ('idle', 'loaf', 'walk') and (L.joy < 0.3 or self.hunger > 0.85 or L.sick):
            face = 'sad'
        ct.expr = None if face == 'blep' else face
        ct.blep += ((1.0 if face in ('derp', 'wink', 'blep') else 0.0) - ct.blep) * min(1.0, dt * 10)
        if face == 'wide':
            ct.yawn = max(ct.yawn, 0.75)

    def st_found(self, dt):
        """Tu decouvres l'animal cache dans sa boite : il se fige, surgit d'un coup, puis se rendort comme si de rien n'etait."""
        ct, u = self.cat, self.u
        o = self.box_obj
        t = self.state_t
        self.vx = 0.0
        if o is None or o.state != 'live':
            ct.yoff = 0.0
            return self.go_idle(0.5)
        ct.x = o.x
        ct.expr = 'wide'
        if t < 0.4:                                              # il se fige, tout petit dans la boite
            ct.yoff = 3.0
            ct.set_pose('loaf', 14)
        elif t < 0.7:                                            # POP !
            ct.yoff = 3.0 - 33.0 * clamp((t - 0.4) / 0.3, 0.0, 1.0)
            ct.set_pose('sit', 26)
            if self.sub == 'a':
                self.sub = 'b'
                self.say('Surprise !')
                self.sound('meow')
                ct.squash = 0.4
                for _ in range(8):
                    self.sparks.append([ct.x + random.uniform(-25, 25) * u, ct.y - random.uniform(25, 50) * u,
                                        random.uniform(-50, 50), -random.uniform(20, 70), 0.0, 'star'])
        elif t < 2.4:                                            # il reste debout, tout gene
            ct.yoff = -30.0 + 1.2 * math.sin(t * 16)
            ct.set_pose('sit', 10)
            ct.wag = 0.8
            if t > 1.3:
                ct.expr = 'smug'
        else:                                                    # il se recache
            ct.yoff = -6.0
            self.found_ok = self.now + 10
            self.set_state('box')

    aa_on = True

    def draw_cat(self, c, ct, angry, clip=None, key='cat'):
        """Dessine un animal : lisse (Pillow x3) dans une fenetre a transparence par pixel, sinon directement sur le canvas."""
        if _PI is not None and self.aa_on:
            l, t, r, b = ct.box()
            mx, my = 30 * self.u, 34 * self.u
            x0, y0 = int(l - mx), int(t - my)
            w, h = int(r - l + 2 * mx), int(b - t + 2 * my + 6 * self.u)
            w, h = min(max(32, (w + 31) // 32 * 32), 1100), min(max(32, (h + 31) // 32 * 32), 900)
            aa = AACanvas(None, x0, y0, w, h)
            ct.draw(ClipCanvas(aa, clip) if clip is not None else aa, angry)
            layer = self.layers.setdefault(key, SpriteLayer())
            if layer.show(aa.render(), MON['ox'] + x0, MON['oy'] + y0, self.sprite_solid):
                self.lay_used.add(key)
                return
            self.aa_on = False                                 # pas de fenetre a transparence : on repasse en dessin direct
        ct.draw(ClipCanvas(c, clip) if clip is not None else c, angry)

    def end_layers(self):
        for k, lay in self.layers.items():
            if k not in self.lay_used:
                lay.hide()
        self.lay_used = set()

    def hide_layers(self):
        for lay in self.layers.values():
            lay.hide()

    def solid_layers(self, solid):
        self.sprite_solid = solid
        for lay in self.layers.values():
            if lay.vis:
                lay.set_solid(solid)

    def close_layers(self):
        for lay in self.layers.values():
            lay.close()

    def decide_trait(self):
        """Son caractere (tire a la naissance) oriente ses envies, puis on retombe sur le choix habituel de l'espece."""
        L = self.life
        r = random.random()
        has = L.has
        if has('joueur') and r < 0.08:
            return self.start_zoom()
        if has('aventurier') and r < 0.10:
            if self.start_climb():
                return
            return self.start_jump_random(prefer_win=True)
        if has('timide') and r < 0.10 and self.start_rim():
            return
        if has('paresseux') and r < 0.14:
            return self.start_sleep()
        if has('curieux') and r < 0.10:
            if hasattr(self, 'start_sniff') and self.start_sniff():
                return
            if hasattr(self, 'start_follow') and self.start_follow():
                return
        if has('calin') and r < 0.10 and self.cspeed < 150 and abs(self.cur[0] - self.cat.x) < 800 * (self.u / 1.75):
            return self.set_state('greet')
        if has('colerique') and r < 0.06:
            return self.set_state('defend')
        self.decide()

    BUSY_STATES = ('zoom', 'frenzy', 'fchase', 'dance', 'chase', 'climb', 'climb_go', 'jump', 'bat', 'tailchase')
    PLAY_STATES = ('bat', 'chase', 'stalk', 'zoom', 'fetch', 'tailchase', 'dance', 'frenzy', 'fchase', 'carry')

    def say(self, text):
        ct, u = self.cat, self.u
        hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
        self.words.append([text, hx + ct.dir * 34 * u, hy - 16 * u, 0.0])

    def life_save(self):
        if self.cfg_save:
            self.life.hunger = self.hunger
            try:
                self.cfg_save({'life': self.life.dump(), 'life_kind': self.animal, 'life_coat': self.cat.coat})
            except Exception:
                pass

    def apply_growth(self):
        self.cat.kid = {'bebe': 1.0, 'jeune': 0.45}.get(self.life.stage(), 0.0)
        g = self.life.growth()
        if abs(g - self.growth) > 1e-3:
            self.growth = g
            self.set_scale(self.s)

    def life_tick(self, dt):
        dt /= getattr(self, 'SPEED', 1.0)                         # le furet va vite, mais ne vit pas plus vite
        L, st = self.life, self.state
        L.hunger = self.hunger
        if st == 'sleep':
            L.energy = min(1.0, L.energy + L.ENERGY_UP * dt)
            if L.energy < 0.9:
                self.state_t = min(self.state_t, 100.0)          # il dort tant qu'il n'a pas recupere
        else:
            L.energy = max(0.0, L.energy - L.ENERGY_DOWN * (3.0 if st in self.BUSY_STATES else 1.0) * (1.35 if L.has('paresseux') else 1.0) * dt)
        L.clean = max(0.0, L.clean - L.CLEAN_DOWN * (3.0 if st == 'dig' else 1.0) * (1.6 if L.has('cochon') else (0.6 if L.has('propre') else 1.0)) * dt)
        n_low = (self.hunger > 0.8) + (L.energy < 0.2) + (L.clean < 0.2)
        L.joy -= (L.JOY_DOWN * (1.4 if L.has('calin') else 1.0) + 0.0004 * n_low) * dt
        if st in self.PLAY_STATES:
            L.joy += 0.006 * (2.0 if L.has('joueur') else 1.0) * dt
        elif st == 'pet':
            L.joy += 0.03 * (2.0 if L.has('calin') else 1.0) * dt
        L.joy = clamp(L.joy, 0.0, 1.0)
        bad = self.hunger > 0.92 or L.clean < 0.08 or L.energy < 0.04
        L.health = clamp(L.health + (-0.00012 if bad else (0.0001 if n_low == 0 else 0.0)) * dt, 0.0, 1.0)
        if L.health < 0.3 and not L.sick:
            L.sick = True
            self.say('Aie...')
        elif L.health > 0.6 and L.sick:
            L.sick = False
        L.size_t -= dt
        if L.size_t <= 0:                                        # grandit avec l'age
            L.size_t = 3.0
            stg = L.stage()
            if L.stage_prev is not None and stg != L.stage_prev:
                for _ in range(8):
                    self.sparks.append([self.cat.x + random.uniform(-20, 20) * self.u, self.cat.y - random.uniform(5, 50) * self.u,
                                        random.uniform(-40, 40), -random.uniform(20, 60), 0.0, 'star'])
                self.sound('ding')
                self.say('J ai grandi !')
            L.stage_prev = stg
            self.apply_growth()
        L.need_t -= dt                                           # il dit ce dont il a besoin
        if L.need_t <= 0 and st not in ('sleep', 'held', 'rim', 'bath', 'heal'):
            L.need_t = random.uniform(60, 110)
            if L.sick:
                self.say('Je suis malade...')
            elif self.hunger > (0.55 if L.has('gourmand') else 0.7):
                self.say('Faim !')
            elif L.energy < 0.25:
                self.say('Fatigue...')
            elif L.clean < 0.25:
                self.say('Sale...')
            elif L.joy < 0.3:
                self.say('Un calin ?')
        if (L.energy < 0.12 and st in ('idle', 'walk', 'loaf', 'groom', 'stretch') and self.now > self.auto_sleep_ok
                and self.cur_plat() is not None):
            self.auto_sleep_ok = self.now + 120
            self.say('Zzz...')
            self.start_sleep()
        L.save_t += dt
        if L.save_t > 20:
            L.save_t = 0.0
            self.life_save()

    def update_egg(self, dt):
        L, ct, u = self.life, self.cat, self.u
        self.now += dt
        cx_, cy_ = self.getcur()
        l_, t_, r_, b_ = self.area
        self.cur = (clamp(cx_, l_, r_), clamp(cy_, t_, b_))
        btn = bool(self.getbtn())
        pressed = btn and not self.btn_prev
        self.btn_prev = btn
        if not getattr(self, 'egg_in', False):                   # premiere image : l'oeuf tombe au milieu de l'ecran
            self.egg_in, self.egg_t0 = True, self.now
            ct.x = (l_ + r_) / 2
            self.sound('pop')
        k = clamp((self.now - self.egg_t0) / 0.7, 0.0, 1.0)
        self.egg_yoff = -(1 - k) ** 2 * 420 * u + (math.sin(k * PI * 3) * 14 * u * (1 - k) if k < 1 else 0.0)
        hit = abs(self.cur[0] - ct.x) < 23 * u and ct.y - 54 * u < self.cur[1] < ct.y + 4 * u
        self.interactive = hit
        if pressed and hit:
            L.egg_t -= 4.0                                       # un petit coup l'aide a eclore
            ct.squash = 0.3
            self.sound('tap')
        L.egg_t -= dt
        ct.update(dt, 0.0, True)
        if L.egg_t <= 0:
            L.egg_t = None
            L.born = time.time()
            L.stage_prev = 'bebe'
            for _ in range(12):
                self.sparks.append([ct.x + random.uniform(-14, 14) * u, ct.y - random.uniform(5, 35) * u,
                                    random.uniform(-60, 60), -random.uniform(20, 80), 0.0, 'star'])
            self.hearts.append([ct.x, ct.y - 50 * u, 0.0])
            self.sound('ding')
            ct.squash = 0.7
            self.state, self.state_t = 'idle', 0.0
            self.apply_growth()
            self.say('Clique sur moi pour me donner un nom !' if not L.name else 'Coucou !')
            self.name_asked = False
            self.life_save()

    def draw_egg(self, c):
        ct, L = self.cat, self.life
        u = self.u * 1.3                                         # un oeuf bien visible
        oy = getattr(self, 'egg_yoff', 0.0)
        co = DOG_COATS.get(ct.coat) or GOAT_COATS.get(ct.coat) or FERRET_COATS.get(ct.coat) or COATS.get(ct.coat) or {}
        spot = co.get('dark', '#b98a5a')
        prog = clamp(1.0 - L.egg_t / L.EGG_TIME, 0.0, 1.0)
        w = math.sin(self.now * (4 + 12 * prog)) * (0.03 + 0.17 * prog) * (1.0 if int(self.now * 0.8) % 2 == 0 or prog > 0.7 else 0.0)
        cw, sw = math.cos(w), math.sin(w)
        rx, ry = 13 * u, 18 * u

        def tr(x, y):                                            # (x, y) relatifs au bas de l'oeuf, pivot au sol
            return ct.x + x * cw - y * sw, ct.y + oy + x * sw + y * cw
        c.create_oval(ct.x - 11 * u, ct.y - 2 * u, ct.x + 11 * u, ct.y + 2 * u, fill='#6a6a78', outline='')
        pts = []
        for q in range(28):
            th = 2 * PI * q / 28
            pts += list(tr(rx * math.sin(th) * (1 - 0.10 * math.cos(th)), -ry * math.cos(th) - ry))
        c.create_polygon(pts, fill='#f6efe0', outline='#5a4a3a', width=max(2, int(1.4 * u)))
        for sx_, sy_, sr in ((-4, -20, 2.6), (3, -12, 2.0), (-2, -8, 1.6), (5, -22, 1.8), (-6, -14, 1.4)):
            px, py = tr(sx_ * u, sy_ * u)
            c.create_oval(px - sr * u, py - sr * u, px + sr * u, py + sr * u, fill=spot, outline='')
        if prog > 0.45:                                          # fissures
            zz = [tr(-9 * u, -16 * u), tr(-5 * u, -19 * u), tr(-2 * u, -15 * u), tr(2 * u, -19 * u), tr(5 * u, -15 * u), tr(9 * u, -18 * u)]
            c.create_line([v for p in zz for v in p], fill='#5a4a3a', width=max(1, int(1.4 * u)))
        age = self.now - getattr(self, 'egg_t0', self.now)
        if self.interactive or 0.8 < age < 14 or (age % 25) < 4:  # au debut, puis de temps en temps : on le remarque
            txt = 'Clique sur moi pour m aider a eclore !' if not self.interactive else 'Encore !'
            fs = -int(12 * self.s)
            for dx, dy, col in ((1, 1, '#000000'), (0, 0, '#ffffff')):
                c.create_text(ct.x + dx, ct.y + oy - 44 * u + dy, text=txt, fill=col, font=('Segoe UI', fs, 'bold'))

    def mood_bar(self, v):
        n = int(round(clamp(v, 0.0, 1.0) * 8))
        return '█' * n + '░' * (8 - n)

    def state_rows(self):
        L = self.life
        return [(('Nom : ' + L.name + '   (changer >)') if L.name else 'Lui donner un nom   >', 'rename'),
                ('Humeur : ' + L.mood(), None),
                ('Age : %s  (%s)' % (L.age_txt(), L.NAMES.get(L.stage(), '')), None),
                ('Caractere : ' + L.traits_txt(), None),
                ('G:Satiete:%.3f:0' % (1.0 - self.hunger), None),
                ('G:Energie:%.3f:0' % L.energy, None),
                ('G:Bonheur:%.3f:0' % L.joy, None),
                ('G:Sante:%.3f:0' % L.health, None),
                ('G:Salete:%.3f:1' % (1.0 - L.clean), None),
                ('Donner a manger (gamelle)', 'feed'),
                ('Friandise', 'treat'),
                ('Laver', 'bath'),
                ('Soigner', 'heal')]

    def start_bath(self):
        if self.cat.pkey is None or self.cur_plat() is None:
            return False
        self.set_state('bath')
        return True

    def st_bath(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('stand', 8)
        ct.eyes = 'happy'
        ct.wag = 1.0
        ct.squash = 0.1 * abs(math.sin(t * 18))
        self.life.clean = min(1.0, self.life.clean + dt * 0.28)
        if int(t * 9) != int((t - dt) * 9):
            self.sparks.append([ct.x + random.uniform(-22, 22) * u, ct.y - random.uniform(5, 40) * u,
                                random.uniform(-10, 10), -random.uniform(25, 60), 0.0, 'bubble'])
        if t > 3.8:
            self.life.clean = 1.0
            self.life.health = min(1.0, self.life.health + 0.03)
            self.say('Tout propre !')
            self.sound('ding')
            self.go_idle(random.uniform(1.5, 3), 'stand')

    def start_heal(self):
        L = self.life
        if L.health > 0.92 and not L.sick:
            self.say('Je vais bien !')
            return False
        if self.cat.pkey is None or self.cur_plat() is None:
            return False
        self.set_state('heal')
        return True

    def st_heal(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('sit', 8)
        ct.eyes = 'closed'
        self.life.health = min(1.0, self.life.health + dt * 0.3)
        if int(t * 4) != int((t - dt) * 4):
            self.sparks.append([ct.x + random.uniform(-14, 14) * u, ct.y - random.uniform(30, 55) * u,
                                random.uniform(-10, 10), -random.uniform(15, 40), 0.0, 'star'])
        if t > 2.6:
            self.life.health = min(1.0, self.life.health + 0.25)
            self.hearts.append([ct.x, ct.y - 70 * u, 0.0])
            self.say('Merci !')
            self.go_idle(random.uniform(1.5, 3), 'sit')

    def give_treat(self):
        if self.now < self.treat_ok:
            self.say('Plus de friandise...')
            return
        self.treat_ok = self.now + 45
        self.hunger = max(0.0, self.hunger - 0.12)
        self.life.joy = min(1.0, self.life.joy + 0.15)
        self.hearts.append([self.cat.x, self.cat.y - 70 * self.u, 0.0])
        self.sound('crunch')
        self.say('Miam !')

    def set_scale(self, new):
        new = clamp(new, 0.8, 3.2)
        self.s = new
        self.u = new * self.UK * self.growth
        self.cat.u = self.u
        self.g = 1400 * self.u
        self.bk.s = new * 0.62
        self.snap_basket()

    def set_cute(self, flag):
        self.cute = bool(flag)
        self.cat.cute = self.cute
        if self.buddy is not None:
            self.buddy.cat.cute = self.cute

    def save_config(self):
        if self.cfg_save:
            try:
                self.cfg_save({'animal': 'cat', 'coat': self.cat.coat, 'bx': self.bk.x, 'by': self.bk.y, 'scale': self.s,
                               'sound': self.snd.on, 'volume': self.snd.volume, 'cute': self.cute, 'ambient': self.ambient,
                               'buddy': self.buddy_on})
            except Exception:
                pass

    # ------------------------------------------------------------------ rendu
    def draw(self, c, static=False):
        self.bk.draw(c, self.hover_bk or self.bk_drag)
        ct = self.cat
        u = self.u
        if self.cup is not None and self.cup.state != 'broken':
            draw_cup(c, self.cup.x, self.cup.y, u)
        for f in self.flies:
            draw_fly(c, f)
        for o in self.toys:
            if o.state == 'carried':
                continue
            if o.kind == 'box':
                if self.state in ('box', 'found') and o is self.box_obj:
                    continue
                draw_box_back(c, o.x, o.y, u)
                draw_box_front(c, o.x, o.y, u)
                continue
            if o.kind == 'bowl':
                draw_bowl(c, o.x, o.y, u, o.food)
            elif o.kind == 'mouse':
                draw_mouse(c, o.x, o.y, u, o.dir, o.t * 12)
            else:
                draw_yarn(c, o.x, o.y, u, o.rot)
        if self.buddy is not None:
            self.draw_cat(c, self.buddy.cat, False, key='buddy')
        angry = self.state in self.ANGRY_STATES
        in_box = self.state in ('box', 'found') and self.box_obj is not None
        if in_box:
            draw_box_back(c, self.box_obj.x, self.box_obj.y, u)
        if self.state == 'rim' and self.rim and self.rim['hw'] in self.win_by:
            self.draw_cat(c, ct, angry, clip=self.win_by[self.rim['hw']][1])
        elif self.life.egg_t is not None:
            self.draw_egg(c)
        else:
            self.draw_cat(c, ct, angry)
        if in_box:
            draw_box_front(c, self.box_obj.x, self.box_obj.y, u)
        if self.life.egg_t is None and self.life.clean < 0.3:             # tres sale : des mouches tournent autour de lui
            for q_ in range(3):
                ang_ = self.now * 4 + q_ * 2.1
                fx_, fy_ = ct.x + math.cos(ang_) * 16 * u, ct.y - 66 * u + math.sin(ang_ * 1.3) * 6 * u
                c.create_oval(fx_ - 1.5 * u, fy_ - 1.2 * u, fx_ + 1.5 * u, fy_ + 1.2 * u, fill='#2a2a2a', outline='')
        if self.state == 'sleep' and self.state_t > 6:                 # bulle de rêve : une souris, puis un poisson
            hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
            bx, by = hx + ct.dir * 30 * u, hy - 34 * u
            c.create_oval(hx + ct.dir * 10 * u - 1.5 * u, hy - 14 * u, hx + ct.dir * 10 * u + 1.5 * u, hy - 11 * u, fill='#ffffff', outline='#8a8a9a')
            c.create_oval(hx + ct.dir * 16 * u - 2.5 * u, hy - 22 * u, hx + ct.dir * 16 * u + 2.5 * u, hy - 17 * u, fill='#ffffff', outline='#8a8a9a')
            c.create_oval(bx - 15 * u, by - 12 * u, bx + 15 * u, by + 12 * u, fill='#ffffff', outline='#8a8a9a', width=2)
            if self.animal in ('dog', 'goat'):
                if int(self.state_t / 3) % 2 == 0:
                    (draw_bone if self.animal == 'dog' else draw_carrot)(c, bx, by, u * 0.9)
                else:
                    draw_yarn(c, bx, by + 7 * u, u * 0.85, self.state_t * 3)
            elif int(self.state_t / 3) % 2 == 0:
                draw_mouse(c, bx, by + 7 * u, u * 0.85, 1, self.state_t * 6)
            else:
                c.create_polygon([v for q in range(16) for v in (bx + 7 * u * math.cos(2 * PI * q / 16), by + 4.4 * u * math.sin(2 * PI * q / 16))], fill='#7ab8e8', outline='#3a78a8')
                c.create_polygon(bx + 6 * u, by, bx + 12 * u, by - 5 * u, bx + 12 * u, by + 5 * u, fill='#7ab8e8', outline='#3a78a8')
                c.create_oval(bx - 5.2 * u, by - 1.8 * u, bx - 3.4 * u, by, fill='#101018', outline='')
        if self.hunger > 0.7 and self.state in ('idle', 'walk', 'loaf') and (self.now % 9) < 2.5:     # a faim : pense à un poisson
            bx, by = ct.x + ct.dir * 34 * u, ct.y - 78 * u
            c.create_oval(bx - ct.dir * 14 * u, by + 22 * u, bx - ct.dir * 10 * u, by + 26 * u, fill='#ffffff', outline='#777777')
            c.create_oval(bx - ct.dir * 8 * u, by + 14 * u, bx - ct.dir * 2 * u, by + 20 * u, fill='#ffffff', outline='#777777')
            c.create_oval(bx - 16 * u, by - 12 * u, bx + 16 * u, by + 12 * u, fill='#ffffff', outline='#777777', width=2)
            if self.animal in ('dog', 'goat'):
                (draw_bone if self.animal == 'dog' else draw_carrot)(c, bx, by, u)
            else:
                c.create_polygon(rot_ell(bx, by, 0, 0, 0, 8 * u, 4.6 * u), fill='#7ab8e8', outline='#3a78a8')
                c.create_polygon(bx + 7 * u, by, bx + 13 * u, by - 5 * u, bx + 13 * u, by + 5 * u, fill='#7ab8e8', outline='#3a78a8')
                c.create_oval(bx - 5.4 * u, by - 1.8 * u, bx - 3.6 * u, by, fill='#101018', outline='')
        for h in self.hearts:
            if h[2] >= 0:
                c.create_text(h[0], h[1], text='♥', fill='#ff5c93', font=('Segoe UI Symbol', -int(20 * self.s), 'bold'))
        for z in self.zzz:
            fs = -int((9 + z[2] * 7) * self.s)
            c.create_text(z[0] + 1, z[1] + 1, text='Z', fill='#000000', font=('Segoe UI', fs, 'bold'))
            c.create_text(z[0], z[1], text='Z', fill='#ffffff', font=('Segoe UI', fs, 'bold'))
        for sk in self.sparks:
            if sk[4] >= 0 and sk[5] == 'chip':
                r_ = 1.5 * self.u
                c.create_oval(sk[0] - r_, sk[1] - r_, sk[0] + r_, sk[1] + r_ * 0.7, fill='#8a6a4a', outline='')
            elif sk[4] >= 0 and sk[5] == 'bubble':
                r_ = (2.5 + 3 * sk[4]) * self.u
                c.create_oval(sk[0] - r_, sk[1] - r_, sk[0] + r_, sk[1] + r_, fill='#d8f0ff', outline='#7ab8e8', width=2)
            elif sk[4] >= 0:
                c.create_text(sk[0], sk[1], text='✦', fill='#ffe066',
                              font=('Segoe UI Symbol', -int(18 * self.s * (1.2 - sk[4] * 0.5)), 'bold'))
        for w in self.words:
            fs = -int((13 + min(w[3], 0.2) * 20) * self.s)
            c.create_text(w[1] + 1, w[2] + 1, text=w[0], fill='#000000', font=('Segoe UI', fs, 'bold'))
            c.create_text(w[1], w[2], text=w[0], fill='#ffffff', font=('Segoe UI', fs, 'bold'))
        if self.paused:
            c.create_text(ct.x + 1, ct.y - 80 * self.u + 1, text='Pause', fill='#000000', font=('Segoe UI', -int(14 * self.s), 'bold'))
            c.create_text(ct.x, ct.y - 80 * self.u, text='Pause', fill='#ffffff', font=('Segoe UI', -int(14 * self.s), 'bold'))
        self.end_layers()
        self.draw_menu(c)



ACTION_ACTS = {'sleep', 'groom', 'stretch', 'zoom', 'climb', 'scratch', 'rim', 'bark', 'beg', 'dig', 'sniff', 'butt',
               'frenzy', 'mad', 'fchase', 'dance', 'show', 'dangle', 'hide', 'wash'}
OUT_ACTS = {'box', 'ball'}
ANIMAL_ACTS = {'race', 'coat', 'cute', 'buddy', 'ambient', 'species', 'comp', 'dew', 'reset', 'load'}
SETTING_ACTS = {'size+', 'size-', 'sound', 'vol+', 'vol-', 'pause', 'quit', 'monitor', 'update', 'quality', 'launcher'}
OUT_ITEMS = {
    'spider': [('Une mouche', 'prey:fly'), ('Un moustique', 'prey:mosquito'), ('Un papillon', 'prey:butterfly')],
    'cat': [('Une mouche', 'prey:fly'), ('Un papillon', 'prey:butterfly'), ('Une souris', 'prey:mouse'), ('Une pelote', 'prey:yarn')],
}
OUT_DEFAULT = [('Une mouche', 'prey:fly'), ('Un papillon', 'prey:butterfly'), ('Une souris', 'prey:mouse')]


def menu_tabs(animal):
    t = [] if animal == 'spider' else [('state', 'Etat')]
    return t + [('actions', 'Actions'), ('out', 'Sortir'), ('animal', 'Animal'), ('settings', 'Reglages')]


def menu_active(page, animal):
    keys = [k for k, _ in menu_tabs(animal)]
    return page if page in keys else keys[0]


def paged_menu(page, animal, rows, pet=None):
    """Menu en onglets (Etat, Actions, Sortir, Animal, Reglages) : une bande d'onglets en haut, le contenu dessous."""
    page = menu_active(page, animal)
    out = [('\x00tabs', 'tabclick')]
    if page == 'state' and pet is not None:
        out += pet.state_rows()
    elif page == 'actions':
        if animal == 'spider':
            out += [r for r in rows if r[1] is None and r[0].startswith('Faim')]
        out += [r for r in rows if r[1] in ACTION_ACTS]
    elif page == 'out':
        out += OUT_ITEMS.get(animal, OUT_DEFAULT) + [r for r in rows if r[1] in OUT_ACTS]
        out.append(('Signaler un bug...', 'bug'))
    elif page == 'animal':
        out += [r for r in rows if r[1] in ANIMAL_ACTS]
        if pet is not None and hasattr(pet, 'life'):
            out += [('Nouvel animal (recommencer)...', 'reset'), ('Charger un animal...', 'load')]
    else:
        base = [r for r in rows if r[1] in SETTING_ACTS and r[1] not in ('size+', 'size-', 'vol+', 'vol-')]
        if pet is not None:                                     # taille et volume : des curseurs a faire glisser
            base = [('S:Taille:%.4f:%d %%' % (clamp((pet.s - 0.8) / 2.4, 0.0, 1.0), round(pet.s / 1.4 * 100)), 'slider:size')] + base
            i_ = next((k for k, r in enumerate(base) if r[1] == 'sound'), len(base) - 1)
            base.insert(i_ + 1, ('S:Volume:%.4f:%d %%' % ((pet.snd.volume - 0.1) / 0.9, round(pet.snd.volume * 100)), 'slider:vol'))
        extra = []
        if pet is not None and hasattr(pet, 'draw_cat') and _PI is not None:
            extra.append(('Qualite : ' + ('lissee' if pet.aa_on else 'standard'), 'quality'))
        n = monitor_count()
        if n > 1:
            extra.append(('Ecran : %d sur %d   (changer >)' % (MON.get('index', 1), n), 'monitor'))
        extra.append(('Menu au lancement : ' + ('oui' if PREFS.get('launcher', True) else 'non'), 'launcher'))
        extra.append(('Mise a jour   (v%s)' % VERSION, 'update'))
        if UPDATER.msg:
            extra.append((UPDATER.msg, None))
        out += [r for r in base if r[1] not in ('pause', 'quit')] + extra + [r for r in base if r[1] in ('pause', 'quit')]
    return out


# ============================================================================ LE CHIEN
class DogPet(CatPet):
    """Cerveau du chien : memes plateformes que le chat, mais il aboie, fait le beau, creuse, rapporte la balle et te suit."""
    UK = 1.6
    ANGRY_STATES = ()
    LOOK_STATES = CatPet.LOOK_STATES + ('beg', 'bark', 'defend', 'fetch')
    HAPPY = ('pet', 'greet', 'beg', 'fetch', 'follow', 'zoom', 'tailchase', 'stretch')

    def __init__(self, area, scale, getcursor, log=None, coat='golden'):
        super().__init__(area, scale, getcursor, log, coat)
        self.animal = 'dog'
        self.menu_ctx = 'dog'
        self.bark_n = -1
        self.dig_x = 0.0

    # ------------------------------------------------------------------ utilitaires
    def sound(self, name):
        if name == 'purr':
            name = 'snore' if self.state == 'sleep' else 'pant'
        elif name == 'meow':
            name = 'woof'
        self.snd.play(name)

    def set_state(self, name):
        m = self.cat.mouth
        super().set_state(name)
        ct = self.cat
        if name == 'fetch':
            ct.mouth = m
        ct.digging = (name == 'dig')
        ct.scratching = False
        if name in ('bark', 'defend'):
            self.bark_n = -1

    def view_for_state(self):
        st = self.state
        if st in ('beg', 'greet'):
            return 'front'
        if st in ('bark', 'defend'):
            return '3q'
        return super().view_for_state()

    def say(self, text):
        ct, u = self.cat, self.u
        hx, hy = ct.T(ct.P['hdx'], ct.P['hdy'])
        self.words.append([text, hx + ct.dir * 34 * u, hy - 16 * u, 0.0])

    def update(self, dt):
        super().update(dt)
        ct = self.cat
        happy = (ct.gal > 0.3 or self.state in self.HAPPY or (self.state == 'idle' and ct.wag > 0.5)
                 or (self.state == 'walk' and self.hunger < 0.5 and False))
        ct.tng += ((1.0 if happy else 0.0) - ct.tng) * min(1.0, dt * 6)

    # ------------------------------------------------------------------ decisions
    def decide(self):
        ct, u, s = self.cat, self.u, self.s
        r = random.random()
        p = self.cur_plat()
        k = u / 1.75
        near = abs(self.cur[0] - ct.x) < 700 * k
        if self.still_t > 50 and random.random() < 0.5:
            return self.start_sleep()
        if near and self.cspeed < 80 and self.still_t > 1.5 and random.random() < 0.16:
            return self.set_state('greet')
        if near and self.still_t > 3 and random.random() < (0.3 if self.hunger > 0.6 else 0.12):
            return self.set_state('beg')
        if random.random() < 0.10 and self.start_follow():
            return
        if random.random() < 0.05:
            return self.start_tailchase()
        if random.random() < 0.06 and self.start_rim():
            return
        if (self.hunger > 0.5 or random.random() < 0.6) and self.prey_list() and self.start_hunt():
            return
        if r < 0.04:
            return self.start_zoom()
        if r < 0.09 and self.start_dig():
            return
        if r < 0.15 and self.start_sniff():
            return
        if r < 0.19:
            return self.set_state('bark')
        if r < 0.40 and p:
            return self.start_walk(random.uniform(p['x0'] + 30 * u, p['x1'] - 30 * u))
        if r < 0.46:
            return self.start_jump_random()
        if r < 0.54:
            return self.set_state('groom')
        if r < 0.62:
            return self.set_state('stretch')
        if r < 0.72:
            return self.set_state('loaf')
        if r < 0.84:
            return self.start_curious()
        return self.go_idle(random.uniform(2, 5))

    def start_sleep(self):
        self.go_sleep()

    def go_sleep(self):
        self.edge_pose = False
        self.set_state('sleep')

    # ------------------------------------------------------------------ etats communs un peu changes
    def st_idle(self, dt):
        super().st_idle(dt)
        if self.state == 'idle':
            near = abs(self.cur[0] - self.cat.x) < 520 * (self.u / 1.75)
            self.cat.wag = 0.7 if (near and self.cspeed < 60 and self.still_t > 1.5) else 0.12

    def st_walk(self, dt):
        super().st_walk(dt)
        if self.state == 'walk':
            self.cat.wag = 0.3

    def st_stretch(self, dt):
        ct = self.cat
        self.vx = 0.0
        t = self.state_t
        ct.set_pose('bow', 6)                                    # courbette : l'arriere en l'air
        ct.wag = 0.9
        ct.eyes = 'happy'
        ct.yawn = clamp((t - 0.6) / 0.4, 0, 1) if 0.6 < t < 1.8 else 0.0
        if t > 2.4:
            self.go_idle(random.uniform(1, 3), 'stand')

    def st_pet(self, dt):
        ct, u = self.cat, self.u
        self.vx = 0.0
        ct.set_pose('sit', 8)
        ct.eyes = 'happy'
        ct.wag = 1.0
        self.pet_heart_t += dt
        if self.pet_heart_t > 0.7:
            self.pet_heart_t = 0.0
            self.hearts.append([ct.x + ct.dir * 10 * u, ct.y - 62 * u, 0.0])
            self.sound('purr')
        self.pet_away = 0.0 if self.over_cat() else self.pet_away + dt
        if self.pet_away > 0.7 or self.state_t > 12:
            self.pet_ok = self.now + 1.0
            self.go_idle(1.5, 'sit')

    def st_greet(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('sit', 9)
        ct.eyes = 'happy'
        ct.wag = 1.0
        if self.sub == 'a' and t > 0.3:
            self.sub = 'b'
            self.sound('meow')
            self.say('Ouaf !')
        if t > 3.0:
            self.hearts.append([ct.x, ct.y - 74 * u, 0.0])
            self.go_idle(random.uniform(2, 4), 'sit')

    def st_defend(self, dt):                                     # curseur trop rapide : il aboie
        self.st_bark(dt)

    # ------------------------------------------------------------------ aboyer
    def st_bark(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('bark', 14)
        if abs(self.cur[0] - ct.x) > 30 * u:
            ct.dir = 1 if self.cur[0] > ct.x else -1
        ct.eyes = 'open'
        ct.wag = 0.5
        ph = (t - 0.25) % 0.55
        n = int((t - 0.25) / 0.55) if t > 0.25 else -1
        ct.yawn = clamp(math.sin(PI * ph / 0.3), 0.0, 1.0) if (t > 0.25 and ph < 0.3 and n < 3) else 0.0
        if 0 <= n < 3 and n != self.bark_n:
            self.bark_n = n
            self.sound('meow')
            ct.squash = 0.45
            self.say('WOUF !' if n != 1 else 'Wouf !')
        if t > 2.3:
            self.go_idle(random.uniform(1.5, 3), 'sit')

    # ------------------------------------------------------------------ faire le beau
    def st_beg(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('beg', 7)
        ct.eyes = 'happy'
        ct.wag = 0.9
        if abs(self.cur[0] - ct.x) > 30 * u:
            ct.dir = 1 if self.cur[0] > ct.x else -1
        if int(t * 0.8) != int((t - dt) * 0.8):
            self.hearts.append([ct.x + ct.dir * 8 * u, ct.y - 72 * u, 0.0])
            self.sound('purr')
        if self.sub == 'a' and t > 1.0 and self.hunger > 0.5:
            self.sub = 'b'
            self.sound('meow')
            self.say('Ouaf ?')
        if self.cspeed > 800 or t > 5.5 or abs(self.cur[0] - ct.x) > 900 * (u / 1.75):
            self.go_idle(random.uniform(1.5, 3), 'sit')

    # ------------------------------------------------------------------ creuser
    def start_dig(self):
        if self.cat.pkey != ('ground', 0):
            return False
        self.set_state('dig')
        return True

    def st_dig(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('dig', 9)
        ct.wag = 0.5
        ct.eyes = 'open'
        if int(t * 4.5) != int((t - dt) * 4.5):
            self.sound('tap')
            fx, fy = ct.feet_pos()[0]
            px, py = ct.T(fx, fy)
            for _ in range(3):
                self.sparks.append([px, py, -ct.dir * random.uniform(30, 120), random.uniform(-170, -70), 0.0, 'chip'])
        if t > 4.2:
            self.go_idle(random.uniform(1.5, 3), 'sit')

    # ------------------------------------------------------------------ renifler
    def start_sniff(self):
        ct, u = self.cat, self.u
        p = self.cur_plat()
        if not p:
            return False
        self.tx = clamp(ct.x + random.choice((-1, 1)) * random.uniform(160, 380) * (u / 1.75), p['x0'] + 30 * u, p['x1'] - 30 * u)
        self.set_state('sniff')
        return True

    def st_sniff(self, dt):
        ct, u = self.cat, self.u
        d = self.tx - ct.x
        ct.set_pose('sniff', 8)
        ct.dir = 1 if d >= 0 else -1
        ct.wag = 0.3
        self.vx = ct.dir * 55 * (u / 1.75) if abs(d) > 8 * u else 0.0
        if int(self.state_t * 3) != int((self.state_t - dt) * 3):
            ct.look = (ct.look[0], 0.5)
        if abs(d) <= 8 * u or self.edge or self.state_t > 9:
            self.go_idle(random.uniform(1, 2.5), 'stand')

    # ------------------------------------------------------------------ te suivre
    def start_follow(self):
        ct, u = self.cat, self.u
        p = self.cur_plat()
        if not p or abs(self.cur[0] - ct.x) < 260 * (u / 1.75):
            return False
        if not (p['x0'] - 30 < self.cur[0] < p['x1'] + 30):
            return False
        self.set_state('follow')
        return True

    def st_follow(self, dt):
        ct, u = self.cat, self.u
        k = u / 1.75
        d = self.cur[0] - ct.x
        want = 120 * u
        ct.dir = 1 if d >= 0 else -1
        ct.wag = 0.5
        if abs(d) > want:
            ct.set_pose('stand', 10)
            self.vx = ct.dir * clamp((abs(d) - want) * 1.6, 80, 560) * k
        else:
            ct.set_pose('sit', 8)
            self.vx = 0.0
        if self.edge or self.state_t > 16 or (self.state_t > 2 and self.cspeed < 5 and abs(d) <= want + 25 * u and self.still_t > 3):
            self.go_idle(random.uniform(1.5, 3), 'sit')

    # ------------------------------------------------------------------ rapporter la balle
    def st_bat(self, dt):
        o = self.prey
        if o is not None and isinstance(o, Toy) and o.kind == 'yarn' and self.prey_alive(o):
            u = self.u
            o.state = 'carried'
            self.carry = o
            self.sound('tap')
            self.cat.mouth = lambda c, x, y: draw_yarn(c, x, y + 1.5 * u, u * 0.8, 0.0)
            return self.set_state('fetch')
        self.give_up(2.0)

    def st_fetch(self, dt):
        ct, u = self.cat, self.u
        o = self.carry
        t = self.state_t
        k = u / 1.75
        ct.set_pose('stand', 10)
        ct.eyes = 'open'
        ct.wag = 0.8
        d = self.cur[0] - ct.x
        ct.dir = 1 if d >= 0 else -1
        if abs(d) > 70 * u and t < 10 and not self.edge:
            self.vx = ct.dir * clamp(abs(d) * 1.2, 140, 480) * k
            return
        self.vx = 0.0
        if o is not None:                                        # il depose la balle devant toi
            hx, hy = ct.T(ct.P['hdx'] + 8, ct.P['hdy'] + 6)
            o.x, o.y = hx, ct.y
            o.vx, o.vy = ct.dir * 60, -240 * k
            o.pkey = None
            o.state = 'live'
            o.t = 0.0
            self.carry = None
        ct.mouth = None
        self.hearts.append([ct.x, ct.y - 74 * u, 0.0])
        self.sound('meow')
        self.say('Ouaf !')
        self.hunt_ok = self.now + 4
        self.go_idle(random.uniform(2, 3.5), 'sit')

    # ------------------------------------------------------------------ menu
    def menu_items(self):
        if self.menu_page == 'race':
            return super().menu_items()
        if self.menu_page == 'coat':
            rows = [('Pelage', None)]
            for k in DOG_ORDER:
                rows.append((DOG_COATS[k]['name'] + ('   (actuel)' if k == self.cat.coat else ''), 'coat:' + k))
            rows.append(('<  Retour', 'back'))
            return rows
        top = []
        if self.menu_ctx == 'basket':
            top = [('Sortir : une balle', 'prey:yarn'), ('Sortir : une mouche', 'prey:fly'),
                   ('Sortir : un papillon', 'prey:butterfly'), ('Sortir : une souris', 'prey:mouse')]
        return paged_menu(self.menu_page, self.animal, top + [
            ('Faim : %d%%' % int(self.hunger * 100), None),
            ('Race : ' + ANIMALS[self.animal] + '   >', 'race'),
            ('Pelage : ' + DOG_COATS[self.cat.coat]['name'] + '   >', 'coat'),
            ('Style mignon : ' + ('oui' if self.cute else 'non'), 'cute'),
            ('Dormir', 'sleep'),
            ('Aboyer', 'bark'),
            ('Faire le beau', 'beg'),
            ('Creuser', 'dig'),
            ('Renifler', 'sniff'),
            ('Se cacher derriere la fenetre', 'rim'),
            ('Jouer a la balle', 'ball'),
            ('Course folle', 'zoom'),
            ('Donner a manger (gamelle)', 'feed'),
            ('Proies spontanees : ' + ('oui' if self.ambient else 'non'), 'ambient'),
            ('Taille +', 'size+'),
            ('Taille -', 'size-'),
            ('Son : ' + ('oui' if self.snd.on else 'coupe'), 'sound'),
            ('Volume + (%d %%)' % int(round(self.snd.volume * 100)), 'vol+'),
            ('Volume -', 'vol-'),
            ('Reprendre' if self.paused else 'Pause', 'pause'),
            ('Quitter', 'quit'),
        ], self)

    def menu_action(self, act):
        if act == 'bark':
            self.set_state('bark')
        elif act == 'beg':
            self.set_state('beg')
        elif act == 'dig':
            if not self.start_dig():
                self.go_idle(0.3)
        elif act == 'sniff':
            self.start_sniff()
        elif act == 'ball':
            self.spawn_toy('yarn')
            self.hunt_ok = 0.0
        else:
            return super().menu_action(act)
        self.save_config()

    def save_config(self):
        if self.cfg_save:
            try:
                self.cfg_save({'animal': 'dog', 'dcoat': self.cat.coat, 'bx': self.bk.x, 'by': self.bk.y, 'scale': self.s,
                               'sound': self.snd.on, 'volume': self.snd.volume, 'cute': self.cute, 'ambient': self.ambient})
            except Exception:
                pass



# ============================================================================ LA CHEVRE NAINE
class GoatPet(DogPet):
    """Chevre naine : meme moteur que le chien, mais elle belait, broute, se dresse, donne des coups de tete et grimpe partout."""
    UK = 1.5
    LOOK_STATES = DogPet.LOOK_STATES + ('butt',)
    HAPPY = ()
    WORDS = {'Ouaf !': 'Meee !', 'WOUF !': 'MEEEH !', 'Wouf !': 'Meeh !', 'Ouaf ?': 'Meeh ?'}

    def __init__(self, area, scale, getcursor, log=None, coat='caramel'):
        super().__init__(area, scale, getcursor, log, coat)
        self.animal = 'goat'
        self.menu_ctx = 'goat'
        self.butted = False
        self.mad = False
        self.frenzy_end = 0.0
        self.hop_t = 0.0

    # ------------------------------------------------------------------ utilitaires
    def sound(self, name):
        if name == 'purr':
            name = 'snore' if self.state == 'sleep' else 'bleat_s'
        elif name == 'meow':
            name = 'bleat'
        self.snd.play(name)

    def say(self, text):
        super().say(self.WORDS.get(text, text))

    def set_state(self, name):
        super().set_state(name)
        self.cat.digging = False
        if name == 'butt':
            self.butted = False

    def view_for_state(self):
        if self.state == 'butt':
            return 'side'
        return super().view_for_state()

    # ------------------------------------------------------------------ decisions
    def decide(self):
        ct, u, s = self.cat, self.u, self.s
        r = random.random()
        p = self.cur_plat()
        k = u / 1.75
        near = abs(self.cur[0] - ct.x) < 700 * k
        if self.still_t > 50 and random.random() < 0.5:
            return self.start_sleep()
        if near and self.cspeed < 80 and self.still_t > 1.5 and random.random() < 0.14:
            return self.set_state('greet')
        if near and self.still_t > 3 and random.random() < (0.3 if self.hunger > 0.6 else 0.10):
            return self.set_state('beg')
        if random.random() < 0.08 and self.start_follow():
            return
        if random.random() < 0.07 and self.start_rim():
            return
        if random.random() < 0.08 and self.start_butt():
            return
        if random.random() < 0.07:
            return self.start_frenzy()
        if (self.hunger > 0.5 or random.random() < 0.5) and self.prey_list() and self.start_hunt():
            return
        if r < 0.05:
            return self.start_zoom()
        if r < 0.15 and self.start_dig():
            return
        if r < 0.19 and self.start_sniff():
            return
        if r < 0.23:
            return self.set_state('bark')
        if r < 0.40 and p:
            return self.start_walk(random.uniform(p['x0'] + 30 * u, p['x1'] - 30 * u))
        if r < 0.58:
            return self.start_jump_random()                          # les chevres sautent sur tout
        if r < 0.64:
            return self.set_state('groom')
        if r < 0.70:
            return self.set_state('stretch')
        if r < 0.80:
            return self.set_state('loaf')
        if r < 0.90:
            return self.start_curious()
        return self.go_idle(random.uniform(2, 5))

    # ------------------------------------------------------------------ brouter (a la place de creuser)
    def start_dig(self):
        if self.cur_plat() is None:
            return False
        self.set_state('dig')
        return True

    def st_dig(self, dt):
        ct, u = self.cat, self.u
        t = self.state_t
        self.vx = 0.0
        ct.set_pose('dig', 9)
        ct.wag = 0.35
        ct.eyes = 'open'
        ct.yawn = 0.3 if math.sin(t * 11) > 0 else 0.0              # elle machonne
        if int(t * 1.6) != int((t - dt) * 1.6):
            self.sound('tap')
        if t > 5.0:
            ct.yawn = 0.0
            self.go_idle(random.uniform(1.5, 3), 'stand')

    # ------------------------------------------------------------------ crise de folie / colere : elle bondit dans tous les sens
    def start_frenzy(self, mad=None):
        self.mad = (random.random() < 0.4) if mad is None else mad
        self.frenzy_end = self.now + random.uniform(4.5, 8.0)
        self.hop_t = 0.0
        self.set_state('frenzy')
        self.sound('meow')
        self.say('MEEEH !' if self.mad else 'Meee !')

    def hop(self):
        ct, u = self.cat, self.u
        k = u / 1.75
        p = self.cur_plat()
        if self.mad and abs(self.cur[0] - ct.x) > 40 * u and random.random() < 0.7:
            ct.dir = 1 if self.cur[0] > ct.x else -1                 # en colere, elle fonce vers le curseur
        elif random.random() < 0.5:
            ct.dir = -ct.dir
        if p is not None and not (p['x0'] + 90 * u < ct.x + ct.dir * 160 * u < p['x1'] - 90 * u):
            ct.dir = 1 if ct.x < (p['x0'] + p['x1']) / 2 else -1     # pas de saut dans le vide
        ct.pkey = None
        self.vy = -random.uniform(560, 860) * k
        self.vx = ct.dir * random.uniform(60, 340) * k
        self.hop_t = self.now

    def st_frenzy(self, dt):
        ct, u = self.cat, self.u
        ct.wag = 1.0
        ct.eyes = 'angry' if self.mad else 'happy'
        if self.mad and int(self.state_t * 0.9) != int((self.state_t - dt) * 0.9):
            self.say('Meeh !')
        if ct.pkey is None:                                      # en l'air : dos cambre, pattes ecartees
            ct.set_pose('pronk', 16)
            return
        self.vx = 0.0
        if self.now > self.frenzy_end:
            return self.go_idle(random.uniform(1.5, 3), 'stand')
        ct.set_pose('crouch', 20)
        if self.now - self.hop_t > 0.12:
            self.hop()

    def st_defend(self, dt):                                     # curseur trop rapide : elle pique une colere
        self.start_frenzy(mad=True)

    def st_zoom(self, dt):
        super().st_zoom(dt)
        if self.state != 'zoom':
            return
        ct = self.cat
        if ct.pkey is None:
            ct.set_pose('pronk', 14)
        elif random.random() < dt * 2.0:                         # en pleine course folle, elle bondit
            self.vy = -random.uniform(520, 760) * (self.u / 1.75)
            ct.pkey = None

    # ------------------------------------------------------------------ coup de tete
    def start_butt(self):
        ct, u = self.cat, self.u
        if self.cur_plat() is None:
            return False
        if abs(self.cur[0] - ct.x) > 30 * u:
            ct.dir = 1 if self.cur[0] > ct.x else -1
        else:
            ct.dir = random.choice((-1, 1))
        self.set_state('butt')
        return True

    def st_butt(self, dt):
        ct, u = self.cat, self.u
        k = u / 1.75
        t = self.state_t
        ct.eyes = 'open'
        ct.wag = 0.8
        if t < 0.75:                                             # elle se dresse sur les pattes arriere
            self.vx = 0.0
            ct.set_pose('beg', 12)
        elif t < 1.1:                                            # puis retombe tete baissee en chargeant
            ct.set_pose('butt', 18)
            self.vx = ct.dir * 380 * k
            if not self.butted:
                self.butted = True
                ct.squash = 0.5
                self.sound('tap')
                self.say('Bam !')
        else:
            self.vx = 0.0
            self.go_idle(random.uniform(1.2, 2.5), 'stand')
            return
        if self.edge:
            self.vx = 0.0
            self.go_idle(1.0, 'stand')

    # ------------------------------------------------------------------ menu
    def menu_items(self):
        if self.menu_page == 'race':
            return super().menu_items()
        if self.menu_page == 'coat':
            rows = [('Robe', None)]
            for k in GOAT_ORDER:
                rows.append((GOAT_COATS[k]['name'] + ('   (actuelle)' if k == self.cat.coat else ''), 'coat:' + k))
            rows.append(('<  Retour', 'back'))
            return rows
        top = []
        if self.menu_ctx == 'basket':
            top = [('Sortir : une balle', 'prey:yarn'), ('Sortir : une mouche', 'prey:fly'),
                   ('Sortir : un papillon', 'prey:butterfly'), ('Sortir : une souris', 'prey:mouse')]
        return paged_menu(self.menu_page, self.animal, top + [
            ('Faim : %d%%' % int(self.hunger * 100), None),
            ('Race : ' + ANIMALS[self.animal] + '   >', 'race'),
            ('Robe : ' + GOAT_COATS[self.cat.coat]['name'] + '   >', 'coat'),
            ('Style mignon : ' + ('oui' if self.cute else 'non'), 'cute'),
            ('Dormir', 'sleep'),
            ('Beler', 'bark'),
            ('Se dresser', 'beg'),
            ('Brouter', 'dig'),
            ('Coup de tete', 'butt'),
            ('Crise de folie', 'frenzy'),
            ('Piquer une colere', 'mad'),
            ('Renifler', 'sniff'),
            ('Se cacher derriere la fenetre', 'rim'),
            ('Jouer a la balle', 'ball'),
            ('Course folle', 'zoom'),
            ('Donner a manger (gamelle)', 'feed'),
            ('Proies spontanees : ' + ('oui' if self.ambient else 'non'), 'ambient'),
            ('Taille +', 'size+'),
            ('Taille -', 'size-'),
            ('Son : ' + ('oui' if self.snd.on else 'coupe'), 'sound'),
            ('Volume + (%d %%)' % int(round(self.snd.volume * 100)), 'vol+'),
            ('Volume -', 'vol-'),
            ('Reprendre' if self.paused else 'Pause', 'pause'),
            ('Quitter', 'quit'),
        ], self)

    def menu_action(self, act):
        if act == 'butt':
            if not self.start_butt():
                self.go_idle(0.3)
            self.save_config()
        elif act in ('frenzy', 'mad'):
            self.start_frenzy(mad=(act == 'mad'))
            self.save_config()
        else:
            super().menu_action(act)

    def save_config(self):
        if self.cfg_save:
            try:
                self.cfg_save({'animal': 'goat', 'gcoat': self.cat.coat, 'bx': self.bk.x, 'by': self.bk.y, 'scale': self.s,
                               'sound': self.snd.on, 'volume': self.snd.volume, 'cute': self.cute, 'ambient': self.ambient})
            except Exception:
                pass




# ============================================================================ LE FURET
class FerretPet(DogPet):
    """Furet : tres rapide, il chasse le curseur (course, bond, repli), fait la danse de guerre, se faufile et creuse."""
    UK = 1.0
    LOOK_STATES = DogPet.LOOK_STATES + ('dance',)
    HAPPY = ()
    SPEED = 1.4
    WORDS = {'Ouaf !': 'Dook !', 'WOUF !': 'DOOK DOOK !', 'Wouf !': 'Dook !', 'Ouaf ?': 'Dook ?'}

    def __init__(self, area, scale, getcursor, log=None, coat='sable'):
        super().__init__(area, scale, getcursor, log, coat)
        self.animal = 'ferret'
        self.menu_ctx = 'ferret'
        self.fsub = 'run'
        self.ft = 0.0
        self.fdir = 1
        self.dance_len = 3.0
        self.hop_t = 0.0
        self.sidedir = 1

    def update(self, dt):
        super().update(dt if self.life.egg_t is not None else dt * self.SPEED)     # tout va plus vite : mouvements, sauts, animation

    # ------------------------------------------------------------------ utilitaires
    def sound(self, name):
        if name == 'purr':
            name = 'snore' if self.state == 'sleep' else 'dook_s'
        elif name == 'meow':
            name = 'dook'
        self.snd.play(name)

    def say(self, text):
        super().say(self.WORDS.get(text, text))

    def set_state(self, name):
        super().set_state(name)
        self.cat.digging = (name == 'dig')
        if name == 'dance':
            self.dance_len = random.uniform(2.6, 4.6)
            self.hop_t = 0.0
            self.sidedir = random.choice((-1, 1))

    def view_for_state(self):
        if self.state == 'dance':
            return '3q'
        return super().view_for_state()

    def start_walk(self, tx, speed=None):
        super().start_walk(tx, speed or random.choice((260, 340, 440, 540)))

    def st_zoom(self, dt):
        super().st_zoom(dt)
        if self.state == 'zoom':
            self.vx *= 1.5

    # ------------------------------------------------------------------ decisions
    def decide(self):
        ct, u = self.cat, self.u
        r = random.random()
        p = self.cur_plat()
        k = u / 1.75
        near = abs(self.cur[0] - ct.x) < 1400 * k
        if self.still_t > 40 and random.random() < 0.5:
            return self.start_sleep()
        if near and self.cspeed > 60 and random.random() < 0.6 and self.start_fchase():
            return                                               # le curseur bouge : il fonce dessus
        if near and random.random() < 0.22 and self.start_fchase():
            return
        if near and self.cspeed < 40 and abs(self.cur[0] - ct.x) < 500 * k and random.random() < 0.15:
            return self.set_state('dance')
        if random.random() < 0.05 and self.start_rim():
            return
        if (self.hunger > 0.5 or random.random() < 0.5) and self.prey_list() and self.start_hunt():
            return
        if r < 0.07:
            return self.start_zoom()
        if r < 0.12 and self.start_dig():
            return
        if r < 0.18 and self.start_sniff():
            return
        if r < 0.22:
            return self.set_state('bark')
        if r < 0.28:
            return self.set_state('dance')
        if r < 0.48 and p:
            return self.start_walk(random.uniform(p['x0'] + 30 * u, p['x1'] - 30 * u))
        if r < 0.60:
            return self.start_jump_random()
        if r < 0.66:
            return self.set_state('groom')
        if r < 0.72:
            return self.set_state('stretch')
        if r < 0.78:
            return self.set_state('beg')
        return self.go_idle(random.uniform(0.3, 1.0), 'stand')

    def st_defend(self, dt):                                     # curseur tres rapide : il part a ses trousses
        if not self.start_fchase():
            self.go_idle(0.3, 'stand')

    # ------------------------------------------------------------------ chasser le curseur
    def start_fchase(self):
        ct, u = self.cat, self.u
        p = self.cur_plat()
        if p is None:
            return False
        cx, cy = self.cur
        if not (p['x0'] - 40 < cx < p['x1'] + 40 and abs(cy - (ct.y - 25 * u)) < 260 * u):
            best = None                                          # le curseur est sur une autre plateforme : il y saute
            for q in self.plats:
                if q['key'] != p['key'] and q['x0'] < cx < q['x1'] and q['y'] >= cy - 10 * u:
                    if best is None or q['y'] - cy < best['y'] - cy:
                        best = q
            if best is not None:
                ok, tx = self.reachable(best, clamp(cx, best['x0'] + 20 * u, best['x1'] - 20 * u))
                if ok:
                    self.jump_to = (tx, best['y'])
                    self.then = None
                    self.set_state('jump')
                    return True
                if ct.pkey == ('ground', 0) and best['key'][0] == 'win' and self.start_climb(then=None, only=best['key'][1]):
                    return True                                  # trop haut pour sauter : il grimpe a la fenetre
            return False
        self.fsub = 'run'
        self.ft = self.now
        self.set_state('fchase')
        return True

    def st_fchase(self, dt):
        ct, u = self.cat, self.u
        k = u / 1.75
        p = self.cur_plat()
        if p is None:                                            # en l'air (bond)
            ct.set_pose('pounce', 20)
            ct.eyes = 'open'
            return
        cx, cy = self.cur
        d = cx - ct.x
        if (self.now - self.ft > 12 or not (p['x0'] - 60 < cx < p['x1'] + 60) or abs(cy - (ct.y - 25 * u)) > 300 * u):
            return self.go_idle(random.uniform(0.2, 0.6), 'stand')
        ct.wag = 1.0
        ct.eyes = 'open'
        if self.fsub == 'air':                                   # il vient d'atterrir : il recule vite
            self.fsub = 'dart'
            self.ft2 = self.now
            ct.dir = -self.fdir
            if random.random() < 0.3:
                return self.set_state('dance')
        if self.fsub == 'run':
            ct.dir = 1 if d >= 0 else -1
            ct.set_pose('stand', 24)
            self.vx = ct.dir * clamp(abs(d) * 3.2, 240, 980) * k
            if abs(d) < 85 * u:
                self.fsub = 'wind'
                self.ft2 = self.now
        elif self.fsub == 'wind':                                # il se tasse en remuant l'arriere-train
            ct.dir = 1 if d >= 0 else -1
            self.vx = 0.0
            ct.set_pose('crouch', 28)
            if self.now - self.ft2 > 0.15:
                self.fdir = ct.dir
                ct.pkey = None
                self.vy = -random.uniform(420, 560) * k
                self.vx = ct.dir * clamp(abs(d) * 5, 320, 720) * k
                self.fsub = 'air'
                self.sound('meow')
                if random.random() < 0.4:
                    self.say('Dook !')
        else:                                                    # 'dart' : repli rapide
            ct.set_pose('stand', 24)
            self.vx = ct.dir * 900 * k
            if self.now - self.ft2 > 0.32 or self.edge:
                self.fsub = 'run'

    # ------------------------------------------------------------------ danse de guerre
    def st_dance(self, dt):
        ct, u = self.cat, self.u
        k = u / 1.75
        ct.puff = 0.9
        ct.wag = 1.0
        ct.eyes = 'open'
        if abs(self.cur[0] - ct.x) > 30 * u:
            ct.dir = 1 if self.cur[0] > ct.x else -1
        ct.set_pose('war', 26)
        if ct.pkey is None:
            return
        self.vx = 0.0
        if self.state_t > self.dance_len:
            return self.go_idle(random.uniform(0.3, 0.8), 'stand')
        if self.now - self.hop_t > 0.18:
            p = self.cur_plat()
            if p is not None and not (p['x0'] + 60 * u < ct.x + self.sidedir * 100 * u < p['x1'] - 60 * u):
                self.sidedir = 1 if ct.x < (p['x0'] + p['x1']) / 2 else -1
            elif random.random() < 0.3:
                self.sidedir = -self.sidedir
            ct.pkey = None
            self.vy = -random.uniform(280, 380) * k
            self.vx = self.sidedir * random.uniform(140, 300) * k
            self.hop_t = self.now
            self.sound('meow')

    # ------------------------------------------------------------------ menu
    def menu_items(self):
        if self.menu_page == 'race':
            return super().menu_items()
        if self.menu_page == 'coat':
            rows = [('Robe', None)]
            for k in FERRET_ORDER:
                rows.append((FERRET_COATS[k]['name'] + ('   (actuelle)' if k == self.cat.coat else ''), 'coat:' + k))
            rows.append(('<  Retour', 'back'))
            return rows
        top = []
        if self.menu_ctx == 'basket':
            top = [('Sortir : une balle', 'prey:yarn'), ('Sortir : une mouche', 'prey:fly'),
                   ('Sortir : un papillon', 'prey:butterfly'), ('Sortir : une souris', 'prey:mouse')]
        return paged_menu(self.menu_page, self.animal, top + [
            ('Faim : %d%%' % int(self.hunger * 100), None),
            ('Race : ' + ANIMALS[self.animal] + '   >', 'race'),
            ('Robe : ' + FERRET_COATS[self.cat.coat]['name'] + '   >', 'coat'),
            ('Style mignon : ' + ('oui' if self.cute else 'non'), 'cute'),
            ('Dormir', 'sleep'),
            ('Chasser le curseur', 'fchase'),
            ('Danse de guerre', 'dance'),
            ('Dooker', 'bark'),
            ('Se dresser', 'beg'),
            ('Creuser', 'dig'),
            ('Renifler', 'sniff'),
            ('Se cacher derriere la fenetre', 'rim'),
            ('Jouer a la balle', 'ball'),
            ('Course folle', 'zoom'),
            ('Donner a manger (gamelle)', 'feed'),
            ('Proies spontanees : ' + ('oui' if self.ambient else 'non'), 'ambient'),
            ('Taille +', 'size+'),
            ('Taille -', 'size-'),
            ('Son : ' + ('oui' if self.snd.on else 'coupe'), 'sound'),
            ('Volume + (%d %%)' % int(round(self.snd.volume * 100)), 'vol+'),
            ('Volume -', 'vol-'),
            ('Reprendre' if self.paused else 'Pause', 'pause'),
            ('Quitter', 'quit'),
        ], self)

    def menu_action(self, act):
        if act == 'fchase':
            if not self.start_fchase():
                self.go_idle(0.3, 'stand')
            self.save_config()
        elif act == 'dance':
            self.set_state('dance')
            self.save_config()
        else:
            super().menu_action(act)

    def save_config(self):
        if self.cfg_save:
            try:
                self.cfg_save({'animal': 'ferret', 'fcoat': self.cat.coat, 'bx': self.bk.x, 'by': self.bk.y, 'scale': self.s,
                               'sound': self.snd.on, 'volume': self.snd.volume, 'cute': self.cute, 'ambient': self.ambient})
            except Exception:
                pass



# ------------------------------------------------------------ fenêtres ouvertes
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
try:
    dwm = ctypes.windll.dwmapi
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
except Exception:
    dwm = None
SKIP_CLASSES = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd', 'Windows.UI.Core.CoreWindow',
                'NotifyIconOverflowWindow', 'TopLevelWindowForOverflowXamlIsland'}


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]


def other_fullscreen(sw, sh):
    """Vrai si une autre application (jeu, vidéo, F11) couvre tout l'écran sans barre de titre."""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return False
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value in SKIP_CLASSES:
            return False
        rc = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        style = user32.GetWindowLongW(hwnd, -16)
        mr = MON['rect'] or (0, 0, sw, sh)
        covers = rc.left <= mr[0] and rc.top <= mr[1] and rc.right >= mr[2] and rc.bottom >= mr[3]
        return bool(covers and not (style & 0x00C00000))        # pas de WS_CAPTION
    except Exception:
        return False


def read_windows(max_n=8):
    """Fenêtres visibles (de la plus haute à la plus basse dans l'empilement) : [(hwnd, l, t, r, b)]."""
    out = []
    mypid = os.getpid()

    def cb(hwnd, lp):
        try:
            if len(out) >= max_n:
                return False
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            if user32.GetWindowTextLengthW(hwnd) == 0:
                return True
            if user32.GetWindowLongW(hwnd, -20) & 0x80:                 # fenêtres outils
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == mypid:
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value in SKIP_CLASSES:
                return True
            if dwm is not None:
                cloaked = wintypes.DWORD(0)
                dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
                if cloaked.value:
                    return True
                rc = wintypes.RECT()
                if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rc), ctypes.sizeof(rc)) != 0:
                    return True
            else:
                rc = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rc))
            if rc.right - rc.left >= 250 and rc.bottom - rc.top >= 120:
                mr = MON['rect']
                if mr and not (mr[0] <= (rc.left + rc.right) // 2 < mr[2] and mr[1] <= (rc.top + rc.bottom) // 2 < mr[3]):
                    return True                                            # fenêtre d'un autre moniteur
                out.append((int(hwnd), rc.left - MON['ox'], rc.top - MON['oy'], rc.right - MON['ox'], rc.bottom - MON['oy']))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(cb), 0)
    except Exception:
        pass
    return out


# ------------------------------------------------------------------- application
# ============================================================================ FENETRES : nom, choix de l'animal, sauvegardes
DLG = dict(bg='#fff6ec', card='#ffffff', fg='#3b2f27', sub='#8c7b6b', acc='#ff7f50', acc2='#ffd9c7', line='#ecdccb', btn='#f3e6d8')
PREFS = {'launcher': True}
MAMMALS = ('cat', 'dog', 'goat', 'ferret')


def coat_table(kind):
    """(dictionnaire des pelages, cle de config, ordre) pour une race."""
    if kind == 'spider':
        return SPECIES, 'species', SPECIES_ORDER
    if kind == 'dog':
        return DOG_COATS, 'dcoat', list(DOG_COATS)
    if kind == 'goat':
        return GOAT_COATS, 'gcoat', list(GOAT_COATS)
    if kind == 'ferret':
        return FERRET_COATS, 'fcoat', list(FERRET_COATS)
    return COATS, 'coat', COAT_ORDER


def coat_name(kind, k):
    return coat_table(kind)[0].get(k, {}).get('name', str(k))


def valid_coat(kind, k):
    tab, _, order = coat_table(kind)
    return k if k in tab else order[0]


def record_text(rec):
    """Ligne de resume d'un animal sauvegarde : nom, race, pelage, age."""
    life = rec.get('life') or {}
    kind = rec.get('kind', 'cat')
    name = str(life.get('name') or 'Sans nom')
    if life.get('egg_t') is not None:
        age = 'oeuf'
    else:
        try:
            d = max(0.0, (time.time() - float(life.get('born', time.time()))) / 86400.0)
        except Exception:
            d = 0.0
        age = '%d h' % int(d * 24) if d < 1 else '%d j' % int(d)
    return '%s  -  %s %s, %s' % (name, ANIMALS.get(kind, kind), coat_name(kind, rec.get('coat')).lower(), age)


def _dlg_window(master, title):
    w = tk.Toplevel(master)
    w.title(title)
    w.configure(bg=DLG['bg'])
    w.resizable(False, False)
    try:
        w.attributes('-topmost', True)
    except Exception:
        pass
    return w


def _dlg_place(w, x=None, y=None):
    """Centre la fenetre (sur l'ecran de l'animal, ou pres d'un point) et lui donne le clavier."""
    w.update_idletasks()
    ww, hh = w.winfo_reqwidth(), w.winfo_reqheight()
    rect = MON.get('rect') or (0, 0, w.winfo_screenwidth(), w.winfo_screenheight())
    if x is None:
        x, y = (rect[0] + rect[2] - ww) // 2, (rect[1] + rect[3] - hh) // 2
    else:
        x, y = int(clamp(x - ww / 2, rect[0] + 10, rect[2] - ww - 10)), int(clamp(y - hh - 30, rect[1] + 10, rect[3] - hh - 60))
    w.geometry('+%d+%d' % (x, y))
    w.lift()

    def grab_focus():
        try:
            hwnd = int(w.wm_frame(), 16)                         # on se branche un instant sur la fenetre active pour avoir le clavier
            fg = user32.GetForegroundWindow()
            t_fg = user32.GetWindowThreadProcessId(fg, None)
            t_me = ctypes.windll.kernel32.GetCurrentThreadId()
            if t_fg and t_fg != t_me:
                user32.AttachThreadInput(t_me, t_fg, True)
            user32.SetForegroundWindow(hwnd)
            if t_fg and t_fg != t_me:
                user32.AttachThreadInput(t_me, t_fg, False)
        except Exception:
            pass
        try:
            w.focus_force()
        except Exception:
            pass
    w.after(30, grab_focus)


def _btn(parent, text, cmd, main=False, small=False):
    return tk.Button(parent, text=text, command=cmd, relief='flat', bd=0, cursor='hand2',
                     bg=DLG['acc'] if main else DLG['btn'], fg='#ffffff' if main else DLG['fg'],
                     activebackground='#ff9a70' if main else DLG['acc2'], activeforeground='#ffffff' if main else DLG['fg'],
                     font=('Segoe UI', 9 if small else 11, 'bold' if main else 'normal'), padx=10 if small else 16, pady=3 if small else 7)


def ask_name(master, on_ok, initial='', x=None, y=None, on_cancel=None):
    """Petite fenetre : « Comment veux-tu le nommer ? » avec une case pour ecrire."""
    w = _dlg_window(master, 'Un nom pour ton animal')
    box = tk.Frame(w, bg=DLG['bg'], padx=26, pady=20)
    box.pack()
    tk.Label(box, text='Comment veux-tu le nommer ?', bg=DLG['bg'], fg=DLG['fg'], font=('Segoe UI', 15, 'bold')).pack(anchor='w')
    tk.Label(box, text='Tu pourras le changer plus tard (État > Nom).', bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 9)).pack(anchor='w', pady=(2, 12))
    var = tk.StringVar(value=initial)
    frame = tk.Frame(box, bg=DLG['acc'], padx=2, pady=2)
    frame.pack(fill='x')
    ent = tk.Entry(frame, textvariable=var, font=('Segoe UI', 15), relief='flat', bd=6, bg=DLG['card'], fg=DLG['fg'],
                   insertbackground=DLG['fg'], width=22)
    ent.pack(fill='x')
    msg = tk.Label(box, text=' ', bg=DLG['bg'], fg='#d0453a', font=('Segoe UI', 9))
    msg.pack(anchor='w', pady=(4, 0))

    def ok(_e=None):
        name = ' '.join(var.get().split())[:18]
        if not name:
            msg.config(text='Écris un nom (ou clique sur « Plus tard »).')
            return
        w.destroy()
        on_ok(name)

    def cancel(_e=None):
        w.destroy()
        if on_cancel:
            on_cancel()
    row = tk.Frame(box, bg=DLG['bg'])
    row.pack(fill='x', pady=(10, 0))
    _btn(row, 'Valider', ok, main=True).pack(side='right')
    _btn(row, 'Plus tard', cancel).pack(side='right', padx=8)
    ent.bind('<Return>', ok)
    ent.bind('<Escape>', cancel)
    w.protocol('WM_DELETE_WINDOW', cancel)
    ent.select_range(0, 'end')
    _dlg_place(w, x, y)
    w.after(60, ent.focus_set)
    return w


def ask_yes_no(master, title, text, on_yes, yes='Oui', no='Annuler'):
    w = _dlg_window(master, title)
    box = tk.Frame(w, bg=DLG['bg'], padx=26, pady=20)
    box.pack()
    tk.Label(box, text=title, bg=DLG['bg'], fg=DLG['fg'], font=('Segoe UI', 14, 'bold')).pack(anchor='w')
    tk.Label(box, text=text, bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 10), justify='left', wraplength=360).pack(anchor='w', pady=(6, 14))
    row = tk.Frame(box, bg=DLG['bg'])
    row.pack(fill='x')

    def go():
        w.destroy()
        on_yes()
    _btn(row, yes, go, main=True).pack(side='right')
    _btn(row, no, w.destroy).pack(side='right', padx=8)
    w.bind('<Escape>', lambda e: w.destroy())
    _dlg_place(w)
    return w


class Chooser:
    """Choix de la race et du pelage, avec un apercu anime. mode 'launch' (au demarrage) ou 'new' (nouvel animal)."""

    def __init__(self, master, mode, kind, coats, on_done, summary='', saves=None, on_load=None):
        self.mode, self.on_done, self.on_load = mode, on_done, on_load
        self.kind = kind if kind in ANIMALS_READY and (mode == 'launch' or kind in MAMMALS) else 'cat'
        self.coats = dict(coats)                                  # pelage retenu pour chaque race
        self.saves = saves or []
        self.done = False
        self.t = 0.0
        w = self.win = _dlg_window(master, 'Desktop Pet' if mode == 'launch' else 'Nouvel animal')
        self.banner = tk.Canvas(w, width=700, height=70, bg=DLG['bg'], highlightthickness=0, cursor='hand2')
        self.banner.pack(fill='x')                                # un animal de chaque, accroche en haut de la fenetre
        self.banner.bind('<Button-1>', self.banner_click)
        self.make_hangers()
        box = tk.Frame(w, bg=DLG['bg'], padx=24, pady=8)
        box.pack()
        tk.Label(box, text='Choisis ton compagnon' if mode == 'launch' else 'Un nouvel animal', bg=DLG['bg'], fg=DLG['fg'],
                 font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        if summary:
            tk.Label(box, text=summary, bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 10), justify='left', wraplength=620).pack(anchor='w', pady=(2, 0))
        body = tk.Frame(box, bg=DLG['bg'])
        body.pack(fill='x', pady=(14, 0))
        card = tk.Frame(body, bg=DLG['line'], padx=1, pady=1)
        card.pack(side='left', anchor='n')
        self.cv = tk.Canvas(card, width=300, height=230, bg='#eaf3fb', highlightthickness=0)
        self.cv.pack()
        right = tk.Frame(body, bg=DLG['bg'], padx=20)
        right.pack(side='left', fill='both', anchor='n')
        tk.Label(right, text='RACE', bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        rr = tk.Frame(right, bg=DLG['bg'])
        rr.pack(anchor='w', pady=(4, 12))
        self.race_btns = {}
        kinds = [k for k in ANIMALS if k in ANIMALS_READY and (mode == 'launch' or k in MAMMALS)]
        for i, k in enumerate(kinds):
            b = tk.Button(rr, text=ANIMALS[k], relief='flat', bd=0, cursor='hand2', font=('Segoe UI', 10), padx=10, pady=5,
                          command=lambda k=k: self.pick_kind(k))
            b.grid(row=i // 3, column=i % 3, padx=(0, 6), pady=(0, 6), sticky='we')
            self.race_btns[k] = b
        tk.Label(right, text='PELAGE', bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        self.coat_box = tk.Frame(right, bg=DLG['bg'])
        self.coat_box.pack(anchor='w', pady=(4, 0))
        self.coat_btns = {}
        bot = tk.Frame(box, bg=DLG['bg'])
        bot.pack(fill='x', pady=(18, 0))
        if mode == 'launch':
            self.show_var = tk.BooleanVar(value=PREFS.get('launcher', True))
            tk.Checkbutton(bot, text='Afficher ce menu au lancement', variable=self.show_var, bg=DLG['bg'], fg=DLG['sub'],
                           activebackground=DLG['bg'], selectcolor=DLG['card'], font=('Segoe UI', 9)).pack(side='left')
            _btn(bot, "C'est parti !", lambda: self.finish('go'), main=True).pack(side='right')
            self.new_btn = _btn(bot, 'Nouvel œuf', lambda: self.finish('new'))
            self.new_btn.pack(side='right', padx=(8, 0))
            if self.saves:
                _btn(bot, 'Charger un animal (%d)' % len(self.saves), self.open_load).pack(side='right', padx=(8, 0))
        else:
            _btn(bot, "Faire éclore l'œuf", lambda: self.finish('new'), main=True).pack(side='right')
            _btn(bot, 'Annuler', self.cancel).pack(side='right', padx=8)
        w.protocol('WM_DELETE_WINDOW', (lambda: self.finish('go')) if mode == 'launch' else self.cancel)
        w.bind('<Return>', lambda e: self.finish('go' if mode == 'launch' else 'new'))
        w.bind('<Escape>', lambda e: self.finish('go') if mode == 'launch' else self.cancel())
        self.pick_kind(self.kind)
        _dlg_place(w)
        self.anim()

    def make_hangers(self):
        self.hangers = []
        for k in ANIMALS:
            if k not in ANIMALS_READY or (self.mode != 'launch' and k not in MAMMALS):
                continue
            try:
                if k == 'spider':
                    m = Spider(0, 0, 1.25, valid_coat('spider', self.coats.get('spider')))
                else:
                    m = Cat(0, 0, 1.05, valid_coat(k, self.coats.get(k)))
                    m.view, m.hlook = 'front', True
                    m.set_pose('rim_peek', 40)
                    for _ in range(30):
                        m.update(0.04, 0, True)
                        m.view = 'front'
            except Exception:
                m = None
            self.hangers.append([k, m, random.uniform(0, 6)])

    def banner_xs(self):
        W = max(300, self.banner.winfo_width())
        n = max(1, len(self.hangers))
        return [W * (i + 0.5) / n for i in range(n)]

    def banner_click(self, e):
        xs = self.banner_xs()
        if xs:
            i = min(range(len(xs)), key=lambda j: abs(xs[j] - e.x))
            self.pick_kind(self.hangers[i][0])

    def draw_banner(self):
        """Comme sur le bureau : les animaux sont derriere la fenetre et passent la tete et les pattes au-dessus du bord ;
        l'araignee, elle, est posee sur le bord."""
        cv = self.banner
        cv.delete('all')
        W = max(300, cv.winfo_width())
        H = int(cv.cget('height'))
        edge = 56                                                 # bord haut de la « fenetre »
        cv.create_rectangle(0, 0, W, edge, fill='#dfeaf4', outline='')            # le bureau, derriere
        spider = None
        for i, ((k, m, ph), x) in enumerate(zip(self.hangers, self.banner_xs())):
            if k == 'spider':
                spider = (i, x)
            elif m is not None:                                   # accroche au bord : le corps est cache derriere la fenetre
                sw = math.sin(self.t * 1.3 + ph)
                m.x, m.y = x + 2 * sw, edge + 34 * m.u + 2 * abs(sw)
                m.update(0.04, 0, True)
                m.view = 'front'
                m.draw(cv)
        cv.create_rectangle(0, edge, W, H, fill=DLG['bg'], outline='')            # la fenetre passe devant le corps
        cv.create_line(0, edge, W, edge, fill='#cdb8a2', width=2)
        if spider is not None:                                    # l'araignee posee sur le bord
            i, x = spider
            m = self.hangers[i][1]
            if m is None or abs(m.x - x) > 1:
                try:
                    m = self.hangers[i][1] = Spider(x, edge - 8, 1.15, valid_coat('spider', self.coats.get('spider')))
                except Exception:
                    m = None
            if m is not None:
                try:
                    m.draw(cv)
                except Exception:
                    pass
        for (k, m, ph), x in zip(self.hangers, self.banner_xs()):
            if k == self.kind:
                cv.create_text(x + 30, 14, text='♥', fill=DLG['acc'], font=('Segoe UI Symbol', 13, 'bold'))

    def pick_kind(self, k):
        self.kind = k
        if getattr(self, 'new_btn', None) is not None:
            self.new_btn.config(state='disabled' if k == 'spider' else 'normal')   # l'araignee n'a pas d'oeuf ni de vie
        for kk, b in self.race_btns.items():
            on = kk == k
            b.config(bg=DLG['acc'] if on else DLG['btn'], fg='#ffffff' if on else DLG['fg'], activebackground='#ff9a70' if on else DLG['acc2'])
        for b in self.coat_btns.values():
            b.destroy()
        self.coat_btns = {}
        tab, _, order = coat_table(k)
        self.coats[k] = valid_coat(k, self.coats.get(k))
        for i, c in enumerate(order):
            b = tk.Button(self.coat_box, text=tab[c]['name'], relief='flat', bd=0, cursor='hand2', font=('Segoe UI', 9), padx=8, pady=4,
                          command=lambda c=c: self.pick_coat(c))
            b.grid(row=i // 3, column=i % 3, padx=(0, 6), pady=(0, 6), sticky='we')
            self.coat_btns[c] = b
        self.pick_coat(self.coats[k])

    def pick_coat(self, c):
        self.coats[self.kind] = c
        for cc, b in self.coat_btns.items():
            on = cc == c
            b.config(bg=DLG['acc2'] if on else DLG['card'], fg=DLG['fg'], relief='solid' if on else 'flat', bd=1 if on else 0)
        self.make_model()

    def make_model(self):
        self.model = None
        self.t = 0.0
        try:
            if self.kind == 'spider':
                self.model = Spider(150, 120, 2.2, self.coats['spider'])
            else:
                u = {'dog': 1.35, 'goat': 1.4, 'ferret': 1.45}.get(self.kind, 1.6)
                ct = Cat(150, 196, u, self.coats[self.kind])
                ct.dir = 1
                ct.view, ct.hlook = '3q', True
                ct.set_pose('sit', 30)
                for _ in range(30):
                    ct.update(0.04, 0, True)
                    ct.view = '3q'
                self.model = ct
        except Exception:
            self.model = None

    def anim(self):
        if self.done:
            return
        try:
            self.draw_banner()
        except Exception:
            pass
        try:
            cv = self.cv
            cv.delete('all')
            cv.create_rectangle(0, 196, 300, 230, fill='#d9e6c8', outline='')
            cv.create_oval(95, 190, 205, 204, fill='#c4d3b2', outline='')
            self.t += 0.04
            m = self.model
            if isinstance(m, Cat):
                ph = int(self.t / 3.5) % 3
                m.set_pose(('sit', 'stand', 'sit')[ph], 6)
                m.view = ('3q', 'side', 'front')[ph]
                m.update(0.04, 0, True)
                m.view = ('3q', 'side', 'front')[ph]
                m.draw(cv)
            elif m is not None:
                m.draw(cv)
            else:
                cv.create_text(150, 110, text=ANIMALS.get(self.kind, ''), fill=DLG['fg'], font=('Segoe UI', 16, 'bold'))
            cv.create_text(150, 20, text='%s  -  %s' % (ANIMALS[self.kind], coat_name(self.kind, self.coats[self.kind])),
                           fill=DLG['fg'], font=('Segoe UI', 11, 'bold'))
        except Exception:
            pass
        self.win.after(40, self.anim)

    def open_load(self):
        def chosen(i):
            self.finish('load', i)
        load_menu(self.win, self.saves, chosen, None)

    def finish(self, what, idx=None):
        if self.done:
            return
        self.done = True
        res = {'what': what, 'kind': self.kind, 'coat': self.coats[self.kind], 'idx': idx}
        if self.mode == 'launch':
            res['show'] = bool(self.show_var.get())
        self.win.destroy()
        self.on_done(res)

    def cancel(self):
        if not self.done:
            self.done = True
            self.win.destroy()
            self.on_done(None)


def load_menu(master, saves, on_load, on_delete):
    """Liste des animaux sauvegardes : Charger (et Supprimer si on_delete)."""
    w = _dlg_window(master, 'Mes animaux')
    box = tk.Frame(w, bg=DLG['bg'], padx=24, pady=18)
    box.pack()
    tk.Label(box, text='Mes animaux sauvegardés', bg=DLG['bg'], fg=DLG['fg'], font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    tk.Label(box, text="Charger un animal met l'animal actuel de côté : tu pourras le reprendre ici.", bg=DLG['bg'], fg=DLG['sub'],
             font=('Segoe UI', 9)).pack(anchor='w', pady=(2, 12))
    lst = tk.Frame(box, bg=DLG['bg'])
    lst.pack(fill='x')

    def fill():
        for ch in lst.winfo_children():
            ch.destroy()
        if not saves:
            tk.Label(lst, text='Aucun animal sauvegardé pour le moment.', bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 10)).pack(anchor='w', pady=8)
        for i, rec in enumerate(saves):
            row = tk.Frame(lst, bg=DLG['card'], padx=12, pady=8, highlightbackground=DLG['line'], highlightthickness=1)
            row.pack(fill='x', pady=(0, 6))
            tk.Label(row, text=record_text(rec), bg=DLG['card'], fg=DLG['fg'], font=('Segoe UI', 11)).pack(side='left')
            _btn(row, 'Charger', lambda i=i: (w.destroy(), on_load(i)), main=True, small=True).pack(side='right')
            if on_delete:
                _btn(row, 'Supprimer', lambda i=i: ask_yes_no(w, 'Supprimer cet animal ?', '%s sera effacé pour de bon.' % record_text(saves[i]),
                                                                lambda i=i: (on_delete(i), fill()), yes='Supprimer'),
                     small=True).pack(side='right', padx=6)
    fill()
    bot = tk.Frame(box, bg=DLG['bg'])
    bot.pack(fill='x', pady=(10, 0))
    _btn(bot, 'Fermer', w.destroy).pack(side='right')
    w.bind('<Escape>', lambda e: w.destroy())
    _dlg_place(w)
    return w


def _anon(text):
    """Retire le nom d'utilisateur Windows des chemins (le rapport est public sur GitHub)."""
    home = os.path.expanduser('~')
    user = os.path.basename(home)
    text = text.replace(home, '~').replace(home.replace('\\', '/'), '~')
    if len(user) > 2:
        text = text.replace(user, '<utilisateur>')
    return text


def bug_dialog(master, info, log_path):
    """Rapport de bug : on decrit le probleme, on voit exactement ce qui sera envoye, puis GitHub s'ouvre
    dans le navigateur avec le ticket pre-rempli (c'est toi qui cliques sur « Submit », avec ton compte GitHub)."""
    import urllib.parse
    import webbrowser
    w = _dlg_window(master, 'Signaler un bug')
    box = tk.Frame(w, bg=DLG['bg'], padx=24, pady=18)
    box.pack()
    tk.Label(box, text='Signaler un bug', bg=DLG['bg'], fg=DLG['fg'], font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    tk.Label(box, text="Raconte ce qui s'est passé : ton navigateur va ouvrir un ticket GitHub déjà rempli, tu n'auras plus qu'à l'envoyer.",
             bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 9), wraplength=520, justify='left').pack(anchor='w', pady=(2, 10))
    tk.Label(box, text='TITRE', bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 8, 'bold')).pack(anchor='w')
    title = tk.StringVar()
    fr = tk.Frame(box, bg=DLG['acc'], padx=2, pady=2)
    fr.pack(fill='x', pady=(2, 8))
    te = tk.Entry(fr, textvariable=title, font=('Segoe UI', 11), relief='flat', bd=5, bg=DLG['card'], fg=DLG['fg'], width=60)
    te.pack(fill='x')
    tk.Label(box, text="QUE S'EST-IL PASSÉ ?  (ce que tu faisais, ce que tu attendais)", bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 8, 'bold')).pack(anchor='w')
    fr2 = tk.Frame(box, bg=DLG['line'], padx=1, pady=1)
    fr2.pack(fill='x', pady=(2, 8))
    desc = tk.Text(fr2, height=6, font=('Segoe UI', 10), relief='flat', bd=6, bg=DLG['card'], fg=DLG['fg'], wrap='word')
    desc.pack(fill='x')
    log_txt = ''
    try:
        with open(log_path, encoding='utf-8', errors='replace') as f:
            log_txt = ''.join(f.readlines()[-40:]).strip()
    except Exception:
        pass
    add_log = tk.BooleanVar(value=bool(log_txt))
    tk.Checkbutton(box, text="Joindre le journal d'erreurs" + ('' if log_txt else '  (vide : aucune erreur enregistrée)'), variable=add_log,
                   state='normal' if log_txt else 'disabled', bg=DLG['bg'], fg=DLG['fg'], activebackground=DLG['bg'], selectcolor=DLG['card'],
                   font=('Segoe UI', 9)).pack(anchor='w')
    tk.Label(box, text='Infos jointes automatiquement (ton nom d’utilisateur est retiré) :', bg=DLG['bg'], fg=DLG['sub'], font=('Segoe UI', 8)).pack(anchor='w', pady=(6, 0))
    tk.Label(box, text=info, bg=DLG['bg'], fg=DLG['sub'], font=('Consolas', 8), justify='left').pack(anchor='w')
    msg = tk.Label(box, text=' ', bg=DLG['bg'], fg='#d0453a', font=('Segoe UI', 9))
    msg.pack(anchor='w')

    def body():
        b = '### Ce qui s\'est passé\n' + (desc.get('1.0', 'end').strip() or '(pas de description)') + '\n\n### Configuration\n```\n' + info + '\n```\n'
        if add_log.get() and log_txt:
            b += '\n### Journal d\'erreurs (fin)\n```\n' + log_txt[-3500:] + '\n```\n'
        return _anon(b)

    def send():
        if not title.get().strip() and not desc.get('1.0', 'end').strip():
            msg.config(text='Écris au moins un titre ou une description.')
            return
        t = title.get().strip() or '[Bug] ' + desc.get('1.0', 'end').strip().splitlines()[0][:60]
        url = 'https://github.com/%s/issues/new?%s' % (GITHUB_REPO, urllib.parse.urlencode({'title': _anon(t), 'body': body()[:6000], 'labels': 'bug'}))
        try:
            webbrowser.open(url)
        except Exception:
            msg.config(text="Impossible d'ouvrir le navigateur : utilise « Copier le rapport ».")
            return
        w.destroy()

    def copy():
        w.clipboard_clear()
        w.clipboard_append((title.get().strip() + '\n\n' if title.get().strip() else '') + body())
        msg.config(text='Rapport copié : colle-le dans un ticket sur github.com/%s/issues' % GITHUB_REPO, fg=DLG['sub'])
    row = tk.Frame(box, bg=DLG['bg'])
    row.pack(fill='x', pady=(8, 0))
    _btn(row, 'Ouvrir le ticket sur GitHub', send, main=True).pack(side='right')
    _btn(row, 'Copier le rapport', copy).pack(side='right', padx=8)
    _btn(row, 'Annuler', w.destroy).pack(side='left')
    w.bind('<Escape>', lambda e: w.destroy())
    _dlg_place(w)
    w.after(60, te.focus_set)
    return w


def make_click_through(root):
    root.update_idletasks()
    wid = root.winfo_id()
    top = user32.GetParent(wid) or wid          # vraie fenetre de premier niveau
    st = user32.GetWindowLongW(top, -20)
    # LAYERED | TRANSPARENT | TOOLWINDOW | NOACTIVATE
    user32.SetWindowLongW(top, -20, st | 0x80000 | 0x20 | 0x80 | 0x08000000)
    # (re)declare la couleur transparente (COLORREF = BGR de KEY)
    user32.SetLayeredWindowAttributes(top, 0x030201, 0, 0x1)
    return top


def set_clickthrough(top, on):
    st = user32.GetWindowLongW(top, -20)
    st = (st | 0x20) if on else (st & ~0x20)
    user32.SetWindowLongW(top, -20, st)


def quit_hotkey():
    down = lambda vk: user32.GetAsyncKeyState(vk) & 0x8000
    return down(0x11) and down(0x12) and down(ord('Q'))


def run_launcher(cfg):
    """Menu de demarrage : race et pelage (et charger / nouvel oeuf). Modifie cfg ; True si quelque chose a change."""
    try:
        lr = tk.Tk()
        lr.withdraw()
    except Exception:
        return False
    kind_now = str(cfg.get('animal') or 'cat')
    life_kind = cfg.get('life_kind') if cfg.get('life_kind') in MAMMALS else (kind_now if kind_now in MAMMALS else 'cat')
    coats = {k: cfg.get(coat_table(k)[1]) for k in ANIMALS}
    life_d = cfg.get('life') if isinstance(cfg.get('life'), dict) else None
    saves = [r for r in cfg.get('saved', []) if isinstance(r, dict) and r.get('kind') in MAMMALS and isinstance(r.get('life'), dict)] \
        if isinstance(cfg.get('saved'), list) else []
    if life_d:
        cur = record_text({'kind': life_kind, 'coat': coats.get(life_kind), 'life': life_d})
        summary = 'Ton animal : ' + cur + ('' if kind_now != 'spider' else '   (en ce moment : araignee)')
    else:
        summary = 'Choisis une race et un pelage : un œuf va apparaître sur ton bureau.'
    res = {}
    ch = Chooser(lr, 'launch', kind_now, coats, lambda r: res.update(r or {}), summary=summary, saves=saves)
    try:
        lr.wait_window(ch.win)
    except Exception:
        pass
    try:
        lr.destroy()
    except Exception:
        pass
    if not res:
        return False
    PREFS['launcher'] = res.get('show', True)
    cfg['show_launcher'] = PREFS['launcher']
    what, kind, coat = res['what'], res['kind'], res['coat']
    cur_rec = {'kind': life_kind, 'coat': valid_coat(life_kind, coats.get(life_kind)), 'life': life_d} if life_d else None
    if what == 'load' and res.get('idx') is not None and 0 <= res['idx'] < len(saves):
        rec = saves.pop(res['idx'])
        if cur_rec:
            saves.append(cur_rec)
        kind, coat = rec['kind'], rec.get('coat')
        cfg['life'] = rec['life']
    elif what == 'new' and kind in MAMMALS:
        if cur_rec:
            saves.append(cur_rec)
        cfg['life'] = Life.new_egg().dump()
    cfg['saved'] = saves
    cfg['animal'] = kind
    cfg[coat_table(kind)[1]] = valid_coat(kind, coat)
    if kind in MAMMALS:
        cfg['life_kind'] = kind
    return True


def main():
    argv = sys.argv[1:]

    def opt(name, default):
        return argv[argv.index(name) + 1] if name in argv else default

    corner = opt('--corner', 'tr')
    if getattr(sys, 'frozen', False):                         # version .exe : reglages et journal dans %APPDATA%
        base_ = os.environ.get('APPDATA') or os.path.dirname(sys.executable)
        app_dir = os.path.join(base_, 'DesktopPet')
        old_ = os.path.join(base_, 'AraigneeBureau')            # ancien nom du dossier : on reprend son contenu une fois
        if os.path.isdir(old_) and not os.path.exists(app_dir):
            try:
                shutil.copytree(old_, app_dir)
            except Exception:
                pass
        try:
            os.makedirs(app_dir, exist_ok=True)
        except Exception:
            app_dir = os.path.dirname(sys.executable)
        if sys.stdout is None:
            sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w')
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = os.path.join(app_dir, 'araignee_config.json')
    cfg = {}
    if '--selftest' not in argv:
        import json
        for pth in (cfg_path, cfg_path + '.bak'):                # fichier abime : on reprend la copie de secours
            try:
                with open(pth, encoding='utf-8') as f:
                    d_ = json.load(f)
            except Exception:
                continue
            if isinstance(d_, dict):
                cfg = d_
                if pth == cfg_path:
                    try:
                        shutil.copy2(cfg_path, cfg_path + '.bak')    # copie de secours d'un fichier qui se lit bien
                    except Exception:
                        pass
                break
    species = opt('--espece', cfg.get('species', 'peacock'))
    if species not in SPECIES:
        species = 'peacock'
    regtest = '--regtest' in argv
    dancetest = '--dancetest' in argv
    flytest = '--flytest' in argv
    selftest = '--selftest' in argv
    speed = float(opt('--speed', 1.0))
    shots = opt('--shots', None)
    here = app_dir

    if not selftest and '--multi' not in argv:
        try:
            k32_ = ctypes.windll.kernel32
            k32_.CreateMutexW.restype = ctypes.c_void_p
            _mutex = k32_.CreateMutexW(None, False, 'Local\\AraigneeBureauPet')
            if k32_.GetLastError() == 183:                         # ERROR_ALREADY_EXISTS : déjà lancée
                return
        except Exception:
            pass

    mons = list_monitors()
    mon_i = 1
    try:
        mon_i = int(opt('--monitor', cfg.get('monitor', 1)))
    except Exception:
        mon_i = 1
    if '--autre-ecran' in argv:
        mon_i = 2
    if selftest or not (1 <= mon_i <= len(mons)):
        mon_i = 1
    MON['index'] = mon_i
    if mons:
        mr = mons[mon_i - 1]['rect']
        MON['ox'], MON['oy'], MON['rect'] = mr[0], mr[1], mr
        sw, sh = mr[2] - mr[0], mr[3] - mr[1]
        wk = mons[mon_i - 1]['work']
    else:
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        wk = None
    PREFS['launcher'] = bool(cfg.get('show_launcher', True))
    launch_changed = False
    if (not selftest and PREFS['launcher'] and '--direct' not in argv and '--animal' not in argv
            and not any(a in argv for a in ('--regtest', '--dancetest', '--flytest', '--switchtest'))):
        launch_changed = run_launcher(cfg)
    root = tk.Tk()
    scale = float(opt('--scale', 1.4)) * max(1.0, sh / 1080.0)
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    opaque = '--opaque' in argv          # test : fond gris visible pour les captures
    bg = '#6b7c8c' if opaque else KEY
    root.configure(bg=bg)
    if not opaque:
        root.attributes('-transparentcolor', KEY)
    root.geometry(f"{sw}x{sh}+{MON['ox']}+{MON['oy']}")
    canvas = tk.Canvas(root, width=sw, height=sh, bg=bg, highlightthickness=0, bd=0)
    canvas.pack()
    root.update()
    top = None
    if not opaque:
        top = make_click_through(root)

    area = (wk[0] - MON['ox'], wk[1] - MON['oy'], wk[2] - MON['ox'], wk[3] - MON['oy']) if wk else work_area()
    pet = Pet(area, scale, corner, real_cursor, log=print if selftest else None, species=species)

    # ---- scénario de test automatique (curseur simulé, temps accéléré)
    if selftest:
        l, t, r, b = area
        hx, hy = pet.web.hub
        sx, sy = pet.web.sx, pet.web.sy
        R = pet.web.R
        cursor = {'p': ((l + r) / 2, (t + b) / 2), 'phase': 0, 't0': 0.0}
        shot_done = set()

        def shot(name):
            if shots and name not in shot_done:
                shot_done.add(name)
                try:
                    from PIL import ImageGrab
                    ImageGrab.grab().save(os.path.join(shots, name + '.png'))
                except Exception as e:
                    print('capture impossible', e)

        def scripted():
            ph = cursor['phase']
            n = pet.now
            if regtest:
                if ph == 0 and n > 1.0:
                    cursor['phase'] = 1
                    pet.start_regius_show()
                elif pet.state == 'rwave' and pet.state_t > 1.3:
                    shot('10_coucou')
                elif pet.state == 'rjump' and pet.state_t > 0.35 and pet.state_t < 0.5:
                    shot('11_saut')
                elif ph == 1 and pet.state == 'idle' and n > 4:
                    cursor['phase'] = 9
                    print('FIN REGIUS')
                    root.after(10, root.destroy)
                return cursor['p']
            if flytest:
                cursor['p'] = (sw * 0.5, sh * 0.85)
                if ph == 0 and pet.web.built_ratio() > 0.9:
                    cursor['phase'] = 1
                    pet.spawn_fly()
                    pet.spawn_fly()
                elif ph == 1:
                    shot('8_panier')
                    for fl in pet.flies:
                        if fl.state == 'stuck' and fl.stuck_t > 0.4 and pet.state != 'hunt' and fl.wrap == 0:
                            shot('6_mouche_collee')
                    if pet.state == 'wrap' and pet.target_fly and pet.target_fly.wrap > 0.55:
                        shot('7_enroule')
                    if pet.state == 'eat' and pet.state_t > 1.5:
                        shot('9_mange')
                    if pet.state == 'eat':
                        cursor['ate'] = True
                    elif cursor.get('ate') and pet.state == 'idle':
                        print('FIN MOUCHE')
                        cursor['phase'] = 9
                        root.after(10, root.destroy)
                    if n > 400:
                        print('ECHEC: temps depasse')
                        cursor['phase'] = 9
                        root.after(10, root.destroy)
                return cursor['p']
            if dancetest:
                if ph == 0 and n > 1.0:
                    cursor['phase'] = 1
                    pet.start_dance()
                elif pet.state == 'dance' and pet.state_t > 3.0:
                    shot('5_danse')
                elif ph == 1 and pet.state == 'idle' and n > 5:
                    cursor['phase'] = 9
                    print('FIN DANSE')
                    root.after(10, root.destroy)
                return cursor['p']
            if ph == 0:
                if pet.web.built_ratio() > 0.5:
                    shot('1_toile_en_cours')
                if pet.web.missing() == 0 or n > 120:
                    shot('2_toile_finie')
                    cursor['phase'], cursor['t0'] = 1, n
            elif ph == 1:                                  # coup de souris à travers la toile
                u = clamp((n - cursor['t0']) / 0.5, 0, 1)
                a = math.radians(50)
                p0 = (hx + sx * math.cos(a) * R * 1.0, hy + sy * math.sin(a) * R * 1.0)
                p1 = (hx + sx * math.cos(a) * R * 0.15, hy + sy * math.sin(a) * R * 0.15)
                cursor['p'] = (lerp(p0[0], p1[0], u), lerp(p0[1], p1[1], u))
                if u >= 1:
                    cursor['phase'], cursor['t0'] = 2, n
            elif ph == 2:
                if pet.state == 'cling':
                    if pet.state_t > 1.5:
                        shot('3_accrochee_souris')
                        cursor['phase'], cursor['t0'] = 3, n
                elif n - cursor['t0'] > 20:
                    cursor['phase'], cursor['t0'] = 3, n
            elif ph == 3:                                  # on secoue la souris
                q = (n - cursor['t0'])
                base = ((l + r) / 2, (t + b) / 2)
                cursor['p'] = (base[0] + 300 * math.sin(q * 25), base[1])
                if pet.state != 'cling' and q > 0.5:
                    cursor['phase'], cursor['t0'] = 4, n
                    cursor['p'] = (200.0, 200.0)
            elif ph == 4:
                if n - cursor['t0'] > 70:
                    shot('4_reconstruction')
                    print('FIN TEST OK, toile', f"{pet.web.built_ratio():.0%}")
                    root.after(10, root.destroy)
                    cursor['phase'] = 5
            return cursor['p']

        pet.getcur = scripted
        pet.cur = pet.pcur = cursor['p']

    shared = dict(cfg)                                          # état persistant (fusionné entre animaux)
    inter = [False]
    renderer = Renderer(canvas)

    def num(key, default, lo, hi):
        try:
            return clamp(float(cfg.get(key, default)), lo, hi)
        except Exception:
            return default

    def save_cfg(d):
        if selftest:
            return
        import json
        shared.update(d)
        tmp = cfg_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(shared, f)
        os.replace(tmp, cfg_path)                                # écriture atomique

    def sample_color(x, y):
        try:
            gdi = ctypes.windll.gdi32
            gdi.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
            gdi.GetPixel.restype = wintypes.DWORD
            user32.GetDC.restype = wintypes.HDC
            user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            hdc = user32.GetDC(None)
            v = gdi.GetPixel(hdc, int(x) + MON['ox'], int(y) + MON['oy'])
            user32.ReleaseDC(None, hdc)
            if v == 0xFFFFFFFF:
                return None
            return (float(v & 0xFF), float((v >> 8) & 0xFF), float((v >> 16) & 0xFF))
        except Exception:
            return None

    def wire(p_):
        p_.getbtn = lambda: user32.GetAsyncKeyState(0x01) & 0x8000
        p_.getbtn2 = lambda: user32.GetAsyncKeyState(0x02) & 0x8000
        p_.getctrl = lambda: user32.GetAsyncKeyState(0x11) & 0x8000
        if selftest:
            p_.getbtn = lambda: False
        p_.cfg_save = save_cfg
        if hasattr(p_, 'draw_cat'):
            p_.aa_on = bool(shared.get('aa', True))
        p_.quit_cb = root.destroy
        p_.switch_animal_cb = switch_animal
        p_.bug_cb = report_bug
        if hasattr(p_, 'life'):
            p_.ask_name_cb, p_.reset_cb, p_.load_cb = ask_pet_name, new_animal, open_saves
        if hasattr(p_, 'sample_cb'):
            p_.sample_cb = sample_color
        return p_

    def switch_animal(kind, life=None, coat=None):
        """Menu > Race : remplace le cerveau actuel (araignée <-> chat) en gardant sons, panier, taille, style.
        life / coat : on installe un autre animal (chargement d'une sauvegarde, nouvel oeuf)."""
        nonlocal pet
        old = pet
        if kind == getattr(old, 'animal', None) and life is None and coat is None:
            return
        if kind in ANIMALS:
            if coat is not None:
                shared[coat_table(kind)[1]] = valid_coat(kind, coat)
        if hasattr(old, 'life_save'):
            old.life_save()
        if hasattr(old, 'close_layers'):
            old.close_layers()
        if kind in ('cat', 'dog', 'goat', 'ferret'):
            if kind == 'cat':
                coat = shared.get('coat') if shared.get('coat') in COATS else 'tabby'
                new = CatPet(area, old.s, old.getcur, log=old.log, coat=coat)
            elif kind == 'ferret':
                coat = shared.get('fcoat') if shared.get('fcoat') in FERRET_COATS else 'sable'
                new = FerretPet(area, old.s, old.getcur, log=old.log, coat=coat)
            elif kind == 'goat':
                coat = shared.get('gcoat') if shared.get('gcoat') in GOAT_COATS else 'caramel'
                new = GoatPet(area, old.s, old.getcur, log=old.log, coat=coat)
            else:
                coat = shared.get('dcoat') if shared.get('dcoat') in DOG_COATS else 'golden'
                new = DogPet(area, old.s, old.getcur, log=old.log, coat=coat)
            new.snd, new.bk = old.snd, old.bk
            new.snap_basket()
            new.set_cute(old.cute)
            if life is not None:
                new.life = life
                new.hunger = life.hunger
            elif hasattr(old, 'life'):
                new.life = old.life                              # c'est le meme animal, il change juste de race
                new.hunger = old.hunger
            else:
                new.life = Life.load(shared.get('life'))
                new.hunger = new.life.hunger
            new.apply_growth()
            new.ambient = bool(shared.get('ambient', True))
            if kind == 'cat':
                new.buddy_on = bool(shared.get('buddy', False))
                new.ensure_buddy()
        elif kind == 'spider':
            sp_name = shared.get('species') if shared.get('species') in SPECIES else 'peacock'
            new = Pet(area, old.s, corner, old.getcur, log=old.log, species=sp_name)
            new.snd, new.bk = old.snd, old.bk
            new.dew_on = bool(shared.get('dew', 5 <= time.localtime().tm_hour < 11))
            new.comp_on = bool(shared.get('comp', False))
            new.set_cute(old.cute)
            new.hunger = old.hunger
        else:
            return
        wire(new)
        if hasattr(new, 'life_save'):
            new.life_save()
        new.set_windows(old.windows)
        if getattr(new, 'comp_on', False):
            new.ensure_comp()
        pet = new
        inter[0] = None                                           # force la mise à jour du clic traversant
        renderer.reset()
        new.save_config()

    dlg_open = {}

    def single(key, make):                                      # une seule fenetre de chaque sorte a la fois
        w = dlg_open.get(key)
        try:
            if w is not None and (w.winfo_exists() if hasattr(w, 'winfo_exists') else w.win.winfo_exists()):
                (w if hasattr(w, 'lift') else w.win).lift()
                return
        except Exception:
            pass
        dlg_open[key] = make()

    def report_bug():
        import platform
        p = pet
        kind = getattr(p, 'animal', 'spider')
        coat = getattr(getattr(p, 'cat', None), 'coat', None) or getattr(getattr(p, 'sp', None), 'species', '?')
        info = '\n'.join([
            'Version : %s (%s)' % (VERSION, 'exe' if getattr(sys, 'frozen', False) else 'sources Python %s' % platform.python_version()),
            'Windows : %s' % platform.platform(),
            'Animal  : %s / %s, taille %.2f' % (ANIMALS.get(kind, kind), coat, getattr(p, 's', 0)),
            'Ecran   : %d sur %d, %dx%d' % (MON.get('index', 1), monitor_count(), sw, sh),
            'Rendu   : %s' % ('lisse' if getattr(p, 'aa_on', False) else 'standard'),
            'Son     : %s, volume %d %%' % ('oui' if p.snd.on else 'coupe', round(p.snd.volume * 100)),
            'Erreurs : %d depuis le lancement' % errs['n']])
        single('bug', lambda: bug_dialog(root, info, err_path))

    def saved_list():
        lst = shared.get('saved')
        return [r for r in lst if isinstance(r, dict) and r.get('kind') in MAMMALS and isinstance(r.get('life'), dict)] if isinstance(lst, list) else []

    def current_record():
        p = pet
        if not hasattr(p, 'life'):
            return None
        p.life.hunger = p.hunger
        return {'kind': p.animal, 'coat': p.cat.coat, 'life': p.life.dump()}

    def ask_pet_name():
        p = pet
        if not hasattr(p, 'life'):
            return

        def ok(name):
            if pet is p:
                p.life.name = name
                p.say('Je m appelle ' + name + ' !')
                p.hearts.append([p.cat.x, p.cat.y - 70 * p.u, 0.0])
                p.sound('ding')
                p.life_save()
        single('name', lambda: ask_name(root, ok, p.life.name, MON['ox'] + p.cat.x, MON['oy'] + p.cat.y - 60 * p.u))

    def new_animal():
        p = pet
        if not hasattr(p, 'life'):
            return
        nm = p.life.name or 'Ton animal actuel'

        def done(res):
            if res is None or pet is not p:
                return
            rec = current_record()
            lst = saved_list()
            if rec:
                lst.append(rec)                                  # l'animal actuel est mis de cote, pas efface
            save_cfg({'saved': lst})
            switch_animal(res['kind'], life=Life.new_egg(), coat=res['coat'])
        coats = {k: shared.get(coat_table(k)[1]) for k in ANIMALS}
        coats[p.animal] = p.cat.coat
        single('chooser', lambda: Chooser(root, 'new', p.animal, coats, done,
                                          summary='%s sera sauvegardé : tu pourras le reprendre avec Animal > Charger un animal.' % nm))

    def open_saves():
        lst = saved_list()

        def load(i):
            lst2 = saved_list()
            if not (0 <= i < len(lst2)):
                return
            rec_new = lst2.pop(i)
            rec = current_record()
            if rec:
                lst2.append(rec)
            save_cfg({'saved': lst2})
            switch_animal(rec_new['kind'], life=Life.load(rec_new['life']), coat=rec_new.get('coat'))

        def delete(i):
            lst2 = saved_list()
            if 0 <= i < len(lst2):
                lst2.pop(i)
                save_cfg({'saved': lst2})
                lst[:] = lst2
        single('saves', lambda: load_menu(root, lst, load, delete))

    wire(pet)
    if launch_changed:
        save_cfg({})
    if '--monitor' in argv or '--autre-ecran' in argv:
        save_cfg({'monitor': mon_i})                          # retenu pour les prochains lancements
    if 'bx' in cfg and 'by' in cfg:
        l_, t_, r_, b_ = area
        pet.bk.x = num('bx', pet.bk.x, l_ + 30 * pet.bk.s, r_ - 30 * pet.bk.s)
        pet.bk.y = num('by', pet.bk.y, t_ + 46 * pet.bk.s, b_ - 30 * pet.bk.s)
    if 'scale' in cfg and '--scale' not in argv:
        pet.set_scale(num('scale', pet.s, 0.8, 3.2))
    pet.snd.set_volume(num('volume', 0.6, 0.1, 1.0))
    pet.snd.on = bool(cfg.get('sound', True)) and pet.snd.on and not selftest
    pet.dew_on = bool(cfg.get('dew', 5 <= time.localtime().tm_hour < 11))
    pet.comp_on = bool(cfg.get('comp', False))
    pet.set_cute(bool(cfg.get('cute', False)))
    pet.set_windows(read_windows())
    if pet.comp_on:
        pet.ensure_comp()
    animal0 = opt('--animal', str(cfg.get('animal', 'spider')))
    if animal0 in ('cat', 'dog', 'goat', 'ferret') and not selftest:
        switch_animal(animal0)
    if '--switchtest' in argv:                                   # test : bascule araignée -> chat -> araignée
        def _rep(tag):
            print(tag, type(pet).__name__, 'erreurs:', errs['n'])
        root.after(2500, lambda: (switch_animal('cat'), _rep('apres bascule chat   :')))
        root.after(7000, lambda: _rep('chat apres 4.5 s     :'))
        root.after(7500, lambda: (switch_animal('spider'), _rep('apres bascule araignee:')))
        root.after(12000, lambda: (_rep('araignee apres 4.5 s :'), root.destroy()))
    last = time.perf_counter()
    win_t = [0.0]
    fs_t = [0.0]
    top_t = [0.0]
    hidden = [False]
    errs = {'n': 0, 'consec': 0}
    err_path = os.path.join(here, 'araignee_erreur.log')

    def log_error():
        import traceback
        errs['n'] += 1
        try:
            if os.path.exists(err_path) and os.path.getsize(err_path) > 200000:
                os.remove(err_path)
            if errs['n'] <= 40:
                with open(err_path, 'a', encoding='utf-8') as f:
                    f.write(traceback.format_exc() + '\n')
        except Exception:
            pass

    def hotkey_poll():                                           # Ctrl+Alt+Q marche même si le dessin plante
        if quit_hotkey() and not selftest:
            root.destroy()
            return
        root.after(150, hotkey_poll)

    def tick():
        nonlocal last
        t0 = time.perf_counter()
        try:
            if not selftest and t0 - fs_t[0] > 0.5:               # se cache devant un jeu / une vidéo plein écran
                fs_t[0] = t0
                fs = other_fullscreen(sw, sh)
                if fs and not hidden[0]:
                    root.withdraw()
                    hidden[0] = True
                    if hasattr(pet, 'hide_layers'):
                        pet.hide_layers()
                elif not fs and hidden[0]:
                    root.deiconify()
                    root.attributes('-topmost', True)
                    hidden[0] = False
                    last = t0
            if hidden[0]:
                root.after(250, tick)
                return
            dt = min(t0 - last, 0.1) * (speed if selftest else 1.0)
            last = t0
            steps = max(1, int(math.ceil(dt / 0.04)))
            for _ in range(steps):
                pet.update(dt / steps)
            if UPDATER.ready:                                      # mise a jour telechargee : on ferme, un script remplace l'exe et relance
                new_exe, UPDATER.ready = UPDATER.ready, None
                if hasattr(pet, 'life_save'):
                    pet.life_save()
                try:
                    shutil.copy2(cfg_path, cfg_path + '.bak')                # filet de securite : age, etat, caractere...
                except Exception:
                    pass
                apply_update(new_exe, UPDATER.exe_path, [x for x in relaunch_cmd()[1:]] + ['--direct'])
                root.destroy()
                return
            if t0 - win_t[0] > 0.4:
                win_t[0] = t0
                pet.set_windows(read_windows())
            if top and pet.interactive != inter[0]:
                inter[0] = pet.interactive
                if hasattr(pet, 'solid_layers'):
                    pet.solid_layers(bool(inter[0]))
                set_clickthrough(top, not inter[0])
                canvas.config(cursor='hand2' if inter[0] else '')
            renderer.render(pet)
            if t0 - top_t[0] > 5:
                top_t[0] = t0
                root.attributes('-topmost', True)
            errs['consec'] = 0
        except tk.TclError:
            return
        except Exception:
            log_error()
            errs['consec'] += 1
            if top:                                              # ne jamais laisser la fenêtre bloquer les clics
                try:
                    set_clickthrough(top, True)
                    inter[0] = False
                except Exception:
                    pass
            if errs['consec'] >= 30:
                try:
                    root.destroy()
                except Exception:
                    pass
                return
        wait = max(1, 33 - int((time.perf_counter() - t0) * 1000))
        root.after(wait, tick)

    root.after(10, tick)
    root.after(150, hotkey_poll)
    root.mainloop()
    if hasattr(pet, 'life_save'):
        try:
            pet.life_save()                                      # on garde les dernieres secondes de vie
        except Exception:
            pass
    if hasattr(pet, 'close_layers'):
        pet.close_layers()


if __name__ == '__main__':
    main()
