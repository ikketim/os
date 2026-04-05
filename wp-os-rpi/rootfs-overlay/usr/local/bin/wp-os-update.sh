#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS -- System Updater
# Downloads the latest versions of OS scripts and the web
# control panel from the source repository.
# Sources /etc/wp-os/config.env -- no build-time placeholders.
#
# Usage (on the device, as root):
#   sudo wp-os-update.sh
# ============================================================
set -euo pipefail

source /etc/wp-os/config.env

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[UPDATE]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}   $*"; }
error() { echo -e "${RED}[ERR]${NC}    $*"; exit 1; }

[ "$EUID" -eq 0 ] || error "Run as root: sudo wp-os-update.sh"
[ -z "${REPO_BASE:-}"    ] && error "REPO_BASE not set in /etc/wp-os/config.env"
[ -z "${OS_PLATFORM:-}"  ] && error "OS_PLATFORM not set in /etc/wp-os/config.env"
[ -z "${WEBSERVER_DIR:-}"] && error "WEBSERVER_DIR not set in /etc/wp-os/config.env"

case "$OS_PLATFORM" in
  rpi|x86) ;;
  *) error "OS_PLATFORM must be 'rpi' or 'x86', got: ${OS_PLATFORM}" ;;
esac

SCRIPTS_URL="${REPO_BASE}/wp-os-${OS_PLATFORM}/rootfs-overlay/usr/local/bin"
# app.py is shared between rpi and x86 -- always fetch from wp-os-x86
WEBSERVER_URL="${REPO_BASE}/wp-os-x86/webserver"

echo "========================================"
echo " WhiteoutProjectOS System Update"
echo " $(date)"
echo "========================================"
echo " Source  : ${REPO_BASE}"
echo " Platform: ${OS_PLATFORM}"
echo "========================================"

UPDATED=0
FAILED=0

update_file() {
  local dst="$1" url="$2" mode="$3"
  info "Updating $(basename "$dst")..."
  local tmp; tmp=$(mktemp "${dst}.XXXXXX")
  if wget -q --timeout=30 -O "$tmp" "$url" 2>/dev/null && [ -s "$tmp" ]; then
    chmod "$mode" "$tmp"
    mv "$tmp" "$dst"
    UPDATED=$((UPDATED + 1))
    info "  OK: ${dst}"
  else
    rm -f "$tmp"
    warn "  FAILED: ${dst} (download error or empty response from ${url})"
    FAILED=$((FAILED + 1))
  fi
}

# Update helper scripts
update_file /usr/local/bin/wp-os-bot-manager.sh \
  "${SCRIPTS_URL}/wp-os-bot-manager.sh" 755
update_file /usr/local/bin/wp-os-bot-start.sh \
  "${SCRIPTS_URL}/wp-os-bot-start.sh" 755
update_file /usr/local/bin/wp-os-install-bot.sh \
  "${SCRIPTS_URL}/wp-os-install-bot.sh" 755

# Update web control panel
update_file "${WEBSERVER_DIR}/app.py" \
  "${WEBSERVER_URL}/app.py" 644

# Update self last so any earlier failure doesn't break future runs
update_file /usr/local/bin/wp-os-update.sh \
  "${SCRIPTS_URL}/wp-os-update.sh" 755

# Restart web panel to pick up new app.py
info "Restarting web control panel..."
if systemctl restart wp-os-web 2>/dev/null; then
  info "  OK"
else
  warn "  Could not restart wp-os-web -- restart manually if needed"
fi

echo "========================================"
echo " Update complete: ${UPDATED} updated, ${FAILED} failed"
echo "========================================"
[ "$FAILED" -gt 0 ] && exit 1 || exit 0
