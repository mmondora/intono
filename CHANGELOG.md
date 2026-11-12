# Changelog

La versione sta in `VERSIONE`, in testa a `intono.py`. `install.sh` la legge
da lì e la scrive in `~/.local/share/intono/VERSION`, così l'installato e il
sorgente non possono divergere in silenzio. `intono --versione` dice quale
copia stai eseguendo.

Da alzare a ogni cambiamento che tocchi il comportamento.

## 1.0.5

- **Maglietta grigia letta come colorata.** Due cause, viste con `--debug`
  sulla webcam reale:
  - la soglia "senza tinta" usava solo la saturazione HSV, che su un grigio
    scuro si gonfia: 0.14-0.16, a cavallo di 0.15, quindi un lancio su due
    proponeva un verde pastello. Ora conta anche la croma Lab: sotto 10 la
    maglietta e senza tinta (grigio misurato: 6; beige: 13.5).
  - la zona sotto il mento introdotta nella 1.0.4 prende il collo, e su un
    grigio la pelle e l'unica cosa satura: vinceva la tinta. Ora i pixel
    color pelle si tolgono quando sono una minoranza della zona; se sono la
    maggioranza (salmone, beige) restano.
- `--debug`: salva il fotogramma con la zona misurata in
  `~/.cache/intono/debug.jpg` e stampa saturazione, croma e quota di pelle.
- `tests/test_maglietta.py`.

## 1.0.4

- **"Volto non trovato" anche con il volto in quadro.** Due cause, viste con
  una diagnostica sulla webcam reale:
  - vicino alla camera il volto e alto mezzo fotogramma, e il busto (1.45
    altezze di volto sotto la fronte) cadeva fuori dall'immagine: il volto
    veniva scartato. Ora, se sotto non resta abbastanza, si misura subito
    sotto il mento; se nemmeno li c'e spazio, il tool lo dice.
  - il rilevatore perde il volto in un frame su due o tre, e veniva guardato
    solo l'ultimo: quando mancava vinceva un falso positivo dello sfondo.
    Ora si cerca in tutti gli ultimi 8 frame del riscaldamento e vince il
    volto piu grande.
- `tests/test_volto.py`: volto vicino, volto intermittente con falso
  positivo fisso, nessun volto.

## 1.0.3

- **Il volto non veniva mai trovato.** `install.sh` installava `opencv-python`
  senza vincoli e pip ha preso la 5.0, che non ha piu `CascadeClassifier`.
  L'errore finiva in un `except` muto: a ogni scatto "volto non trovato" e la
  misura cadeva su una fascia fissa dell'inquadratura (tavolo, pelle, sfondo),
  quindi la stessa maglietta dava tinte diverse a ogni lancio. Ora
  `install.sh` installa `opencv-python>=4.8,<5` e, se il rilevatore manca, il
  tool lo dice invece di tacere.
- **Fallback ffmpeg rotto.** Quando OpenCV non apre la camera (per esempio
  perche e occupata da una call) si passava a ffmpeg, che falliva con
  `Selected pixel format (yuv420p) is not supported`. Ora chiede `nv12`.
- **`--sheet` non faceva niente**: l'opzione c'era ma nessuno la leggeva, e il
  tool partiva con la webcam. Ora scrive la tavola numerata della gallery
  Teams in `~/.cache/intono/tavola.png`.
- **`install.sh` cancellava l'immagine di base personale**: reinstallando da un
  clone senza `master.png` ci copiava sopra l'esempio. Ora tiene quella gia
  installata.
- `install.sh` chiamava `say`, mai definita: con `set -e` l'installazione si
  interrompeva se c'era la vecchia installazione teams-tone.

## 1.0.1

- `griglia()` leggeva la tinta dal nome del file spezzandolo sui trattini e
  prendendo il campo per indice. Rinominando il tool i pezzi sono passati da
  cinque (`teams-tone-set-035-pastello`) a quattro (`intono-set-035-pastello`),
  quindi leggeva il campo sbagliato e il set risultava **sempre vuoto**: niente
  posizioni, `--pagina` che ricadeva su Teams. Ora e una regex sul nome del
  programma, che non dipende da quanti trattini contiene.
