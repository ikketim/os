#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS Raspberry Pi -- Image Builder
# Run on a Linux machine (not on the Pi itself) as root.
#
# Requirements:
#   sudo apt install wget xz-utils
#
# Usage:
#   sudo ./build.sh           -- build with current config.sh
#   sudo ./build.sh --clean   -- remove cached base image first
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

WORK_DIR="${SCRIPT_DIR}/build-tmp"
OUTPUT_DIR="${SCRIPT_DIR}/output"
BASE_IMG="${WORK_DIR}/${UBUNTU_IMAGE_FILE}"
FINAL_IMG="${OUTPUT_DIR}/wp-os-rpi-$(date +%Y%m%d).img"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[RPI]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

LOOP_DEV=""
MOUNT_DIR="${WORK_DIR}/mnt"

cleanup() {
  sync 2>/dev/null || true
  if mountpoint -q "${MOUNT_DIR}/proc" 2>/dev/null; then
    umount -R "${MOUNT_DIR}" 2>/dev/null || true
  fi
  if [ -n "$LOOP_DEV" ] && losetup "$LOOP_DEV" &>/dev/null; then
    losetup -d "$LOOP_DEV" 2>/dev/null || true
  fi
}
trap cleanup EXIT

check_deps() {
  info "Checking dependencies..."
  [ "$EUID" -eq 0 ] || error "Run as root: sudo ./build.sh"
  for cmd in wget losetup mount; do
    command -v "$cmd" &>/dev/null || error "Missing: $cmd"
  done
}

download_image() {
  mkdir -p "$WORK_DIR" "$OUTPUT_DIR"
  if [ "${1:-}" = "--clean" ] && [ -f "$BASE_IMG" ]; then
    info "Removing cached image..."
    rm -f "$BASE_IMG"
  fi
  if [ ! -f "$BASE_IMG" ]; then
    UBUNTU_IMG_URL=$(resolve_ubuntu_image_url)
    info "Downloading ${UBUNTU_IMG_URL##*/}..."
    wget --show-progress -O "${BASE_IMG}.xz" "$UBUNTU_IMG_URL"
    info "Decompressing..."
    xz -d "${BASE_IMG}.xz"
  else
    info "Using cached base image."
  fi
}

mount_image() {
  info "Mounting image..."
  mkdir -p "$MOUNT_DIR"
  LOOP_DEV=$(losetup -fP --show "$BASE_IMG")
  info "Loop device: ${LOOP_DEV}"

  # Identify root partition (usually p2 for Ubuntu Pi)
  ROOT_PART=""
  for part in "${LOOP_DEV}p2" "${LOOP_DEV}p1"; do
    if [ -b "$part" ]; then
      ROOT_PART="$part"
      break
    fi
  done
  [ -n "$ROOT_PART" ] || error "Could not find root partition on ${LOOP_DEV}"

  mount "$ROOT_PART" "$MOUNT_DIR"

  # Mount boot partition if separate
  if [ -b "${LOOP_DEV}p1" ] && [ "$ROOT_PART" != "${LOOP_DEV}p1" ]; then
    mkdir -p "${MOUNT_DIR}/boot/firmware"
    mount "${LOOP_DEV}p1" "${MOUNT_DIR}/boot/firmware" 2>/dev/null || true
  fi

  # Bind mounts for chroot
  mount --bind /proc "${MOUNT_DIR}/proc"
  mount --bind /sys  "${MOUNT_DIR}/sys"
  mount --bind /dev  "${MOUNT_DIR}/dev"
  mount --bind /dev/pts "${MOUNT_DIR}/dev/pts"

  info "Image mounted at ${MOUNT_DIR}"
}

