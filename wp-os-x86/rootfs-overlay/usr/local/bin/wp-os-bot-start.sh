#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS -- Bot Slot Entry Point
# Invoked by systemd: ExecStart=/usr/local/bin/wp-os-bot-start.sh %i
# ============================================================
source /etc/wp-os/config.env 2>/dev/null || true

SLOT_ID="${1:-}"
[ -z "$SLOT_ID" ] && { echo "ERROR: slot-id required" >&2; exit 1; }
[[ "$SLOT_ID" =~ ^[a-zA-Z0-9_-]+$ ]] || { echo "ERROR: invalid slot-id: ${SLOT_ID}" >&2; exit 1; }

SLOT_DIR="${BOTS_DIR}/${SLOT_ID}"
META="${SLOT_DIR}/.meta.json"
TOKEN_FILE="${SLOT_DIR}/token.txt"
APP_DIR="${SLOT_DIR}/app"
FLAGS_FILE="${SLOT_DIR}/.startup_flags"

[ -f "$META" ]    || { echo "ERROR: meta not found: ${META}" >&2; exit 1; }
[ -d "$APP_DIR" ] || { echo "ERROR: app dir not found: ${APP_DIR}" >&2; exit 1; }

BOT_TYPE=$(jq -r '.type'  "$META" 2>/dev/null \
  || grep -o '"type":"[^"]*"' "$META" | head -1 | cut -d'"' -f4)
[ -z "$BOT_TYPE" ] && { echo "ERROR: could not determine bot type from ${META}" >&2; exit 1; }
LABEL=$(jq    -r '.label' "$META" 2>/dev/null || echo "$SLOT_ID")
TOKEN=$(cat "$TOKEN_FILE" 2>/dev/null || true)

# --- Read dynamic flags from UI ---
BOT_FLAGS="--autoupdate"
if [ -f "$FLAGS_FILE" ]; then
  UI_FLAGS=$(cat "$FLAGS_FILE" | tr -d '\n' | xargs)
  if [ -n "$UI_FLAGS" ]; then
    BOT_FLAGS="$UI_FLAGS"
  fi
fi

# --- ONE-TIME FLAG RESET LOGIC ---
if [[ "$BOT_FLAGS" == *"--repair"* ]]; then
  echo "--autoupdate" > "$FLAGS_FILE"
fi

[ -z "$TOKEN" ] && echo "[wp-os] WARNING: no token set for '${LABEL}' (${SLOT_ID})" >&2
echo "[wp-os] Starting slot '${LABEL}' type=${BOT_TYPE} flags=[${BOT_FLAGS}]" >&2

case "$BOT_TYPE" in
  wos-py)
    cd "$APP_DIR"
    printf '%s\n' "$TOKEN" > "${APP_DIR}/bot_token.txt"
    chmod 600 "${APP_DIR}/bot_token.txt"
    exec "${APP_DIR}/venv/bin/python3" "${APP_DIR}/main.py" $BOT_FLAGS
    ;;
  wos-js)
    [ -d "${APP_DIR}/src" ] || { echo "ERROR: wos-js not installed" >&2; exit 1; }
    cd "${APP_DIR}/src"
    exec env TOKEN="$TOKEN" npm start
    ;;
  kingshot)
    cd "$APP_DIR"
    printf '%s\n' "$TOKEN" > "${APP_DIR}/bot_token.txt"
    chmod 600 "${APP_DIR}/bot_token.txt"
    exec "${APP_DIR}/venv/bin/python3" "${APP_DIR}/main.py" $BOT_FLAGS
    ;;
  voicechat)
    cd "$APP_DIR"
    EXTRA="${SLOT_DIR}/.config.json"
    CLIENT_ID=""
    GUILD_ID=""
    if [ -f "$EXTRA" ]; then
      CLIENT_ID=$(jq -r '.client_id // empty' "$EXTRA" 2>/dev/null || true)
      GUILD_ID=$(jq  -r '.guild_id  // empty' "$EXTRA" 2>/dev/null || true)
    fi
    jq -n --arg token "$TOKEN" --arg clientId "$CLIENT_ID" --arg guildId "$GUILD_ID" \
      '{"token":$token,"clientId":$clientId,"guildId":$guildId}' > "${APP_DIR}/config/config.json"
    chmod 600 "${APP_DIR}/config/config.json"
    exec npm start
    ;;
  *)
    echo "ERROR: unknown bot type '${BOT_TYPE}'" >&2
    exit 1
    ;;
esac
