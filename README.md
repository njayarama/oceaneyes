# OceanEyes Radio API

Python API for Ocean Digital Internet Radios or radios with the Skytune (ALD) chipset.
https://www.oceandigitalshop.com/internet-radio

Ocean Digital's radios expose a small embedded web server that manages on-board station presets ("favourites"). OceanEyes wraps that server-side protocol in a Python library, exposes it as a REST API (FastAPI, port `1929`), and adds local stream sources (HD Radio, FM, NOAA weather, YouTube, BBC) via Icecast (port `3345`) so legacy radios can reach modern streams.

Tested on the Ocean Digital WR-26F and WR-336N, and likely compatible with other Skytune/ALD radios (see [compatible devices](#radios-that-may-use-skytune)).

> **New in this checkout:** quick-start for the venv-based developer layout, two utility scripts (`play_all.py`, `favsync.py`), a couple of bug fixes, and a full [architecture document](ARCHITECTURE.md).

---

## Quick start (this checkout)

The project runs inside a Python virtual environment.

```bash
cd oceaneyes

# 1. Create the venv if it isn't there yet (Python 3.13)
python3 -m venv .oceaneyes

# 2. Install dependencies (requirements.txt already includes requests)
.oceaneyes/bin/python3 -m pip install -r requirements.txt

# 3. Run - use the venv interpreter, NOT bare python3
.oceaneyes/bin/python3 main.py
```

`main.py` waits ~20 s, auto-detects Skytune radios on the LAN (if no IP is configured yet), starts the FastAPI server on `http://<your-ip>:1929`, and prints the device status.

Open the interactive docs in a browser:

```
firefox http://<your-ip>:1929/docs
```

### If you get "ModuleNotFoundError"

All dependencies live in the `.oceaneyes` venv. Either invoke it explicitly (`.oceaneyes/bin/python3 ...`) or activate it first:

```bash
source .oceaneyes/bin/activate
python3 main.py
```

> **Note on Python 3.13:** `requirements.txt` deliberately comments out `asyncio==3.4.3` (it is part of the standard library — there is no such PyPI version) and `PyAudio==0.2.13` (no longer compiles on 3.13, and no code imports it).

---

## Install as a service (original flow)

```bash
$ chmod +x *.sh
$ chmod +x *.py
$ ./install.sh
```

The installer:
1. Installs system dependencies (ffmpeg, icecast2, vlc, RTL-SDR tools, yt-dlp).
2. Creates a dedicated venv at `~/python-apps/oceaneyes`.
3. Copies the app into `~/python-apps/oceaneyes/app`.
4. Optionally installs the `oe.service` systemd unit.

Control the service with the helper scripts:

```bash
$ ./oe.start      # sudo systemctl start oe.service
$ ./oe.stop       # sudo systemctl stop oe.service
$ ./oe.status     # watch systemctl status oe.service
```

---

## Usage as a module

Be on the same network as your radio device:

```python
#!/usr/bin/python3
import oceaneyes as oe

settings, stations = oe.init("192.168.1.200")
ip = settings["ipaddress"]

print(oe.get_status(ip))      # (code, status, playing)
print(oe.get_total(1, "fav")) # number of presets in use
```

---

## REST API

FastAPI server on port 1929. Interactive docs at `http://<your-ip>:1929/docs`.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/v1/{device}/status` | Radio online/offline |
| GET | `/v1/{device}/playing` | Currently playing station |
| GET | `/v1/device/scan` | Re-scan the LAN for radios/tuners |
| GET | `/v1/{device}/app` | Redirect to the radio's native web UI |
| GET | `/v1/{device}/volume/{up\|down\|mute\|unmute}` | Volume control |
| POST | `/v1/fav/add?n=NAME&u=URL` | Add a favourite |
| GET | `/v1/{device}/fav/{vacant\|engaged}` | Free / used preset slots |
| GET | `/v1/{device}/fav/play/{c}` | Play preset `c` |
| GET | `/v1/{device}/fav/playlist/{format}` | Export favourites (m3u/pls/json/csv/ssv/plain/youtube) |
| GET | `/v1/{device}/fav/backup` | Backup favourites to a local TinyDB |
| GET | `/v1/{device}/fav/move/{from}:{to}` | Move a preset |
| GET | `/v1/{device}/streamto/{vlc\|browser}/{chid}` | Stream a preset to this PC |
| GET | `/v1/fav/sync/linux-mint` | Export to Linux Mint's Radio++ applet |
| GET | `/v1/search/{radiobrowser\|tunein}/{keywords}` | Station search |
| GET | `/v1/listen/{fmradio\|wxradio\|hdradio\|ytradio\|bbcradio}...` | Start a local stream source |
| GET | `/v1/listen/tv/{ch}` | Stream an HDHomeRun channel via Icecast |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full endpoint catalogue and the device protocol.

---

## CLI utilities

| Script | Purpose |
|---|---|
| `scan.py` | Standalone LAN scanner (writes found devices to `settings.db`) |
| `search.py` | RadioBrowser CLI search → `export_rb.{m3u,pls}` |
| `play_all.py` | Play every favourite for N seconds each (preview loop), e.g. `.oceaneyes/bin/python3 play_all.py` |
| `favsync.py` | Add/delete favourites from a flat file keyed by preset id |

### favsync.py — flat-file preset management

Manifest format (see `favsync.example.txt`):

```
# Replace whatever is currently at preset 16
16,Telugu Music UK,https://c8.radioboss.fm:18033/stream,United Kingdom,Asian Music

# Remove a preset
-16
```

Country/genre accept plain text (`United Kingdom`, `Jazz`) or raw Skytune codes (`3;17;-1`, `2;21`). Adding at an occupied slot replaces it; adding at a free slot appends; slots beyond the end of the list are rejected.

```bash
.oceaneyes/bin/python3 favsync.py favsync.example.txt --dry-run   # preview
.oceaneyes/bin/python3 favsync.py favsync.example.txt             # apply
```

### Example of bulk import from *.pls

```
oe.add_import("./import.pls", False)

[i] Importing station presets from ./import.pls
[+] 1 of 3 ...
[+] 2 of 3 ...
[+] 3 of 3 ...

200,OpenFM - EDM Anthems,http://stream.open.fm/361
200,OpenFM - Trance,http://stream.open.fm/7
200,OpenFM - House,http://stream.open.fm/5
```

---

## Python API methods (highlights)

```python
import oceaneyes as oe

settings, stations = oe.init("192.168.2.20")     # init, or auto-scan if no IP configured
ip = settings["ipaddress"]

oe.is_online(ip)                                 # check connectivity
oe.get_status(ip)                                # (code, status, playing)
oe.volume("up"|"down"|"mute"|"unmute")           # volume control
oe.get_remaining(1, "fav"), oe.get_total(1, "fav")  # preset usage
oe.play(1, "5")                                  # play preset 5 on device 1
oe.listen(1, "5")                                # play locally via VLC
oe.info_get(1, "5")                              # (id, name, url, country, genre)
oe.add(1, "Jazz FM", "http://edge-bauerall-01-gos2.sharp-stream.com/jazz.mp3",
        "3;17;-1", "2;21", True)
oe.edit("1", "New Name", "https://new.url/stream", "3;17;-1", "2;14", "0")
oe.move(1, "2", "1")                             # move preset 2 → 1
oe.delete(1, "16")                               # delete preset 16
oe.backup(1, True)                               # backup favourites (optionally enrich masked URLs)
oe.restore(1, False)                             # restore favourites from local DB
oe.get_list(1, "m3u", True)                      # export favourites
oe.search("BBC Radio 4", "RadioBrowser", True)   # (code, result)
oe.enrich_url("BBC Radio 4")                     # find real URL for a Skytune-masked station
oe.cache("RadioBrowser")                         # download full Radio Browser DB (slow)
oe.hdradio("90.3", "0")                          # local HD Radio via RTL-SDR → Icecast
oe.ytradio("jfKfPfyJRdk", "91")                  # local YouTube audio via yt-dlp → Icecast
oe.bbcradio("m001p1n9")                          # local BBC Sounds → Icecast
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'requests'` | Use the venv interpreter: `.oceaneyes/bin/python3` (or `source .oceaneyes/bin/activate`). |
| `pip install -r requirements.txt` fails on `asyncio` | Expected — `asyncio` is stdlib. That pin is commented out. |
| `/v1/1/status` reports "offline" but the radio is playing | Fixed in this checkout: handler now passes the device IP to `oe.is_online()`. Restart the server. |
| Radio web UI says "Favourite record is corrupted" | This is the device flagging a malformed preset (e.g. a truncated country code). Remove it with `oe.delete(1, "<id>")`, `favsync.py`, or the radio's own UI. |
| No radios found | Turn radios on, run `/v1/device/scan` (takes ~2–5 min) or `./scan.py`. |

---

## Useful Resources
- https://heyrick.eu/blog/index.php?diary=20230110
- https://github.com/pfbrowning/od-radio-sync
- https://www.radio-browser.info
- https://www.skytune.net

## Ideas and features
- Cache Community Radio Browser locally and direct REST API to look up that instead
- Evolve the onboard web server to allow more playback controls and device configuration
- Automate station selection on a schedule
- Automate emergency alerts by changing the station to an emergency broadcast and back again
- Import favourites from a local database or online community radio browser
- Export presets in as many formats as possible
- Synchronize station presets across other software
- Display now-playing data in a Home Automation Dashboard
- Control volume upon system events such as phone or video calls
- Import favourites from Radio++, Rhythmbox, Moode or Volumio to radio

---

## Own your URLs!

Internet Radio is a standalone category of hardware that can continue to grow if we invest in the right ways to allow people to manage their own databases. Preset data should be a high priority in product reviews, and buyers should ask for devices that allow adding station URLs directly rather than relying solely on a vendor portal. See [ARCHITECTURE.md](ARCHITECTURE.md) for the project's engineering view and open problems.

### Radios that may use Skytune:
- Most Ocean Digital radios (WR-50CD, WR-26F, WR-336F, WR-336N, WR-210N, WR-880N, WR-23D, WR-230SF)
- Denver Electronics IR-140 / IR-135B
- Release WiFi Internet Radios
- Renkforce RF-IR-MONOV2
- Opticum Ton4 DAB+, Internet, FM Radio
- CC WiFi 3 Internet Radio (with Skytune)

## Hybrid Digital Radio
Ocean Digital chips decode DAB/DAB+ but not HD Radio. OceanEyes bridges this with an RTL-SDR dongle + `nrsc5`, transposed to MP3 and published to Icecast, so an HD Radio signal can be listened to on the Ocean Digital as a local preset.