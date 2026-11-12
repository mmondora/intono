#!/usr/bin/env python3
"""
intono - genera lo sfondo Teams in armonia con la maglietta che hai addosso.

Uno scatto dalla webcam, legge il colore della maglietta, rimappa la tua
immagine di base sulla tinta giusta e mette lo sfondo in gallery. Il nome del
file e deterministico per fascia di tinta: la stessa maglietta riusa lo stesso
sfondo invece di accumularne.

    intono                    genera lo sfondo per questa maglietta
    intono --mode tono        armonia morbida (salmone -> verde oliva)
    intono --mode contrasto   colore opposto (salmone -> teal)
    intono --dai-miei         scegli tra gli sfondi che hai gia, non generare
    intono --master FOTO      imposta l'immagine di base
    intono --init             completa il set di base sulla ruota dei colori
    intono --pagina           pagina HTML: quale sfondo con quale maglietta
    intono --image FOTO       usa una foto invece della webcam (per provare)

Dipendenze: numpy, pillow, opencv-python. Tutto in locale, niente rete.
"""

from __future__ import annotations

VERSIONE = "1.0.3"   # unica fonte: install.sh la legge da qui
NOME = "intono"      # usato nei nomi dei file generati

import argparse
import hashlib
import re
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
CONFUSIONE_MAX = 0.020   # sopra: immagine troppo affollata, distrae in call
# Calibrata su immagini reali, non su casi sintetici estremi: i gradienti lisci
# stanno a 0.001-0.010, una foto di una stanza dettagliata a 0.03. Il valore
# precedente (0.040) veniva da rumore RGB e righe a contrasto pieno, che sono
# molto piu "energici" di una foto vera e lasciavano passare tutto il resto.

REC709 = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
FINESTRA_TINTA = 25.0
THUMB = (280, 158)
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp")
NS = uuid.UUID("6f2d1b8e-4c3a-5f77-9b21-0ad3f5c81e42")
# I semi uuid5 restano "teams-tone/...": cambiarli cambierebbe i nomi dei file
# installati in Teams, e la pulizia cerca gli uuid correnti — quelli vecchi
# resterebbero orfani e invisibili nella gallery di chi aggiorna. E uno
# identificatore interno, non un nome che qualcuno legge.

CARTELLE_TEAMS = [
    Path.home() / "Library/Containers/com.microsoft.teams2/Data/Library"
                  "/Application Support/Microsoft/MSTeams/Backgrounds/Uploads",
    Path.home() / "Library/Application Support/Microsoft/Teams/Backgrounds/Uploads",
]
CACHE = Path.home() / ".cache/intono/misure.json"
# Versione dello schema di misura: entra nella chiave di cache, cosi cambiare
# le metriche invalida le voci vecchie invece di leggerne i campi mancanti
# come zero, che disattiverebbe una penalita senza dirlo.
MISURA_V = 3
CONFIG = Path.home() / ".config/intono/config.json"


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
    # La confusione vale SEMPRE. Prima era "neutra or (...)": un'immagine quasi
    # senza colore passava qualunque fosse il suo livello di dettaglio, quindi
    # una foto piena di oggetti in bianco e grigio risultava usabile. La deroga
    # per le immagini neutre riguarda solo la coerenza di tinta, che su una cosa
    # grigia non e misurabile ne significativa.
    usabile = confusione <= CONFUSIONE_MAX and (neutra or coerenza >= COERENZA_MIN)
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


def _misura_cached(f: Path, cache: dict) -> tuple[dict, bool]:
    """Misura con cache su (versione, percorso, mtime, dimensione)."""
    st = f.stat()
    key = f"v{MISURA_V}|{f}|{int(st.st_mtime)}|{st.st_size}"
    m = cache.get(key)
    if m is not None:
        return m, False
    m = misura_sfondo(f)
    cache[key] = m
    return m, True


def misura_set(g: list[dict]) -> list[dict]:
    """Arricchisce le voci della griglia con le misure di colore."""
    cache = _cache_load()
    out, nuovi = [], 0
    for i, e in enumerate(g, 1):
        m, fresco = _misura_cached(Path(e["path"]), cache)
        nuovi += fresco
        out.append({**e, **m, "pos": i})
    if nuovi:
        _cache_save(cache)
    return out


