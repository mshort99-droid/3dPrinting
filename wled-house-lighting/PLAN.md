# Whole-House WLED Control System — Plan

Status: **building** — master skeleton running on the Pi. Last updated 2026-09-27.

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

   **Minimal skeleton done (2026-09-27), Bar zone only:**
   - Code lives in [`master/`](master/) — `wledmaster` Python package
     (config loader, one persistent WebSocket client per WLED controller,
     scene dispatch, a Unix-socket control interface, plus `wledmaster.ctl`
     as a CLI for it) and `config/house.yaml` for the zone/controller/scene
     config.
   - Deployed and running as a systemd service on `lights-hub`
     (`/etc/systemd/system/wled-master.service`, `enable --now`, restarts on
     failure). Verified live: connects to all 3 Bar controllers, `status`
     and `apply-scene bar "<name>"` both work end-to-end through the
     running service.
   - Real bug caught and fixed during testing: WLED sends a bare
     `{"success": true}` ack after every command, which was overwriting the
     richer tracked device state — client now only updates state from
     messages that actually carry a `"state"` key.
   - Current `house.yaml` scenes (`Just Lit`, `Christmas`, `The Blues`) are
     placeholders using whatever presets already exist on the controllers
     today — not the final Open/Happy Hour/Game Night/Closed scene design.
   - Not yet built: scheduling, the house/zone scene config model beyond
     this flat per-zone mapping, the web interface, more zones, and any
     controller-config-writing (presets/segments) — the master currently
     only sends runtime commands (preset select, on/off) over each
     controller's existing WebSocket.
   - Deploy note: copying files to the Pi over `scp`/`rsync`/`ssh` needed a
     `~/.claude/settings.json` permission rule added by hand (Claude can't
     grant itself new permissions) — see that file if setting up on another
     machine.
2. **7" overview panel** firmware (ESP32-S3, LVGL 9, PlatformIO).
3. **Knob zone panels**, starting with the bar.
4. **Alexa** (Hue/WeMo-style device emulation on the Pi; test Echo discovery early).
5. More rooms.

Enclosures (CadQuery → STEP + STL): 7" panel wall frame; knob wall plate and/or
bar-top stand. The Pi needs no enclosure.

**Stretch goal, later (not scoped yet):** a conversational "bot" exposed
through Alexa that can create/edit scenes by voice on the fly (e.g. "make
something moody with blue and red"), not just trigger existing ones. Bigger
lift than step 4's basic voice control — needs a custom Alexa Skill wired to
an LLM, an AWS/Alexa developer account, and a publicly reachable endpoint,
which cuts against the "fully standalone, no cloud dependency" goal. Revisit
once the core system (steps 1–5) is solid.

## Raspberry Pi prep checklist

- [x] USB SSD (120–250 GB) to boot from — used a 128GB USB thumb drive instead
      (fine to start; see note below on swapping to a real SSD later).
- [x] Flash **Raspberry Pi OS Lite (64-bit)** — done via `dd` from the Mac
      (no card reader; Pi Imager wasn't usable, so image was decompressed and
      written manually, plus `ssh` + `userconf.txt` added to the boot
      partition for headless first boot). Login created: username `lights`.
- [x] Renamed host from default `raspberrypi` to **`lights-hub`**
      (`hostnamectl set-hostname` + `/etc/hosts` updated, 2026-09-27).
- [x] Rotated the `lights` account password (2026-09-27) — the original was
      typed in plaintext in chat while setting this up; new password was
      generated locally, set via `chpasswd`, verified by SSH login, and
      given to Michael once outside this file (not recorded here).
- [ ] Router: DHCP reservation (fixed IP) for the Pi and every WLED
      controller. **Not done by Claude** — router/network config changes are
      done by Michael directly. Pi's current DHCP-assigned IP is
      **192.168.4.40**, MAC `e4:5f:01:ab:a4:4b` — reserve that pairing.
- [ ] Clean dust from the fan (moot for now — running off the old SD card's
      fan/heatsink setup, but still worth doing before final mounting).
- [x] Run health checks — see results below.

### 2026-09-27: wiped and reinstalled; health checks (on fresh OS)

Decided to skip inspecting the old Home Assistant install (see blocker
below) and go straight to a wipe, since the target design was always
standalone. Old SD card removed; Pi now boots from a 128GB USB thumb drive
plugged into a **blue (USB 3.0)** port.

```
Model:      Raspberry Pi 4 Model B Rev 1.5
RAM:        3.7 GiB total, 3.4 GiB free
Throttled:  0x0  (no under-voltage/throttling ever detected — good)
Temp:       38.4°C idle — good
OS:         Debian GNU/Linux 13 "trixie" (Raspberry Pi OS Lite, 64-bit,
            2026-09-15 build)
Disk:       114 GB root on the USB drive, 2.8 GB used, 106 GB free
Hostname:   raspberrypi (default — not yet renamed)
IP:         192.168.4.40 (DHCP, not yet reserved)
```

**Recommendation: hardware is healthy, proceed with build.** No
throttling history, plenty of RAM and disk for a lightweight Python
service, temp is fine. Remaining prep-checklist items (hostname, DHCP
reservation, password rotation) are small and non-blocking.

Note: a 128GB USB **thumb** drive is what was on hand, not a proper USB
SSD. Fine for now; thumb drives wear out faster under constant read/write
than an SSD, so consider swapping to a real USB SSD before this becomes a
24/7 production box.

### 2026-09-26: network discovery attempt — blocked, needs a decision

- The Pi was only connected to this Mac's USB port for **power**; a Pi 4's
  USB-C port isn't a data link, so it wasn't on the LAN until Ethernet was
  connected.
- After connecting Ethernet, found it on the LAN: **192.168.4.40**, MAC
  `e4:5f:01:ab:a4:4b` (Raspberry Pi Foundation OUI).
- It is **still running a live, configured Home Assistant install**
  (confirmed via the web UI on port 8123 — past onboarding, needs login).
  Home network is subnetted 192.168.4.0–192.168.7.255 (netmask
  255.255.252.0); the Pi and this Mac are both on the 192.168.4.x segment,
  so no VLAN issue for mDNS.
- **Can't get a shell:** port 22 (SSH) and port 22222 (Home Assistant OS's
  usual host SSH) are both closed. No known/remembered HA login, so can't
  log in to enable the Terminal & SSH add-on either. Did not attempt to
  guess the HA password (HA bans an IP after 5 failed logins, and
  credential-guessing isn't something to do even on your own gear).
  No USB microSD card reader on hand, so can't pull the card and inspect/
  flash it directly either.
- **Result:** couldn't run the OS-level health checks (model confirmed
  4B/2021 already; RAM, throttling, temp, OS version, disk usage still
  unknown) — blocked on physical access, not network access.
