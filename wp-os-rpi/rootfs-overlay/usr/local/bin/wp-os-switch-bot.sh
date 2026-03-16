#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS -- Switch Bot Script
# Switches the active bot (wos-py | wos-js | kingshot)
# Called by app.py: bash wp-os-switch-bot.sh <bot-type>
# Placeholders are substituted by build-lxc.sh / build-iso.sh
# ============================================================
set -euo pipefail

OS_USERNAME="@@OS_USERNAME@@"
BOT_DIR="@@BOT_DIR@@"
VENV_DIR="@@VENV_DIR@@"
SERVICE_NAME="@@SERVICE_NAME@@"
TOKEN_FILE="@@TOKEN_FILE@@"
BOT_MAIN_PY="@@BOT_MAIN_PY@@"
BOT_INSTALL_PY="@@BOT_INSTALL_PY@@"
BOT_JS_REPO="@@BOT_JS_REPO@@"
BOT_JS_BRANCH="@@BOT_JS_BRANCH@@"
BOT_KINGSHOT_REPO="@@BOT_KINGSHOT_REPO@@"
BOT_KINGSHOT_BRANCH="@@BOT_KINGSHOT_BRANCH@@"
DEFAULT_BOT="@@DEFAULT_BOT@@"
BACKGROUND_IMAGE_URL="@@BACKGROUND_IMAGE_URL@@"
DESKTOP="@@DESKTOP@@"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[SWITCH]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}   $*"; }
error() { echo -e "${RED}[ERR]${NC}    $*"; exit 1; }

BOT_TYPE="${1:-}"
[ -z "$BOT_TYPE" ] && error "Usage: $0 <wos-py|wos-js|kingshot>"

BOT_TYPE_FILE="${BOT_DIR}/.bot_type"
CURRENT_TOKEN=""

# -- Read current token before wiping bot dir
read_current_token() {
  if [ -f "$TOKEN_FILE" ]; then
    CURRENT_TOKEN=$(cat "$TOKEN_FILE" 2>/dev/null || echo "")
  fi
  if [ -z "$CURRENT_TOKEN" ] && [ -f "${BOT_DIR}/src/.env" ]; then
    CURRENT_TOKEN=$(grep "^TOKEN=" "${BOT_DIR}/src/.env" 2>/dev/null | cut -d= -f2- || echo "")
  fi
}

stop_service() {
  info "Stopping ${SERVICE_NAME}..."
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  sleep 2
}

wipe_bot() {
  info "Removing existing bot files..."
  rm -rf "${BOT_DIR:?}/main.py" "${BOT_DIR:?}/src" "${BOT_DIR:?}/venv" \
         "${BOT_DIR:?}/__pycache__" "${BOT_DIR:?}/*.pyc" \
         "${BOT_DIR:?}/install.py" "${BOT_DIR:?}/node_modules" \
         "${BOT_DIR:?}/package.json" "${BOT_DIR:?}/package-lock.json" \
         "${BOT_DIR:?}/tsconfig.json" "${BOT_DIR:?}/dist" 2>/dev/null || true
}

install_wos_py() {
  info "Installing WOS Python bot..."
  mkdir -p "$BOT_DIR"
  cd "$BOT_DIR"
  wget -q -O main.py "$BOT_MAIN_PY"
  wget -q -O install.py "$BOT_INSTALL_PY"
  chown "${OS_USERNAME}:${OS_USERNAME}" main.py install.py
  sudo -u "$OS_USERNAME" python3 -m venv "$VENV_DIR"
  sudo -u "$OS_USERNAME" "$VENV_DIR/bin/pip" install --quiet --upgrade pip
  sudo -u "$OS_USERNAME" "$VENV_DIR/bin/python3" install.py || true
  rm -f install.py
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "$BOT_DIR"

  # Update service
  cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=WOSBot (Whiteout Survival - Python)
After=network.target
[Service]
ExecStart=${VENV_DIR}/bin/python3 ${BOT_DIR}/main.py --autoupdate
WorkingDirectory=${BOT_DIR}
Restart=always
RestartSec=5
User=${OS_USERNAME}
Environment="OMP_NUM_THREADS=1"
Environment="ONNXRUNTIME_NTHREADS=1"
[Install]
WantedBy=multi-user.target
EOF
}