def leggi_gallery(dest: Path, verbose: bool = True) -> list[dict]:
    """Misura gli sfondi presenti, con cache su (percorso, mtime, dimensione)."""
    files = sorted(f for f in dest.iterdir()
                   if f.suffix.lower() in IMG_EXT and not f.stem.endswith("_thumb"))
    cache = _cache_load()
    out, nuovi = [], 0
    for f in files:
        m, fresco = _misura_cached(f, cache)
        nuovi += fresco
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
                 "-framerate", "30", "-pixel_format", "nv12", "-i", "0", "-frames:v", "1", "-y", str(tmp)]):
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


def _rilevatore_volti():
    """Classificatore Haar dei volti, oppure (None, motivo).

    OpenCV 5 ha tolto CascadeClassifier dal pacchetto opencv-python. Prima
    l'errore finiva in un except muto e il tool diceva "volto non trovato" a
    ogni scatto, misurando una fascia fissa dell'inquadratura: tavolo, pelle,
    sfondo. Il colore della maglietta cambiava a ogni lancio.
    """
    try:
        import cv2
    except ImportError:
        return None, "opencv non installato"
    if not hasattr(cv2, "CascadeClassifier"):
        return None, (f"opencv {cv2.__version__} non ha il rilevatore di volti: "
                      "reinstalla con  bash install.sh  (porta opencv < 5)")
    casc = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if casc.empty():
        return None, "modello dei volti di opencv non caricabile"
    return casc, ""


def zona_busto(rgb: np.ndarray) -> tuple[np.ndarray, str]:
    h, w = rgb.shape[:2]
    casc, motivo = _rilevatore_volti()
    if casc is None:
        print(f"  ATTENZIONE: {motivo}", file=sys.stderr)
    try:
        import cv2

        facce = () if casc is None else casc.detectMultiScale(
            cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), 1.1, 5, minSize=(60, 60))
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


def griglia(pieno: bool = False) -> list[dict]:
    """Il set di base cosi come sta nella griglia di macOS.

    macOS si COPIA l'immagine quando la selezioni: non rilegge il file, ne a
    runtime ne al riavvio dell'app (verificato). Quindi rigenerare non cambia
    niente e l'unico modo e importare il set una volta sola e poi cliccare.
    L'ordine della griglia e l'ordine di importazione: importando in ordine di
    nome, e ordinato per tinta, quindi la posizione e calcolabile.
    """
    suffisso = "pieno" if pieno else "pastello"
    # Regex e non split posizionale: leggere la tinta per indice dipende da
    # quanti trattini ha il nome del programma, e rinominando il tool da
    # teams-tone a intono i pezzi sono passati da cinque a quattro — il parser
    # leggeva il campo sbagliato e il set risultava sempre vuoto.
    rx = re.compile(rf"^{re.escape(NOME)}-set-(\d+)-{suffisso}$")
    out = []
    for f in sorted(cartella_uscita().glob(f"{NOME}-set-*-{suffisso}.png")):
        m = rx.match(f.stem)
        if not m:
            continue
        out.append({"path": str(f), "tinta": float(m.group(1)), "file": f.name})
    return out


def posizione(tinta_target: float, g: list[dict]) -> tuple[int, dict, float]:
    """Indice 1-based nella griglia della tinta piu vicina, piu lo scarto."""
    dist = [dist_tinta(tinta_target, e["tinta"]) for e in g]
    i = int(np.argmin(dist))
    return i + 1, g[i], dist[i]


def bersaglio(maglietta: dict, mode: str) -> tuple[float, str]:
    """Tinta da generare e modalita effettiva, senza guardare la gallery.

    Maglietta senza tinta: la ruota dei colori non dice niente, quindi resto
    sulla tinta del master (il brand) e lascio che sia la luminanza a creare lo
    stacco, cosa che genera() garantisce per costruzione.
    """
    if maglietta["sat"] < S_ACROMATICA:
        return master_tinta(), "neutro"
    eff = mode if mode != "auto" else (
        "contrasto" if maglietta["sat"] >= S_ACCESA else "tono")
    delta = D_CONTRASTO if eff == "contrasto" else D_TONO
    return (maglietta["tinta"] + delta) % 360.0, eff


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
CROMA_TARGET = 16.0      # croma C* CIELab dello sfondo generato (pastello)
AMPIEZZA = 0.42          # ampiezza della banda di luminosita: contrasto basso
CROMA_TARGET_PIENO = 30.0   # con --pieno: piu carico e piu contrastato
AMPIEZZA_PIENO = 0.70
PASSO_RUOTA = 45.0       # spaziatura del set di base sulla ruota dei colori
TOLLERANZA_COPERTURA = 22.0   # sotto questa distanza la tinta e gia coperta


