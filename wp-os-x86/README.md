# WhiteoutProjectOS x86

Runs on any x86-64 machine (bare metal, VM) via bootable ISO, or as a Proxmox LXC container.

---

## Using the Pre-built ISO

### Requirements
- A USB stick (4 GB or larger) or a VM with an ISO attached
- The machine has internet access on first boot

### 1. Download the ISO

**[→ Download from the latest release](https://github.com/ikketim/os/releases/latest)**

Download the file named `wp-os-x86-*.iso.xz`.

### 2. Flash the ISO to USB

**Linux / macOS:**
```bash
xz -dc wp-os-x86-YYYYMMDD.iso.xz | sudo dd of=/dev/sdX bs=4M status=progress
sync
```
Replace `/dev/sdX` with your USB device (check with `lsblk`).

**Windows:**
Use [Rufus](https://rufus.ie/) or [balenaEtcher](https://etcher.balena.io/).

### 3. Boot and install

1. Insert the USB stick and boot from it (press F12 / F2 / DEL at POST for the boot menu)
2. The installer runs fully automatically — no keyboard input needed
3. Installation takes 5–15 minutes; the machine reboots when done
4. Remove the USB stick when the machine reboots

### 4. First login

After reboot the system is fully configured:

| Method | Details |
|---|---|
| SSH | `ssh wp-os-user@<ip>` — password: `wpusr` |
| VNC | `<ip>:5900` — password: `wpusr` |
| Web panel | `http://<ip>:8080` |
| Desktop | Auto-login to XFCE at the console |

### 5. Set your bot token

Open `http://<ip>:8080`, go to the **Tokens** tab, paste your Discord bot token next to the default slot, and click **Save**.

For VoiceChat bots, expand the slot card and fill in the **Client ID** and **Guild ID** fields before saving.

---

## Using Proxmox LXC

Run on your Proxmox host as root:

```bash
# Default: unprivileged container, DHCP, auto CTID
sudo ./build-lxc.sh

# Custom CTID and static IP
CT_IP="192.168.1.50/24" CT_GW="192.168.1.1" sudo ./build-lxc.sh --ctid 200

# Privileged container (only if required)
sudo ./build-lxc.sh --unprivileged 0
```

---

## OS Self-Update

To update the web panel and bot scripts without reflashing, open the web panel → **System** → **OS Update**. This downloads the latest versions from the source repository.

Via SSH:
```bash
sudo wp-os-update.sh
```

---

## Build from Source

### Prerequisites

**ISO builds:**
```bash
sudo apt install xorriso wget openssl p7zip-full
```

**LXC builds:** Run on a Proxmox host as root.

### Configuration

Edit `config.sh` to change credentials, bot repositories, or install paths before building.

### Build an ISO

```bash
sudo ./build-iso.sh
# Force re-download of the base Ubuntu ISO:
sudo ./build-iso.sh --clean
```

Output: `output/wp-os-x86-YYYYMMDD.iso`

**WSL2:**
```bash
sudo ./build-iso-wsl.sh
```

---

## File Layout

```
wp-os-x86/
├── config.sh                              Central configuration — edit this
├── config-wsl.sh                          WSL2 variant of config.sh
├── build-iso.sh                           ISO builder (native Linux)
├── build-iso-wsl.sh                       ISO builder (WSL2)
├── build-lxc.sh                           Proxmox LXC builder (runs on Proxmox host)
├── build-lxc-image.sh                     Portable LXC/Incus image builder (CI / debootstrap)
├── iso-builder/
│   ├── user-data                          Ubuntu autoinstall cloud-config
│   └── meta-data                          Instance metadata
├── rootfs-overlay/
│   ├── etc/systemd/system/
│   │   └── wp-os-firstboot.service        Runs wp-os-provision.sh on first boot
│   └── usr/local/bin/
│       ├── wp-os-provision.sh             Main provisioning script (templated)
│       ├── wp-os-install-bot.sh           On-demand bot installer
│       ├── wp-os-bot-start.sh             Bot service launcher
│       ├── wp-os-bot-manager.sh           CLI tool for token and slot management
│       └── wp-os-update.sh                OS self-update script
└── webserver/
    └── app.py                             Flask web control panel
```

---

## Access Summary

| Service | Default |
|---|---|
| SSH | `ssh wp-os-user@<ip>` — port 22 |
| VNC | `<ip>:5900` — password: `wpusr` |
| Web panel | `http://<ip>:8080` |

> **Security:** The web panel and VNC are unencrypted. Keep ports 8080 and 5900 on a trusted local network only. For remote access use SSH port-forwarding:
> ```bash
> ssh -L 8080:localhost:8080 -L 5900:localhost:5900 wp-os-user@<ip>
> ```

---

## Managing Bot Tokens

**Via the web panel:** `http://<ip>:8080` → Tokens tab → Set / Assign

**Via SSH:**
```bash
ssh wp-os-user@<ip>
sudo wp-os-bot-manager.sh token-set wos-1 YOUR_TOKEN
sudo wp-os-bot-manager.sh list
```
