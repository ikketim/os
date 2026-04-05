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

# -- 1. Hostname
echo "[1/13] Setting hostname..."
hostnamectl set-hostname "$OS_HOSTNAME" 2>/dev/null || echo "$OS_HOSTNAME" > /etc/hostname
sed -i "s/127.0.1.1.*/127.0.1.1\t${OS_HOSTNAME}/" /etc/hosts 2>/dev/null || \
  echo "127.0.1.1\t${OS_HOSTNAME}" >> /etc/hosts

# -- 2. User
echo "[2/13] Creating user ${OS_USERNAME}..."
if ! id "$OS_USERNAME" &>/dev/null; then
  useradd -m -s /bin/bash -G sudo,adm "$OS_USERNAME"
fi
echo "${OS_USERNAME}:${OS_PASSWORD}" | chpasswd
echo "${OS_USERNAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${OS_USERNAME}"
chmod 440 "/etc/sudoers.d/${OS_USERNAME}"

# -- 3. System update
echo "[3/13] Updating system..."
apt-get update -qq
apt-get upgrade -y -qq --no-install-recommends

# -- 4. Core packages
echo "[4/13] Installing core packages..."
apt-get install -y -qq --no-install-recommends \
  python3 python3-full python3-venv python3-pip \
  wget curl git ca-certificates \
  openssh-server python3-flask \
  feh jq net-tools unzip xdotool

# -- 5. Node.js 22
echo "[5/13] Installing Node.js 22..."
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
apt-get install -y -qq nodejs

# -- 6. Desktop
echo "[6/13] Installing desktop (${DESKTOP})..."
if [ "$IS_LXC" -eq 1 ]; then
  apt-get install -y -qq --no-install-recommends \
    xfce4 xfce4-terminal xfce4-session dbus-x11 x11vnc xvfb
else
  apt-get install -y -qq --no-install-recommends \
    xfce4 xfce4-terminal xfce4-session lightdm lightdm-gtk-greeter x11vnc xvfb
  systemctl enable lightdm || true
  systemctl set-default graphical.target || true
  mkdir -p /etc/lightdm/lightdm.conf.d
  cat > /etc/lightdm/lightdm.conf.d/50-autologin.conf <<EOF
[Seat:*]
autologin-user=${OS_USERNAME}
autologin-user-timeout=0
user-session=${DESKTOP}
EOF
fi

# -- 7. Wallpaper
echo "[7/13] Setting up wallpaper..."
WALL_DIR="/usr/share/wallpapers/wp-os"
mkdir -p "$WALL_DIR"
wget -q -O "${WALL_DIR}/wp-os.png" "$BACKGROUND_IMAGE_URL" || true

mkdir -p "/home/${OS_USERNAME}/.config/autostart"
cat > "/home/${OS_USERNAME}/.config/autostart/wallpaper.desktop" <<'DESK'
[Desktop Entry]
Type=Application
Name=Set Wallpaper
Exec=feh --bg-scale /usr/share/wallpapers/wp-os/wp-os.png
Hidden=false
X-GNOME-Autostart-enabled=true
DESK

mkdir -p "/home/${OS_USERNAME}/.config/xfce4/xfconf/xfce-perchannel-xml"
cat > "/home/${OS_USERNAME}/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml" <<'XML'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty">
    <property name="screen0" type="empty">
      <property name="monitor0" type="empty">
        <property name="workspace0" type="empty">
          <property name="image-style" type="int" value="5"/>
          <property name="last-image" type="string" value="/usr/share/wallpapers/wp-os/wp-os.png"/>
        </property>
      </property>
    </property>
  </property>
</channel>
XML
chown -R "${OS_USERNAME}:${OS_USERNAME}" "/home/${OS_USERNAME}/.config"

