#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS -- LXC Image Builder (CI)
# Produces a portable LXC/Incus image:
#   wp-os-x86-<version>-lxc-rootfs.tar.xz
#   wp-os-x86-<version>-lxc-metadata.tar.xz
#   wp-os-x86-<version>-lxc.sha256
#
# Run as root in a GitHub Actions ubuntu-latest runner.
# Does NOT require Proxmox -- produces a standalone image.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/config.sh"

VERSION="${VERSION:-dev}"
OUTPUT_DIR="${OUTPUT_DIR:-${SCRIPT_DIR}/output-lxc}"
ROOTFS="${SCRIPT_DIR}/build-tmp-lxc/rootfs"
META_DIR="${SCRIPT_DIR}/build-tmp-lxc/meta"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[LXC-BUILD]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

[ "$EUID" -eq 0 ] || error "Must be run as root"
command -v debootstrap &>/dev/null || error "debootstrap not found"
command -v systemd-nspawn &>/dev/null || error "systemd-nspawn not found"

cleanup() { rm -rf "${SCRIPT_DIR}/build-tmp-lxc"; }
trap cleanup EXIT

mkdir -p "$ROOTFS" "$META_DIR" "$OUTPUT_DIR"

# ------------------------------------------------------------------
# 1. Bootstrap Ubuntu base
# ------------------------------------------------------------------
info "Bootstrapping Ubuntu ${UBUNTU_SERIES} rootfs..."
debootstrap \
  --arch=amd64 \
  --include=systemd,dbus,iproute2,openssh-server,curl,sudo,ca-certificates \
  "${UBUNTU_SERIES%.*}.${UBUNTU_SERIES##*.}" \
  "$ROOTFS" \
  http://archive.ubuntu.com/ubuntu

# ------------------------------------------------------------------
# 2. Inject overlay files
# ------------------------------------------------------------------
info "Injecting rootfs overlay..."
cp -a "${SCRIPT_DIR}/rootfs-overlay/." "$ROOTFS/"

# Substitute placeholders in provision script
PROVISION_DEST="${ROOTFS}/usr/local/bin/wp-os-provision.sh"
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
  -e "s|@@BOT_VOICECHAT_REPO@@|${BOT_VOICECHAT_REPO}|g" \
  -e "s|@@BOT_VOICECHAT_BRANCH@@|${BOT_VOICECHAT_BRANCH}|g" \
  -e "s|@@DEFAULT_BOT@@|${DEFAULT_BOT}|g" \
  -e "s|@@DEFAULT_BOT_LABEL@@|${DEFAULT_BOT_LABEL}|g" \
  -e "s|@@BACKGROUND_IMAGE_URL@@|${BACKGROUND_IMAGE_URL}|g" \
  -e "s|@@DESKTOP@@|${DESKTOP}|g" \
  -e "s|@@BOTS_DIR@@|${BOTS_DIR}|g" \
  -e "s|@@WEBSERVER_DIR@@|${WEBSERVER_DIR}|g" \
  -e "s|@@WEBSERVER_PORT@@|${WEBSERVER_PORT}|g" \
  -e "s|@@REPO_BASE@@|${REPO_BASE}|g" \
  "${SCRIPT_DIR}/rootfs-overlay/usr/local/bin/wp-os-provision.sh" \
  > "$PROVISION_DEST"

chmod 0755 \
  "${ROOTFS}/usr/local/bin/wp-os-provision.sh" \
  "${ROOTFS}/usr/local/bin/wp-os-install-bot.sh" \
  "${ROOTFS}/usr/local/bin/wp-os-bot-start.sh" \
  "${ROOTFS}/usr/local/bin/wp-os-bot-manager.sh" \
  "${ROOTFS}/usr/local/bin/wp-os-update.sh"

# Inject webserver
mkdir -p "${ROOTFS}${WEBSERVER_DIR}"
cp "${SCRIPT_DIR}/webserver/app.py" "${ROOTFS}${WEBSERVER_DIR}/app.py"
chmod 0755 "${ROOTFS}${WEBSERVER_DIR}/app.py"

# ------------------------------------------------------------------
# 3. Write LXC-specific config inside rootfs
# ------------------------------------------------------------------
info "Configuring LXC environment markers..."

# Disable services that don't work in containers
mkdir -p "${ROOTFS}/etc/systemd/system"
for unit in \
  systemd-resolved.service \
  multipathd.service \
  multipathd.socket \
  udev.service \
  systemd-udevd.service; do
  ln -sf /dev/null "${ROOTFS}/etc/systemd/system/${unit}" 2>/dev/null || true
done

# Enable firstboot service if present
if [ -f "${ROOTFS}/etc/systemd/system/wp-os-firstboot.service" ]; then
  mkdir -p "${ROOTFS}/etc/systemd/system/multi-user.target.wants"
  ln -sf /etc/systemd/system/wp-os-firstboot.service \
    "${ROOTFS}/etc/systemd/system/multi-user.target.wants/wp-os-firstboot.service"
fi

# ------------------------------------------------------------------
# 4. Minimal cleanup before packaging
# ------------------------------------------------------------------
info "Cleaning up rootfs..."
rm -rf \
  "${ROOTFS}/var/cache/apt/archives"/*.deb \
  "${ROOTFS}/var/lib/apt/lists"/* \
  "${ROOTFS}/tmp"/* \
  "${ROOTFS}/var/tmp"/* \
  "${ROOTFS}/run"/* 2>/dev/null || true

# ------------------------------------------------------------------
# 5. Build metadata
# ------------------------------------------------------------------
info "Generating LXC metadata..."
CREATION_DATE=$(date +%s)

cat > "${META_DIR}/metadata.yaml" <<EOF
architecture: x86_64
creation_date: ${CREATION_DATE}
properties:
  description: WhiteoutProjectOS ${VERSION} (LXC)
  os: ubuntu
  release: "${UBUNTU_SERIES}"
  variant: wp-os
templates: {}
EOF

# ------------------------------------------------------------------
# 6. Package
# ------------------------------------------------------------------
ROOTFS_ARCHIVE="${OUTPUT_DIR}/wp-os-x86-${VERSION}-lxc-rootfs.tar.xz"
META_ARCHIVE="${OUTPUT_DIR}/wp-os-x86-${VERSION}-lxc-metadata.tar.xz"
SHA_FILE="${OUTPUT_DIR}/wp-os-x86-${VERSION}-lxc.sha256"

info "Compressing rootfs (this takes a few minutes)..."
tar -cJf "$ROOTFS_ARCHIVE" -C "$ROOTFS" --numeric-owner .

info "Compressing metadata..."
tar -cJf "$META_ARCHIVE" -C "$META_DIR" metadata.yaml

info "Generating checksums..."
(cd "$OUTPUT_DIR" && sha256sum \
  "$(basename "$ROOTFS_ARCHIVE")" \
  "$(basename "$META_ARCHIVE")" \
  > "$(basename "$SHA_FILE")")

ls -lh "$OUTPUT_DIR"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   WhiteoutProjectOS LXC image ready!                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  Import on any LXC/Incus host:"
echo -e "  ${YELLOW}lxc image import $(basename "$META_ARCHIVE") $(basename "$ROOTFS_ARCHIVE") --alias wp-os${NC}"
echo -e "  ${YELLOW}lxc launch wp-os my-wp-container${NC}"
echo ""
echo -e "  Or with Incus:"
echo -e "  ${YELLOW}incus image import $(basename "$META_ARCHIVE") $(basename "$ROOTFS_ARCHIVE") --alias wp-os${NC}"
echo ""
