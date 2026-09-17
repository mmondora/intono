# teams-tone

Looks at the shirt you are actually wearing and tells you which video-call
background goes with it — from a stated colour-harmony rule, using your own base
image, in one click.

No cloud, no network calls, no Teams API. The frame never leaves your machine.

```
$ teams-tone

  volto trovato, guardo il busto sotto
  maglietta: tinta 8°  intensita 0.50  luminosita 0.52
  colore opposto: tinta ideale 183°

  griglia macOS: posizione 4 di 8   (tinta 185°, 2° dall'ideale)
  vale per Teams, Zoom, Meet: e lo sfondo di sistema
```

## Why one click and not zero

Worth saying up front, because it shapes everything below: **nothing here can
select the background for you.** Three layers were checked, and all three are
closed.

- **Teams** exposes no API for it — not Graph, not the Teams JS SDK. The
  `videoEffects` capability could process frames directly but is Beta and
  explicitly not recommended for production.
- **macOS** (15+, Apple silicon) does replace the background at the camera
  layer, for every app at once. But it **copies** the image when you select it.
  It does not re-read the file at runtime, and not on app restart either —
  tested. A symlink, an alias, or overwriting the path changes nothing.
- A **virtual camera** owning the frames would work, and is the only thing that
  would. It is also a per-device install outside any governance, which is a
  different project with a real operational cost.

So the click stays. What this tool does is make it trivial: one keystroke tells
you exactly which slot to click, with the reasoning shown.

## Quick start — the macOS grid

This is the recommended path: the background is replaced at the camera layer, so
one choice covers Teams, Zoom, Meet and anything else simultaneously.

```bash
git clone https://github.com/mmondora/teams-tone.git
cd teams-tone
bash install.sh
teams-tone --master path/to/your-background.png   # your own base image
teams-tone --init                                 # generate eight hues
teams-tone --griglia                              # the order to import them in
```

`--griglia` prints the set:

```
   1.  tinta  35°   teams-tone-set-035-pastello.png
   2.  tinta  80°   teams-tone-set-080-pastello.png
   3.  tinta 125°   teams-tone-set-125-pastello.png
   4.  tinta 170°   teams-tone-set-170-pastello.png
   ...
```

Import them **in that order**, once, into Control Center → video effects →
Background → `+`. The order is the point: importing in filename order makes the
grid hue-ordered, which is what turns "find the right thumbnail" into "click
slot 4". From then on:

```bash
teams-tone          # → griglia macOS: posizione 4 di 8
teams-tone --pagina # a cheat-sheet: shirt colour → slot, as one HTML file
```

`--pagina` writes a single self-contained HTML file — thumbnails embedded, works
offline, sendable to a colleague — with the numbered set across the top so you
can check your import order, then a row per common shirt colour giving the slot
for soft harmony and for contrast.

Nothing is generated, so it answers instantly. The chosen slot is at most ~22°
from the ideal hue — half of the 45° spacing, comfortably inside the harmony
tolerance.

**Requirements for this path:** macOS 15 or later on Apple silicon, and an Apple
camera — built-in, Studio Display, or an iPhone as Continuity Camera. Third-party
USB webcams do not get the feature at all.

## The other path — the Teams gallery

For a USB webcam, an Intel Mac, or when you want a background only inside Teams,
the tool writes directly into the Teams custom-background folder. This is what
happens automatically when no grid set exists yet, or on `--genera`:

```bash
teams-tone --genera
```

It remaps your base image to the exact hue, installs it with the `<uuid>.png` +
`<uuid>_thumb.png` pair Teams requires, and opens the file so you can find it in
the gallery. Names are deterministic `uuid5` per hue bucket, so re-running
overwrites instead of accumulating, and an image already there is detected by
hash and never duplicated. Cleanup only touches entries this tool created.

Every generated image is also copied to `~/Pictures/teams-tone/` under a name
that says what it is, plus a fixed `sfondo-attuale.png` — because inside the
Teams container a background is a UUID in a hidden folder that no other
application can reasonably use. `--out DIR` moves that folder.

## Install

`install.sh` creates an isolated virtualenv under `~/.local/share/teams-tone`,
installs `numpy`, `pillow` and `opencv-python` there, and puts a `teams-tone`
command in `~/.local/bin`. Nothing goes into the system Python.
`bash install.sh --uninstall` removes all of it.

On first run macOS asks for camera access. Grant it to your terminal, or to the
`Teams Tone.command` launcher the installer drops on your Desktop.

Re-run `install.sh` after every change: the `teams-tone` command runs the
installed snapshot, not the file in your working tree. It reports what it
replaced, and `teams-tone --versione` says which copy you are running.