- `--pagina` senza set e senza Teams installato diceva "apri Teams almeno una
  volta" invece della cosa vera: ora dice di generare il set.

## 1.0.0

- **Rinominato `intono`.** Il tool non scrive piu in Teams per default e lo
  sfondo vale per tutte le app: il vecchio nome diceva il vendor sbagliato.
  Cambiano comando, file, `~/.local/share/`, `~/.config/`, `~/.cache/`, la
  cartella di uscita `~/Pictures/intono/` e il prefisso dei file generati. I
  semi `uuid5` restano invariati: cambiarli orfanerebbe i file gia installati
  in Teams da chi aggiorna, e sono identificatori interni che nessuno legge.
  `install.sh` segnala la vecchia installazione e dice come rimuoverla.
- **Niente piu scrittura in Teams per default.** La copia utile e quella in
  `~/Pictures/intono/`, da importare nella griglia di macOS. `--anche-teams`
  ripristina l'installazione nella gallery di Teams, per webcam USB, Mac Intel
  o sfondi solo dentro Teams.
- **La cartella di Teams non e piu un prerequisito.** Prima il tool si
  rifiutava di partire se non la trovava, anche per generare uno sfondo che in
  Teams non finiva: ora si risolve solo nei comandi che la usano davvero
  (`--anche-teams`, `--dai-miei`, `--aggiungi`, `--sheet`). Verificato su una
  macchina senza Teams installato.

## 0.9.0

- La pagina HTML (`--pagina`) e costruita sulla **griglia**, non piu sulla
  gallery di Teams: ogni riga dice quale **posizione** cliccare, con il numero
  sulla miniatura. In testa c'e la striscia del set numerata, per verificare che
  l'ordine di importazione corrisponda. Senza set ricade sulla gallery di Teams
  e lo dice.
- `--delete` cancella dalla cartella di uscita solo i file che il tool ha creato
  (`intono-*.png`, `sfondo-attuale.png`), elencandoli e chiedendo conferma.
  Il filtro e sui nomi e non su tutta la cartella: in Pictures ci sono le foto
  di qualcuno. `--si` salta la conferma; senza terminale interattivo si ferma e
  lo dice invece di procedere.
- Rimossa una duplicazione di sei funzioni e di `MAGLIETTE_COMUNI` introdotta
  riscrivendo `pagina()`: le due copie erano identiche, quindi il comportamento
  non era cambiato, ma Python teneva la seconda.

## 0.8.1

- `--init` misurava la copertura sulla **gallery di Teams** mentre costruiva il
  set per la griglia di macOS: due collezioni diverse. Saltava i settori "gia
  coperti" da immagini che nella griglia non ci sono, e produceva un set
  incompleto — tre sfondi invece di otto. Ora la copertura si misura sul set.
- Il set canonico ha un prefisso proprio (`intono-set-NNN-...`), cosi le
  generazioni ad-hoc per una maglietta specifica non finiscono nella griglia e
  non spostano le posizioni.
- `--init` non installa piu il set anche nella gallery di Teams: serve alla
  griglia di macOS, e otto miniature in piu la in mezzo sono esattamente
  l'ingombro che il tool cerca di evitare. `--anche-teams` lo fa comunque.
- README e ISTRUZIONI riscritti intorno alla griglia di macOS come strada
  principale, con la gallery di Teams come alternativa per webcam USB, Mac Intel
  o sfondi solo dentro Teams.

## 0.8.0

- **La griglia di macOS.** Verificato che macOS si copia l'immagine quando la
  selezioni e non rilegge il file, ne a runtime ne al riavvio dell'app: nessun
  symlink, alias o sovrascrittura puo aggirarlo. Quindi rigenerare a ogni
  maglietta non serve, e il set va importato una volta sola.
