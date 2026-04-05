# WhiteoutProjectOS x86

Runs on any x86/64 machine (bare metal, VM) via bootable ISO, or as a Proxmox LXC container.

---

## Using the Pre-built ISO

### Requirements
- A USB stick (4 GB or larger) or a VM with an ISO attached
- The machine you are installing on has internet access

### 1. Download the ISO

> **Download link will be added here.**

### 2. Flash the ISO to USB

**Linux / macOS:**
```bash
sudo dd if=wp-os-x86-YYYYMMDD.iso of=/dev/sdX bs=4M status=progress
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

After reboot the system is fully configured. Log in via:

| Method | Details |
|---|---|
| SSH | `ssh wp-os-user@<ip>` |
| VNC | `<ip>:5900` — password: `wpusr` |
| Web panel | `http://<ip>:8080` |
| Desktop | Auto-login at the console / XFCE session |

### 5. Set your bot token

Open the web panel at `http://<ip>:8080`, go to **Bot Token**, paste your token and click **Save & Restart**.

---

## Using the Pre-built LXC Container (Proxmox)

> LXC image/template download link will be added here.

If you prefer to build the LXC container yourself, see the **Build from Source** section below.

---

## Build from Source

### Prerequisites

**For ISO builds:**
```bash
sudo apt install xorriso wget openssl p7zip-full
```

**For LXC builds:**  
Run on a Proxmox host as root.

### Configuration

Edit `config.sh` to change credentials, bot repositories, or any install paths before building. All builder scripts source this file.

### Build an ISO

```bash
sudo ./build-iso.sh
# With --clean to re-download the base Ubuntu ISO:
sudo ./build-iso.sh --clean
```

The finished ISO is written to `output/wp-os-x86-YYYYMMDD.iso`.

**WSL2 users:**
```bash
sudo ./build-iso-wsl.sh
```

### Build a Proxmox LXC container

```bash
# Default: unprivileged container, DHCP, auto CTID
sudo ./build-lxc.sh

# Custom CTID and static IP
CT_IP="192.168.1.50/24" CT_GW="192.168.1.1" sudo ./build-lxc.sh --ctid 200

# Privileged container (only if you have a specific reason)
sudo ./build-lxc.sh --unprivileged 0
```

---

## File Layout

```
wp-os-x86/
├── config.sh                              Central configuration — edit this
├── build-lxc.sh                           Proxmox LXC builder
├── build-iso.sh                           ISO builder (native Linux)
├── build-iso-wsl.sh                       ISO builder (WSL2)
├── config-wsl.sh                          WSL2 variant of config.sh
├── iso-builder/
│   ├── user-data                          Ubuntu autoinstall cloud-config
│   └── meta-data                          Instance metadata
├── rootfs-overlay/
│   ├── etc/systemd/system/
│   │   └── wp-os-firstboot.service      Runs wp-os-provision.sh on first boot
│   └── usr/local/bin/
│       ├── wp-os-provision.sh           Main provisioning script (templated)
│       ├── wp-os-install-bot.sh         On-demand bot installer
│       ├── wp-os-bot-start.sh           Bot service launcher
│       └── wp-os-bot-manager.sh         CLI tool for token and slot management
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

> **Security:** The web panel and VNC are unencrypted. Keep ports 8080 and 5900 on a trusted local network only. Use SSH port-forwarding for remote access: `ssh -L 8080:localhost:8080 -L 5900:localhost:5900 wp-os-user@<ip>`

---

## Updating the Bot Token

**Via the web panel:** `http://<ip>:8080` → Bot Token → Save & Restart

**Via SSH:**
```bash
ssh wp-os-user@<ip>
# Set token for a slot via the CLI manager:
sudo wp-os-bot-manager.sh token-set wos-1 YOUR_TOKEN
```