install_wos_js() {
  info "Installing WOS JavaScript bot..."
  mkdir -p "$BOT_DIR"
  cd "$BOT_DIR"
  git clone --depth 1 --branch "$BOT_JS_BRANCH" "$BOT_JS_REPO" src
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "${BOT_DIR}/src"
  cd "${BOT_DIR}/src"
  sudo -u "$OS_USERNAME" npm install --silent

  # Update service
  cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=WOSBot (Whiteout Survival - JavaScript)
After=network.target
[Service]
ExecStart=/usr/bin/node ${BOT_DIR}/src/src/index.js
WorkingDirectory=${BOT_DIR}/src
Restart=always
RestartSec=5
User=${OS_USERNAME}
[Install]
WantedBy=multi-user.target
EOF
}

install_kingshot() {
  info "Installing Kingshot bot..."
  mkdir -p "$BOT_DIR"
  cd "$BOT_DIR"
  git clone --depth 1 --branch "$BOT_KINGSHOT_BRANCH" "$BOT_KINGSHOT_REPO" kingshot_src
  cp -r kingshot_src/. .
  rm -rf kingshot_src
  wget -q -O install.py "$BOT_INSTALL_PY"
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "$BOT_DIR"
  sudo -u "$OS_USERNAME" python3 -m venv "$VENV_DIR"
  sudo -u "$OS_USERNAME" "$VENV_DIR/bin/pip" install --quiet --upgrade pip
  sudo -u "$OS_USERNAME" "$VENV_DIR/bin/python3" install.py || true
  rm -f install.py
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "$BOT_DIR"

  # Update service
  cat > /etc/systemd/system/${SERVICE_NAME}.service <<EOF
[Unit]
Description=Kingshot Bot
After=network.target
[Service]
ExecStart=${VENV_DIR}/bin/python3 ${BOT_DIR}/main.py --autoupdate
WorkingDirectory=${BOT_DIR}
Restart=always
RestartSec=5
User=${OS_USERNAME}
Environment="OMP_NUM_THREADS=1"
Environment="ONNXRUNTIME_NTHREADS=1"
[Install]
WantedBy=multi-user.target
EOF
}

restore_token() {
  if [ -n "$CURRENT_TOKEN" ]; then
    info "Restoring bot token..."
    if [ "$BOT_TYPE" = "wos-js" ]; then
      mkdir -p "${BOT_DIR}/src"
      echo "TOKEN=${CURRENT_TOKEN}" > "${BOT_DIR}/src/.env"
      chmod 644 "${BOT_DIR}/src/.env"
      chown "${OS_USERNAME}:${OS_USERNAME}" "${BOT_DIR}/src/.env"
    else
      echo "$CURRENT_TOKEN" > "$TOKEN_FILE"
      chmod 644 "$TOKEN_FILE"
      chown root:root "$TOKEN_FILE"
    fi
  fi
}

start_service() {
  info "Starting ${SERVICE_NAME}..."
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME" 2>/dev/null || true
  systemctl start "$SERVICE_NAME"
  sleep 3
  STATUS=$(systemctl is-active "$SERVICE_NAME" || echo "unknown")
  if [ "$STATUS" = "active" ]; then
    info "${SERVICE_NAME} is running."
  else
    warn "${SERVICE_NAME} status: ${STATUS}"
  fi
}

# -- Main
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  WhiteoutProjectOS -- Switching to: ${BOT_TYPE}${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

read_current_token
stop_service
wipe_bot

case "$BOT_TYPE" in
  wos-py)   install_wos_py ;;
  wos-js)   install_wos_js ;;
  kingshot) install_kingshot ;;
  *) error "Unknown bot type: ${BOT_TYPE}" ;;
esac

echo "$BOT_TYPE" > "$BOT_TYPE_FILE"
chown "${OS_USERNAME}:${OS_USERNAME}" "$BOT_TYPE_FILE"

restore_token
start_service

echo ""
info "Switch to ${BOT_TYPE} complete."
echo ""
