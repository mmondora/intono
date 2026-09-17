# teams-tone

Guarda la maglietta dalla webcam e ti dice quale sfondo usare, applicando una
regola di armonia dichiarata alla tua immagine di base.

## Perché un click e non zero

Vale dirlo subito, perché decide tutto il resto: **nessuno può selezionare lo
sfondo al posto tuo.** Tre livelli, tutti chiusi.

- **Teams** non espone nessuna API. La capability `videoEffects` potrebbe
  lavorare sui frame ma è Beta e dichiaratamente non da produzione.
- **macOS** sostituisce lo sfondo a livello di camera, per tutte le app insieme,
  ma si **copia** l'immagine quando la selezioni. Non rilegge il file né a
  runtime né al riavvio dell'app — provato. Symlink, alias e sovrascritture non
  cambiano niente.
- Una **virtual camera** che possiede i frame funzionerebbe, ed è l'unica cosa
  che funzionerebbe. È anche un'installazione per macchina fuori da qualunque
  governance: un altro progetto, con un costo operativo reale.

Quindi il click resta. Quello che fa il tool è renderlo banale: un comando ti
dice quale posizione cliccare, mostrando il perché.

## Installazione

1. Nel Finder: click destro sulla cartella → **Servizi → Nuovo Terminale nella
   cartella**.
2. `bash install.sh`
3. `teams-tone` — la prima volta macOS chiede la Camera: concedila.

`install.sh` va rilanciato **a ogni cambiamento del codice**: il comando
`teams-tone` esegue una copia installata, non il file nel progetto. Ti dice
quale versione sta sostituendo, e `teams-tone --versione` dice quale stai
eseguendo.

## Setup della griglia macOS — una volta sola

È la strada buona: lo sfondo vale per Teams, Zoom, Meet e tutto il resto
insieme.

```
teams-tone --master ~/percorso/tuo-sfondo.png
teams-tone --init       # genera gli 8 in ~/Pictures/teams-tone/
teams-tone --griglia    # l'ordine in cui importarli
```

Poi importali **in quell'ordine** in Centro di Controllo → effetti video →
Sfondo → `+`. L'ordine è il punto: importandoli per nome la griglia risulta
ordinata per tinta, ed è questo che trasforma "cerca la miniatura giusta" in
"clicca la quarta".

Da lì in avanti:

```
teams-tone
```

```
  maglietta: tinta 8°  intensita 0.50  luminosita 0.52
  colore opposto: tinta ideale 183°

  griglia macOS: posizione 4 di 8   (tinta 185°, 2° dall'ideale)
```

Non genera niente, quindi risponde subito. Lo scarto dall'ideale resta sotto i
22°, metà del passo di 45°: dentro la tolleranza dell'armonia.

Il set vive solo in `~/Pictures/teams-tone/` e **non** viene installato anche in
Teams: otto miniature in più in quella griglia sono esattamente l'ingombro che
il tool cerca di evitare. Con `--anche-teams` lo fa comunque.

**Serve** macOS 15 o successivo su Apple silicon e una camera Apple (integrata,
Studio Display, o iPhone come Continuity Camera). Con una webcam USB di terze
parti quella voce non compare.

## L'altra strada — la gallery di Teams

Per una webcam USB, un Mac Intel, o quando vuoi uno sfondo solo dentro Teams:

```
teams-tone --genera
```

Rimappa la tua immagine sulla tinta esatta, la installa nella cartella degli
sfondi di Teams con la coppia `<uuid>.png` + `<uuid>_thumb.png` che Teams
pretende, e apre il file così lo riconosci nella griglia. È anche quello che
succede da solo se il set degli 8 non esiste ancora.

Ogni immagine generata finisce anche in `~/Pictures/teams-tone/` con un nome
leggibile, perché dentro il container di Teams ha un nome UUID e non la
raggiunge nessun altro programma. `teams-tone --out CARTELLA` sposta la
destinazione.

## Gli altri comandi

```
teams-tone --mode tono        armonia morbida (salmone → verde oliva)
teams-tone --mode contrasto   colore opposto  (salmone → teal)
teams-tone --pieno            resa più carica invece che pastello
teams-tone --pagina           pagina HTML: quale sfondo con quale maglietta
teams-tone --sheet            tavola numerata dei tuoi sfondi Teams
teams-tone --dai-miei         scegli tra gli sfondi già in gallery Teams
teams-tone --aggiungi FILE    aggiungi un'immagine alla gallery Teams
teams-tone --image FOTO       usa una foto invece della webcam (per provare)
teams-tone --versione         quale versione stai eseguendo
```

## L'immagine di partenza

`teams-tone --master ~/Desktop/tua.png`. La tinta la **misura da sola**, non
devi dichiararla: chiedertela era un invito a sbagliare, e un valore sbagliato
sposta ogni colore generato di quella differenza facendo sembrare difettosa la
regola.

Nel repo c'è `examples/master-example.png`, un gradiente neutro generato, così
il tool funziona prima che tu configuri qualcosa. Nessun asset aziendale è
versionato.

## Le regole, in chiaro

Sono le costanti in testa a `teams_tone.py`:

- mai uno sfondo a meno di **25°** dalla maglietta: ti mimetizzi
- armonia morbida = **70°** di distanza; contrasto = **175°**
- luminosità dello sfondo lontana almeno **0.10** da quella della maglietta
- lo sfondo non può essere molto più **carico**: la croma è in CIELab, non
  saturazione HSV, perché a pari saturazione un magenta e un oliva hanno
  intensità visiva molto diversa
- maglietta **senza tinta**: decide la luminosità — nera vuole sfondo chiaro,
  bianca scuro
- immagini **affollate o senza tinta dominante** escluse dalla scelta
  automatica: una foto di una libreria non ha un colore

## Disinstallare

`bash install.sh --uninstall`
