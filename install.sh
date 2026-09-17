#!/bin/bash
# Installer intono (macOS).
#   bash install.sh              installa
#   bash install.sh --uninstall  rimuove
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HOME/.local/share/intono"
BIN="$HOME/.local/bin"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$APP"; rm -f "$BIN/intono" "$HOME/Desktop/Intono.command"
  rm -rf "$HOME/.cache/intono"
  echo; ok "rimosso (gli sfondi in Teams restano dove sono)"; echo
  exit 0
fi

echo; echo "  Installazione intono"; echo

# Il tool si chiamava teams-tone: segnalo la vecchia installazione invece di
# lasciarla in giro a confondere le idee.
if [[ -d "$HOME/.local/share/teams-tone" ]]; then
  warn "trovata la vecchia installazione teams-tone. Per rimuoverla:"
  say  "rm -rf ~/.local/share/teams-tone ~/.config/teams-tone ~/.cache/teams-tone"
  say  "rm -f ~/.local/bin/teams-tone \"$HOME/Desktop/Teams Tone.command\""
  say  "e gli sfondi vecchi: rm -rf ~/Pictures/teams-tone"
  echo
fi

command -v python3 >/dev/null 2>&1 || {
  warn "python3 non trovato. Lancia:  xcode-select --install"; exit 1; }
ok "python3 $(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"

[[ -e "$SRC/intono.py" ]] || { warn "manca intono.py: sei nella cartella giusta?"; exit 1; }

# La versione sta solo in intono.py: qui viene letta, non duplicata, cosi
# non possono divergere. Bump di VERSIONE a ogni cambiamento.
VER="$(sed -n 's/^VERSIONE = "\(.*\)".*/\1/p' "$SRC/intono.py" | head -1)"
[[ -n "$VER" ]] || VER="sconosciuta"
PREC="$(cat "$APP/VERSION" 2>/dev/null || true)"

# L'immagine di base: la tua se c'e, altrimenti l'esempio neutro del repo.
MASTER=""
[[ -e "$SRC/master.png" ]] && MASTER="$SRC/master.png"
[[ -z "$MASTER" && -e "$SRC/examples/master-example.png" ]] && MASTER="$SRC/examples/master-example.png"
[[ -n "$MASTER" ]] || { warn "nessuna immagine di base trovata (master.png o examples/master-example.png)"; exit 1; }

mkdir -p "$APP" "$BIN"
cp "$SRC/intono.py" "$APP/"
cp "$MASTER" "$APP/master.png"
printf '%s\n' "$VER" > "$APP/VERSION"
if [[ -n "$PREC" && "$PREC" != "$VER" ]]; then
  ok "intono $VER  (aggiornato da $PREC)"
elif [[ -n "$PREC" ]]; then
  ok "intono $VER  (era gia questa versione: reinstallata)"
else
  ok "intono $VER"
fi
ok "copiato in $APP"
[[ "$MASTER" == *examples* ]] && warn "uso l'immagine di base di esempio; imposta la tua con: intono --master TUA.png"

[[ -x "$APP/venv/bin/python" ]] || python3 -m venv "$APP/venv"
"$APP/venv/bin/python" -m pip install -q --upgrade pip
echo "  installo numpy, pillow, opencv-python (un minuto)..."
"$APP/venv/bin/python" -m pip install -q numpy pillow opencv-python
ok "dipendenze pronte"

cat > "$BIN/intono" <<EOF
#!/bin/bash
exec "$APP/venv/bin/python" "$APP/intono.py" "\$@"
EOF
chmod +x "$BIN/intono"
ok "comando: intono"

cat > "$APP/Intono.command" <<EOF
#!/bin/bash
"$APP/venv/bin/python" "$APP/intono.py"
echo; read -n 1 -s -r -p "Premi un tasto per chiudere."
EOF
chmod +x "$APP/Intono.command"
cp "$APP/Intono.command" "$HOME/Desktop/" 2>/dev/null \
  && ok 'sul Desktop: "Intono.command" (doppio click)' \
  || warn 'niente icona sul Desktop; usa il comando intono'

echo
if [[ ":$PATH:" != *":$BIN:"* ]]; then
  warn "aggiungi una volta sola questa riga, poi riapri il Terminale:"
  printf '  echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> ~/.zshrc\n\n'
fi
ok "fatto. Prova:  intono        (versione: intono --versione)"
echo
