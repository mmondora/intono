# Changelog

La versione sta in `VERSIONE`, in testa a `teams_tone.py`. `install.sh` la legge
da lì e la scrive in `~/.local/share/teams-tone/VERSION`, così l'installato e il
sorgente non possono divergere in silenzio. `teams-tone --versione` dice quale
copia stai eseguendo.

Da alzare a ogni cambiamento che tocchi il comportamento.

## 0.7.0

- `sfondo-attuale.png`, sempre allo stesso percorso nella cartella di uscita.
  Lo sfondo di sistema di macOS (Centro di Controllo → effetti video → Sfondo,
  da Sequoia) si imposta scegliendo un file e vale per tutte le app che usano la
  camera. Se macOS tiene il riferimento al percorso invece di copiarsi
  l'immagine, selezionarlo una volta basta e da lì ogni lancio cambia lo sfondo
  di tutte le app senza click.

## 0.6.0

- Copia riusabile fuori dalla cartella di Teams, in `~/Pictures/teams-tone/`,
  con nome parlante (`teams-tone-080-pastello.png`: tinta e resa). Dentro il
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