## Commands

| Command | What it does |
| --- | --- |
| `teams-tone` | look at the shirt, name the grid slot to click |
| `teams-tone --init` | generate the eight-hue set (only the hues you lack) |
| `teams-tone --griglia` | list the set in the order to import it into macOS |
| `teams-tone --genera` | generate a fresh exact-hue background instead |
| `teams-tone --master FILE` | set the base image everything is derived from |
| `teams-tone --mode tono\|contrasto` | force soft harmony or complementary |
| `teams-tone --pieno` | punchier rendering instead of the pastel default |
| `teams-tone --out DIR` | where to keep the reusable copies |
| `teams-tone --dai-miei` | pick among backgrounds already in the Teams gallery |
| `teams-tone --pagina` | single-file HTML page: which slot for which shirt |
| `teams-tone --delete` | remove the backgrounds the tool created in Pictures |
| `teams-tone --sheet` | numbered contact sheet of your Teams backgrounds |
| `teams-tone --aggiungi FILE` | add an image to the Teams gallery |
| `teams-tone --image FILE` | use a photo instead of the webcam |
| `teams-tone --versione` | which installed version you are running |

## The rule

Every threshold is a named constant at the top of `teams_tone.py`.

- **Never within 25°** of the shirt's hue — you blend into your own background.
- **Soft harmony** targets 70° of hue distance; **contrast** targets 175°.
  `auto` picks contrast for a saturated shirt, harmony for a muted one.
- Background lightness stays at least **0.10** away from the shirt's.
- The background may not be much more **chromatic** than the shirt.
- **Achromatic shirt** (white, grey, black): hue says nothing, so lightness
  decides — black shirt gets a light background, white shirt a dark one.
- **Busy images are excluded** from automatic selection. A photo of a bookshelf
  has no single colour, so matching harmony against one would be make-believe.

## How it works, and the parts that are not obvious

**Dominant hue is the circular mode, not the mean.** Blue sky at 215° and green
grass at 100° in equal measure average to 161° — a teal that appears nowhere in
the image, with enough apparent coherence to pass a naive gate. The mode finds
the region that actually dominates, and the weight mass around it is the honest
measure of how representative that hue is.

**Chroma is measured in CIELab, not as HSV saturation.** A magenta and an olive
at the same HSV saturation have very different visual intensity — 68 against 29
in C\*. Using HSV for intensity makes the tool pick garish colours while
believing they are as muted as everything else.

**Generated backgrounds are bisected on luminance and chroma, not set with HSV
multipliers.** Rec.709 weights green at 0.71, so one HSV value rendered on a
yellow-green hue gives acid lime and on a blue gives midnight. Both axes are
solved for a target — median luminance and median CIELab C\* — so "pastel" means
the same thing at every hue, and the separation from the shirt is true by
construction rather than checked and rejected afterwards.

**The lightness range is compressed, not just gamma-corrected.** A gamma moves
the midtones but leaves the base image's light source almost white, which is
what makes a recolour look blown out. Normalising the value channel into a narrow
band removes both the clipped highlight and the crushed shadow — low chroma plus
low contrast is what actually reads as pastel.

**`--init` fills gaps instead of generating a set.** It divides the wheel into
eight sectors from your base image's hue and generates only the sectors you do
not already cover. The problem with a background gallery is not having too few,
it is finding one.

**Generating is not the answer once the grid exists.** A ninth exact-hue image
would have to be imported again to be usable, so naming an existing slot beats
producing a better file. The copy-on-select behaviour that blocks automation is
the same behaviour that makes a fixed set worth having.

**Busyness is calibrated on real photographs.** The first threshold came from
synthetic adversarial images — RGB noise, hard-edged stripes — which are far more
gradient-energetic than a real room. A detailed photograph measured 0.033 and
sailed through a limit of 0.040. Smooth gradients sit at 0.001–0.010, so the
limit is 0.020.

## Base images

The repository ships no corporate assets. `examples/master-example.png` is a
neutral generated gradient, there so the tool runs before you configure
anything. Point `--master` at your own image; its hue is measured, not declared
— being asked to state it was an invitation to get it wrong, and a wrong value
shifts every generated colour by that error while looking like a bug in the rule.

## Versioning

`VERSIONE` at the top of `teams_tone.py` is the single source; `install.sh` reads
it from there and records it in `~/.local/share/teams-tone/VERSION`, so the
installed copy and the source cannot drift apart silently. See `CHANGELOG.md`.

## Platforms

macOS only. The Teams background folder and the webcam backend are macOS paths;
Windows support is not implemented. On Linux, Teams runs as a web app and exposes
no background folder at all.

## Licence

MIT
