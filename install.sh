#!/usr/bin/env bash
# ============================================================================
#  Instalador do Farol para Linux e macOS
#
#  Desktop (seu usuário):        ./install.sh
#  Linux server (systemd):  sudo ./install.sh --server
#
#  A SENHA de acesso é definida durante a instalação (não existe senha padrão).
# ============================================================================
set -euo pipefail

SERVER=0
PORT=8765
for arg in "$@"; do
  case "$arg" in
    --server) SERVER=1 ;;
    --port=*) PORT="${arg#*=}" ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
  esac
done

SRC="$(cd "$(dirname "$0")" && pwd)"
c_ok()   { printf "\033[32m✔ %s\033[0m\n" "$*"; }
c_info() { printf "\033[36m➜ %s\033[0m\n" "$*"; }
c_err()  { printf "\033[31m✘ %s\033[0m\n" "$*" >&2; exit 1; }

# ---- 1. Python 3.9+ --------------------------------------------------------
PY="$(command -v python3 || true)"
[ -z "$PY" ] && c_err "Python 3.9+ não encontrado. Instale: sudo apt install python3 python3-venv  |  brew install python"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)' || c_err "Precisa de Python 3.9 ou mais novo."
"$PY" -c 'import venv' 2>/dev/null || c_err "Módulo venv ausente. No Debian/Ubuntu: sudo apt install python3-venv"
c_ok "Python: $("$PY" --version)"

# ============================================================================
#  MODO SERVIDOR (Linux + systemd)
# ============================================================================
if [ "$SERVER" = "1" ]; then
  [ "$(uname -s)" = "Linux" ] || c_err "O modo --server com systemd é só para Linux."
  [ "$(id -u)" = "0" ] || c_err "Rode com sudo:  sudo ./install.sh --server"

  APP=/opt/farol
  DATA=/var/lib/farol
  c_info "Criando usuário de sistema 'farol' (sem login)…"
  id farol >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin farol

  c_info "Copiando arquivos para $APP…"
  mkdir -p "$APP" "$DATA"
  cp -r "$SRC/farol" "$SRC/requirements.txt" "$APP/"
  "$PY" -m venv "$APP/.venv"
  "$APP/.venv/bin/pip" install --upgrade pip -q
  "$APP/.venv/bin/pip" install -r "$APP/requirements.txt" -q
  chown -R farol:farol "$DATA"
  c_ok "Dependências instaladas"

  echo
  read -r -p "Pastas para indexar (separe por espaço, ex.: /srv/arquivos /mnt/nas): " ROOTS
  ROOT_ARGS=()
  for r in $ROOTS; do ROOT_ARGS+=(--root "$r"); done

  echo
  c_info "Defina a senha de acesso do Farol:"
  sudo -u farol env FAROL_HOME="$DATA" "$APP/.venv/bin/python" -m farol setup --server --port "$PORT" "${ROOT_ARGS[@]}"

  c_info "Instalando serviço systemd…"
  sed "s#__PORT__#$PORT#g" "$SRC/scripts/farol.service" > /etc/systemd/system/farol.service
  systemctl daemon-reload
  systemctl enable --now farol
  c_ok "Farol rodando como serviço!"
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo
  echo "  Acesse:   http://${IP:-SEU_IP}:$PORT"
  echo "  Status:   systemctl status farol"
  echo "  Logs:     journalctl -u farol -f"
  echo "  Senha:    sudo -u farol FAROL_HOME=$DATA $APP/.venv/bin/python -m farol passwd"
  echo
  echo "  ⚠  Recomendado: coloque atrás de HTTPS (Caddy/Nginx) — veja docs/SERVIDOR.md"
  echo "  ⚠  As pastas indexadas precisam ser legíveis pelo usuário 'farol'."
  exit 0
fi

# ============================================================================
#  MODO DESKTOP (Linux / macOS)
# ============================================================================
c_info "Criando ambiente virtual em $SRC/.venv…"
"$PY" -m venv "$SRC/.venv"
"$SRC/.venv/bin/pip" install --upgrade pip -q
"$SRC/.venv/bin/pip" install -r "$SRC/requirements.txt" -q
c_ok "Dependências instaladas"

echo
c_info "Configuração inicial (idioma, pastas e SENHA):"
"$SRC/.venv/bin/python" -m farol setup --port "$PORT"

# Atalho de linha de comando
cat > "$SRC/farol.sh" <<EOF
#!/usr/bin/env bash
# Inicia o Farol (abre o navegador automaticamente)
cd "$SRC" && exec "$SRC/.venv/bin/python" -m farol "\${@:-run}"
EOF
chmod +x "$SRC/farol.sh"

if [ "$(uname -s)" = "Darwin" ]; then
  # macOS: atalho clicável na Mesa
  cp "$SRC/farol.sh" "$HOME/Desktop/Farol.command" && chmod +x "$HOME/Desktop/Farol.command"
  c_ok "Atalho criado na Mesa: Farol.command"
else
  # Linux: entrada no menu de aplicativos
  mkdir -p "$HOME/.local/share/applications"
  cat > "$HOME/.local/share/applications/farol.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Farol
Comment=Buscador offline dos seus arquivos
Exec=$SRC/farol.sh run
Icon=$SRC/farol/static/favicon.svg
Terminal=false
Categories=Utility;FileTools;
EOF
  c_ok "Atalho adicionado ao menu de aplicativos"
fi

echo
c_ok "Instalação concluída! Para iniciar:  ./farol.sh"
