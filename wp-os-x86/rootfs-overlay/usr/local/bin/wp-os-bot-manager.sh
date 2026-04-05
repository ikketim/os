#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS -- Bot Manager (CLI)
# Token operations and slot lifecycle for SSH users.
#
# Usage:
#   wp-os-bot-manager.sh list
#   wp-os-bot-manager.sh token-set     <slot-id> <token>
#   wp-os-bot-manager.sh token-clear   <slot-id>
#   wp-os-bot-manager.sh token-migrate <src-slot> <dst-slot>
#   wp-os-bot-manager.sh slot-create   <slot-id> <type> <label>
#   wp-os-bot-manager.sh slot-remove   <slot-id>
#   wp-os-bot-manager.sh slot-label    <slot-id> <new-label>
# ============================================================
set -euo pipefail

source /etc/wp-os/config.env

REGISTRY="${BOTS_DIR}/.registry.json"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

sha256t() { printf '%s' "$1" | sha256sum | cut -d' ' -f1; }

registry_find() {
  [ -f "$REGISTRY" ] \
    && jq -r --arg h "$1" '.tokens[$h] // empty' "$REGISTRY" 2>/dev/null \
    || true
}
registry_set() {
  local tmp; tmp=$(mktemp)
  jq --arg h "$1" --arg s "$2" '.tokens[$h]=$s' "$REGISTRY" > "$tmp"
  mv "$tmp" "$REGISTRY"; chmod 600 "$REGISTRY"; chown root:root "$REGISTRY"
}
registry_del() {
  local tmp; tmp=$(mktemp)
  jq --arg h "$1" 'del(.tokens[$h])' "$REGISTRY" > "$tmp"
  mv "$tmp" "$REGISTRY"; chmod 600 "$REGISTRY"; chown root:root "$REGISTRY"
}

token_read()  { cat "${BOTS_DIR}/${1}/token.txt" 2>/dev/null || true; }
token_write() {
  local f="${BOTS_DIR}/${1}/token.txt"
  printf '%s' "$2" > "$f"; chmod 600 "$f"
  chown "${OS_USERNAME}:${OS_USERNAME}" "$f"
}
token_zero() {
  local f="${BOTS_DIR}/${1}/token.txt"
  > "$f"; chmod 600 "$f"; chown "${OS_USERNAME}:${OS_USERNAME}" "$f"
}

