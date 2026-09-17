#!/bin/bash
# Installer teams-tone (macOS).
#   bash install.sh              installa
#   bash install.sh --uninstall  rimuove
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HOME/.local/share/teams-tone"
BIN="$HOME/.local/bin"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "$APP"; rm -f "$BIN/teams-tone" "$HOME/Desktop/Teams Tone.command"
  rm -rf "$HOME/.cache/teams-tone"
  echo; ok "rimosso (gli sfondi in Teams restano dove sono)"; echo
  exit 0
fi

echo; echo "  Installazione teams-tone"; echo

command -v python3 >/dev/null 2>&1 || {
  warn "python3 non trovato. Lancia:  xcode-select --install"; exit 1; }
ok "python3 $(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')"

[[ -e "$SRC/teams_tone.py" ]] || { warn "manca teams_tone.py: sei nella cartella giusta?"; exit 1; }

# La versione sta solo in teams_tone.py: qui viene letta, non duplicata, cosi
# non possono divergere. Bump di VERSIONE a ogni cambiamento.
VER="$(sed -n 's/^VERSIONE = "\(.*\)".*/\1/p' "$SRC/teams_tone.py" | head -1)"
[[ -n "$VER" ]] || VER="sconosciuta"
PREC="$(cat "$APP/VERSION" 2>/dev/null || true)"

# L'immagine di base: la tua se c'e, altrimenti l'esempio neutro del repo.
MASTER=""
[[ -e "$SRC/master.png" ]] && MASTER="$SRC/master.png"
[[ -z "$MASTER" && -e "$SRC/examples/master-example.png" ]] && MASTER="$SRC/examples/master-example.png"
[[ -n "$MASTER" ]] || { warn "nessuna immagine di base trovata (master.png o examples/master-example.png)"; exit 1; }

mkdir -p "$APP" "$BIN"
cp "$SRC/teams_tone.py" "$APP/"
cp "$MASTER" "$APP/master.png"
printf '%s\n' "$VER" > "$APP/VERSION"
if [[ -n "$PREC" && "$PREC" != "$VER" ]]; then
  ok "teams-tone $VER  (aggiornato da $PREC)"
elif [[ -n "$PREC" ]]; then
  ok "teams-tone $VER  (era gia questa versione: reinstallata)"
else
  ok "teams-tone $VER"
fi
ok "copiato in $APP"
[[ "$MASTER" == *examples* ]] && warn "uso l'immagine di base di esempio; imposta la tua con: teams-tone --master TUA.png"

[[ -x "$APP/venv/bin/python" ]] || python3 -m venv "$APP/venv"
"$APP/venv/bin/python" -m pip install -q --upgrade pip
echo "  installo numpy, pillow, opencv-python (un minuto)..."
"$APP/venv/bin/python" -m pip install -q numpy pillow opencv-python
ok "dipendenze pronte"

cat > "$BIN/teams-tone" <<EOF
#!/bin/bash
exec "$APP/venv/bin/python" "$APP/teams_tone.py" "\$@"
EOF
chmod +x "$BIN/teams-tone"
ok "comando: teams-tone"

cat > "$APP/Teams Tone.command" <<EOF
#!/bin/bash
"$APP/venv/bin/python" "$APP/teams_tone.py"
echo; read -n 1 -s -r -p "Premi un tasto per chiudere."
EOF
chmod +x "$APP/Teams Tone.command"
cp "$APP/Teams Tone.command" "$HOME/Desktop/" 2>/dev/null \
  && ok 'sul Desktop: "Teams Tone.command" (doppio click)' \
  || warn 'niente icona sul Desktop; usa il comando teams-tone'

echo
if [[ ":$PATH:" != *":$BIN:"* ]]; then
  warn "aggiungi una volta sola questa riga, poi riapri il Terminale:"
  printf '  echo '"'"'export PATH="$HOME/.local/bin:$PATH"'"'"' >> ~/.zshrc\n\n'
fi
ok "fatto. Prova:  teams-tone        (versione: teams-tone --versione)"
echo
