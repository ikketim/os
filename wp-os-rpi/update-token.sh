#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS -- Update Bot Token Helper
# Lists available slots and sets a token via the bot manager.
#
# Usage (on the Pi, as root):
#   sudo ./update-token.sh
#   sudo ./update-token.sh <slot-id> <token>
# ============================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

[ "$EUID" -eq 0 ] || { echo -e "${RED}Run as root: sudo $0${NC}"; exit 1; }

MANAGER="/usr/local/bin/wp-os-bot-manager.sh"
[ -x "$MANAGER" ] || { echo -e "${RED}Bot manager not found: ${MANAGER}${NC}"; exit 1; }

# Non-interactive mode
if [ -n "${1:-}" ] && [ -n "${2:-}" ]; then
  "$MANAGER" token-set "$1" "$2"
  exit $?
fi

# Interactive mode
echo -e "${GREEN}WhiteoutProjectOS -- Bot Token Updater${NC}"
echo ""
echo "Available slots:"
"$MANAGER" list
echo ""

echo -n "Enter slot ID (e.g. wos-1, kingshot-1): "
read -r SLOT_ID

if [ -z "$SLOT_ID" ]; then
  echo -e "${RED}Error: slot ID cannot be empty.${NC}"
  exit 1
fi

echo -n "Enter bot token: "
read -r TOKEN

if [ -z "$TOKEN" ]; then
  echo -e "${RED}Error: token cannot be empty.${NC}"
  exit 1
fi

"$MANAGER" token-set "$SLOT_ID" "$TOKEN"
