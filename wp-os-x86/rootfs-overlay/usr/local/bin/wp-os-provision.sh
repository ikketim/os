#!/usr/bin/env bash
# ============================================================
# WhiteoutProjectOS x86/LXC -- Provisioning Script
# Placeholders (@@VAR@@) are substituted by build-lxc.sh / build-iso.sh
# ============================================================
set -euo pipefail

LOG="/var/log/wp-os-setup.log"
exec > >(tee -a "$LOG") 2>&1

echo "========================================="
echo " WhiteoutProjectOS Provisioning Starting"
echo " $(date)"
echo "========================================="

OS_USERNAME="@@OS_USERNAME@@"
OS_PASSWORD="@@OS_PASSWORD@@"
OS_HOSTNAME="@@OS_HOSTNAME@@"
REPO_BASE="@@REPO_BASE@@"
GITHUB_REPO="@@GITHUB_REPO@@"
BOT_MAIN_PY="@@BOT_MAIN_PY@@"
BOT_INSTALL_PY="@@BOT_INSTALL_PY@@"
BOT_JS_REPO="@@BOT_JS_REPO@@"
BOT_JS_BRANCH="@@BOT_JS_BRANCH@@"
BOT_KINGSHOT_REPO="@@BOT_KINGSHOT_REPO@@"
BOT_KINGSHOT_BRANCH="@@BOT_KINGSHOT_BRANCH@@"
BOT_KINGSHOT_INSTALL_PY="@@BOT_KINGSHOT_INSTALL_PY@@"
BOT_VOICECHAT_REPO="@@BOT_VOICECHAT_REPO@@"
BOT_VOICECHAT_BRANCH="@@BOT_VOICECHAT_BRANCH@@"
BACKGROUND_IMAGE_URL="@@BACKGROUND_IMAGE_URL@@"
DESKTOP="@@DESKTOP@@"
BOTS_DIR="@@BOTS_DIR@@"
DEFAULT_BOT="@@DEFAULT_BOT@@"
DEFAULT_BOT_LABEL="@@DEFAULT_BOT_LABEL@@"
WEBSERVER_DIR="@@WEBSERVER_DIR@@"
WEBSERVER_PORT="@@WEBSERVER_PORT@@"

IS_LXC=0
if grep -q "container=lxc" /proc/1/environ 2>/dev/null || \
   systemd-detect-virt --container &>/dev/null 2>&1; then
  IS_LXC=1; echo "[INFO] Running inside LXC container"
fi

export DEBIAN_FRONTEND=noninteractive

# -- Connectivity check
echo "[NET] Checking internet connectivity..."
if ! curl --silent --max-time 15 --output /dev/null https://deb.nodesource.com/ 2>/dev/null; then
  echo "[WARN] Cannot reach deb.nodesource.com -- internet may be unavailable."
  echo "[WARN] Node.js and package downloads may fail. Ensure the machine has internet access."
fi

# -- 1. Hostname
echo "[1/9] Setting hostname..."
hostnamectl set-hostname "$OS_HOSTNAME" 2>/dev/null || echo "$OS_HOSTNAME" > /etc/hostname
sed -i "s/127.0.1.1.*/127.0.1.1\t${OS_HOSTNAME}/" /etc/hosts 2>/dev/null || \
  echo "127.0.1.1\t${OS_HOSTNAME}" >> /etc/hosts

# -- 2. User
echo "[2/9] Creating user ${OS_USERNAME}..."
if ! id "$OS_USERNAME" &>/dev/null; then
  useradd -m -s /bin/bash -G sudo,adm "$OS_USERNAME"
fi
echo "${OS_USERNAME}:${OS_PASSWORD}" | chpasswd
echo "${OS_USERNAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${OS_USERNAME}"
chmod 440 "/etc/sudoers.d/${OS_USERNAME}"

# -- 3. System update
echo "[3/9] Updating system..."
apt-get update -qq
apt-get upgrade -y -qq --no-install-recommends

# -- 4. Core packages
echo "[4/9] Installing core packages..."
apt-get install -y -qq --no-install-recommends \
  python3 python3-full python3-venv python3-pip \
  wget curl git ca-certificates gnupg \
  build-essential python3-dev \
  openssh-server python3-flask \
  feh jq net-tools unzip

# -- 5. Node.js 22
echo "[5/9] Installing Node.js 22..."
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
  | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
  > /etc/apt/sources.list.d/nodesource.list
apt-get update -qq
apt-get install -y -qq nodejs

# -- 6. Runtime config + bots directory
echo "[6/9] Writing runtime config and bot directory structure..."
mkdir -p /etc/wp-os
cat > /etc/wp-os/config.env <<EOF
OS_USERNAME=${OS_USERNAME}
BOTS_DIR=${BOTS_DIR}
BOT_MAIN_PY=${BOT_MAIN_PY}
BOT_INSTALL_PY=${BOT_INSTALL_PY}
BOT_JS_REPO=${BOT_JS_REPO}
BOT_JS_BRANCH=${BOT_JS_BRANCH}
BOT_KINGSHOT_REPO=${BOT_KINGSHOT_REPO}
BOT_KINGSHOT_BRANCH=${BOT_KINGSHOT_BRANCH}
BOT_KINGSHOT_INSTALL_PY=${BOT_KINGSHOT_INSTALL_PY}
BOT_VOICECHAT_REPO=${BOT_VOICECHAT_REPO}
BOT_VOICECHAT_BRANCH=${BOT_VOICECHAT_BRANCH}
WEBSERVER_DIR=${WEBSERVER_DIR}
WEBSERVER_PORT=${WEBSERVER_PORT}
REPO_BASE=${REPO_BASE}
GITHUB_REPO=${GITHUB_REPO}
OS_PLATFORM=x86
EOF
chmod 644 /etc/wp-os/config.env

