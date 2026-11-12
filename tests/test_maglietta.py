"""Test della misura della maglietta (collo nella zona, grigio con luce calda).
    python tests/test_maglietta.py ."""
import sys
import numpy as np
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
import intono

rng = np.random.default_rng(0)

def zona(colore, pelle_frac=0.0, h=81, w=1200, rumore=6):
    z = np.empty((h, w, 3), np.float32)
    z[:] = colore
    n = int(round(h * pelle_frac))
    z[:n] = (196, 142, 120)                       # collo, in alto nella zona
    z += rng.normal(0, rumore, z.shape)
    return np.clip(z, 0, 255).astype(np.uint8)

def caso(nome, roi, neutra, tinta=None):
    m = intono.misura_maglietta(roi)
    ok = intono.acromatica(m) == neutra
    if tinta is not None:
        ok = ok and intono.dist_tinta(m["tinta"], tinta) <= 15
    print("PASS" if ok else "FAIL", f"{nome:42s} sat {m['sat']:.2f} croma {m['croma']:5.1f} "
          f"tinta {m['tinta']:5.1f} -> {'senza tinta' if intono.acromatica(m) else 'colorata'}")
    return ok

r = [
    caso("grigio scuro, luce calda", zona((86, 80, 77)), True),
    caso("grigio scuro, luce calda, 32% collo", zona((86, 80, 77), 0.32), True),
    caso("grigio chiaro, 45% collo", zona((150, 146, 143), 0.45), True),
    caso("blu, 35% collo", zona((40, 70, 150), 0.35), False, 222),
    caso("verde oliva, 30% collo", zona((105, 110, 60), 0.30), False, 66),
    caso("salmone (simile alla pelle), 100%", zona((225, 140, 115)), False, 14),
    caso("beige", zona((200, 180, 150)), False, 36),
    caso("nera", zona((25, 24, 26)), True),
]
sys.exit(0 if all(r) else 1)
