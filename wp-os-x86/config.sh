#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS x86 / LXC -- Central Configuration
# Edit ONLY this file when repo links or credentials change.
# ============================================================

# -- System identity -----------------------------------------
OS_USERNAME="wp-os-user"
OS_PASSWORD="wpusr"
OS_HOSTNAME="wp-os-server"

# -- Source repository ---------------------------------------
REPO_BASE="https://raw.githubusercontent.com/ikketim/os/main"
GITHUB_REPO="ikketim/os"

# -- Bot repositories ----------------------------------------
# WOS Python bot
BOT_MAIN_PY="https://raw.githubusercontent.com/whiteout-project/bot/main/main.py"
BOT_INSTALL_PY="https://raw.githubusercontent.com/whiteout-project/install/main/install.py"

# WOS JavaScript bot
BOT_JS_REPO="https://github.com/whiteout-project/Whiteout-Survival-Discord-Bot"
BOT_JS_BRANCH="main"

# Kingshot bot
BOT_KINGSHOT_REPO="https://github.com/kingshot-project/Kingshot-Discord-Bot"
BOT_KINGSHOT_BRANCH="main"
BOT_KINGSHOT_INSTALL_PY="https://raw.githubusercontent.com/kingshot-project/Kingshot-Discord-Bot/main/install/install.py"

# WOS VoiceChat Counter bot
BOT_VOICECHAT_REPO="https://github.com/ikketimnl/wos-voicechat-counter"
BOT_VOICECHAT_BRANCH="main"

# Default bot type on first install (wos-py | wos-js | kingshot | voicechat)
DEFAULT_BOT="wos-py"

# Label for the default pre-installed bot slot
DEFAULT_BOT_LABEL="WOS Bot"

# -- Background image ----------------------------------------
BACKGROUND_IMAGE_URL="${REPO_BASE}/etc/wp-os.png"

# -- Install paths (on the target machine) -------------------
BOTS_DIR="/home/${OS_USERNAME}/bots"
WEBSERVER_DIR="/opt/wp-os-webserver"
WEBSERVER_PORT="8080"

# -- Desktop environment -------------------------------------
DESKTOP="xfce"

# -- Ubuntu base for ISO builds ------------------------------
UBUNTU_SERIES="24.04"
UBUNTU_ISO_FILE="ubuntu-server-base.iso"

resolve_ubuntu_iso_url() {
  echo "Auto-detecting latest Ubuntu ${UBUNTU_SERIES} ISO..." >&2
  local index_url="https://releases.ubuntu.com/${UBUNTU_SERIES}/"
  local iso_name
  iso_name=$(wget -qO- "$index_url" \
    | grep -oP "ubuntu-[0-9]+\.[0-9]+\.[0-9]+-live-server-amd64\.iso" \
    | grep -vE 'torrent|zsync' \
    | sort -V | tail -1)
  if [ -z "$iso_name" ]; then
    echo "ERROR: Could not detect Ubuntu ${UBUNTU_SERIES} ISO from ${index_url}" >&2
    exit 1
  fi
  echo "  -> ${iso_name}" >&2
  echo "${index_url}${iso_name}"
}

# -- LXC template --------------------------------------------
LXC_TEMPLATE="ubuntu-24.04-standard"