# -- 8. Desktop shortcut
echo "[8/13] Creating desktop shortcut..."
DESK_DIR="/home/${OS_USERNAME}/Desktop"
mkdir -p "$DESK_DIR"
cat > "${DESK_DIR}/WhiteoutProjectOS-Panel.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=WhiteoutProjectOS Control Panel
Exec=xdg-open http://localhost:${WEBSERVER_PORT}
Icon=applications-internet
Terminal=false
Categories=Network;
EOF
chmod +x "${DESK_DIR}/WhiteoutProjectOS-Panel.desktop"
chown -R "${OS_USERNAME}:${OS_USERNAME}" "$DESK_DIR"

# -- 9. Runtime config + bots directory
echo "[9/13] Writing runtime config and bot directory structure..."
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
printf '{"type":"%s","label":"%s","created":"%s","installed":false}\n' \
  "${DEFAULT_BOT}" "${DEFAULT_BOT_LABEL}" "${NOW}" > "${SLOT_DIR}/.meta.json"
touch "${SLOT_DIR}/token.txt"
chmod 644 "${SLOT_DIR}/.meta.json"
chmod 600 "${SLOT_DIR}/token.txt"
chown root:root "${SLOT_DIR}/.meta.json"
chown "${OS_USERNAME}:${OS_USERNAME}" \
  "${SLOT_DIR}/token.txt" "${SLOT_DIR}" "${SLOT_DIR}/app"

# -- 10. Install default bot
echo "[10/13] Installing default bot (${DEFAULT_BOT}) into slot ${DEFAULT_SLOT_ID}..."
chmod +x /usr/local/bin/wp-os-install-bot.sh
/usr/local/bin/wp-os-install-bot.sh "${DEFAULT_SLOT_ID}" "${DEFAULT_BOT}" || \
  echo "[WARN] Default bot install had errors -- check /var/log/wp-os-setup.log"

# -- 11. SSH
echo "[11/13] Configuring SSH..."
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
sed -i 's/PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config

# -- 12. VNC
echo "[12/13] Setting up VNC..."
mkdir -p "/home/${OS_USERNAME}/.vnc"
x11vnc -storepasswd "$OS_PASSWORD" "/home/${OS_USERNAME}/.vnc/passwd" 2>/dev/null || true
chown -R "${OS_USERNAME}:${OS_USERNAME}" "/home/${OS_USERNAME}/.vnc"

cat > /etc/systemd/system/xvfb.service <<'EOF'
[Unit]
Description=Virtual Framebuffer
After=network.target
[Service]
ExecStart=/usr/bin/Xvfb :1 -screen 0 1920x1080x24
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/x11vnc.service <<EOF
[Unit]
Description=x11vnc VNC Server
After=xvfb.service
Requires=xvfb.service
[Service]
ExecStart=/usr/bin/x11vnc -display :1 -rfbauth /home/${OS_USERNAME}/.vnc/passwd -rfbport 5900 -forever -shared -noxdamage
Restart=always
RestartSec=3
User=${OS_USERNAME}
[Install]
WantedBy=multi-user.target
EOF

# -- 13. Systemd services + web control panel
echo "[13/13] Installing systemd services and web control panel..."

# Bot slot service template (OS_USERNAME baked in here at provision time)
cat > /etc/systemd/system/wp-os-bot@.service <<EOF
[Unit]
Description=WhiteoutProjectOS Bot slot %i
After=network.target

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

if [ "$IS_LXC" -eq 0 ]; then touch /etc/wp-os/gui_enabled; fi

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
for svc in xvfb x11vnc wp-os-web ssh openssh-server; do
  systemctl enable "$svc" 2>/dev/null || true
done
systemctl enable "wp-os-bot@${DEFAULT_SLOT_ID}" 2>/dev/null || true

for svc in ssh openssh-server xvfb x11vnc wp-os-web; do
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
echo " VNC  : port 5900"
echo " Web  : http://<ip>:${WEBSERVER_PORT}"
echo "========================================="

if [ "${WPOS_REBOOT:-1}" = "1" ] && [ "$IS_LXC" -eq 0 ]; then
  echo "Rebooting in 5 seconds..."
  sleep 5
  reboot
fi
