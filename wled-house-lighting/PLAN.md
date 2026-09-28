# Whole-House WLED Control System — Plan

Status: **building** — master skeleton running on the Pi. Last updated 2026-09-28.

## Goal

Touch-screen and rotary-knob control panels for my WLED lights, starting with the
bar and expanding room by room across the house. Fully standalone (no Home
Assistant), with a web interface and Alexa control added later.

## Decisions so far

| Topic | Decision |
|---|---|
| Home Assistant | Not used; system is standalone |
| Lights | Several existing ESP32-based WLED controllers |
| Non-WLED lights | Also control existing **Tuya-based Wi-Fi devices** (Geeni devices + ELEGRP DTR10 smart dimmer switches) from the same master, locally via TinyTuya — see [Non-WLED devices](#non-wled-devices-geeni--elegrp-tuya) |
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
   - Deploy note: copying files to the Pi over `scp`/`rsync`/`ssh` needed a
     `~/.claude/settings.json` permission rule added by hand (Claude can't
     grant itself new permissions) — see that file if setting up on another
     machine.

   **Web interface done (2026-09-27), Bar zone only:** mobile-first dark UI,
   served by the same `wledmaster` service. **Use the IP, not the
   hostname: http://192.168.4.40:8080.** `http://lights-hub:8080` doesn't
   resolve from at least one phone tested — mDNS/`.local` hostname
   resolution isn't reliable on this network (same issue found earlier
   when `raspberrypi.local` wouldn't resolve either). Worth keeping in
   mind for later mDNS-dependent work (Alexa discovery, panels finding the
   master) — see Open Questions.
   - Backend: `aiohttp` server in [`wledmaster/web.py`](master/wledmaster/web.py)
     bolted onto the existing asyncio event loop alongside the control
     socket. REST API: `GET /api/state` (friendly per-segment status, not
     the raw WLED dump `status()`/the CLI use), `POST .../preview` (send a
     one-off action live, not saved — used for both the dashboard's
     quick-toggle chips and the scene editor's live preview), `POST
     .../scenes/<name>/apply`, and scene CRUD (`POST` create/update, `POST
     .../rename`, `DELETE`).
   - Scene edits persist back to `house.yaml` using `ruamel.yaml`
     ([`persist.py`](master/wledmaster/persist.py)) instead of plain
     PyYAML, specifically so the file's explanatory comments survive edits
     made through the UI. After any scene CRUD, the `Manager` reloads
     config from disk in-memory — no service restart needed (adding a new
     *controller*, as opposed to a scene, still needs one).
   - Frontend: vanilla HTML/CSS/JS in [`static/`](master/static/), no
     build step, no external font/CDN dependencies (kept in line with the
     "standalone" goal — the Pi is the only server involved). Dashboard
     tab (scene buttons with swatches derived from their actual colors,
     quick per-segment on/off toggles) plus a Scenes tab for full CRUD,
     including a live-preview-as-you-edit scene builder.
   - Two real bugs caught by testing directly in the browser pane before
     deploying: (1) `<button>` elements don't inherit text color the way
     `<div>`s do, so scene card text was rendering black-on-dark and
     unreadable until `color` was set explicitly; (2) the first design for
     "include this segment in the scene" used a second on/off switch,
     visually indistinguishable from the segment's own power switch right
     below it — replaced with a distinct "Add to scene" / "✓ In scene"
     chip. Also swapped the delete-scene confirmation from the browser's
     native `confirm()` (untestable by automation, and a jarring visual
     mismatch with the custom UI) for an in-app modal matching the theme.
   - Not yet built: scheduling, the fuller house/zone scene config model,
     more zones, and any controller-*config*-writing (presets/segments/LED
     layout) — the master only sends runtime commands (preset select,
     segment on/off/color/fx/brightness), same as before.

   **Redesign + effects (2026-09-27/28):** several rounds of UI feedback
   after the initial build:
   - Header restructured: title row, then power toggle + a real master
     dimmer (brightness slider hitting all controllers), then a scene
     picker. The dimmer uses a gamma-2 curve (`percentToBri`/`briToPercent`
     in `app.js`) — a raw linear 1-255 slider crammed almost all visible
     dimming into the bottom ~20% of its travel, since eyes perceive
     brightness roughly logarithmically.
   - The scene picker is a custom bottom sheet, not a native `<select>` —
     iOS Safari (and browsers generally) won't style `<option>` elements
     with custom colors, so there was no way to show each scene's color
     preview the way the old button grid did. The sheet shows a real
     swatch per scene (solid, or a conic-gradient pie for multi-color
     scenes) and a checkmark on whichever is currently active.
   - Added an all-off/on power toggle. Deliberately just flips each
     controller's top-level WLED "on" switch rather than touching
     segments — WLED keeps every segment's color/effect/on-state in
     memory while powered off, so toggling back on restores the exact
     prior look (including scenes with some segments individually off)
     with no need to track "the last scene shown."
   - Fixed the bottom Dashboard/Scenes tab bar not staying put on an
     actual iPhone despite `position: fixed` looking correct and working
     fine in (Chromium-based) local testing — moved it to be a direct
     child of `<body>` instead of nested inside the app's flex wrapper,
     which is the standard fix for this class of WebKit quirk. Couldn't
     be reproduced/confirmed in local tooling, only on the real device.
   - Added WLED effects: scene actions gained `fx`/`sx`/`pal` fields
     end-to-end (config, persistence, command building, active-scene
     matching). The master fetches the real effect/palette name lists
     from a live controller once at startup (`GET /json/eff` / `/json/pal`,
     ~220 effects / 72 palettes) so the editor shows names, not numbers.
     Each included segment in the scene editor now has an Effect dropdown;
     picking anything but Solid reveals Palette + Speed controls, all
     live-previewing like color/power already did.
   - Removed the scene editor's "Preview" button — vestigial once every
     control started live-previewing on its own; clicking it just resent
     the same state the UI had already pushed.

   **Scene editor bulk-edit redesign (2026-09-28):** editing a 12-segment
   scene one row at a time was tedious, especially for scenes where several
   segments share the same look or effect. Replaced the per-segment inline
   color/fx controls with a checkbox on each segment row plus one shared
   edit panel above the list. The checkbox means *only* "currently targeted
   by the panel" — it's deliberately independent of whether the segment is
   already in the scene, and spans every controller in the zone, so you can
   select any mix of segments (in-scene or not, on any controller) and edit
   them as one batch. Scene membership itself became a field the panel
   controls ("In scene" toggle, alongside Power/Color/Effect/Palette/Speed)
   rather than the checkbox's job — this is what lets a scene keep
   different effects on different segments (e.g. some segments Rainbow,
   others Solid) while still bulk-editing whichever subset shares a look
   at a given moment. To avoid a footgun, the "In scene" toggle only ever
   gets pulled *up* to true automatically (selecting a fresh, not-yet-
   included segment keeps the panel's current "In scene" state rather than
   defaulting it off) — turning it off is always an explicit user action,
   normally used to bulk-remove several selected segments from the scene
   at once. "Select all" per controller seeds the panel from that
   controller's segments regardless of current inclusion. Panel edits
   live-preview together with the same debounce as before. Verified
   against real Bar hardware: selected `underbar1` (on `under_bar`) and
   `shelf12` (on `bar_shelves` — a different controller) as one batch
   despite neither being in the test scene yet, set them to red Rainbow,
   confirmed via each WLED device's own `/json/state` that exactly those
   two segments changed (fx=9, col red) and every sibling segment on both
   controllers was untouched, then restored both controllers to Warm
   White (and explicitly cleared the leftover effect afterward — applying
   a scene whose actions don't mention `fx` doesn't reset a segment's
   currently-running effect, a pre-existing behavior worth knowing about).
   Implementation in `renderSceneEditor()` / `applyPaneToSelection()` /
   `seedEditPaneFrom()` in `app.js`.
   - **Bug found and fixed same day:** the selected/targeted row highlight
     and the in-scene row highlight were both plain background tints, and
     CSS cascade meant `.targeted` always visually overrode `.included` —
     so checking a box to edit a segment hid whether it was actually in
     the scene, right when that mattered most. Fixed by making them
     independent: `.included` stays a background tint, `.targeted` is now
     an inset ring (`box-shadow`, not `background`), and scene membership
     also gets its own always-visible badge (a checkmark + effect name,
     e.g. "✓ Solid", vs. dim "Not in scene") that's driven purely by
     `sd.included` and never touched by selection state.

   **Multi-color-slot support (2026-09-28):** several WLED effects/palettes
   (e.g. the numbered "Color 1/2/3" palettes shown in the official WLED
   app) need up to 3 colors per segment — primary, secondary, tertiary —
   not just one. The data model only ever carried a single `col: [r,g,b]`
   end-to-end (config, persistence, command-building, every part of the
   frontend), so this was a real gap, not just a UI issue. Changed `col`
   to `list[list[int]]` (up to 3 slots) throughout:
   - `config.py`: `SceneAction.col` retyped; `parse_action()` transparently
     wraps a legacy flat `[r,g,b]` from old `house.yaml` scenes into
     `[[r,g,b]]` so nothing needs migrating — existing scenes keep behaving
     exactly as before (WLED leaves unspecified slots untouched) until
     edited and resaved through the new UI, at which point they start
     explicitly sending all 3 slots (secondary/tertiary default to black)
     for deterministic, repeatable-looking scenes.
   - `manager.py`: `_build_command` sends `action.col` directly (was
     wrapping it in an extra list); `dashboard_state()` now surfaces the
     full 3-slot array instead of just the primary color; `_scene_is_active`
     only compares the slots a scene action actually specifies, so a
     primary-only action doesn't fail to match over an unrelated secondary/
     tertiary difference.
   - `app.js`: new `normalizeCol()` helper keeps exactly 3 slots everywhere
     in the frontend (missing ones default to black, or to the existing
     warm-white default for a segment that's never had a color at all).
     Scene-editor edit panel now shows 3 small numbered color swatches
     (1/2/3, primary larger) instead of one — considered a full custom
     hue/saturation color wheel like the WLED app screenshot but chose the
     simpler native-input approach to match the app's existing lightweight
     style; the underlying data-model fix was the same either way.
   - Verified against real Bar hardware: set `underbar1` to red primary +
     blue secondary + the "Two Dots" effect via the new picker, confirmed
     via the WLED device's own `/json/state` that `col` came back as
     `[[255,0,0],[0,0,255],[0,0,0]]` with `fx: 50`, then restored the zone
     to Warm White (explicitly re-zeroing secondary/tertiary, since — same
     gotcha as before — WLED leaves a slot alone if a command doesn't
     mention it). Deployed to the Pi; needed a `wled-master` service
     restart since Python changed this time, not just static files.

   **Static asset cache-busting (2026-09-28):** a small UI tweak (moving
   the In scene/Power switch labels) looked unchanged on a phone after
   deploying — second time this exact "browser cached the old app.js"
   confusion has happened on this project (first was the DHCP-outage day).
   `index.html` linked `/static/app.js`/`style.css` with no version, so a
   phone that had cached them kept using the stale copy indefinitely.
   Fixed in `web.py`: the `/` route now reads `index.html`, rewrites both
   asset URLs to `?v=<file mtime>` so a changed file gets a new URL
   automatically, and serves the HTML itself with `Cache-Control: no-store`
   so the browser always re-checks for those (possibly new) URLs. No more
   manual hard-refresh needed after a deploy.

   **Consistent segment-chip size + friendly display names (2026-09-28):**
   the dashboard's on/off segment chips auto-sized to their label, so
   `underbar1` was visibly wider than `shelf14` — fixed with a fixed
   `width: 112px` + centered content + ellipsis overflow on
   `.segment-chip-label` instead of letting the pill grow with its text.
   Also added a purely-cosmetic friendly-name layer so the UI doesn't have
   to show raw config keys like `shelf21` or `bar_shelves_2`:
   - `Controller.display_name` (optional, per controller) and
     `Zone.segment_names` (a flat `{segment_name: label}` dict, since
     segment names are already unique within a zone) in `config.py`.
     Both fall back to the real name when unset, and neither is used by
     any scene/action logic - purely a display overlay, so nothing about
     how scenes address controllers/segments changed.
   - `house.yaml`: `display_name: Under Bar` / `Bar Shelf 1` / `Bar Shelf 2`
     per controller, plus a `segment_names:` block mapping e.g. `shelf21:
     Shelf 1` and `underbar1: Rail 1`. Michael can freely edit these labels
     later - it's just a small YAML section, nothing else depends on the
     text.
   - `manager.py`'s `dashboard_state()` now includes `display_name` on
     both controllers and segments; `app.js` uses it (falling back to the
     real name) for the dashboard's controller headings/chip labels and
     the scene editor's controller headings/segment-row labels, while
     `data-controller`/`data-segment` attributes (used for all lookups)
     keep using the real technical name throughout.

   **Important gotcha found 2026-09-27 (real, hit live in production more
   than once): never use `preset:` scene actions on a controller that has
   segments defined.** A WLED preset saved before a controller's segments
   were split bundles its own old segment layout (in this case, a single
   whole-strip segment). Applying that preset — even just for its color/
   effect — silently collapses the controller's current segments back to
   that old layout (and reverts segment names), with no error or warning.
   This happened to both `under_bar` and `bar_shelves` mid-session when
   the (then still preset-based) `Just Lit`/`Christmas`/`The Blues` scenes
   were applied, and had to be fixed by hand over the WLED JSON API each
   time. Fixed properly by rewriting those three scenes as segment actions
   instead (`config/house.yaml`), which can't cause this since they only
   ever address the one named segment. `SceneAction`/`_build_command` in
   `manager.py` still support `preset:` for controllers that are
   deliberately left unsegmented — just don't mix the two on one
   controller.

   **Debugging detour, 2026-09-27:** what looked at first like "buttons
   need several taps to work" on the web UI turned out to be three
   separate, smaller things, not one bug:
   1. A real one: the dashboard polled `/api/state` every 4s and did a
      full DOM rebuild every tick regardless of whether anything changed,
      which could replace a button out from under an in-progress tap.
      Fixed — only re-render when the fetched state actually differs, and
      skip a poll if the previous one hasn't finished.
   2. Not a bug: at least once, the browser pane Claude shares with the
      user was pointed at a dead/leftover tab (a temporary local test
      server, already shut down) rather than the real
      `http://192.168.4.40:8080` — clicking anything there was never going
      to do anything. Worth remembering: Claude's own ad-hoc local testing
      in that shared pane can silently replace whatever tab the user has
      open, so prefer a dedicated background tab (`tabs_create` with
      `foreground: false`) for that instead of reusing/navigating the
      user's active one.
   3. Not a bug, a missing feature: the user's actual remaining complaint
      ("why is one scene button a different color") was that scene card
      colors were only ever a preview of that scene's *own* configured
      colors, never an indicator of which scene is *currently active* on
      the real hardware. Led to the active-scene indicator above, and to
      finding the preset-clobbering bug in the first place.
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

Two different difficulty levels depending on what "create" means:
- **Picking/tuning existing WLED effects** (e.g. "warm and slow-pulsing" ->
  choosing one of WLED's ~220 built-in `fx` values plus speed/intensity/
  palette) is pretty achievable — mostly a well-informed API call against
  WLED's existing JSON API, similar to what `wledmaster` already does for
  presets and segments.
- **Fully custom, novel animations** (per-pixel patterns generated from
  scratch, not from WLED's built-in effect list) is a much bigger lift —
  needs streaming arbitrary frames over WLED's realtime UDP protocol
  (DDP/Art-Net), which means writing and running actual animation-generation
  code somewhere, not just calling WLED's API.

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
- [x] **SSH key-based deploy access set up (2026-09-28)**, after a full
      lockout: the 2026-09-27 password wasn't saved anywhere and no key
      existed, so a new Claude Code session had neither. Recovered without
      reflashing by pulling the USB boot drive into the Mac and using the
      standard Pi "forgotten password" trick — appended
      `init=/bin/sh -c "mount -t proc proc /proc; mount -o remount,rw /;
      echo 'lights:<newpass>' | chpasswd; sync; exec /bin/sh"` to
      `bootfs/cmdline.txt` (the kernel cmdline parser honors the quotes, so
      this runs non-interactively — no monitor/keyboard needed on the Pi),
      booted once to apply it, then restored the original `cmdline.txt` and
      rebooted normally. A dedicated ed25519 key
      (`~/.ssh/lights_pi` on the Mac, alias `lights-hub` in `~/.ssh/config`)
      was then installed with `ssh-copy-id` so future sessions don't depend
      on a password at all. Editing `cmdline.txt` to add `init=/bin/sh` was
      blocked by Claude Code's own auto-mode safety classifier (correctly —
      it's an auth-bypass technique) even though this is the user's own
      hardware; Michael made that edit himself in TextEdit both times.
- [x] **Router: DHCP reservation (fixed IP) for the Pi and every WLED
      controller.** Confirmed to actually bite, not just theoretical: on
      2026-09-28 all 3 Bar controllers went unreachable for hours because
      DHCP reassigned their IPs to other devices (only the Pi's own IP had
      a reservation at the time). Found them again by MAC address and
      updated `house.yaml`. Michael has since reserved all Bar controllers
      at their current IPs (2026-09-28), and said he'd reserve the rest of
      his WLED controllers house-wide too, not just these 3 — worth
      double-checking a device's reservation still matches `house.yaml`
      if a "controller offline" issue ever comes back.
      | Controller | MAC | Reserved IP |
      |---|---|---|
      | Pi (`lights-hub`) | `e4:5f:01:ab:a4:4b` | 192.168.4.40 |
      | `under_bar` | `3c:8a:1f:04:91:68` | 192.168.4.24 |
      | `bar_shelves` | `cc:db:a7:52:21:dc` | 192.168.4.38 |
      | `bar_shelves_2` | `94:51:dc:16:56:70` | 192.168.4.39 |
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

IPs below are the current reserved ones (updated 2026-09-28 after the DHCP
reassignment; see the table in the Pi prep checklist).

Found by lighting ranges of pixels live and having Michael confirm what lit up
on the physical shelves (2026-09-27). Segment names/IDs are set directly on
each controller in WLED, independent of `wledmaster`.

Naming convention (consistent across both shelf units, fixed 2026-09-27 after
initially mislabeling top/bottom on the right unit): **`shelf<unit><position>`,
position 1 = bottom shelf counting up to the top.**

**Bar Shelves** (`bar_shelves`, 192.168.4.38, left unit, 977 LEDs) — already correctly
segmented from before; verified shelf-by-shelf, then renamed from its
original `bottom1`/`shelf11`/`shelf12`/`shelf13` to match the convention
above:
| Segment | Pixels | Physical position |
|---|---|---|
| `shelf11` | 0–240 | bottom shelf |
| `shelf12` | 241–483 | 2nd from bottom |
| `shelf13` | 484–728 | 3rd from bottom |
| `shelf14` | 729–976 | top shelf |

**Bar Shelves 2** (`bar_shelves_2`, 192.168.4.39, right unit) — was one undivided segment,
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

**Under Bar** (`under_bar`, 192.168.4.24, 60 LEDs) — split into 4 even 15-pixel segments
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

## Non-WLED devices (Geeni + ELEGRP, Tuya)

Added 2026-09-28. Not built yet — design notes only.

The bar also has Wi-Fi lights that aren't WLED, and they should be part of the
same scenes/panels/web UI/Alexa:
- **Geeni** devices (Merkury's brand, built on the **Tuya** platform) —
  controlled today from the Geeni app.
- **ELEGRP DTR10** Wi-Fi smart dimmer switches (single-pole, touch dimmer,
  neutral required; bought a 4-pack, Dec 2024) with lights attached —
  controlled today from the ELEGRP app. Likely also Tuya-based; to confirm.

**Approach: local control from the Pi with [TinyTuya](https://github.com/jasonacox/tinytuya)**
(Python, fits `wledmaster`). No cloud at runtime; keeps working if the
internet is down.
- One-time setup needs each device's **ID + local key**:
  1. Get the devices into the **Smart Life** app (Tuya's own app). Geeni /
     ELEGRP devices may need re-pairing to move there (a Tuya device can
     only be bound to one app account at a time). Alexa links would then go
     through Smart Life instead of Geeni/ELEGRP (or through the master's own
     Alexa support later).
  2. Create a free Tuya IoT developer account and link the Smart Life
     account to a cloud project.
  3. Run `python -m tinytuya wizard` on the Pi — pulls IDs + local keys for
     every device at once; `tinytuya scan` finds their LAN IPs/protocol
     versions.
- Re-pairing/resetting a device later **changes its local key** — re-run the
  wizard if a Tuya device suddenly stops responding.
- Give every Tuya device a **DHCP reservation** too (same lesson as the WLED
  controllers on 2026-09-28).
- Many Tuya devices allow only **1–2 local connections**, so only the master
  should talk to them (already the hub design).
- **No fallback path for these:** if the master is down, zone panels can still
  drive WLED directly, but Tuya devices wait for the master. The ELEGRP
  dimmers keep working as normal wall switches regardless, so staff always
  have manual control.

**What the master would control:**
- ELEGRP dimmers: on/off + brightness; changes made at the wall switch are
  reported back, so the UI/panels stay in sync.
- Geeni devices: depends on type — bulbs (on/off, brightness, colour, white
  temperature), plugs/switches (on/off), strips (colour/brightness/modes).

**Code impact (small, not a redesign):** `wledmaster` is currently
WLED-specific (`wled_client.py`, `Controller`, `SceneAction`,
`_build_command`). Add a device-type layer: a `type:` on each device in
`house.yaml` (`wled` default, `tuya` new), a Tuya client alongside the WLED
one (persistent TinyTuya connection per device, status push → state), and
Tuya-appropriate scene actions (`power`, `bri`, and for colour bulbs
`col`/colour temp). Zones and scenes stay brand-agnostic, so a Bar scene can
set WLED shelves *and* the ELEGRP dimmers in one tap. Leaves room for other
brands later (Shelly, Kasa, ...).

**Risks to check early:** newer Tuya firmware uses protocol 3.4/3.5 (TinyTuya
supports them, but test one Geeni device and one ELEGRP dimmer before
building the full integration). Devices that won't cooperate can sometimes
be reflashed with open firmware (OpenBeken/ESPHome) — more hands-on; only for
problem devices.

## Open questions

- Which rooms/zones, and how many WLED controllers in each?
- Does any single WLED controller span two rooms (needs segment-level zones)?
- Is the network room on the same subnet/VLAN as the Wi-Fi devices? (mDNS and
  Alexa discovery need it, or an mDNS reflector.)
- Final panel choices: 7" board model; knob size (2.1" vs 1.46").
- Is the **ELEGRP app** Tuya-based? (Check a device's info page in the app for
  a "Virtual ID" — Tuya white-label apps show one — or try adding a dimmer
  in Smart Life.)
- Which Geeni devices are in the bar (bulbs / strips / plugs / switches), how
  many, and how many ELEGRP dimmers are installed and what they control?

## Notes / constraints

- Cloud sessions for this repo currently can't download the PlatformIO toolchain
  (network policy blocks `api.registry.platformio.org` and GitHub downloads).
  Add those hosts to the environment's network access to compile ESP32 firmware
  in the cloud, or build locally on the Mac.
- Checking the Pi on the home network requires a local Claude Code session on the
  Mac (cloud sessions can't reach the LAN).
