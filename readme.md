# WhiteoutProjectOS

A purpose-built operating system image for running Whiteout Survival and Kingshot Discord bots. Available for x86/64 (bare metal or Proxmox LXC) and Raspberry Pi.

# THIS IS FOR TESTING PURPOSE ONLY!!! 
## It's still in development so bugs are expected
---

## Pre-built Images

> **Download links will be added here.**

| Platform | Image | Notes |
|---|---|---|
| x86 / bare metal | `wp-os-x86-YYYYMMDD.iso` | Flash to USB, boot and it auto-installs |
| Proxmox LXC | — | Use the builder script instead |
| Raspberry Pi | `wp-os-rpi-YYYYMMDD.img.xz` | Flash to SD card or SSD |

### Using a pre-built image

See the platform-specific README for full flashing and first-boot instructions:

- **x86 / Proxmox** → [`wp-os-x86/README.md`](wp-os-x86/README.md)
- **Raspberry Pi** → [`wp-os-rpi/README.md`](wp-os-rpi/README.md)

---

## Repository Layout

```
WhiteoutProjectOS/
├── wp-os-x86/          x86 bare-metal ISO + Proxmox LXC builder
└── wp-os-rpi/          Raspberry Pi image builder
```

---

## Default Credentials

| | |
|---|---|
| Username | `wp-os-user` |
| Password | `wpusr` |
| SSH port | `22` |
| VNC port | `5900` |
| Web panel | `http://<ip>:8080` |

> Change the password after first boot: `passwd wp-os-user`

> **Security:** The web panel runs over plain HTTP and VNC is unencrypted. Do not expose port 8080 or 5900 to the public internet. Access them over a local network or via SSH port-forwarding (`ssh -L 8080:localhost:8080 wp-os-user@<ip>`).

---

## Web Control Panel

Once the system is running, open `http://<ip>:8080` in your browser. The panel lets you:

- Start / stop / restart the bot service
- Save and update the bot token
- Switch between bot flavours (WOS Python, WOS JS, Kingshot)
- Toggle the desktop GUI on/off
- View recent bot logs

---

## Supported Bots

| Bot | Language | Key |
|---|---|---|
| Whiteout Survival | Python | `wos-py` |
| Whiteout Survival | Node.js 22 | `wos-js` |
| Kingshot | Python | `kingshot` |