- `--griglia` elenca il set nell'ordine in cui importarlo in Centro di Controllo
  → effetti video → Sfondo → +. Importando in ordine di nome la griglia risulta
  ordinata per tinta, quindi la posizione e calcolabile.
- Se il set esiste, il comando dice **quale posizione cliccare** invece di
  generare un nono file che andrebbe reimportato per essere usato. Immediato,
  perche non genera niente. `--genera` forza la generazione di uno esatto.
- Lo sfondo di sistema vale per Teams, Zoom e Meet insieme: un click, tutte le
  app. Richiede macOS 15+ su Apple silicon e una camera Apple (le webcam USB di
  terze parti non hanno la voce).

## 0.7.0

- `sfondo-attuale.png`, sempre allo stesso percorso nella cartella di uscita.
  Lo sfondo di sistema di macOS (Centro di Controllo → effetti video → Sfondo,
  da Sequoia) si imposta scegliendo un file e vale per tutte le app che usano la
  camera. Se macOS tiene il riferimento al percorso invece di copiarsi
  l'immagine, selezionarlo una volta basta e da lì ogni lancio cambia lo sfondo
  di tutte le app senza click.

## 0.6.0

- Copia riusabile fuori dalla cartella di Teams, in `~/Pictures/intono/`,
  con nome parlante (`intono-080-pastello.png`: tinta e resa). Dentro il
  container di Teams il file ha un nome UUID e non lo raggiunge nessun altro
  programma. `--out CARTELLA` sposta la destinazione.

## 0.5.0

- Resa pastello. La luminosità non si corregge più solo col gamma, che sposta i
  mezzitoni e lascia quasi bianca la macchia di luce del master: il canale di
  luminosità viene normalizzato e rimappato in una banda stretta, il cui centro
  è trovato per bisezione sul bersaglio.
- La saturazione non è più un moltiplicatore fisso su HSV, che a pari valore
  rende un oliva tenue e un magenta sgargiante: si biseca sulla croma C\* CIELab
  fino a un bersaglio, quindi "pastello" significa la stessa cosa a ogni tinta.
- `--pieno` per la resa precedente, più carica e contrastata.

## 0.4.0

- **Generare è il default**; scegliere tra gli sfondi già in gallery diventa
  `--dai-miei`. Il vecchio default dipendeva da cosa si era accumulato in
  gallery — vecchie foto, immagini di altri — e produceva scelte imprevedibili
  pur funzionando come progettato.
- Maglietta senza tinta: si genera sulla tinta del master, perché la ruota dei
  colori non dice niente e lo stacco lo fa la luminanza.
- L'output stampa il path completo del file.

## 0.3.0

- Le immagini affollate non passano più il filtro. Il test era
  `usabile = neutra or (coerenza e confusione ok)`: un'immagine quasi senza
  colore passava senza che il dettaglio venisse guardato, e una foto piena di
  oggetti in bianco e grigio vinceva come jolly neutro.
- Soglia di confusione da 0.040 a 0.020. Era calibrata su rumore RGB e righe a
  contrasto pieno, molto più energici di una foto vera: una stanza dettagliata
  sta a 0.033 e passava.
- `MISURA_V` a 3: la cache conserva anche il verdetto `usabile`, quindi le
  misure vecchie terrebbero quello sbagliato.

## 0.2.0

- Si apre il file dello sfondo così com'è. L'anteprima precedente componeva
  l'immagine con una didascalia e la pastiglia del colore della maglietta: non
  entrava mai nella gallery, ma era indistinguibile dal prodotto finale.

## 0.1.0

- Prima versione. Regola di armonia con soglie dichiarate, tinta dominante come
  moda circolare invece che media, croma in CIELab, generazione per rimappatura
  della tinta del master, `--init` che copre i buchi sulla ruota dei colori,
  pagina HTML di riferimento, nomi `uuid5` deterministici e idempotenti.
