# Whole-House WLED Control System — Plan

Status: **planning** (nothing built yet). Last updated 2026-09-26.

## Goal

Touch-screen and rotary-knob control panels for my WLED lights, starting with the
bar and expanding room by room across the house. Fully standalone (no Home
Assistant), with a web interface and Alexa control added later.

## Decisions so far

| Topic | Decision |
|---|---|
| Home Assistant | Not used; system is standalone |
| Lights | Several existing ESP32-based WLED controllers |
| Architecture | Hub and spoke: one **master** talks to all WLED controllers; panels talk only to the master |
| Master hardware | Existing **Raspberry Pi 4 Model B** (board made late 2021), in the network room, wired Ethernet, no screen |
| Master case | Keep the existing official Pi case (red/white, fan + heatsinks fitted) |
| Master power | My own external USB-C supply (must be 5V / 3A; verify with `vcgencmd get_throttled` = `0x0`) |
| Panels | 7" ESP32-S3 touch screen (whole-house overview) + Elecrow ESP32-S3 rotary knob displays as zone panels (2.1" preferred) |
| 3D designs | CadQuery, exported to **STEP** (for editing in Shapr3D) plus STL |

## Architecture

```
                 ┌──────── Master: Raspberry Pi 4 (network room, wired) ───────┐
                 │ scenes · schedule · web interface · Alexa · config backup   │
                 └───────┬────────────────────────────────────┬────────────────┘
        one WebSocket    │ per WLED controller                │ panel link (LAN)
                         ▼                                    ▼
           WLED controllers (Wi-Fi)              Panels: 7" overview, zone knobs
           Bar, Kitchen, Lounge, ...             (each has a "home zone")
```

- **WLED controllers** are the source of truth for light state. The master keeps one
  live WebSocket (`/ws`) to each and sends commands over it (WLED JSON API).
  One connection per controller avoids WLED's small WebSocket client limit.
- **Master** (Python service under systemd, auto-restart) owns config, scenes,
  schedule, web UI and Alexa, and relays live state to panels.
- **Panels** only need Wi-Fi details and their home zone. They find the master via
  mDNS, download the config, and send commands like "Bar → Happy Hour".
- **Fallback:** if the master is down, a zone panel controls its own zone's WLED
  controllers directly using its last cached config. Schedule/web/Alexa pause.
- The master–panel protocol will be simple and documented, so the master could
  later move to other hardware (e.g. an ESP32 PoE board) without changing panels.

## Config model

- **House:** house-wide scenes (All Off, Away, Night, Party), schedule.
- **Zones** (Bar, Kitchen, Lounge, ...): WLED controllers or segments, zone scenes
  (e.g. Bar: Open, Happy Hour, Game Night, Closed), zone schedule entries.
- Scenes trigger **WLED presets/playlists** stored on the controllers, so effects
  and colours are designed in WLED itself.
- PIN protection for settings on panels; editing happens mainly in the web UI.
- Restore the last scheduled scene after a power cut / reboot.

## Panel UI ideas

- **7" overview panel:** all zones at a glance, tap a zone to control it, house-wide
  scene buttons, screen dimming/sleep when idle.
- **Knob zone panel:** turn to pick a scene, press to apply; long-press for zone
  mode (turn = brightness, tap = on/off); optional PIN-protected browsing of other
  zones.

## Build order

1. **Pi master + web interface** (can be built and tested in a cloud session; Python
   packages are reachable there).
2. **7" overview panel** firmware (ESP32-S3, LVGL 9, PlatformIO).
3. **Knob zone panels**, starting with the bar.
4. **Alexa** (Hue/WeMo-style device emulation on the Pi; test Echo discovery early).
5. More rooms.

Enclosures (CadQuery → STEP + STL): 7" panel wall frame; knob wall plate and/or
bar-top stand. The Pi needs no enclosure.

## Raspberry Pi prep checklist

- [ ] (Optional) Image the old SD card if anything from the old install is wanted.
- [ ] USB SSD (120–250 GB) to boot from, or at least a new high-endurance SD card.
- [ ] Flash **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager; set
      hostname (e.g. `lights-hub`), enable SSH, create login.
- [ ] Router: DHCP reservations (fixed IPs) for the Pi and every WLED controller.
- [ ] Clean dust from the fan.
- [ ] Run health checks and record results:
      ```
      cat /proc/device-tree/model; echo
      free -h
      vcgencmd get_throttled     # want throttled=0x0
      vcgencmd measure_temp
      cat /etc/os-release | head -3
      df -h /
      ```

## Open questions

- Which rooms/zones, and how many WLED controllers in each?
- Does any single WLED controller span two rooms (needs segment-level zones)?
- Is the network room on the same subnet/VLAN as the Wi-Fi devices? (mDNS and
  Alexa discovery need it, or an mDNS reflector.)
- Final panel choices: 7" board model; knob size (2.1" vs 1.46").
- Pi RAM size (any is fine; check with `free -h`).

## Notes / constraints

- Cloud sessions for this repo currently can't download the PlatformIO toolchain
  (network policy blocks `api.registry.platformio.org` and GitHub downloads).
  Add those hosts to the environment's network access to compile ESP32 firmware
  in the cloud, or build locally on the Mac.
- Checking the Pi on the home network requires a local Claude Code session on the
  Mac (cloud sessions can't reach the LAN).
