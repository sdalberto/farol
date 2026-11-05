#!/bin/sh
# Configura o Farol na primeira execução e inicia o servidor.
set -e
if [ ! -f "$FAROL_HOME/config.json" ]; then
  if [ -z "$FAROL_PASSWORD" ]; then
    echo "ERRO: defina FAROL_PASSWORD (mín. 8 caracteres) na primeira execução." >&2
    exit 1
  fi
  ROOTS=""
  # Cada subpasta de /media vira uma pasta indexada (monte seus volumes ali).
  for d in /media/*; do [ -d "$d" ] && ROOTS="$ROOTS --root $d"; done
  echo "$FAROL_PASSWORD" | python -m farol setup --server --password-stdin \
      --lang "${FAROL_LANG:-pt-BR}" --port 8765 $ROOTS
fi
exec python -m farol run --no-browser --host 0.0.0.0 --port 8765 ${FAROL_PROXY:+--proxy}
