#!/usr/bin/env python3
"""
teams-tone - ti dice quale dei TUOI sfondi Teams sta bene con la maglietta.

Uno scatto dalla webcam, legge il colore della maglietta, misura gli sfondi che
hai gia in gallery e apre l'immagine di quello giusto, cosi la riconosci nella
griglia di miniature. Non aggiunge niente alla gallery, se non glielo chiedi.

    teams-tone                    scegli tra i tuoi sfondi
    teams-tone --mode tono        armonia morbida (salmone -> verde oliva)
    teams-tone --mode contrasto   colore opposto (salmone -> teal)
    teams-tone --sheet            tavola numerata di tutti i tuoi sfondi
    teams-tone --aggiungi FILE    aggiungi un'immagine alla gallery Teams
    teams-tone --image FOTO       usa una foto invece della webcam (per provare)

Dipendenze: numpy, pillow, opencv-python. Tutto in locale, niente rete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# --------------------------------------------------------------------------- #
# Regola di armonia: quale sfondo sta bene con quale maglietta.
# Tutte le soglie sono qui, in chiaro, modificabili.
# --------------------------------------------------------------------------- #
S_ACROMATICA = 0.15      # sotto: maglietta bianca/grigia/nera
S_ACCESA = 0.35          # sopra: tinta piena, conviene il contrasto
D_MIMETISMO = 25.0       # sotto: sfondo troppo simile alla maglietta, ti mimetizzi
D_TONO = 70.0            # armonia morbida: distanza sulla ruota dei colori
D_CONTRASTO = 175.0      # stacco: colore opposto
LUM_DELTA_MIN = 0.10     # stacco minimo di luminosita soggetto/sfondo
LUM_PENALITA = 8.0
CROMA_TOLLERANZA = 18.0  # di quanto lo sfondo puo essere piu carico della maglietta
CROMA_PENALITA = 0.35    # punti per unita di croma in eccesso
COERENZA_MIN = 0.60      # sotto: l'immagine non ha una tinta dominante chiara
CONFUSIONE_MAX = 0.040   # sopra: immagine troppo affollata, distrae in call

REC709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
FINESTRA_TINTA = 25.0
THUMB = (280, 158)
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp")
NS = uuid.UUID("6f2d1b8e-4c3a-5f77-9b21-0ad3f5c81e42")

CARTELLE_TEAMS = [
    Path.home() / "Library/Containers/com.microsoft.teams2/Data/Library"
                  "/Application Support/Microsoft/MSTeams/Backgrounds/Uploads",
    Path.home() / "Library/Application Support/Microsoft/Teams/Backgrounds/Uploads",
]
CACHE = Path.home() / ".cache/teams-tone/misure.json"
# Versione dello schema di misura: entra nella chiave di cache, cosi cambiare
# le metriche invalida le voci vecchie invece di leggerne i campi mancanti
# come zero, che disattiverebbe una penalita senza dirlo.
MISURA_V = 2
CONFIG = Path.home() / ".config/teams-tone/config.json"


def carica_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def salva_config(c: dict) -> None:
    try:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(c, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# misura colore
# --------------------------------------------------------------------------- #

def _hsv(a: np.ndarray) -> np.ndarray:
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mx, mn = a.max(-1), a.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-9
    rm, gm, bm = (mx == r) & m, (mx == g) & m, (mx == b) & m
    with np.errstate(invalid="ignore", divide="ignore"):
        h[rm] = ((g - b)[rm] / d[rm]) % 6.0
        h[gm] = ((b - r)[gm] / d[gm]) + 2.0
        h[bm] = ((r - g)[bm] / d[bm]) + 4.0
    s = np.where(mx > 1e-9, d / np.maximum(mx, 1e-9), 0.0)
    return np.stack([h / 6.0, s, mx], axis=-1)


def _tinta_dominante(hsv: np.ndarray) -> tuple[float, float]:
    """Tinta dominante come MODA circolare, piu quanto pesa sul totale.

    La media e un cattivo stimatore: cielo blu (215) e prato verde (100) in
    parti uguali danno 161, un verde acqua che nell'immagine non c'e. La moda
    trova la regione dominante vera.
    """
    nbins, bw = 72, 5.0
    deg = hsv[:, 0] * 360.0
    w = hsv[:, 1] ** 2 + 1e-9                       # i grigi non votano la tinta
    hist = np.bincount(np.minimum((deg / bw).astype(int), nbins - 1),
                       weights=w, minlength=nbins)
    tot = hist.sum()
    if tot <= 1e-8:
        return 0.0, 0.0

    half = int(round(FINESTRA_TINTA / bw))
    offs = np.arange(-half, half + 1)
    win = np.array([hist[(offs + i) % nbins].sum() for i in range(nbins)])
    peak = int(win.argmax())

    # Parto dal centroide pesato dei bin nella finestra vincente, non dal suo
    # centro geometrico: con la massa in un solo bin molte posizioni pareggiano
    # e argmax prende la piu a sinistra, il cui centro cade fuori dai pixel.
    idx = (offs + peak) % nbins
    ba = (idx + 0.5) * bw * np.pi / 180.0
    bwt = hist[idx]
    c = (np.arctan2((np.sin(ba) * bwt).sum(),
                    (np.cos(ba) * bwt).sum()) % (2 * np.pi)) * 180.0 / np.pi

    ang = deg * np.pi / 180.0
    for _ in range(6):                               # mean-shift sulla moda
        sel = np.abs((deg - c + 180.0) % 360.0 - 180.0) <= FINESTRA_TINTA
        if not sel.any():
            break
        ws = w[sel]
        nxt = (np.arctan2((np.sin(ang[sel]) * ws).sum(),
                          (np.cos(ang[sel]) * ws).sum()) % (2 * np.pi)) * 180.0 / np.pi
        shift = abs((nxt - c + 180.0) % 360.0 - 180.0)
        c = nxt
        if shift < 0.25:
            break
    sel = np.abs((deg - c + 180.0) % 360.0 - 180.0) <= FINESTRA_TINTA
    return float(c % 360.0), float(w[sel].sum() / tot)


def _croma_lab(rgb: np.ndarray) -> np.ndarray:
    """Croma C* CIELab per pixel.

    Serve perche la saturazione HSV NON e la croma percepita: un magenta e un
    oliva con la stessa sat HSV hanno intensita visiva molto diverse, e usare
    HSV per l'armonia di intensita fa scegliere colori sgargianti convinti che
    siano tenui come gli altri.
    """
    a = rgb.astype(np.float32) / 255.0
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124, 0.3576, 0.1805],
                  [0.2126, 0.7152, 0.0722],
                  [0.0193, 0.1192, 0.9505]], dtype=np.float32).T
    xyz = lin @ m
    white = np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    t = xyz / white
    f = np.where(t > 0.008856, np.cbrt(np.maximum(t, 1e-9)), 7.787 * t + 16.0 / 116.0)
    aa = 500.0 * (f[..., 0] - f[..., 1])
    bb = 200.0 * (f[..., 1] - f[..., 2])
    return np.hypot(aa, bb)


def misura(rgb: np.ndarray) -> dict:
    a = rgb.astype(np.float32) / 255.0
    hsv = _hsv(a).reshape(-1, 3)
    flat = a.reshape(-1, 3)
    keep = (hsv[:, 2] > 0.12) & (hsv[:, 2] < 0.97)   # via bruciati e ombre chiuse
    if keep.sum() > 200:
        flat, hsv = flat[keep], hsv[keep]

    tinta, coerenza = _tinta_dominante(hsv)
    sat = float(np.median(hsv[:, 1]))
    lum = float(np.median(flat @ REC709))

    small = np.asarray(Image.fromarray(rgb).resize((320, 180), Image.BILINEAR),
                       dtype=np.float32) / 255.0
    luma = small @ REC709
    confusione = float((np.abs(np.diff(luma, axis=1)).mean()
                        + np.abs(np.diff(luma, axis=0)).mean()) / 2.0)

    croma = float(np.median(_croma_lab(rgb.reshape(-1, 3))))

    neutra = sat < 0.12
    usabile = neutra or (coerenza >= COERENZA_MIN and confusione <= CONFUSIONE_MAX)
    return {"tinta": round(tinta, 1), "sat": round(sat, 3), "lum": round(lum, 3),
            "croma": round(croma, 1), "coerenza": round(coerenza, 3),
            "confusione": round(confusione, 4), "neutra": neutra, "usabile": usabile}


def misura_sfondo(path: Path) -> dict:
    """Misura la fascia centrale: la zona che sta dietro al busto."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    band = img.crop((int(0.20 * w), int(0.25 * h), int(0.80 * w), int(0.85 * h)))
    return misura(np.asarray(band))