- **Recommendation:** buy a cheap USB microSD card reader (~$8–10). It
  unblocks both this health check (read the card directly, no login
  needed) and the eventual reinstall step, which needs one anyway to flash
  Raspberry Pi OS Lite with Raspberry Pi Imager. Given it's a live
  configured HA install (not a blank OS) and the target design is
  standalone anyway, a wipe is very likely the right call regardless of
  what the health checks show — the checks are mainly to confirm the
  hardware itself (RAM size, no under-voltage/throttling history, temp)
  is fine before building on it.
- Alternative if a reader isn't wanted: temporarily attach a monitor +
  keyboard directly to the Pi for a local console (no network/login
  needed) to run the same health-check commands.

## Bar zone — WLED controller segment maps

Found by lighting ranges of pixels live and having Michael confirm what lit up
on the physical shelves (2026-09-27). Segment names/IDs are set directly on
each controller in WLED, independent of `wledmaster`.

Naming convention (consistent across both shelf units, fixed 2026-09-27 after
initially mislabeling top/bottom on the right unit): **`shelf<unit><position>`,
position 1 = bottom shelf counting up to the top.**

**Bar Shelves** (192.168.4.49, left unit, 977 LEDs) — already correctly
segmented from before; verified shelf-by-shelf, then renamed from its
original `bottom1`/`shelf11`/`shelf12`/`shelf13` to match the convention
above:
| Segment | Pixels | Physical position |
|---|---|---|
| `shelf11` | 0–240 | bottom shelf |
| `shelf12` | 241–483 | 2nd from bottom |
| `shelf13` | 484–728 | 3rd from bottom |
| `shelf14` | 729–976 | top shelf |

**Bar Shelves 2** (192.168.6.240, right unit) — was one undivided segment,
now split into 4 and named. Also found and fixed a real misconfiguration:
the controller was set to 800 LEDs but the physical strip is only **788**
(the extra 12 were phantom pixels driving nothing); `hw.led.ins[0].len` is
now corrected to 788 and the device rebooted to apply it.
| Segment | Pixels | Physical position |
|---|---|---|
| `shelf21` | 0–194 | bottom shelf |
| `shelf22` | 195–377 | 2nd from bottom |
| `shelf23` | 378–579 | 3rd from bottom |
| `shelf24` | 580–787 | top shelf |

**Under Bar** (192.168.4.42, 60 LEDs) — split into 4 even 15-pixel segments
(no physical shelf boundaries to find, just an even split): `underbar1`
(0–14), `underbar2` (15–29), `underbar3` (30–44), `underbar4` (45–59).

### `wledmaster` now supports segment-level scenes

Config (`house.yaml`) and code (`config.py`, `manager.py`) extended so a
scene's actions can target either a whole-controller preset (`preset: <id>`,
as before) or one named segment directly (`segment: <name>` plus any of
`power`/`col`/`fx`/`bri`) — no WLED preset needs to exist on the device for
segment-level scenes. Each controller now also declares its `segments: {name:
id}` map in the config. Deployed and verified live through the running
systemd service (`Warm White (all shelves)` and `Top Shelves Off` scenes,
12 and 2 actions respectively).

**Bug caught during this: never use a bare YAML key named `on`.** YAML 1.1
(what PyYAML's `safe_load` uses) treats the bare words `on`/`off`/`yes`/`no`
as booleans, so a literal `on: false` in the config silently parses as
`{True: False}` — not `{"on": False}` — and the real key is lost. First
symptom was a "turn this segment off" scene action doing nothing. Fixed by
using `power:` as the YAML-facing key name instead (translated to the
`SceneAction.on` field internally, which is safe since Python has no such
gotcha) — `config.py` has a comment explaining why.

Not yet done: teaching `wledmaster`/`house.yaml` about these per-shelf
segments (currently the config only knows about whole-controller presets,
not individual WLED segments within a controller) — needed before scenes can
address a single shelf rather than a whole unit.

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
