# WhiteoutProjectOS Raspberry Pi

Runs on a Raspberry Pi 4 or 5 (arm64). The image includes XFCE desktop, SSH, VNC, and the WhiteoutProjectOS web control panel pre-configured.

---

## Using the Pre-built Image

### Requirements
- Raspberry Pi 4 or 5 (8 GB RAM recommended)
- MicroSD card (32 GB or larger) or a USB/NVMe SSD
- The Pi has internet access on first boot

### 1. Download the image

> **Download link will be added here.**

### 2. Flash the image

**Recommended:** Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/).

1. Open Raspberry Pi Imager
2. Click **Choose OS** → **Use custom** → select the `.img.xz` file
3. Click **Choose Storage** → select your SD card or SSD
4. Click **Write**

**Alternative (Linux/macOS):**
```bash
xz -dc wp-os-rpi-YYYYMMDD.img.xz | sudo dd of=/dev/sdX bs=4M status=progress
sync
```
Replace `/dev/sdX` with your SD card device.

### 3. First boot

Insert the SD card / SSD, power on the Pi. First boot setup runs automatically and takes 5–15 minutes. The Pi **reboots once** when setup is complete.

### 4. Find the Pi's IP address

Check your router's DHCP table, or use:
```bash
# From another machine on the same network
nmap -sn 192.168.1.0/24 | grep -A1 "Raspberry"
# Or after SSHing in:
hostname -I
```

### 5. Access

| Method | Details |
|---|---|
| SSH | `ssh wp-os-user@<pi-ip>` — password: `wpusr` |
| VNC | `<pi-ip>:5900` — password: `wpusr` |
| Web panel | `http://<pi-ip>:8080` |
| Desktop | XFCE auto-login on the Pi's HDMI output |

### 6. Set your bot token

Open the web panel at `http://<pi-ip>:8080`, go to **Bot Token**, paste your token and click **Save & Restart**.

---

## Updating the Bot Token Later

**Via the web panel:** `http://<pi-ip>:8080` → Bot Token → Save & Restart

**Via SSH:**
```bash
ssh wp-os-user@<pi-ip>
sudo /home/wp-os-user/update-token.sh YOUR_TOKEN
# or interactively:
sudo /home/wp-os-user/update-token.sh
```

---

## Build from Source

### Prerequisites

Run on a Linux machine (not on the Pi itself). You need:
```bash
sudo apt install wget xz-utils
```

### Configuration

Edit `config.sh` before building to change credentials, bot repositories, or install paths. All values in the script are sourced from here.

### Build

```bash
sudo ./build.sh
# With --clean to re-download the base Ubuntu Pi image:
sudo ./build.sh --clean
```

The finished image is written to `output/wp-os-rpi-YYYYMMDD.img.xz`.

---

## File Layout

```
wp-os-rpi/
├── config.sh                              Central configuration — edit this
├── build.sh                               Pi image builder
├── update-token.sh                        Token update helper (run on the Pi)
└── rootfs-overlay/
    └── usr/local/bin/
        ├── wp-os-firstboot.sh           First-boot provisioning (runs once)
        └── wp-os-switch-bot.sh          Bot-switching helper
```

---

## Access Summary

| Service | Default |
|---|---|
| SSH | `ssh wp-os-user@<pi-ip>` — port 22 |
| VNC | `<pi-ip>:5900` — password: `wpusr` |
| Web panel | `http://<pi-ip>:8080` |

---

## Notes

- The Pi image is built on Ubuntu 24.04 Server (arm64+raspi)
- Default bot is `wos-py` (Whiteout Survival Python edition)
- Switch bots via the web panel without reflashing
- Change the default password after first boot: `passwd wp-os-user`