def dist_tinta(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def sha(path: Path) -> str:
    d = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            d.update(c)
    return d.hexdigest()


# --------------------------------------------------------------------------- #
# gallery
# --------------------------------------------------------------------------- #

def cartella_teams(override: str | None = None) -> Path:
    if override:
        p = Path(override).expanduser()
        if not p.is_dir():
            raise SystemExit(f"cartella non trovata: {p}")
        return p
    for d in CARTELLE_TEAMS:
        if d.is_dir():
            return d
    raise SystemExit(
        "Non trovo la cartella degli sfondi di Teams. Attesa in:\n  "
        + "\n  ".join(str(d) for d in CARTELLE_TEAMS)
        + "\n\nApri Teams almeno una volta e carica uno sfondo, "
          "oppure indica la cartella con --teams-dir."
    )


def _cache_load() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_save(c: dict) -> None:
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(c), encoding="utf-8")
    except OSError:
        pass


def leggi_gallery(dest: Path, verbose: bool = True) -> list[dict]:
    """Misura gli sfondi presenti, con cache su (percorso, mtime, dimensione)."""
    files = sorted(f for f in dest.iterdir()
                   if f.suffix.lower() in IMG_EXT and not f.stem.endswith("_thumb"))
    cache = _cache_load()
    out, nuovi = [], 0
    for f in files:
        st = f.stat()
        key = f"v{MISURA_V}|{f}|{int(st.st_mtime)}|{st.st_size}"
        m = cache.get(key)
        if m is None:
            m = misura_sfondo(f)
            cache[key] = m
            nuovi += 1
        out.append({"path": str(f), "nome": f.stem[:8], **m})
    if nuovi:
        _cache_save(cache)
        if verbose:
            print(f"  misurati {nuovi} sfondi nuovi ({len(files)} in gallery)")
    return out