def cartella_uscita() -> Path:
    """Dove depositare una copia riusabile fuori da Teams.

    Dentro la cartella di Teams il file ha un nome UUID e sta in un container
    nascosto: inutilizzabile da qualunque altro strumento. La copia va in un
    posto che il selettore file di qualsiasi app raggiunge, con un nome che dice
    cosa contiene.
    """
    cfg = carica_config()
    if cfg.get("uscita"):
        return Path(cfg["uscita"]).expanduser()
    return Path.home() / "Pictures" / "intono"


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


def genera(tinta_target: float, lum_maglietta: float, dest: Path | None = None,
           pieno: bool = False, del_set: bool = False,
           in_teams: bool = False) -> tuple[Path, bool, Path | None]:
    """Rimappa il master TeamSystem sulla tinta richiesta.

    La luminosita viene spinta finche lo stacco dalla maglietta supera la
    soglia: cosi il requisito e soddisfatto per costruzione, invece di essere
    verificato e poi bocciato come accade scegliendo tra sfondi esistenti.
    """
    croma_target = CROMA_TARGET_PIENO if pieno else CROMA_TARGET
    ampiezza = AMPIEZZA_PIENO if pieno else AMPIEZZA

    mp = master_path()
    if not mp.is_file():
        raise SystemExit(f"immagine di base non trovata: {mp}\n"
                         "Indicane una con: intono --master FOTO.png")

    src = Image.open(mp).convert("RGB").resize((1920, 1080), Image.LANCZOS)
    a = np.asarray(src).astype(np.float32) / 255.0
    hsv = _hsv(a)
    h0, s0, v0 = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    nh = np.mod(tinta_target / 360.0
                + (h0 - master_tinta() / 360.0) * COMPRESSIONE, 1.0)
    # Comprimo il RANGE di luminosita in una banda stretta, invece di limitarmi
    # a un gamma. Il gamma sposta i mezzitoni ma lascia dov'e la macchia di luce
    # del master, che resta quasi bianca: e da li che viene la sensazione di
    # immagine "sparata". Normalizzando e rimappando in una banda si tolgono sia
    # il bianco bruciato sia il nero chiuso, che con poca croma e quello che
    # rende un colore pastello.
    vmin, vmax = float(v0.min()), float(v0.max())
    v_norm = (v0 - vmin) / max(vmax - vmin, 1e-6)

    scuro = lum_maglietta > 0.5
    target = lum_maglietta + (-LUM_TARGET_DELTA if scuro else LUM_TARGET_DELTA)
    target = float(np.clip(target, LUM_BANDA[0], LUM_BANDA[1]))

    def rendi(centro: float, sat_mul: float, arr_v: np.ndarray,
              arr_h: np.ndarray, arr_s: np.ndarray) -> np.ndarray:
        nv = np.clip(centro - ampiezza / 2.0 + arr_v * ampiezza, 0.04, 0.96)
        ns = np.clip(arr_s * sat_mul, 0, 1)
        return np.clip(_hsv_to_rgb(np.stack([arr_h, ns, nv], axis=-1)), 0, 1)

    # Due bisezioni alternate su una copia ridotta. Sulla CROMA, non sulla
    # saturazione HSV: a pari saturazione un magenta ha croma percepita molto
    # piu alta di un oliva, quindi un moltiplicatore fisso rende "pastello" solo
    # alcune tinte e sgargianti le altre. Sulla LUMINANZA per lo stacco.
    sh, ss, sv = (x[::6, ::6] for x in (nh, s0, v_norm))
    sat_mul, centro = 0.5, 0.5
    for _ in range(3):
        lo, hi = 0.02, 1.0
        for _ in range(12):
            mid = (lo + hi) / 2.0
            c = float(np.median(_croma_lab(
                (rendi(centro, mid, sv, sh, ss) * 255).astype(np.uint8))))
            if c < croma_target:
                lo = mid
            else:
                hi = mid
        sat_mul = (lo + hi) / 2.0

        lo, hi = 0.10, 0.95
        for _ in range(12):
            mid = (lo + hi) / 2.0
            if float(np.median(rendi(mid, sat_mul, sv, sh, ss) @ REC709)) < target:
                lo = mid
            else:
                hi = mid
        centro = (lo + hi) / 2.0

    rgb = rendi(centro, sat_mul, v_norm, nh, s0)
    out_img = (rgb * 255).round().astype(np.uint8)
    lum_finale = float(np.median(rgb[270:918, 384:1536] @ REC709))

    tmp = Path(tempfile.mkdtemp()) / "gen.png"
    Image.fromarray(out_img).save(tmp)

    # nome deterministico su bucket di 5°: rilanciare con la stessa maglietta
    # riusa lo stesso file invece di riempire la gallery
    bucket = int(round(tinta_target / 5.0)) * 5 % 360
    im = Image.open(tmp).convert("RGB")
    main, gia = tmp, False
    if in_teams and dest is not None:
        # Teams pretende <uuid>.png piu <uuid>_thumb.png. Serve solo a chi usa
        # la gallery di Teams: con lo sfondo di sistema di macOS quella copia e
        # solo una miniatura in piu in una griglia gia illeggibile.
        uid = uuid.uuid5(NS, f"teams-tone/gen/{bucket}/{'d' if scuro else 'l'}"
                             f"/{'pieno' if pieno else 'pastello'}")
        main = dest / f"{uid}.png"
        gia = main.is_file()
        im.save(main)
        im.resize(THUMB, Image.LANCZOS).save(dest / f"{uid}_thumb.png")

    # Due copie fuori da Teams. Una con nome parlante, da archivio. L'altra
    # sempre allo STESSO percorso: serve per lo sfondo di sistema di macOS
    # (Centro di Controllo > effetti video > Sfondo), che si imposta scegliendo
    # un file. Se macOS tiene il riferimento al percorso invece di copiarsi
    # l'immagine, sovrascrivere questo file cambia lo sfondo di tutte le app
    # senza toccare niente: e l'unica strada verso l'automatismo che cercavi.
    copia = None
    try:
        out_dir = cartella_uscita()
        out_dir.mkdir(parents=True, exist_ok=True)
        nome = f"{NOME}-set-" if del_set else f"{NOME}-"
        copia = out_dir / f"{nome}{bucket:03d}-{'pieno' if pieno else 'pastello'}.png"
        gia = gia or copia.is_file()
        im.save(copia)
        im.save(out_dir / "sfondo-attuale.png")
    except OSError as exc:
        print(f"  (copia in {cartella_uscita()} non riuscita: {exc})", file=sys.stderr)
        copia = None
    # senza installazione in Teams il file "principale" e la copia riusabile
    if main is tmp and copia is not None:
        main = copia
    return main, gia, copia


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


