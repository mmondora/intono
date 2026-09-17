# teams-tone

Picks the Microsoft Teams background that goes with the shirt you are actually
wearing. One webcam shot, a stated colour-harmony rule, and the answer is one of
the backgrounds you already have — or a new one generated for the occasion.

No cloud, no network calls, no Teams API. The frame never leaves your machine.

```
$ teams-tone

  volto trovato, guardo il busto sotto
  maglietta: tinta 8°  intensita 0.50  luminosita 0.52
  cerco: armonia morbida

  -> avocado.png  tinta   66.9°  59° dalla maglietta
     teal.png     tinta  186.7°  179° dalla maglietta
     oro.png      tinta   33.7°  scartata: solo 26° dalla maglietta, ti mimetizzi

  sfondo: avocado.png
  tinta 67°   luminosita 0.65
  In Teams: Effects and avatars > Sfondi, cerca questa immagine.
```

## Why it exists

Teams gives you a grid of unlabelled thumbnails and no way to sort it. Picking a
background that clashes with what you are wearing is easy; noticing it during the
call is worse. This makes the choice explicit and repeatable.

## Install (macOS)

```bash
git clone https://github.com/mmondora/teams-tone.git
cd teams-tone
bash install.sh
teams-tone --master path/to/your-background.png   # your own base image
teams-tone
```

`install.sh` creates an isolated virtualenv under
`~/.local/share/teams-tone`, installs `numpy`, `pillow` and `opencv-python`
there, and puts a `teams-tone` command in `~/.local/bin`. Nothing is installed
into the system Python. `bash install.sh --uninstall` removes all of it.

On first run macOS asks for camera access. Grant it to your terminal, or to the
`Teams Tone.command` launcher the installer drops on your Desktop.

## Commands

| Command | What it does |
| --- | --- |
| `teams-tone` | look at the shirt, recommend a background, open its image |
| `teams-tone --init` | fill gaps in your base set around the colour wheel |
| `teams-tone --pagina` | single-file HTML page: which background for which shirt |
| `teams-tone --master FILE` | set the base image new backgrounds are derived from |
| `teams-tone --mode tono\|contrasto` | force soft harmony or complementary |
| `teams-tone --genera` | generate a made-to-measure background anyway |
| `teams-tone --sheet` | numbered contact sheet of every background you have |
| `teams-tone --aggiungi FILE` | add an image to the Teams gallery |
| `teams-tone --image FILE` | use a photo instead of the webcam |

## The rule

Every threshold is a named constant at the top of `teams_tone.py`.

- **Never within 25°** of the shirt's hue — you blend into your own background.
- **Soft harmony** targets 70° of hue distance; **contrast** targets 175°.
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
in C\*. Using HSV for intensity harmony makes the tool pick garish colours while
believing they are as muted as everything else.

**Generated backgrounds are normalised on luminance, not on HSV value.** Rec.709
weights green at 0.71, so one value rendered on a yellow-green hue gives acid
lime and on a blue gives midnight. Targeting a luminance found by bisection
keeps results consistent across hues and makes the separation from the shirt true
by construction rather than checked and rejected afterwards.

**`--init` fills gaps instead of generating a set.** It divides the colour wheel
into eight sectors from your base image's hue and generates only the sectors you
do not already cover. The problem with a Teams gallery is not having too few
backgrounds, it is finding one; a full set on every install would double a grid
that is already hard to read.

**Installed files are content-addressed and idempotent.** Backgrounds get
deterministic `uuid5` names, so re-running overwrites instead of accumulating,
and an image already in the gallery is detected by hash and never duplicated.
Cleanup only ever touches entries this tool created.

## What it does not do

**It does not select the background for you.** Teams exposes no API for that —
not in Graph, not in the Teams JS SDK. The `videoEffects` capability, which
could process frames directly, is Beta and explicitly not recommended for
production. So the last click stays yours. The tool opens the chosen
background's own file — unaltered, no caption, no colour swatch — because in a
grid of thirty unlabelled thumbnails the name is useless and anything drawn on
top would make the preview look like the thing you are about to wear.

Windows paths and capture are not implemented yet; the Teams background folder
and webcam backend are macOS-only in this version.

## Base images

The repository ships no corporate assets. `examples/master-example.png` is a
neutral generated gradient, there so the tool runs before you configure
anything. Point `--master` at your own image; its hue is measured, not declared
— being asked to state it was an invitation to get it wrong, and a wrong value
shifts every generated colour by that error while looking like a bug in the rule.

## Licence

MIT
