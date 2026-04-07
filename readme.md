# WhiteoutProjectOS

A plug-and-play OS for hosting Whiteout Survival and Kingshot Discord bots. Flash an image, power on, and your bot is running — no Linux knowledge required.

---

## Download

**[→ Latest release](https://github.com/ikketim/os/releases/latest)**

| Platform | File | Flash with |
|---|---|---|
| **x86 / PC / VM / bare metal** | `wp-os-x86-*.iso.xz` | [Rufus](https://rufus.ie) · [balenaEtcher](https://etcher.balena.io) · `xz -dc … \| dd` |
| **Raspberry Pi 4 / 5 (arm64)** | `wp-os-rpi-*.img.xz` | [Raspberry Pi Imager](https://www.raspberrypi.com/software/) · `xz -dc … \| dd` |

Full flashing and first-boot instructions in the platform guides below.

---

## Features

- **Web control panel** — manage bots, tokens, and the system from a browser at `http://<ip>:8080`
- **Multiple bot slots** — run several bots side by side on one device
- **Token vault** — store spare tokens and assign them to slots in one click
- **OS self-update** — update scripts and the web panel without reflashing (`System → OS Update`)
- **SSH + VNC + XFCE desktop** — full remote access from day one

---

## Supported Bots

| Bot | Type key | Notes |
|---|---|---|
| WOS Python | `wos-py` | Whiteout Survival — Python edition |
| WOS JavaScript | `wos-js` | Whiteout Survival — JavaScript edition |
| Kingshot | `kingshot` | Kingshot Discord Bot |
| VoiceChat Counter | `voicechat` | [wos-voicechat-counter](https://github.com/ikketimnl/wos-voicechat-counter) — needs Client ID + Guild ID |

---

## Quick Start

1. Download the image for your platform from the **[latest release](https://github.com/ikketim/os/releases/latest)**
2. Flash it (see platform guide)
3. Boot the device — first-boot setup runs automatically (~5–15 min)
4. Open `http://<device-ip>:8080` in a browser
5. Set your bot token in the **Tokens** tab and click **Save**

---

## Platform Guides

- [Raspberry Pi (arm64)](wp-os-rpi/README.md)
- [x86 / PC / VM / Proxmox LXC](wp-os-x86/README.md)

---

## Default Credentials

> Change these after first boot.

| | |
|-|-|
| Username | `wp-os-user` |
| Password | `wpusr` |
| Web panel | `http://<ip>:8080` |
| SSH | `ssh wp-os-user@<ip>` |
| VNC | `<ip>:5900` |

---

## Repository Layout

```
WhiteoutProjectOS/
├── wp-os-x86/          x86 ISO builder + Proxmox LXC builder
├── wp-os-rpi/          Raspberry Pi image builder
└── .github/workflows/  Automated build & release (GitHub Actions)
```

---

## Security Note

The web panel (`:8080`) and VNC (`:5900`) are **unencrypted and unauthenticated**. Keep them on a trusted local network. For remote access use SSH port-forwarding:

```bash
ssh -L 8080:localhost:8080 -L 5900:localhost:5900 wp-os-user@<ip>
```