def init_set(dest: Path | None = None, passo: float = PASSO_RUOTA,
             pieno: bool = False,
             in_teams: bool = False) -> list[Path]:
    """Genera il set di base, ma SOLO le tinte che non sono gia coperte.

    Generare un set completo a ogni installazione raddoppierebbe una gallery
    che e gia una griglia di miniature senza etichette: il problema non e avere
    pochi sfondi, e trovarli. Quindi copro i buchi sulla ruota dei colori e
    lascio stare il resto.
    """
    # La copertura si misura sul set in cartella_uscita(), non sulla gallery di
    # Teams: sono due collezioni diverse, e quella che va importata nella
    # griglia di macOS deve essere completa per conto suo. Guardare la gallery
    # di Teams faceva saltare i settori "gia coperti" da immagini che nella
    # griglia non ci sono.
    hue_esistenti = [e["tinta"] for e in griglia(pieno)]
    base = master_tinta()
    bersagli = [(base + k * passo) % 360.0 for k in range(int(round(360.0 / passo)))]

    print(f"\n  immagine di base: tinta {base:.0f}°")
    print(f"  set in {cartella_uscita()}")
    if hue_esistenti:
        print("  tinte che il set ha gia: "
              + ", ".join(f"{h:.0f}°" for h in sorted(hue_esistenti)))

    fatti = []
    for t in bersagli:
        vicino = min((dist_tinta(t, h) for h in hue_esistenti), default=999.0)
        if vicino <= TOLLERANZA_COPERTURA:
            print(f"  {t:5.0f}°  gia coperta (a {vicino:.0f}° di distanza)")
            continue
        # luminanza di riferimento 0.5: il set di base non e legato a una
        # maglietta specifica, la scelta fine la fa la regola al momento dell'uso
        # Per default NON finisce anche nella gallery di Teams: il set serve
        # alla griglia di macOS, e otto miniature in piu la in mezzo sono
        # esattamente l'ingombro che questo tool cerca di evitare.
        path, riusato, _ = genera(t, 0.5, dest, pieno=pieno, del_set=True,
                                  in_teams=in_teams)
        hue_esistenti.append(float(int(round(t / 5.0)) * 5 % 360))
        fatti.append(path)
        etichetta = "aggiornata" if riusato else "generata"
        print(f"  {t:5.0f}°  {etichetta}")
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


