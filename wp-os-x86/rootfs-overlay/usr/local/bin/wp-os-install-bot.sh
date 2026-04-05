#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS -- On-Demand Bot Installer
# Usage: wp-os-install-bot.sh <slot-id> <bot-type>
# Bot types: wos-py | wos-js | kingshot | voicechat
# Called by the web panel and provisioning script.
# Sources /etc/wp-os/config.env -- no build-time placeholders needed.
# ============================================================
set -euo pipefail

source /etc/wp-os/config.env

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INSTALL]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}    $*"; }
error() { echo -e "${RED}[ERR]${NC}     $*"; exit 1; }

SLOT_ID="${1:-}"
BOT_TYPE="${2:-}"
[ -z "$SLOT_ID" ]  && error "Usage: $0 <slot-id> <bot-type>"
[ -z "$BOT_TYPE" ] && error "Usage: $0 <slot-id> <bot-type>"

SLOT_DIR="${BOTS_DIR}/${SLOT_ID}"
APP_DIR="${SLOT_DIR}/app"
mkdir -p "$APP_DIR"

install_wos_py() {
  info "Installing WOS Python bot into ${SLOT_DIR}/app ..."
  cd "$APP_DIR"
  wget -q -O main.py    "$BOT_MAIN_PY"    || error "Failed to download main.py"
  wget -q -O install.py "$BOT_INSTALL_PY" || error "Failed to download install.py"
  chown "${OS_USERNAME}:${OS_USERNAME}" main.py install.py
  sudo -u "$OS_USERNAME" python3 -m venv "${APP_DIR}/venv"
  sudo -u "$OS_USERNAME" "${APP_DIR}/venv/bin/pip" install --quiet --upgrade pip
  if ! sudo -u "$OS_USERNAME" "${APP_DIR}/venv/bin/python3" install.py; then
    warn "Dependency installation had errors -- bot may not function correctly"
  fi
  rm -f install.py
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "$APP_DIR"
}

install_wos_js() {
  info "Installing WOS JavaScript bot into ${SLOT_DIR}/app ..."
  cd "$APP_DIR"
  git clone --depth 1 --branch "$BOT_JS_BRANCH" "$BOT_JS_REPO" src \
    || error "Failed to clone ${BOT_JS_REPO}"
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "${APP_DIR}/src"
  cd "${APP_DIR}/src"
  sudo -u "$OS_USERNAME" npm install --silent || error "npm install failed"
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "$APP_DIR"
}

install_kingshot() {
  info "Installing Kingshot bot into ${SLOT_DIR}/app ..."
  cd "$APP_DIR"
  git clone --depth 1 --branch "$BOT_KINGSHOT_BRANCH" "$BOT_KINGSHOT_REPO" . \
    || error "Failed to clone ${BOT_KINGSHOT_REPO}"
  wget -q -O install.py "$BOT_KINGSHOT_INSTALL_PY" \
    || error "Failed to download Kingshot install.py"
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "$APP_DIR"
  sudo -u "$OS_USERNAME" python3 -m venv "${APP_DIR}/venv"
  sudo -u "$OS_USERNAME" "${APP_DIR}/venv/bin/pip" install --quiet --upgrade pip
  if ! sudo -u "$OS_USERNAME" "${APP_DIR}/venv/bin/python3" install.py; then
    warn "Dependency installation had errors -- bot may not function correctly"
  fi
  rm -f install.py
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "$APP_DIR"
}

install_voicechat() {
  info "Installing WOS VoiceChat Counter into ${SLOT_DIR}/app ..."
  cd "$APP_DIR"
  git clone --depth 1 --branch "$BOT_VOICECHAT_BRANCH" "$BOT_VOICECHAT_REPO" . \
    || error "Failed to clone ${BOT_VOICECHAT_REPO}"
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "$APP_DIR"
  sudo -u "$OS_USERNAME" npm install --silent || error "npm install failed"
  chown -R "${OS_USERNAME}:${OS_USERNAME}" "$APP_DIR"
}

case "$BOT_TYPE" in
  wos-py)    install_wos_py ;;
  wos-js)    install_wos_js ;;
  kingshot)  install_kingshot ;;
  voicechat) install_voicechat ;;
  *) error "Unknown bot type: ${BOT_TYPE}" ;;
esac

# Mark as installed in meta.json
META="${SLOT_DIR}/.meta.json"
if [ -f "$META" ]; then
  if command -v jq &>/dev/null; then
    TMP=$(mktemp)
    jq '.installed = true' "$META" > "$TMP" && mv "$TMP" "$META"
    chmod 644 "$META"; chown root:root "$META"
  else
    warn "jq not found -- cannot update .meta.json installed flag"
  fi
fi

systemctl daemon-reload 2>/dev/null || true
systemctl enable "wp-os-bot@${SLOT_ID}" 2>/dev/null || true

info "Slot ${SLOT_ID} (${BOT_TYPE}) installed successfully."
