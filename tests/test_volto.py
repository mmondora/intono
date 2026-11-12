"""Test del rilevamento volto/busto. Uso:
    python tests/test_volto.py . FOTO_CON_UN_VOLTO.jpg
(es. lena.jpg dai sample di opencv). Esce con 1 se un caso fallisce."""
import sys, numpy as np, cv2
sys.path.insert(0, sys.argv[1]); import intono
from PIL import Image
lena = np.asarray(Image.open(sys.argv[2]).convert("RGB"))
casc, _ = intono._rilevatore_volti()
fx, fy, fw, fh = max(casc.detectMultiScale(cv2.cvtColor(lena, cv2.COLOR_RGB2GRAY), 1.1, 5), key=lambda f: f[2]*f[3])
print("lena volto", fx, fy, fw, fh)

def scena(face_px, face_top, con_volto=True, falso=True):
    W, H = 1920, 1080
    img = np.full((H, W, 3), (200, 190, 170), np.uint8)       # parete beige
    k = face_px / fh
    big = cv2.resize(lena, None, fx=k, fy=k)
    ox, oy = int(W/2 - (fx + fw/2)*k), int(face_top - fy*k)
    face = big[int(fy*k):int((fy+fh)*k), int(fx*k):int((fx+fw)*k)]
    chin = oy + int((fy+fh)*k)
    img[chin:, :] = (40, 80, 170)                               # maglietta blu
    if con_volto:
        y0, x0 = oy + int(fy*k), ox + int(fx*k)
        img[y0:y0+face.shape[0], x0:x0+face.shape[1]] = face
    if falso:                                                   # "quadro" con volto a sinistra
        small = cv2.resize(face, (240, 240)); img[450:690, 170:410] = small
    return img

def check(nome, frames, atteso_msg, tinta=(200, 240)):
    roi, msg = intono.zona_busto(frames)
    m = intono.misura(roi)
    ok = atteso_msg in msg and (tinta is None or tinta[0] <= m["tinta"] <= tinta[1])
    print(("PASS" if ok else "FAIL"), nome, "|", msg, "| tinta", m["tinta"])
    return ok

r = []
r.append(check("lena originale", [lena], "volto trovato", None))
r.append(check("volto vicino 650px", [scena(650, 230)], "volto trovato"))
r.append(check("volto normale 300px", [scena(300, 250)], "volto trovato"))
r.append(check("volto solo in 3 frame su 8, falso fisso",
               [scena(650, 230, con_volto=(i in (2, 5, 7))) for i in range(8)], "volto trovato"))
r.append(check("nessun volto", [np.full((1080,1920,3),(40,80,170),np.uint8)], "volto non trovato", None))
sys.exit(0 if all(r) else 1)