def pagina(dest: Path | None, out: Path, pieno: bool = False) -> Path:
    """Pagina di riferimento: maglietta -> posizione nella griglia di macOS.

    Le immagini sono incorporate come data URI: resta un file singolo, funziona
    offline e si manda a un collega senza allegare una cartella.
    """
    g = misura_set(griglia(pieno))
    sorgente = "griglia"
    if not g and dest is not None:
        # senza set, ricado sulla gallery di Teams: meglio una pagina utile a
        # meta che nessuna pagina
        g = leggi_gallery(dest, verbose=False)
        sorgente = "teams"
    if not g:
        raise SystemExit("\nNessun set e nessuna gallery da cui costruire la "
                         "pagina.\nGeneralo con: intono --init\n")

    def cella(mag: dict, modo: str) -> str:
        sc, _, _ = scegli(mag, g, modo)
        if sc is None:
            return '<td class="vuoto">nessuno adatto</td>'
        img = f'<img src="{_data_uri(Path(sc["path"]))}" alt="">'
        if sorgente == "griglia":
            d = dist_tinta(mag["tinta"], sc["tinta"])
            return (f'<td><div class="slot"><b>{sc["pos"]}</b>{img}</div>'
                    f'<span>tinta {sc["tinta"]:.0f}° &middot; {d:.0f}° dalla '
                    f'maglietta</span></td>')
        d = dist_tinta(mag["tinta"], sc["tinta"])
        return (f'<td>{img}<span>tinta {sc["tinta"]:.0f}° &middot; {d:.0f}° '
                f'dalla maglietta</span></td>')

    righe = []
    for nome, t, sa, lu in MAGLIETTE_COMUNI:
        mag = {"tinta": float(t), "sat": sa, "lum": lu,
               "croma": _croma_maglietta(t, sa, lu)}
        intestazione = f'<th><i style="background:{_hex(t, sa, lu)}"></i>{nome}</th>'

        # Una maglietta senza tinta non ha una "distanza sulla ruota dei
        # colori": stampare quel numero sarebbe un dato inventato.
        if sa < S_ACROMATICA:
            sc, _, _ = scegli(mag, g, "tono")
            if sc is None:
                righe.append(f'<tr>{intestazione}'
                             '<td class="vuoto" colspan="2">nessuno adatto</td></tr>')
            else:
                d = sc["lum"] - lu
                slot = (f'<div class="slot"><b>{sc["pos"]}</b>'
                        if sorgente == "griglia" else '<div class="slot">')
                righe.append(
                    f'<tr>{intestazione}<td colspan="2" class="unica">{slot}'
                    f'<img src="{_data_uri(Path(sc["path"]))}" alt=""></div>'
                    f'<span>senza tinta: conta lo stacco di luminosita '
                    f'({d:+.2f}), non la ruota dei colori</span></td></tr>')
            continue

        righe.append(f'<tr>{intestazione}'
                     + cella(mag, "tono") + cella(mag, "contrasto") + "</tr>")

    if sorgente == "griglia":
        strip = "".join(
            f'<figure><div class="slot"><b>{e["pos"]}</b>'
            f'<img src="{_data_uri(Path(e["path"]), 200)}" alt=""></div>'
            f'<figcaption>{e["tinta"]:.0f}°</figcaption></figure>' for e in g)
        testa = f"""<h1>Quale sfondo con quale maglietta</h1>
<p class="sub">I numeri sono le <strong>posizioni nella griglia</strong> di
Centro di Controllo &rarr; effetti video &rarr; Sfondo. Valgono se hai importato
il set in ordine di nome: controlla qui sotto che l'ordine corrisponda.</p>
<div class="strip">{strip}</div>"""
    else:
        testa = f"""<h1>Quale sfondo con quale maglietta</h1>
<p class="sub">Generata dai {len(g)} sfondi nella tua gallery Teams. Per avere
le posizioni della griglia di macOS: <code>intono --init</code> e poi
<code>intono --pagina</code>.</p>"""

    html = f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sfondi &mdash; quale con quale maglietta</title>