# --------------------------------------------------------------------------- #
# cattura webcam
# --------------------------------------------------------------------------- #

def scatta(warmup: int = 14) -> np.ndarray:
    try:
        import cv2

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            raise RuntimeError("webcam non apribile")
        frame = None
        for _ in range(warmup):          # l'esposizione ha bisogno di frame
            ok, f = cap.read()
            if ok:
                frame = f
            time.sleep(0.03)
        cap.release()
        if frame is None:
            raise RuntimeError("nessun frame letto")
        return frame[:, :, ::-1].copy()
    except Exception as exc:
        print(f"  (opencv non utilizzabile: {exc})", file=sys.stderr)

    tmp = Path(tempfile.mkdtemp()) / "shot.jpg"
    for cmd in (["imagesnap", "-w", "1", str(tmp)],
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "avfoundation",
                 "-framerate", "30", "-i", "0", "-frames:v", "1", "-y", str(tmp)]):
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, check=True, timeout=25)
            if tmp.is_file() and tmp.stat().st_size:
                return np.asarray(Image.open(tmp).convert("RGB"))
        except Exception:
            continue

    raise SystemExit(
        "Non riesco a scattare.\n"
        "  Installa opencv:  pip install opencv-python\n"
        "  e concedi la Camera al Terminale in\n"
        "  Impostazioni di Sistema > Privacy e sicurezza > Camera"
    )


def zona_busto(rgb: np.ndarray) -> tuple[np.ndarray, str]:
    h, w = rgb.shape[:2]
    try:
        import cv2

        casc = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        facce = casc.detectMultiScale(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY),
                                      1.1, 5, minSize=(60, 60))
        if len(facce):
            fx, fy, fw, fh = max(facce, key=lambda f: f[2] * f[3])
            cx = fx + fw // 2
            x0, x1 = max(0, cx - int(0.9 * fw)), min(w, cx + int(0.9 * fw))
            y0, y1 = min(h - 1, fy + int(1.45 * fh)), min(h, fy + int(3.3 * fh))
            if y1 - y0 > 20 and x1 - x0 > 20:
                return rgb[y0:y1, x0:x1], "volto trovato, guardo il busto sotto"
    except Exception:
        pass
    return (rgb[int(0.58 * h):int(0.95 * h), int(0.28 * w):int(0.72 * w)],
            "volto non trovato, guardo la fascia bassa centrale")


def colore_medio(roi: np.ndarray) -> tuple[int, int, int]:
    px = roi.reshape(-1, 3).astype(np.float32)
    return tuple(int(v) for v in np.median(px, axis=0))


# --------------------------------------------------------------------------- #
# scelta
# --------------------------------------------------------------------------- #

def scegli(maglietta: dict, sfondi: list[dict], mode: str):
    if not sfondi:
        return None, mode, []

    if maglietta["sat"] < S_ACROMATICA:
        # Senza tinta la ruota dei colori non dice niente, ma la LUMINOSITA si:
        # una maglietta nera vuole uno sfondo chiaro e una bianca uno piu scuro,
        # altrimenti il soggetto non stacca. Senza questa regola bianca e nera
        # ricevevano lo stesso sfondo, scelto dall'ordine dei file.
        eff = "neutro"
        cl = []
        for s in sfondi:
            if not s["usabile"]:
                cl.append((s, -1e6, "troppo affollata o senza tinta dominante"))
                continue
            # segnato, non assoluto: il verso e l'informazione utile
            d = s["lum"] - maglietta["lum"]
            cl.append((s, 10.0 * abs(d) - CROMA_PENALITA * max(
                0.0, s.get("croma", 0.0) - maglietta.get("croma", 0.0)
                - CROMA_TOLLERANZA) / 10.0,
                f"senza tinta: sfondo {'piu chiaro' if d > 0 else 'piu scuro'} "
                f"di {abs(d):.2f}"))
        cl.sort(key=lambda r: -r[1])
        return (cl[0][0] if cl and cl[0][1] > -1e5 else None), eff, cl

    eff = mode if mode != "auto" else ("contrasto" if maglietta["sat"] >= S_ACCESA else "tono")
    target = D_CONTRASTO if eff == "contrasto" else D_TONO

    cl = []
    for s in sfondi:
        if not s["usabile"]:
            cl.append((s, -1e6, "troppo affollata o senza tinta dominante"))
            continue
        if s["neutra"]:
            cl.append((s, -30.0, "neutra, jolly"))
            continue
        d = dist_tinta(maglietta["tinta"], s["tinta"])
        if d < D_MIMETISMO:
            cl.append((s, -1e6, f"scartata: solo {d:.0f}° dalla maglietta, ti mimetizzi"))
            continue
        score = -abs(d - target)
        nota = f"{d:.0f}° dalla maglietta"
        if abs(maglietta["lum"] - s["lum"]) < LUM_DELTA_MIN:
            score -= LUM_PENALITA
            nota += ", luminosita simile"
        eccesso = max(0.0, s.get("croma", 0.0) - maglietta.get("croma", 0.0)
                      - CROMA_TOLLERANZA)
        if eccesso > 0:
            score -= CROMA_PENALITA * eccesso
            nota += f", piu carico della maglietta (+{eccesso:.0f} croma)"
        cl.append((s, score, nota))

    cl.sort(key=lambda r: -r[1])
    return (cl[0][0] if cl and cl[0][1] > -1e5 else None), eff, cl