cmd_list() {
  printf '%-16s %-10s %-8s %-12s %s\n' SLOT TYPE STATUS TOKEN LABEL
  printf '%-16s %-10s %-8s %-12s %s\n' ---- ---- ------ ----- -----
  for d in "${BOTS_DIR}"/*/; do
    [ -f "${d}.meta.json" ] || continue
    local sid; sid=$(basename "$d")
    local type; type=$(jq -r '.type'  "${d}.meta.json" 2>/dev/null || echo '?')
    local lbl;  lbl=$(jq  -r '.label' "${d}.meta.json" 2>/dev/null || echo "$sid")
    local st;   st=$(systemctl is-active "wp-os-bot@${sid}" 2>/dev/null || echo inactive)
    local tok="[none]"
    local t; t=$(token_read "$sid")
    [ -n "$t" ] && tok="[....${t: -4}]"
    printf '%-16s %-10s %-8s %-12s %s\n' "$sid" "$type" "$st" "$tok" "$lbl"
  done
}

cmd_token_set() {
  local sid="$1" tok="$2"
  [ -d "${BOTS_DIR}/${sid}" ] || error "Slot not found: ${sid}"
  [ -z "$tok" ] && error "Token cannot be empty"
  local h; h=$(sha256t "$tok")
  local ex; ex=$(registry_find "$h")
  [ -n "$ex" ] && [ "$ex" != "$sid" ] && error "Token already in use by slot: ${ex}"
  local old; old=$(token_read "$sid")
  [ -n "$old" ] && registry_del "$(sha256t "$old")"
  token_write "$sid" "$tok"
  registry_set "$h" "$sid"
  systemctl restart "wp-os-bot@${sid}" 2>/dev/null || true
  ok "Token set for ${sid} — service restarted"
}

cmd_token_clear() {
  local sid="$1"
  [ -d "${BOTS_DIR}/${sid}" ] || error "Slot not found: ${sid}"
  local old; old=$(token_read "$sid")
  [ -n "$old" ] && registry_del "$(sha256t "$old")"
  token_zero "$sid"
  systemctl stop "wp-os-bot@${sid}" 2>/dev/null || true
  ok "Token cleared for ${sid} — service stopped"
}

cmd_token_migrate() {
  local src="$1" dst="$2"
  local tok; tok=$(token_read "$src")
  [ -z "$tok" ] && error "No token on source slot ${src}"
  [ -d "${BOTS_DIR}/${dst}" ] || error "Destination slot not found: ${dst}"
  local h; h=$(sha256t "$tok")
  local ex; ex=$(registry_find "$h")
  [ -n "$ex" ] && [ "$ex" != "$src" ] && error "Token already in use by: ${ex}"
  local dst_old; dst_old=$(token_read "$dst")
  [ -n "$dst_old" ] && registry_del "$(sha256t "$dst_old")"
  token_write "$dst" "$tok"
  registry_set "$h" "$dst"
  token_zero "$src"
  systemctl stop    "wp-os-bot@${src}" 2>/dev/null || true
  systemctl restart "wp-os-bot@${dst}" 2>/dev/null || true
  ok "Token migrated from ${src} to ${dst}"
}

cmd_slot_create() {
  local sid="$1" type="$2" label="$3"
  [ -d "${BOTS_DIR}/${sid}" ] && error "Slot already exists: ${sid}"
  mkdir -p "${BOTS_DIR}/${sid}/app"
  local now; now=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  printf '{"type":"%s","label":"%s","created":"%s","installed":false}\n' \
    "$type" "$label" "$now" > "${BOTS_DIR}/${sid}/.meta.json"
  chmod 644 "${BOTS_DIR}/${sid}/.meta.json"
  chown root:root "${BOTS_DIR}/${sid}/.meta.json"
  touch "${BOTS_DIR}/${sid}/token.txt"
  chmod 600 "${BOTS_DIR}/${sid}/token.txt"
  chown "${OS_USERNAME}:${OS_USERNAME}" \
    "${BOTS_DIR}/${sid}/token.txt" \
    "${BOTS_DIR}/${sid}" \
    "${BOTS_DIR}/${sid}/app"
  systemctl daemon-reload 2>/dev/null || true
  systemctl enable "wp-os-bot@${sid}" 2>/dev/null || true
  ok "Slot ${sid} created (type: ${type}, label: ${label})"
}

cmd_slot_remove() {
  local sid="$1"
  [ -d "${BOTS_DIR}/${sid}" ] || error "Slot not found: ${sid}"
  local old; old=$(token_read "$sid")
  [ -n "$old" ] && registry_del "$(sha256t "$old")"
  systemctl stop    "wp-os-bot@${sid}" 2>/dev/null || true
  systemctl disable "wp-os-bot@${sid}" 2>/dev/null || true
  rm -rf "${BOTS_DIR:?}/${sid}"
  ok "Slot ${sid} removed"
}

cmd_slot_label() {
  local sid="$1" lbl="$2"
  local m="${BOTS_DIR}/${sid}/.meta.json"
  [ -f "$m" ] || error "Slot not found: ${sid}"
  local tmp; tmp=$(mktemp)
  jq --arg l "$lbl" '.label=$l' "$m" > "$tmp" && mv "$tmp" "$m"
  chmod 644 "$m"; chown root:root "$m"
  ok "Label updated to '${lbl}'"
}

CMD="${1:-}"; shift || true
case "$CMD" in
  list)           cmd_list ;;
  token-set)      cmd_token_set "$@" ;;
  token-clear)    cmd_token_clear "$@" ;;
  token-migrate)  cmd_token_migrate "$@" ;;
  slot-create)    cmd_slot_create "$@" ;;
  slot-remove)    cmd_slot_remove "$@" ;;
  slot-label)     cmd_slot_label "$@" ;;
  *)
    echo "Usage: $0 {list|token-set|token-clear|token-migrate|slot-create|slot-remove|slot-label}"
    exit 1 ;;
esac