<style>
 :root {{ color-scheme: light dark; --bg:#fbfaf8; --fg:#1b1b1d; --mut:#6b6b70;
          --line:#e4e2dd; --card:#fff; --acc:#2f6f6a; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#16161a; --fg:#ececf0;
          --mut:#9a9aa2; --line:#2c2c33; --card:#1e1e24; --acc:#6fc4bc; }} }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; padding:32px 16px 64px; background:var(--bg); color:var(--fg);
        font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }}
 main {{ max-width:940px; margin:0 auto; }}
 h1 {{ font-size:1.5rem; margin:0 0 6px; letter-spacing:-.01em; }}
 p.sub {{ color:var(--mut); margin:0 0 24px; max-width:66ch; }}
 code {{ font-size:.85em; background:var(--line); padding:1px 5px; border-radius:4px; }}
 .strip {{ display:flex; gap:10px; flex-wrap:wrap; margin:0 0 30px; }}
 .strip figure {{ margin:0; width:120px; }}
 .strip figcaption {{ font-size:.72rem; color:var(--mut); text-align:center;
                      margin-top:4px; font-variant-numeric:tabular-nums; }}
 .slot {{ position:relative; }}
 .slot img {{ display:block; width:100%; border-radius:6px; }}
 .slot b {{ position:absolute; top:5px; left:5px; z-index:1; min-width:22px;
            height:22px; padding:0 5px; border-radius:11px; background:var(--acc);
            color:#fff; font-size:.78rem; font-weight:700; line-height:22px;
            text-align:center; box-shadow:0 1px 3px rgba(0,0,0,.3); }}
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
 td .slot, td img {{ max-width:190px; }}
 td span {{ display:block; margin-top:5px; font-size:.75rem; color:var(--mut);
            font-variant-numeric:tabular-nums; }}
 td.vuoto {{ color:var(--mut); font-size:.85rem; }}
 tbody tr:last-child th, tbody tr:last-child td {{ border-bottom:0; }}
 footer {{ margin-top:24px; color:var(--mut); font-size:.8rem; max-width:66ch; }}