# --------------------------------------------------------------------------- #
# output visivo
# --------------------------------------------------------------------------- #

def apri(path: Path) -> None:
    try:
        if platform.system() == "Darwin":
            subprocess.run(["open", str(path)], check=False)
        elif platform.system() == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        pass


def preview(scelto: dict, rgb_maglietta, out: Path) -> Path:
    """L'immagine da cercare nella griglia. In trenta miniature senza nome,
    sapere che si chiama 'avocado' non serve: bisogna vederla."""
    bg = Image.open(scelto["path"]).convert("RGB").resize((720, 405), Image.LANCZOS)
    c = Image.new("RGB", (720, 500), (22, 22, 24))
    c.paste(bg, (0, 0))
    d = ImageDraw.Draw(c)
    if rgb_maglietta:
        c.paste(Image.new("RGB", (76, 60), tuple(rgb_maglietta)), (18, 420))
        d.text((18, 484), "maglietta", fill=(130, 130, 135))
    d.text((110, 424), "Cerca QUESTO sfondo in Teams", fill=(245, 245, 245))
    d.text((110, 446), f"tinta {scelto['tinta']:.0f}°   "
                       f"luminosita {scelto['lum']:.2f}", fill=(150, 150, 155))
    d.text((110, 466), Path(scelto["path"]).name, fill=(110, 110, 115))
    out.parent.mkdir(parents=True, exist_ok=True)
    c.save(out)
    return out


