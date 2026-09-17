# teams-tone

Guarda la maglietta dalla webcam e **genera** lo sfondo Teams che ci sta bene,
rimappando la tua immagine di base sulla tinta giusta.

## Installazione

1. Scompatta lo zip. Nel Finder: click destro sulla cartella → **Servizi → Nuovo
   Terminale nella cartella**.
2. `bash install.sh`
3. `teams-tone` — la prima volta macOS chiede la Camera: concedila.

## I quattro comandi che servono

```
teams-tone            genera lo sfondo per la maglietta che hai addosso
teams-tone --dai-miei scegli tra gli sfondi che hai gia, invece di generarne
teams-tone --init     completa il set di base (solo le tinte che non hai)
teams-tone --pagina   pagina HTML: quale sfondo con quale maglietta
teams-tone --master FOTO.png    cambia l'immagine di partenza
```

Si apre il file dello sfondo scelto, così com'è: è quello da cercare in Teams
(**Effects and avatars → Sfondi**). Serve perché la tua griglia ha trenta
miniature senza nomi, e sapere che si chiama "avocado" non aiuta a trovarla.
Nessuna didascalia e nessuna pastiglia di colore sopra: un'anteprima con delle
scritte è indistinguibile dallo sfondo vero, e fa pensare di averle addosso in
riunione. I numeri stanno nel terminale.

Altre opzioni: `--mode tono|contrasto` per forzare il criterio, `--sheet` per una tavola numerata dei tuoi
sfondi, `--aggiungi FILE` per metterne uno in gallery, `--image FOTO` per provare
senza webcam.

## Le copie riusabili

Ogni sfondo generato viene scritto **due volte**: nella cartella di Teams con il
nome UUID che Teams pretende, e in `~/Pictures/teams-tone/` con un nome
leggibile tipo `teams-tone-080-pastello.png` (tinta e resa). La seconda serve
perché dentro il container di Teams quel file non lo raggiunge nessun altro
programma: da Pictures lo usi in Zoom, Meet, una slide, o come sfondo del
desktop. Con `teams-tone --out CARTELLA` la sposti dove vuoi.

## L'immagine di partenza

Nello zip c'è `master.png`, lo sfondo TeamSystem arancione, e l'installer la copia
in `~/.local/share/teams-tone/`. È solo un default: **ognuno può usare la sua.**

```
teams-tone --master ~/Desktop/il-mio-sfondo.png
```

La tinta la **misura da sola**, non devi dichiararla. Chiedertela era un invito a
sbagliare: se dichiari una tinta diversa da quella vera, ogni colore generato
esce spostato di quella differenza e sembra un difetto della regola.

## `--init`: il set di base per differenza

Divide la ruota dei colori in 8 spicchi partendo dalla tinta del tuo master, poi
**genera solo gli spicchi che non hai già**. Sulla tua gallery salta arancio,
oliva e teal — ce li hai — e riempie i buchi.

Il motivo è che il tuo problema non è avere pochi sfondi, è trovarli: un set
completo a ogni installazione raddoppierebbe una griglia già difficile da
leggere.

## La pagina

`teams-tone --pagina` genera un file HTML unico, con le miniature incorporate:
funziona offline e lo puoi mandare a un collega senza allegare cartelle. Una riga
per ogni colore di maglietta diffuso, con lo sfondo consigliato in armonia
morbida e in contrasto.

I valori delle magliette in tabella sono tipici di quei capi sotto luce
d'ufficio, non misure di un campione reale: servono a costruire la tabella. Per
la maglietta che hai addosso adesso, misurata davvero, lancia `teams-tone`.

## Le regole, in chiaro

Sono le costanti in testa a `teams_tone.py`:

- mai uno sfondo a meno di **25°** dalla maglietta: ti mimetizzi
- armonia morbida = **70°** di distanza sulla ruota dei colori
- contrasto = **175°**, il colore opposto
- luminosità dello sfondo lontana almeno **0.10** da quella della maglietta
- lo sfondo non può essere molto più **carico** della maglietta: la croma è
  misurata in CIELab, non come saturazione HSV, perché un magenta e un oliva con
  la stessa saturazione HSV hanno intensità visiva molto diversa
- maglietta **senza tinta** (bianca, grigia, nera): la ruota dei colori non dice
  niente, decide lo stacco di luminosità — nera vuole sfondo chiaro, bianca scuro
- immagini **affollate o senza tinta dominante** sono escluse dalla scelta
  automatica: una foto di una libreria non ha un colore, e farci un match di
  armonia sarebbe finto

## Cosa NON fa

Non seleziona lo sfondo al posto tuo: Teams non espone nessuna API per farlo.
Quel click resta tuo.

## Disinstallare

`bash install.sh --uninstall`