</style></head><body><main>
{testa}
<table>
<thead><tr><th>Maglietta</th><th>Armonia morbida</th><th>Contrasto</th></tr></thead>
<tbody>
{chr(10).join(righe)}
</tbody></table>
<footer>Armonia morbida tiene lo sfondo a circa {D_TONO:.0f}&deg; dalla maglietta
sulla ruota dei colori, contrasto va sul colore opposto a {D_CONTRASTO:.0f}&deg;;
sotto {D_MIMETISMO:.0f}&deg; lo sfondo viene scartato perche ti mimetizzi.
I valori delle magliette sono tipici di quei capi sotto luce d'ufficio, non
misure di un campione reale: servono a costruire la tabella. Per la maglietta che
hai addosso adesso, misurata davvero, lancia <code>intono</code>.</footer>
</main></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def pulisci(si: bool = False) -> int:
    """Cancella dalla cartella di uscita solo cio che ha creato questo tool.

    Il filtro e sui nomi che il tool produce, non su tutta la cartella: in
    Pictures ci sono le foto di qualcuno, e una cancellazione ricorsiva la
    prima volta che si sbaglia un percorso non si annulla.
    """
    d = cartella_uscita()
    if not d.is_dir():
        print(f"\n  {d} non esiste: niente da pulire\n")
        return 0

    files = sorted(set(list(d.glob(f"{NOME}-*.png"))
                       + list(d.glob("sfondo-attuale.png"))))
    if not files:
        print(f"\n  niente da pulire in {d}\n")
        return 0

    tot = sum(f.stat().st_size for f in files)
    print(f"\n  {len(files)} file in {d}  ({tot / 1e6:.1f} MB)")
    for f in files:
        print(f"    {f.name}")

    if not si:
        if not sys.stdin.isatty():
            print("\n  non interattivo: ripeti con --si per confermare\n")
            return 0
        try:
            risposta = input("\n  cancello? [s/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if risposta not in ("s", "si", "sì", "y", "yes"):
            print("  lasciati dove sono\n")
            return 0

    n = 0
    for f in files:
        try:
            f.unlink()
            n += 1
        except OSError as exc:
            print(f"    {f.name}: {exc}", file=sys.stderr)
    print(f"\n  cancellati {n} file")
    print("  Le copie che macOS si e gia importato nella griglia restano:")
    print("  quelle si togliono da Centro di Controllo > effetti video > Sfondo.\n")
    return n


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
    ap.add_argument("--delete", action="store_true",
                    help="cancella gli sfondi che il tool ha creato in Pictures")
    ap.add_argument("--si", action="store_true",
                    help="con --delete, non chiedere conferma")
    ap.add_argument("--anche-teams", action="store_true", dest="anche_teams",
                    help="con --init, installa il set anche nella gallery Teams")
    ap.add_argument("--griglia", action="store_true",
                    help="elenca il set nell'ordine in cui importarlo in macOS")
    ap.add_argument("--genera", action="store_true",
                    help="genera un nuovo sfondo invece di indicare la griglia")
    ap.add_argument("--versione", action="version",
                    version=f"intono {VERSIONE}")
    ap.add_argument("--out", metavar="DIR",
                    help="cartella dove depositare la copia riusabile")
    ap.add_argument("--pieno", action="store_true",
                    help="resa piu carica e contrastata invece che pastello")
    ap.add_argument("--dai-miei", action="store_true", dest="dai_miei",
                    help="scegli tra gli sfondi che hai gia, invece di generarne uno")
    ap.add_argument("--top", type=int, default=5, help="quante alternative mostrare (con --dai-miei)")
    ap.add_argument("--no-open", action="store_true", help="non aprire l'immagine dello sfondo")
    args = ap.parse_args()

    if args.delete:
        pulisci(args.si)
        return

    if args.out:
        d = Path(args.out).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        cfg = carica_config(); cfg["uscita"] = str(d); salva_config(cfg)
        print(f"\n  copie riusabili in: {d}\n")
        return

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

    if args.griglia:
        g = griglia(args.pieno)
        if not g:
            raise SystemExit(
                f"\nNessun set in {cartella_uscita()}\n"
                "Generalo con: intono --init\n")
        print(f"\n  {len(g)} sfondi in {cartella_uscita()}")
        print("  Importali in QUESTO ordine in Centro di Controllo > effetti")
        print("  video > Sfondo > +, cosi la posizione corrisponde alla tinta.\n")
        for i, e in enumerate(g, 1):
            print(f"  {i:2d}.  tinta {e['tinta']:3.0f}°   {e['file']}")
        print()
        return

    # La cartella di Teams non e piu un prerequisito: serve solo ai comandi che
    # la usano davvero. Prima il tool si rifiutava di partire senza Teams
    # installato, anche per generare uno sfondo che in Teams non finisce.
    dest = None

    def teams_dest() -> Path:
        nonlocal dest
        if dest is None:
            dest = cartella_teams(args.teams_dir)
        return dest

    if args.init:
        fatti = init_set(teams_dest() if args.anche_teams else None,
                         pieno=args.pieno, in_teams=args.anche_teams)
        print(f"\n  {len(fatti)} sfondi nel set, in {cartella_uscita()}")
        print("  Ora: intono --griglia   per l'ordine di importazione")
        if args.anche_teams:
            print("  Installati anche in Teams: riavvialo per vederli.")
        print()
        return

    if args.pagina:
        if griglia(args.pieno):
            dest_pag = None
        else:
            try:
                dest_pag = teams_dest()
            except SystemExit:
                dest_pag = None   # ne set ne Teams: lo dira pagina()
        out = pagina(dest_pag, Path.home() / ".cache/intono/sfondi.html",
                     pieno=args.pieno)
        print(f"\n  pagina: {out}\n")
        if not args.no_open:
            apri(out)
        return

    if args.sheet:
        sfondi = leggi_gallery(teams_dest())
        if not sfondi:
            raise SystemExit("\nNessuno sfondo nella gallery di Teams.\n")
        out = tavola(sfondi, Path.home() / ".cache/intono/tavola.png")
        print(f"\n  tavola di {len(sfondi)} sfondi: {out}\n")
        if not args.no_open:
            apri(out)
        return

    if args.dai_miei and not leggi_gallery(teams_dest(), verbose=False):
        print("\n  Nessuno sfondo personalizzato in gallery: ne genero uno.")
        args.dai_miei = False

    if args.aggiungi:
        path, gia = aggiungi(Path(args.aggiungi), teams_dest())
        print(f"\n  {'era gia in gallery' if gia else 'aggiunto'}: {path.name}")
        print("  Riavvia Teams se non lo vedi.\n")
        return

    frame = (np.asarray(Image.open(args.image).convert("RGB"))
             if args.image else scatta())
    roi, come = zona_busto(frame)
    mag = misura(roi)

    print(f"\n  {come}")
    print(f"  maglietta: tinta {mag['tinta']:.0f}°  "
          f"intensita {mag['sat']:.2f}  luminosita {mag['lum']:.2f}")

    scelto, generato, copia = None, False, None

    if args.dai_miei:
        # Scegliere tra gli sfondi gia in gallery e l'eccezione, non la regola:
        # il risultato dipende da cosa ci si e accumulato dentro, che non e
        # prevedibile ne coerente col brand.
        sfondi = leggi_gallery(teams_dest())
        scelto, eff, cl = scegli(mag, sfondi, args.mode)
        print(f"  cerco tra i tuoi: {eff}\n")
        for sf, score, nota in cl[:args.top]:
            mark = "->" if scelto is not None and sf is scelto else "  "
            print(f"  {mark} {Path(sf['path']).name[:12]:12s} "
                  f"tinta {sf['tinta']:6.1f}°  {nota}")
        if scelto is None:
            print("\n  Nessuno dei tuoi regge questa maglietta: ne genero uno.")

    if scelto is None:
        tinta_target, eff = bersaglio(mag, args.mode)
        etichetta = {"contrasto": "colore opposto", "tono": "armonia morbida",
                     "neutro": "maglietta senza tinta, resto sul brand"}[eff]

        g = griglia(args.pieno)
        if g and not args.genera:
            # Il set e gia importato: generare un nono file non serve a niente,
            # perche per usarlo andrebbe importato di nuovo. Dico quale cliccare.
            i, e, scarto = posizione(tinta_target, g)
            print(f"  {etichetta}: tinta ideale {tinta_target:.0f}°\n")
            print(f"  griglia macOS: posizione {i} di {len(g)}"
                  f"   (tinta {e['tinta']:.0f}°, {scarto:.0f}° dall'ideale)")
            print(f"  vale per Teams, Zoom, Meet: e lo sfondo di sistema\n")
            print(f"  {e['path']}")
            if not args.no_open:
                apri(Path(e["path"]))
            return

        print(f"  {etichetta}: genero a {tinta_target:.0f}°")
        path, riusato, copia = genera(
            tinta_target, mag["lum"],
            teams_dest() if args.anche_teams else None,
            pieno=args.pieno, in_teams=args.anche_teams)
        scelto = {"path": str(path), "nome": path.stem[:8], **misura_sfondo(path)}
        generato = True
        if riusato:
            print("  (stesso sfondo dell'ultima volta con questa maglietta)")

    out = Path(scelto["path"])
    print(f"\n  sfondo: {out.name}")
    print(f"  tinta {scelto['tinta']:.0f}°   luminosita {scelto['lum']:.2f}")
    print(f"  {out}")
    if copia is not None:
        print(f"\n  copia riusabile (Zoom, Meet, Slides, qualunque cosa):")
        print(f"  {copia}")
        print(f"  {copia.parent / 'sfondo-attuale.png'}   <- sempre questo percorso")
    if generato and args.anche_teams:
        print("  Riavvia Teams, poi: Effects and avatars > Sfondi.\n")
    elif generato:
        print("  Importalo in Centro di Controllo > effetti video > Sfondo > +\n")
    else:
        print("  In Teams: Effects and avatars > Sfondi, cerca questa immagine.\n")
    if not args.no_open:
        apri(out)


if __name__ == "__main__":
    main()