def tavola(sfondi: list[dict], out: Path) -> Path:
    """Tavola numerata di tutti gli sfondi in gallery, con le loro misure."""
    cols, cw, ch, pad = 4, 260, 176, 10
    rows = (len(sfondi) + cols - 1) // cols
    c = Image.new("RGB", (cols * (cw + pad) + pad, rows * (ch + pad) + pad), (22, 22, 24))
    d = ImageDraw.Draw(c)
    for i, s in enumerate(sfondi):
        x = pad + (i % cols) * (cw + pad)
        y = pad + (i // cols) * (ch + pad)
        try:
            c.paste(Image.open(s["path"]).convert("RGB").resize((cw, 146), Image.LANCZOS),
                    (x, y))
        except Exception:
            d.rectangle([x, y, x + cw, y + 146], fill=(60, 60, 64))
        tag = "usabile" if s["usabile"] else "affollata"
        d.text((x + 4, y + 150), f"{i + 1:2d}. tinta {s['tinta']:.0f}°  "
                                 f"lum {s['lum']:.2f}  {tag}", fill=(200, 200, 205))
    out.parent.mkdir(parents=True, exist_ok=True)
    c.save(out)
    return out


# --------------------------------------------------------------------------- #
# generazione
# --------------------------------------------------------------------------- #

COMPRESSIONE = 0.40      # quanto stringere lo spread di tinta rimappando
PASSO_RUOTA = 45.0       # spaziatura del set di base sulla ruota dei colori
TOLLERANZA_COPERTURA = 22.0   # sotto questa distanza la tinta e gia coperta


def master_path() -> Path:
    """Il master e configurabile: ognuno parte dalla sua immagine."""
    cfg = carica_config()
    if cfg.get("master"):
        p = Path(cfg["master"]).expanduser()
        if p.is_file():
            return p
    here = Path(__file__).resolve().parent
    if (here / "master.png").is_file():
        return here / "master.png"
    # Il repo non contiene immagini di brand: si parte da un esempio neutro,
    # e il primo passo del setup e indicare la propria con --master.
    return here / "examples" / "master-example.png"


def master_tinta() -> float:
    """Tinta del master, MISURATA e messa in cache.

    Chiederla all'utente era un invito a sbagliare: se dichiari una tinta
    diversa da quella vera, ogni colore generato esce spostato di quella
    differenza, e il risultato sembra un bug della regola di armonia.
    """
    p = master_path()
    st = p.stat()
    key = f"v{MISURA_V}|{p}|{int(st.st_mtime)}|{st.st_size}"
    cfg = carica_config()
    if cfg.get("master_key") == key and "master_tinta" in cfg:
        return float(cfg["master_tinta"])
    t = misura_sfondo(p)["tinta"]
    cfg.update({"master_key": key, "master_tinta": t, "master": str(p)})
    salva_config(cfg)
    return float(t)
LUM_TARGET_DELTA = 0.18  # di quanto allontanare la luminanza da quella della maglietta
LUM_BANDA = (0.34, 0.66) # gli sfondi restano in questa banda: ne slavati ne cupi


def _hsv_to_rgb(hsv: np.ndarray) -> np.ndarray:
    h, s, v = hsv[..., 0] * 6.0, hsv[..., 1], hsv[..., 2]
    i = np.floor(h).astype(int)
    f = h - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    i = i % 6
    out = np.empty_like(hsv)
    for k, (r, g, b) in enumerate([(v, t, p), (q, v, p), (p, v, t),
                                   (p, q, v), (t, p, v), (v, p, q)]):
        m = i == k
        out[m] = np.stack([r, g, b], axis=-1)[m]
    return out


def genera(tinta_target: float, lum_maglietta: float, dest: Path,
           sat_mul: float = 0.55) -> tuple[Path, bool]:
    """Rimappa il master TeamSystem sulla tinta richiesta.

    La luminosita viene spinta finche lo stacco dalla maglietta supera la
    soglia: cosi il requisito e soddisfatto per costruzione, invece di essere
    verificato e poi bocciato come accade scegliendo tra sfondi esistenti.
    """
    mp = master_path()
    if not mp.is_file():
        raise SystemExit(f"immagine di base non trovata: {mp}\n"
                         "Indicane una con: teams-tone --master FOTO.png")

    src = Image.open(mp).convert("RGB").resize((1920, 1080), Image.LANCZOS)
    a = np.asarray(src).astype(np.float32) / 255.0
    hsv = _hsv(a)
    h0, s0, v0 = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    nh = np.mod(tinta_target / 360.0
                + (h0 - master_tinta() / 360.0) * COMPRESSIONE, 1.0)
    ns = np.clip(s0 * sat_mul, 0, 1)

    # Punto a una LUMINANZA bersaglio, non a una V: Rec.709 pesa il verde 0.71,
    # quindi la stessa V resa su una tinta giallo-verde da un lime acido e su un
    # blu un blu notte. Normalizzando sulla luminanza il risultato e coerente a
    # qualunque tinta, e lo stacco dalla maglietta e garantito.
    scuro = lum_maglietta > 0.5
    target = lum_maglietta + (-LUM_TARGET_DELTA if scuro else LUM_TARGET_DELTA)
    target = float(np.clip(target, LUM_BANDA[0], LUM_BANDA[1]))

    def rendi(gamma: float, arr_v: np.ndarray, arr_h: np.ndarray,
              arr_s: np.ndarray) -> np.ndarray:
        nv = np.clip(np.power(arr_v, gamma), 0, 1)
        return np.clip(_hsv_to_rgb(np.stack([arr_h, arr_s, nv], axis=-1)), 0, 1)

    # bisezione del gamma su una copia ridotta: la luminanza decresce in modo
    # monotono al crescere del gamma, quindi bastano poche iterazioni
    sh, ss, sv = (x[::6, ::6] for x in (nh, ns, v0))
    lo, hi = 0.35, 4.0
    for _ in range(14):
        mid = (lo + hi) / 2.0
        lum = float(np.median(rendi(mid, sv, sh, ss) @ REC709))
        if lum > target:
            lo = mid
        else:
            hi = mid
    gamma = (lo + hi) / 2.0

    rgb = rendi(gamma, v0, nh, ns)
    out_img = (rgb * 255).round().astype(np.uint8)
    lum_finale = float(np.median(rgb[270:918, 384:1536] @ REC709))

    tmp = Path(tempfile.mkdtemp()) / "gen.png"
    Image.fromarray(out_img).save(tmp)

    # nome deterministico su bucket di 5°: rilanciare con la stessa maglietta
    # riusa lo stesso file invece di riempire la gallery
    bucket = int(round(tinta_target / 5.0)) * 5 % 360
    uid = uuid.uuid5(NS, f"teams-tone/gen/{bucket}/{'d' if scuro else 'l'}")
    ext = ".png"
    main = dest / f"{uid}{ext}"
    gia = main.is_file()
    im = Image.open(tmp).convert("RGB")
    im.save(main)
    im.resize(THUMB, Image.LANCZOS).save(dest / f"{uid}_thumb{ext}")
    return main, gia


def aggiungi(img: Path, dest: Path) -> tuple[Path, bool]:
    """Aggiunge un'immagine alla gallery, senza duplicare cio che c'e gia."""
    img = img.expanduser().resolve()
    if not img.is_file():
        raise SystemExit(f"immagine non trovata: {img}")
    digest = sha(img)
    for f in dest.iterdir():
        if (f.suffix.lower() in IMG_EXT and not f.stem.endswith("_thumb")
                and sha(f) == digest):
            return f, True
    uid = uuid.uuid5(NS, f"teams-tone/{digest[:16]}")
    ext = img.suffix.lower() if img.suffix.lower() in IMG_EXT else ".png"
    main = dest / f"{uid}{ext}"
    im = Image.open(img).convert("RGB")
    im.save(main)
    im.resize(THUMB, Image.LANCZOS).save(dest / f"{uid}_thumb{ext}")
    return main, False



# --------------------------------------------------------------------------- #
# set di base e pagina di riferimento
# --------------------------------------------------------------------------- #

# Colori di maglietta piu diffusi: tinta, intensita, luminosita indicative.
# Non sono misure di un campione reale, sono i valori tipici di quei capi sotto
# luce d'ufficio: servono a costruire la tabella di lookup, non a fingere dati.
MAGLIETTE_COMUNI = [
    ("bianca",        0, 0.05, 0.85), ("grigia",      0, 0.04, 0.45),
    ("nera",          0, 0.05, 0.10), ("beige",      35, 0.20, 0.70),
    ("salmone",       8, 0.50, 0.52), ("rossa",     355, 0.70, 0.30),
    ("bordeaux",    350, 0.55, 0.18), ("rosa",      340, 0.35, 0.65),
    ("arancio",      28, 0.70, 0.50), ("gialla",     50, 0.65, 0.75),
    ("verde oliva",  80, 0.40, 0.40), ("verde",     130, 0.50, 0.35),
    ("teal",        180, 0.45, 0.40), ("azzurra",   205, 0.45, 0.55),
    ("blu navy",    220, 0.55, 0.16), ("viola",     280, 0.40, 0.30),
]


def init_set(dest: Path, passo: float = PASSO_RUOTA) -> list[Path]:
    """Genera il set di base, ma SOLO le tinte che non sono gia coperte.

    Generare un set completo a ogni installazione raddoppierebbe una gallery
    che e gia una griglia di miniature senza etichette: il problema non e avere
    pochi sfondi, e trovarli. Quindi copro i buchi sulla ruota dei colori e
    lascio stare il resto.
    """
    esistenti = [s for s in leggi_gallery(dest, verbose=False)
                 if s["usabile"] and not s["neutra"]]
    hue_esistenti = [s["tinta"] for s in esistenti]
    base = master_tinta()
    bersagli = [(base + k * passo) % 360.0 for k in range(int(round(360.0 / passo)))]

    print(f"\n  immagine di base: tinta {base:.0f}°")
    if hue_esistenti:
        print("  tinte che hai gia: "
              + ", ".join(f"{h:.0f}°" for h in sorted(hue_esistenti)))

    fatti = []
    for t in bersagli:
        vicino = min((dist_tinta(t, h) for h in hue_esistenti), default=999.0)
        if vicino <= TOLLERANZA_COPERTURA:
            print(f"  {t:5.0f}°  gia coperta (a {vicino:.0f}° di distanza)")
            continue
        # luminanza di riferimento 0.5: il set di base non e legato a una
        # maglietta specifica, la scelta fine la fa la regola al momento dell'uso
        path, riusato = genera(t, 0.5, dest)
        hue_esistenti.append(misura_sfondo(path)["tinta"])
        fatti.append(path)
        print(f"  {t:5.0f}°  {'aggiornata' if riusato else 'generata'}: {path.name}")
    return fatti


def _data_uri(path: Path, w: int = 320) -> str:
    import base64
    import io
    im = Image.open(path).convert("RGB")
    im = im.resize((w, int(w * im.height / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=72)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _croma_maglietta(tinta: float, sat: float, lum: float) -> float:
    """Croma C* del colore rappresentativo della maglietta, misurata come per
    gli sfondi: le due grandezze del confronto devono venire dalla stessa
    funzione, o la penalita di croma confronta unita diverse."""
    v = float(np.clip(lum + 0.25 * sat, 0.05, 1.0))
    rgb = _hsv_to_rgb(np.array([[[tinta / 360.0, sat, v]]], dtype=np.float32))
    return float(_croma_lab((rgb[0] * 255).astype(np.uint8))[0])


def _hex(tinta: float, sat: float, lum: float) -> str:
    v = float(np.clip(lum + 0.25 * sat, 0.05, 1.0))
    rgb = _hsv_to_rgb(np.array([[[tinta / 360.0, sat, v]]], dtype=np.float32))[0, 0]
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in rgb)


def pagina(dest: Path, out: Path) -> Path:
    """Pagina di riferimento: maglietta -> sfondo, con le miniature vere.

    Le immagini sono incorporate come data URI: la pagina resta un singolo file
    che funziona offline e si puo mandare a un collega senza portarsi dietro
    una cartella di allegati.
    """
    sfondi = leggi_gallery(dest, verbose=False)
    righe = []
    for nome, t, sa, lu in MAGLIETTE_COMUNI:
        mag = {"tinta": float(t), "sat": sa, "lum": lu,
               "croma": _croma_maglietta(t, sa, lu)}
        intestazione = f'<th><i style="background:{_hex(t, sa, lu)}"></i>{nome}</th>'

        # Una maglietta senza tinta non ha una "distanza sulla ruota dei colori":
        # stampare quel numero sarebbe un dato inventato. Le due colonne
        # collassano in una, e il criterio dichiarato e quello vero.
        if sa < S_ACROMATICA:
            sc, _, _ = scegli(mag, sfondi, "tono")
            if sc is None:
                righe.append(f'<tr>{intestazione}'
                             '<td class="vuoto" colspan="2">nessuno adatto</td></tr>')
            else:
                d = sc["lum"] - lu
                righe.append(
                    f'<tr>{intestazione}<td colspan="2" class="unica">'
                    f'<img src="{_data_uri(Path(sc["path"]))}" alt="">'
                    f'<span>senza tinta: conta lo stacco di luminosita '
                    f'({d:+.2f}), non la ruota dei colori</span></td></tr>')
            continue

        celle = []
        for modo in ("tono", "contrasto"):
            sc, _, _ = scegli(mag, sfondi, modo)
            if sc is None:
                celle.append('<td class="vuoto">nessuno adatto</td>')
            else:
                d = dist_tinta(mag["tinta"], sc["tinta"])
                celle.append(
                    f'<td><img src="{_data_uri(Path(sc["path"]))}" alt="">'
                    f'<span>{sc["tinta"]:.0f}° &middot; {d:.0f}° di distanza</span></td>')
        righe.append(f'<tr>{intestazione}' + "".join(celle) + "</tr>")

    html = f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sfondi Teams &mdash; quale con quale maglietta</title>
<style>
 :root {{ color-scheme: light dark; --bg:#fbfaf8; --fg:#1b1b1d; --mut:#6b6b70;
          --line:#e4e2dd; --card:#fff; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#16161a; --fg:#ececf0;
          --mut:#9a9aa2; --line:#2c2c33; --card:#1e1e24; }} }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; padding:32px 16px 64px; background:var(--bg); color:var(--fg);
        font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }}
 main {{ max-width:900px; margin:0 auto; }}
 h1 {{ font-size:1.5rem; margin:0 0 6px; letter-spacing:-.01em; }}
 p.sub {{ color:var(--mut); margin:0 0 28px; max-width:60ch; }}
 table {{ width:100%; border-collapse:collapse; background:var(--card);
          border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
 thead th {{ text-align:left; font-size:.75rem; text-transform:uppercase;
             letter-spacing:.06em; color:var(--mut); font-weight:600;
             padding:14px 16px; border-bottom:1px solid var(--line); }}
 tbody th {{ text-align:left; font-weight:600; padding:12px 16px; width:170px;
             border-bottom:1px solid var(--line); vertical-align:middle; }}
 tbody th i {{ display:inline-block; width:16px; height:16px; border-radius:50%;
               margin-right:9px; vertical-align:-3px;
               box-shadow:inset 0 0 0 1px rgba(0,0,0,.14); }}
 td {{ padding:10px 16px; border-bottom:1px solid var(--line); vertical-align:middle; }}
 td img {{ display:block; width:100%; max-width:200px; border-radius:6px; }}
 td span {{ display:block; margin-top:5px; font-size:.75rem; color:var(--mut);
            font-variant-numeric:tabular-nums; }}
 td.vuoto {{ color:var(--mut); font-size:.85rem; }}
 td.unica img {{ max-width:200px; }}
 tbody tr:last-child th, tbody tr:last-child td {{ border-bottom:0; }}
 footer {{ margin-top:24px; color:var(--mut); font-size:.8rem; max-width:64ch; }}
 code {{ font-size:.85em; background:var(--line); padding:1px 5px; border-radius:4px; }}
</style></head><body><main>
<h1>Quale sfondo con quale maglietta</h1>
<p class="sub">Generata dai {len(sfondi)} sfondi presenti nella tua gallery Teams.
<strong>Armonia morbida</strong> tiene lo sfondo a circa {D_TONO:.0f}° dalla maglietta
sulla ruota dei colori; <strong>contrasto</strong> va sul colore opposto, a
{D_CONTRASTO:.0f}°. Sotto {D_MIMETISMO:.0f}° lo sfondo viene scartato: ti mimetizzi.</p>
<table>
<thead><tr><th>Maglietta</th><th>Armonia morbida</th><th>Contrasto</th></tr></thead>
<tbody>
{chr(10).join(righe)}
</tbody></table>
<footer>I valori delle magliette sono tipici di quei capi sotto luce d'ufficio,
non misure di un campione reale: servono a costruire la tabella. Per la maglietta
che hai addosso adesso, misurata davvero, lancia <code>teams-tone</code>.</footer>
</main></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ti dice quale dei tuoi sfondi Teams sta bene con la maglietta")
    ap.add_argument("--mode", choices=["auto", "tono", "contrasto"], default="auto")
    ap.add_argument("--image", help="usa una foto invece della webcam")
    ap.add_argument("--teams-dir", help="cartella sfondi Teams (override)")
    ap.add_argument("--sheet", action="store_true",
                    help="tavola numerata di tutti i tuoi sfondi")
    ap.add_argument("--aggiungi", metavar="FILE",
                    help="aggiungi un'immagine alla gallery Teams")
    ap.add_argument("--init", action="store_true",
                    help="genera il set di base, solo le tinte che non hai")
    ap.add_argument("--pagina", action="store_true",
                    help="pagina HTML: quale sfondo con quale maglietta")
    ap.add_argument("--master", metavar="FOTO",
                    help="imposta l'immagine di base da cui generare")
    ap.add_argument("--genera", action="store_true",
                    help="genera uno sfondo su misura anche se uno dei tuoi va bene")
    ap.add_argument("--top", type=int, default=5, help="quante alternative mostrare")
    ap.add_argument("--no-open", action="store_true", help="non aprire il preview")
    args = ap.parse_args()

    if args.master:
        mp = Path(args.master).expanduser().resolve()
        if not mp.is_file():
            raise SystemExit(f"immagine non trovata: {mp}")
        cfg = carica_config()
        cfg.pop("master_key", None)
        cfg["master"] = str(mp)
        salva_config(cfg)
        print(f"\n  immagine di base: {mp}")
        print(f"  tinta misurata: {master_tinta():.0f}°\n")
        return

    dest = cartella_teams(args.teams_dir)

    if args.init:
        fatti = init_set(dest)
        out = pagina(dest, Path.home() / ".cache/teams-tone/sfondi.html")
        print(f"\n  {len(fatti)} sfondi generati. Pagina: {out}")
        print("  Riavvia Teams per vedere i nuovi sfondi.\n")
        if not args.no_open:
            apri(out)
        return

    if args.pagina:
        out = pagina(dest, Path.home() / ".cache/teams-tone/sfondi.html")
        print(f"\n  pagina: {out}\n")
        if not args.no_open:
            apri(out)
        return

    if args.aggiungi:
        path, gia = aggiungi(Path(args.aggiungi), dest)
        print(f"\n  {'era gia in gallery' if gia else 'aggiunto'}: {path.name}")
        print("  Riavvia Teams se non lo vedi.\n")
        return

    sfondi = leggi_gallery(dest)
    if not sfondi and args.sheet:
        raise SystemExit(f"\nNessuno sfondo personalizzato in {dest}\n")
    if not sfondi:
        print("\n  Nessuno sfondo personalizzato in gallery: ne generero uno.")

    if args.sheet:
        out = tavola(sfondi, Path.home() / ".cache/teams-tone/tavola.png")
        print(f"\n  {len(sfondi)} sfondi. Tavola: {out}\n")
        if not args.no_open:
            apri(out)
        return

    frame = (np.asarray(Image.open(args.image).convert("RGB"))
             if args.image else scatta())
    roi, come = zona_busto(frame)
    mag = misura(roi)
    rgb_mag = colore_medio(roi)

    print(f"\n  {come}")
    print(f"  maglietta: tinta {mag['tinta']:.0f}°  "
          f"intensita {mag['sat']:.2f}  luminosita {mag['lum']:.2f}")

    scelto, eff, cl = scegli(mag, sfondi, args.mode)
    print(f"  cerco: {'colore opposto' if eff == 'contrasto' else 'armonia morbida' if eff == 'tono' else eff}\n")

    for s, score, nota in cl[:args.top]:
        mark = "->" if scelto is not None and s is scelto else "  "
        print(f"  {mark} {Path(s['path']).name[:12]:12s} tinta {s['tinta']:6.1f}°  {nota}")

    generato = False
    if scelto is None or args.genera:
        if scelto is None:
            print("\n  Nessuno dei tuoi sfondi regge questa maglietta: ne genero uno.")
        else:
            print("\n  Genero uno sfondo su misura (--genera).")
        delta = D_CONTRASTO if eff == "contrasto" else D_TONO
        tinta_target = (mag["tinta"] + delta) % 360.0
        path, riusato = genera(tinta_target, mag["lum"], dest)
        m = misura_sfondo(path)
        scelto = {"path": str(path), "nome": path.stem[:8], **m}
        generato = True
        print(f"  tinta {tinta_target:.0f}° dal master TeamSystem"
              f"{' (riuso quello di prima)' if riusato else ''}")
        print(f"  {'aggiornato' if riusato else 'aggiunto alla gallery'}: {path.name}")

    out = preview(scelto, rgb_mag, Path.home() / ".cache/teams-tone/scelto.png")
    print(f"\n  Preview: {out}")
    if generato:
        print("  Riavvia Teams per vederlo, poi: Effects and avatars > Sfondi.\n")
    else:
        print("  In Teams: Effects and avatars > Sfondi, e cerca questa immagine.\n")
    if not args.no_open:
        apri(out)


if __name__ == "__main__":
    main()
