# WhiteoutProjectOS Raspberry Pi

Runs on a Raspberry Pi 4 or 5 (arm64). Includes XFCE desktop, SSH, VNC, and the WhiteoutProjectOS web control panel pre-configured out of the box.

---

## Using the Pre-built Image

### Requirements
- Raspberry Pi 4 or 5 (4 GB RAM minimum, 8 GB recommended)
- MicroSD card (32 GB or larger) or USB/NVMe SSD
- Internet access on first boot

### 1. Download the image

**[→ Download from the latest release](https://github.com/ikketim/os/releases/latest)**

Download the file named `wp-os-rpi-*.img.xz`.

### 2. Flash the image

**Recommended — Raspberry Pi Imager:**

1. Open [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Click **Choose OS** → **Use custom** → select the `.img.xz` file
3. Click **Choose Storage** → select your SD card or SSD
4. Click **Write**

**Alternative (Linux / macOS):**
```bash
xz -dc wp-os-rpi-YYYYMMDD.img.xz | sudo dd of=/dev/sdX bs=4M status=progress
sync
```
Replace `/dev/sdX` with your SD card device (check with `lsblk`).

### 3. First boot

Insert the SD card / SSD and power on the Pi. First-boot setup runs automatically and takes 5–15 minutes. The Pi **reboots once** when setup is complete.

### 4. Find the Pi's IP address

Check your router's DHCP table, or run from another machine on the same network:
```bash
nmap -sn 192.168.1.0/24 | grep -B1 "Raspberry"
```

### 5. Access

| Method | Details |
|---|---|
| SSH | `ssh wp-os-user@<pi-ip>` — password: `wpusr` |
| VNC | `<pi-ip>:5900` — password: `wpusr` |
| Web panel | `http://<pi-ip>:8080` |
| Desktop | XFCE auto-login on the Pi's HDMI output |

### 6. Set your bot token

Open `http://<pi-ip>:8080`, go to the **Tokens** tab, paste your Discord bot token next to the default slot, and click **Save**.

For VoiceChat bots, expand the slot card and fill in the **Client ID** and **Guild ID** fields before saving.

---

## OS Self-Update

To update the web panel and bot scripts without reflashing, open the web panel → **System** → **OS Update**. This downloads the latest versions from the source repository.

Via SSH:
```bash
sudo wp-os-update.sh
```

---

## Managing Bot Tokens

**Via the web panel:** `http://<pi-ip>:8080` → Tokens tab → Set / Assign

**Via SSH:**
```bash
ssh wp-os-user@<pi-ip>
sudo wp-os-bot-manager.sh token-set wos-1 YOUR_TOKEN
sudo wp-os-bot-manager.sh list
```

---

## Build from Source

### Prerequisites

Run on a Linux machine (not the Pi itself):
```bash
sudo apt install wget xz-utils
```

### Configuration

Edit `config.sh` to change credentials, bot repositories, or install paths before building.

### Build

```bash
sudo ./build.sh
# Force re-download of the base Ubuntu Pi image:
sudo ./build.sh --clean
```

Output: `output/wp-os-rpi-YYYYMMDD.img.xz`

---

## File Layout

```
wp-os-rpi/
├── config.sh                              Central configuration — edit this
├── build.sh                               Pi image builder
└── rootfs-overlay/
    └── usr/local/bin/
        ├── wp-os-firstboot.sh             First-boot provisioning (runs once)
        ├── wp-os-install-bot.sh           On-demand bot installer
        ├── wp-os-bot-start.sh             Bot service launcher
        ├── wp-os-bot-manager.sh           CLI tool for token and slot management
        └── wp-os-update.sh                OS self-update script
```

---

## Access Summary

| Service | Default |
|---|---|
| SSH | `ssh wp-os-user@<pi-ip>` — port 22 |
| VNC | `<pi-ip>:5900` — password: `wpusr` |
| Web panel | `http://<pi-ip>:8080` |

> **Security:** The web panel and VNC are unencrypted. Keep ports 8080 and 5900 on a trusted local network only. For remote access use SSH port-forwarding:
> ```bash
> ssh -L 8080:localhost:8080 -L 5900:localhost:5900 wp-os-user@<pi-ip>
> ```

---

## Notes

- Built on Ubuntu 24.04 Server (arm64 + raspi)
- Default bot slot is `wos-py` (Whiteout Survival Python edition)
- Switch bots via the web panel without reflashing
- Change the default password after first boot: `passwd wp-os-user`