inject_files() {
  info "Injecting WhiteoutProjectOS files..."

  # Substitute and copy firstboot script
  FB_TMP=$(mktemp)
  sed \
    -e "s|@@OS_USERNAME@@|${OS_USERNAME}|g" \
    -e "s|@@OS_PASSWORD@@|${OS_PASSWORD}|g" \
    -e "s|@@OS_HOSTNAME@@|${OS_HOSTNAME}|g" \
    -e "s|@@BOT_MAIN_PY@@|${BOT_MAIN_PY}|g" \
    -e "s|@@BOT_INSTALL_PY@@|${BOT_INSTALL_PY}|g" \
    -e "s|@@BOT_JS_REPO@@|${BOT_JS_REPO}|g" \
    -e "s|@@BOT_JS_BRANCH@@|${BOT_JS_BRANCH}|g" \
    -e "s|@@BOT_KINGSHOT_REPO@@|${BOT_KINGSHOT_REPO}|g" \
    -e "s|@@BOT_KINGSHOT_BRANCH@@|${BOT_KINGSHOT_BRANCH}|g" \
    -e "s|@@BOT_KINGSHOT_INSTALL_PY@@|${BOT_KINGSHOT_INSTALL_PY}|g" \
    -e "s|@@DEFAULT_BOT@@|${DEFAULT_BOT}|g" \
    -e "s|@@BACKGROUND_IMAGE_URL@@|${BACKGROUND_IMAGE_URL}|g" \
    -e "s|@@DESKTOP@@|${DESKTOP}|g" \
    -e "s|@@BOT_DIR@@|${BOT_DIR}|g" \
    -e "s|@@VENV_DIR@@|${VENV_DIR}|g" \
    -e "s|@@SERVICE_NAME@@|${SERVICE_NAME}|g" \
    -e "s|@@SERVICE_FILE@@|${SERVICE_FILE}|g" \
    -e "s|@@TOKEN_FILE@@|${TOKEN_FILE}|g" \
    -e "s|@@WEBSERVER_DIR@@|${WEBSERVER_DIR}|g" \
    -e "s|@@WEBSERVER_PORT@@|${WEBSERVER_PORT}|g" \
    "${SCRIPT_DIR}/rootfs-overlay/usr/local/bin/wp-os-firstboot.sh" \
    > "$FB_TMP"
  install -m 0755 "$FB_TMP" "${MOUNT_DIR}/usr/local/bin/wp-os-firstboot.sh"
  rm -f "$FB_TMP"

  # Copy switch-bot script (placeholders substituted at first boot by wp-os-firstboot.sh)
  install -m 0755 \
    "${SCRIPT_DIR}/rootfs-overlay/usr/local/bin/wp-os-switch-bot.sh" \
    "${MOUNT_DIR}/usr/local/bin/wp-os-switch-bot.sh"

  # Copy webserver
  mkdir -p "${MOUNT_DIR}${WEBSERVER_DIR}"
  install -m 0755 \
    "${SCRIPT_DIR}/../wp-os-x86/webserver/app.py" \
    "${MOUNT_DIR}${WEBSERVER_DIR}/app.py"

  # Install firstboot service
  cat > "${MOUNT_DIR}/etc/systemd/system/wp-os-firstboot.service" <<'EOF'
[Unit]
Description=WhiteoutProjectOS First Boot Provisioning
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/wp-os-firstboot.sh
RemainAfterExit=yes
StandardOutput=journal+console
StandardError=journal+console

[Install]
WantedBy=multi-user.target
EOF

  # Enable firstboot service
  chroot "$MOUNT_DIR" systemctl enable wp-os-firstboot.service 2>/dev/null || true

  info "Files injected."
}

compress_image() {
  info "Compressing final image..."
  cp "$BASE_IMG" "$FINAL_IMG"
  xz -T0 -z "${FINAL_IMG}"
  FINAL_IMG="${FINAL_IMG}.xz"

  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║  WhiteoutProjectOS RPi image built successfully!             ║${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  Image : ${YELLOW}${FINAL_IMG}${NC}  ($(du -sh "$FINAL_IMG" | cut -f1))"
  echo -e "  Flash : Use Raspberry Pi Imager or:"
  echo -e "          ${YELLOW}xz -dc ${FINAL_IMG} | sudo dd of=/dev/sdX bs=4M status=progress${NC}"
  echo ""
}

main() {
  echo ""
  echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
  echo -e "${GREEN}║     WhiteoutProjectOS Raspberry Pi Image Builder             ║${NC}"
  echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
  echo ""
  check_deps
  download_image "${1:-}"
  mount_image
  inject_files
  compress_image
}

main "$@"