mkdir -p "${BOTS_DIR}"
echo '{"tokens":{}}' > "${BOTS_DIR}/.registry.json"
echo '{"tokens":[]}' > "${BOTS_DIR}/.vault.json"
chmod 600 "${BOTS_DIR}/.registry.json" "${BOTS_DIR}/.vault.json"
chown -R "${OS_USERNAME}:${OS_USERNAME}" "${BOTS_DIR}"
chown root:root "${BOTS_DIR}/.registry.json" "${BOTS_DIR}/.vault.json"

# Determine default slot ID
case "$DEFAULT_BOT" in
  wos-py|wos-js) DEFAULT_SLOT_ID="wos-1" ;;
  kingshot)       DEFAULT_SLOT_ID="kingshot-1" ;;
  voicechat)      DEFAULT_SLOT_ID="vc-1" ;;
  *)              DEFAULT_SLOT_ID="wos-1" ;;
esac

SLOT_DIR="${BOTS_DIR}/${DEFAULT_SLOT_ID}"
mkdir -p "${SLOT_DIR}/app"
NOW=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
jq -n --arg type "${DEFAULT_BOT}" --arg label "${DEFAULT_BOT_LABEL}" --arg created "${NOW}" \
  '{"type":$type,"label":$label,"created":$created,"installed":false}' > "${SLOT_DIR}/.meta.json"
touch "${SLOT_DIR}/token.txt"
chmod 644 "${SLOT_DIR}/.meta.json"
chmod 600 "${SLOT_DIR}/token.txt"
chown root:root "${SLOT_DIR}/.meta.json"
chown "${OS_USERNAME}:${OS_USERNAME}" \
  "${SLOT_DIR}/token.txt" "${SLOT_DIR}" "${SLOT_DIR}/app"

# -- 7. Install default bot
echo "[7/9] Installing default bot (${DEFAULT_BOT}) into slot ${DEFAULT_SLOT_ID}..."
chmod +x /usr/local/bin/wp-os-install-bot.sh
/usr/local/bin/wp-os-install-bot.sh "${DEFAULT_SLOT_ID}" "${DEFAULT_BOT}" || \
  echo "[WARN] Default bot install had errors -- check /var/log/wp-os-setup.log"

# -- 8. SSH
echo "[8/9] Configuring SSH..."
cp -n /etc/ssh/sshd_config /etc/ssh/sshd_config.bak
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config

# -- 9. Systemd services + web control panel
echo "[9/9] Installing systemd services and web control panel..."

# Bot slot service template (OS_USERNAME baked in here at provision time)
cat > /etc/systemd/system/wp-os-bot@.service <<EOF
[Unit]
Description=WhiteoutProjectOS Bot slot %i
After=network.target
StartLimitIntervalSec=30
StartLimitBurst=3

[Service]
Type=simple
ExecStart=/usr/local/bin/wp-os-bot-start.sh %i
WorkingDirectory=${BOTS_DIR}/%i
Restart=always
RestartSec=5
User=${OS_USERNAME}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

chmod +x /usr/local/bin/wp-os-bot-manager.sh \
         /usr/local/bin/wp-os-bot-start.sh 2>/dev/null || true

mkdir -p "$WEBSERVER_DIR"
chown root:root "$WEBSERVER_DIR"
chmod 755 "$WEBSERVER_DIR"

cat > /etc/systemd/system/wp-os-web.service <<EOF
[Unit]
Description=WhiteoutProjectOS Web Control Panel
After=network.target
[Service]
ExecStart=/usr/bin/python3 ${WEBSERVER_DIR}/app.py
WorkingDirectory=${WEBSERVER_DIR}
Restart=always
RestartSec=5
User=root
EnvironmentFile=/etc/wp-os/config.env
Environment=PORT=${WEBSERVER_PORT}
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
for svc in wp-os-web ssh openssh-server; do
  systemctl enable "$svc" 2>/dev/null || true
  systemctl start "$svc" 2>/dev/null || true
done
systemctl start "wp-os-bot@${DEFAULT_SLOT_ID}" 2>/dev/null || true

if [ "$IS_LXC" -eq 1 ]; then
  systemctl disable rsyslog 2>/dev/null || true
  systemctl mask    rsyslog 2>/dev/null || true
fi

systemctl disable wp-os-firstboot.service 2>/dev/null || true
rm -f /etc/systemd/system/wp-os-firstboot.service

echo "========================================="
echo " WhiteoutProjectOS Provisioning COMPLETE"
echo " $(date)"
echo "========================================="
echo " SSH  : port 22  (user: ${OS_USERNAME})"
echo " Web  : http://<ip>:${WEBSERVER_PORT}"
echo "========================================="

if [ "${WPOS_REBOOT:-1}" = "1" ] && [ "$IS_LXC" -eq 0 ]; then
  echo "Rebooting in 5 seconds..."
  sleep 5
  reboot
fi
