# OceanEyes — Software Design & Architecture

| | |
|---|---|
| **Status** | In development (working prototype, single-owner project) |
| **Primary language** | Python 3.13 (project originally targeted 3.9) |
| **Runtime model** | Scripted daemon + FastAPI service + external COTS binaries |
| **Target hardware** | Ocean Digital / Skytune (ALD) internet radios, e.g. WR-336N, WR-26F |
| **Related docs** | [README.md](README.md) |

---

## 1. Introduction & problem statement

Ocean Digital internet radios store their station *presets* ("favourites") on the device, managed by a small embedded web server exposed on port 80. The vendor's portal ("Skytune") supplies station metadata over the internet; some station URLs behind that portal are **masked** — the device returns a placeholder string instead of the real stream URL, so the user technically owns the hardware but not the playlists.

OceanEyes solves two problems:

1. **Programmatic management of on-device presets** — a thin, readable Python wrapper around the device's embedded HTTP/CGI API, exposed as a local REST API so any script, browser, or home-automation dashboard can read/write presets, control playback and volume, and export favourites to open formats.
2. **Future-proofing and reach** — because the device can be pointed at any stream URL, OceanEyes adds local *stream sources* (HD Radio via RTL-SDR + `nrsc5`, FM via `rtl_fm`, NOAA weather radio, YouTube via `yt-dlp`, BBC Sounds) transcoded with `ffmpeg` to MP3 over **Icecast**, all reachable as ordinary presets.

**Non-goals:** high-throughput streaming (Icecast is the front for that), a full replacement of the device's UX, multi-user authentication (LAN/home-trust model), and support for non-Skytune radios.

---

## 2. System context

```
                        LAN (192.168.x.x)
┌────────────┐   HTTP    ┌──────────────────────────────────────────────────────┐
│  Skytune   │◄──────────│                    SERVER (this repo)                 │
│  radio(s)  │  port 80  │                                                       │
│  :80 CGI   │           │  ┌────────────┐   ┌────────────┐   ┌───────────────┐  │
└────────────┘           │  │ main.py    │──►│ oceaneyes  │   │ api.py        │  │
                         │  │ (bootstrap)│   │  .py (core │   │ FastAPI :1929 │  │
┌─────────────────────┐  │  │            │   │  library)  │   └──────┬────────┘  │
│  Clients            │  │  └────────────┘   └─────┬──────┘          │           │
│  browser / curl /   │  │        │                │                 │           │
│  favsync.py /       │  │        ▼                ▼                 ▼           │
│  play_all.py        │  │  ┌────────────────────────────────────────────────┐   │
│  smart-home         │  │  │ SQLite-like TinyDB (settings/stations/*.db)    │   │
└─────────────────────┘  │  └────────────────────────────────────────────────┘   │
                         │                                                       │
┌─────────────────────┐  │  ┌─────────────┐   ┌────────────────────────────────┐  │
│ RTL-SDR dongle      │──►│  nrsc5       │   │  Icecast2 :3345                 │  │
│ (HD/FM/weather)     │  │  rtl_fm       │──►│  MP3-over-HTTP presets          │  │
│ YouTube / BBC (net) │  │  yt-dlp/ffmpeg│   │  /hdradio /fmradio /ytradio...  │  │
└─────────────────────┘  │  VLC (cdradio)│   └────────────────────────────────┘  │
                         │  :3372 proxy  │                                        │
                         └─────────────┘                                          │
```

**Ports**

| Port | Owner | Use |
|---|---|---|
| 80 | Skytune radio | Embedded web/CGI API used by OceanEyes |
| 1929 | uvicorn | OceanEyes REST API (`/docs` = OpenAPI UI) |
| 3345 | icecast2 | Local stream publishing (HD/FM/wx/yt/bbc) |
| 3372 | VLC | (optional) HLS/CD-quality transcode proxy (`/v1/listen/cdradio`) |

---

## 3. Repository layout

| File | Role |
|---|---|
| `oceaneyes.py` | Core library (~2,150 LOC). Everything the API and CLIs need. |
| `api.py` | FastAPI application: maps REST endpoints onto `oceaneyes.py`. |
| `main.py` | Daemon entrypoint: init → auto-scan → spawn API server → status banner. |
| `scan.py` | Standalone LAN scanner (duplicates `oe.scan()`). |
| `search.py` | CLI: RadioBrowser search → `export_rb.{m3u,pls}`. |
| `play_all.py` | CLI: preview-loop, plays every favourite N seconds. |
| `favsync.py` + `favsync.example.txt` | CLI: flat-file add/delete of favourites keyed by preset id. |
| `testdb.py` | TinyDB sanity script (dev aid). |
| `requirements.txt` | PyPI deps. (`asyncio` commented out — stdlib; `PyAudio` commented out — no longer builds on 3.13, unused.) |
| `install.sh` / `oe.service` / `oe.{start,stop,status}` / `run.sh` / `yt.sh` | Deployment/service scaffolding. |
| `settings.db` | TinyDB: per-slot device configuration (IP, name, make, uuid). |
| `stations.db` | TinyDB: cached favourite data (offline id → name/url/country/genre). |
| `stations_device{n}.db` | TinyDB: per-device favourites backup (created by `oe.backup`). |
| `stations_yt.db` | TinyDB: YouTube preset slots (1–99) + last played (doc 100). |
| `export*`, `import.{pls,json}` | Favourite export/import samples produced by the export code. |
| `.oceaneyes/` | Python venv for this checkout (created by the developer, not by `install.sh`). |

---

## 4. Component architecture

### 4.1 `oceaneyes.py` — core library

Coarse module map:

| Area | Functions (selection) |
|---|---|
| Discovery & init | `init()`, `scan()`, `switch()`, `get_serverip()`, `is_online()` |
| Device state | `get_status()`, `get_total()`, `get_remaining()`, `volume()` |
| Favourites CRUD | `play()`, `add()`, `edit()`, `delete()`, `move()`, `add_current()`, `del_current()`, `cleaner()` |
| Listing & parsing | `list_get()` (favList parser), `set_list()`, `info_get()`, `info_cached()` |
| Search | `search()` → RadioBrowser (`pyradios`) or TuneIn (`opml`) |
| URL enrichment | `enrich_url()`, `is_streamable()` (VLC probe), `cache()` (full Radio Browser mirror) |
| Import/export | `add_import()`, `get_list()` (plain/json/csv/ssv/m3u/pls/rpp/backup/yt), `backup()`, `restore()` |
| Codec tables | `decode_country()` / `decode_genre()` / `encode_country()` / `encode_genre()` |
| Local stream sources | `hdradio()` (nrsc5), `fmradio()` (rtl_fm), `wxradio()`, `ytradio()`/`play_yt()`, `bbcradio()`, `rtl_reset()` |

**Design trait:** the module is a *bag of functions* that operate on module-level globals (`url`, `ip`, `sip`, `settings`) which are (re)assigned by `switch()`/`init()`. Each call that needs a device starts with `settings, url, ip = switch(device)`.

### 4.2 `api.py` — REST layer

A single FastAPI app. Most handlers share the same shape:

```
parse path params -> oe.switch(device) -> call oceaneyes function -> return hand-built JSON string (or Redirect/PlainText)
```

The full endpoint catalogue is in §7. Known weaknesses of the layer: responses are string-concatenated (several are malformed JSON — see §10), and path parameters are not type-validated by FastAPI (they arrive as strings; numeric checks are done inline).

### 4.3 `main.py` — bootstrap/daemon

```
time.sleep(20)     # let the network/app settle (workaround for slow device boot)
oe.init()          # read settings.db; scan if IP is 0.0.0.0
api()              # spawn uvicorn on 1929 via @background
main()             # print device status
```

`api()` launches uvicorn **out-of-process** via `os.system(f"{dir_home}/python-apps/oceaneyes/bin/uvicorn api:app ...")`. In this git-checkout layout the worker path does not exist, so the API server must be started manually (`uvicorn api:app --host 0.0.0.0 --port 1929`) or via the installed-layout flow.

### 4.4 Deployment topology

`install.sh` copies the app to `~/python-apps/oceaneyes/app` with a sibling venv `~/python-apps/oceaneyes`, then optionally registers `oe.service` (systemd). This mirrors the `#!../bin/python3` shebangs the scripts use. The repository checkout used interactively with `.oceaneyes/` is an alternative developer layout.

---

## 5. Device protocol (reverse-engineered contract)

The Skytune/ALD device exposes a plain-HTTP, CGI-style API. No authentication. Responses are custom text formats (JS-like) rather than JSON.

### 5.1 Endpoint catalogue

| Endpoint | Method | Params | Semantics |
|---|---|---|---|
| `/php/favList.php` | GET | `PG=n` (page) | Favourites list, 10 items/page |
| `/php/playing.php` | GET | – | Now-playing info (JSON-ish, single quotes) |
| `/php/doVol.php` | GET | `VL=-1\|1\|128\|0` | Volume down/up/mute/unmute; returns `{level, muted}` |
| `/php/get_CG.php` | GET | – | Country/genre code tables (referenced by codec layer) |
| `/addCh.cgi` | POST | `EX, chName, chUrl, chCountry, chGenre` | Append a favourite |
| `/delCh.cgi` | GET | `CI=n` | Delete favourite at 0-based index |
| `/updateCh.cgi` | GET | `CI=n` | Update favourite fields |
| `/moveCh.cgi` | GET | `CI=f, DI=t, EX=0` | Move favourite |
| `/doApi.cgi` | GET | `AI=n[, CI]` | Actions: `16` play preset, `8` add current, `4` delete current |
| `/device.xml` | GET | – | UPnP device description (fingerprinting: friendlyName/modelName/UDN) |

**Index conventions:** public API is **1-based** (pet preset numbers); the wire protocol is **0-based** (`CI`, `PG`, etc.). OceanEyes converts at the boundary (`chid - 1` in every CRUD call).

### 5.2 `favList.php` wire format & parser

```js
favListInfo = {curPage:0, total:0, favCapacity:150, itemsPerPage:10, chIndex:-1, rowIdx:-1, curPageCount:-1};
myFavChannelList = [];
myFavChannelList.push(["Station Name","https://stream.url/aac-320",0,[[1,1,38],[2,32]]]);
myFavChannelList.push(["Skytune Station","****** Channel URL is maintained by Skytune",1,[[-1,-1,-1],[-1,-1]]]);
favListInfo = {curPage:0, total:14, favCapacity:150, itemsPerPage:10, chIndex:-1, rowIdx:-1, curPageCount:10};
```

Per `push` row (index after splitting on quotes):
`[0]=name, [1]=URL, [2]=masked-flag, [3..]=country codes / genre codes`.

Parsing (`list_get`, `get_total`):
- Lines split on `\n`; the final footer `favListInfo` line (which is `s[-2]` because responses end with a newline) yields the **total** count and `curPageCount`.
- Station lines are split on `"`, then mapped to a flat preset id. Preset ids are reconstructed from page/row via a brittle string concat (`str(page) + str(row)`) with special-case fixes (`"110"→"20"`, …) — see §10 tech-debt notes.
- `get_total` extracts the total via `favListInfo`-line split on `":"` (`c[2]` lands on the total field given the exact field order).

### 5.3 Masked URLs & enrichment

Skytune-managed stations return the literal string `****** Channel URL is maintained by Skytune`. OceanEyes:
1. Substitutes a local placeholder stream ("Bird Song radio") so the preset still plays something.
2. On export with `enrich=True`, looks the station up in the **Community Radio Browser** by name and probes candidates with VLC (`is_streamable`) to recover the real URL (`enrich_url`).

### 5.4 Country & genre codec

Skytune encodes region as strings like `country "3;17;78"` / `genre "2;57"` where `3=Europe`, `17=United Kingdom`, `78=England` and `2=Music`, `57=Asian Music`. `oceaneyes.py` embeds the full code tables as dicts and provides:
- `decode_country(code_1, code_2, code_3)` / `decode_genre(code_1, code_2)` → human text (also initialises module-level `locations`/`genres` globals used by `encode_*`).
- `encode_country(text)` / `encode_genre(text)` → Skytune codes (reverse lookup; supports `"State:Country"` format).
- `favsync.py` leverages both plus a raw-code passthrough (`^-?\d+(;-?\d+){0,2}$`).

---

## 6. Data model (TinyDB)

TinyDB is a pure-Python document store persisted as JSON files — adequate for a handful of config documents and a low-volume favourites cache.

| File | Documents | Meaning |
|---|---|---|
| `settings.db` | doc 1..20 | Device slots. Filled by `scan()` with `ipaddress`, `name` (friendly name), `make`, `uuid`. `language` tag `"TV"` marks HDHomeRun tuner slots (doc ≥ 100). |
| `settings.db` | doc 100+ | Detected HDHomeRun tuners. |
| `stations.db` | one per preset | Offline cache: `{channel, name, url, country, genre}` used by `info_cached()` when the radio is offline. |
| `stations_device{n}.db` | one per preset | Per-device favourites **backup**, written by `oe.backup()` / `get_list("backup")`, replayed by `oe.restore()`. |
| `stations_yt.db` | doc 1..99 | YouTube preset slots `{vid, aid, sid}`. |
| `stations_yt.db` | doc 100 | "Last played" YouTube stream. |

Slots are **contiguous and compacted**: deleting a favourite collapses the list (verified against the WR-336N), which is what makes the "add at slot N" algorithm in §8.3 possible.

---

## 7. REST API catalogue

Base path `/v1`. FastAPI OpenAPI docs at `/docs` (Swagger UI) and `/redoc`.

| Method | Route | Function | Notes |
|---|---|---|---|
| GET | `/v1/{device}/status` | online/offline | Fixed in this checkout (was querying `0.0.0.0`) |
| GET | `/v1/{device}/playing` | now playing | |
| GET | `/v1/{device}/fav/{engaged\|vacant}` | used/free preset count | |
| GET | `/v1/{device}/fav/play/{c}` | play preset | streamable probe currently hard-wired `True` |
| GET | `/v1/{device}/fav/playlist/{format}` | export favourites | formats: `m3u, pls, json, csv, ssv, plain, m3u-yt, json-yt` |
| GET | `/v1/{device}/fav/backup` | backup to TinyDB | |
| GET | `/v1/{device}/fav/move/{from}:{to}` | move preset | |
| POST | `/v1/fav/add` | add favourite | args `n`,`u` |
| GET | `/v1/device/scan` | LAN rescan | long-running (minutes) |
| GET | `/v1/{device}/app` | redirect to device web UI | |
| GET | `/v1/{device}/volume/{up\|down\|mute\|unmute}` | volume | |
| GET | `/v1/{device}/streamto/{vlc\|browser}/{chid}` | stream preset to this PC | VLC local or redirect |
| GET | `/v1/fav/sync/linux-mint` | export to Radio++ applet | writes Cinnamon config |
| GET | `/v1/fav/sync/radioplusplus` | export (JSON) | |
| GET | `/v1/search/{radiobrowser\|tunein}/{keywords}` | search stations | |
| GET | `/v1/listen/{fmradio\|wxradio\|hdradio}/{f...}` | start SDR source → Icecast | spawns background processes |
| GET | `/v1/listen/ytradio/{c}/{p}/{n}` | YouTube → Icecast | |
| GET | `/v1/listen/bbcradio/{c}` | BBC Sounds → Icecast | |
| GET | `/v1/listen/cdradio` | VLC transcode proxy | port 3372 (HTTP) |
| GET | `/v1/listen/tv/{ch}` | HDHomeRun channel → Icecast | hard-coded tuner IP |

---

## 8. Key flows

### 8.1 Device discovery / scan
1. Determine local subnet from a UDP "connect" trick (`get_serverip`/`scan`).
2. For `.2..254`: HTTP probe port 80 (1 s timeout) → `ping -w 5` (English-locale assertion `"5 received"`).
3. Fingerprint: `GET /php/favList.php` body contains `favListInfo` → Skytune radio; `GET /lineup.html` title `HDHomeRun Lineup` → HDHomeRun tuner.
4. Pull `/device.xml` for friendly name/make/UUID; write slot into `settings.db`.
5. Touch `~/.oceaneyes` as a completion marker used by `install.sh`.

### 8.2 Play a preset
`oe.play(device, ch)` → `GET /doApi.cgi?AI=16&CI={ch-1}` → poll `playing.php` for confirmation.

### 8.3 Add a station at a specific preset id (`favsync.py`)
Because the device only *appends*:

```
total = get_total()
if favid > total: skip (out of range; must fill in order)
if favid <= total: delete preset favid     # free + compact the list
add(name, url, country, genre)             # now lands at the new end
newtotal = get_total()
if newtotal != favid: move(newtotal, favid)  # shift into the target slot
```

Verified against the device: delete compacts, so the algorithm yields exactly "replaced at slot N".

### 8.4 Backup / restore / export
- `get_list("backup")`: reads all pages, writes `stations_device{n}.db` (optionally *enriches* masked URLs first).
- `restore()`: `cleaner()` deletes all presets (1/s to avoid device drop), then re-`add()`s from the cache.
- Exports: m3u, pls, csv, ssv, json, Radio++ `export-rpp.json` (also auto-installs into Cinnamon's `radio@driglu4it` config).

### 8.5 Local stream sources (Icecast pipeline)
All follow the same shape — a shell pipeline that exits into Icecast:

```
SDR/comms tool | sox/ffmpeg -re -codec:a libmp3lame -> icecast://source:rdo@<server>:3345/<mount>
```

| Feature | Pipeline |
|---|---|
| HD Radio | `nrsc5 -q -d 0 <freq> <prog> -o - \| ffmpeg … /hdradio-<freq>-<prog>` |
| FM | `rtl_fm … \| sox … \| ffmpeg … /fmradio-<freq>` |
| NOAA WX | `rtl_fm … \| sox … \| ffmpeg … /wxradio` |
| YouTube | `yt-dlp -f <fmt> <url> -o - \| ffmpeg … /ytradio-<vid>` (slots tracked in `stations_yt.db`) |
| BBC Sounds | `yt-dlp -f mf_cloudfront_nonbidi-audio_eng_1=96000-1 <url> … /bbcradio-<id>` |
| HDHomeRun TV | `ffmpeg -i http://<tuner>/auto/v<ch> … /hdhomerun` |

All launch via `subprocess.Popen(shell=True, …)` inside `@background`-decorated functions (one new thread + event loop per invocation).

---

## 9. Concurrency & execution model

- **`@background` decorator** (`oceaneyes.py` / `main.py`): wraps a function so each call runs in a fresh thread via `asyncio.new_event_loop().run_in_executor(None, f, …)`. Used for the API server task, SDR/stream sources, and (in `main.py`) for `api()`, `hdradio()`, `ytradio()`.
- **uvicorn as a subprocess** — started with `os.system` rather than in-process, so FastAPI handlers are independent async defs in uvicorn's loop; heavy work is synchronous calls into `oceaneyes.py` (uvicorn will block during them).
- **Shared mutable global state** (`url`, `ip`, `settings`, `sip`) is the de-facto "device context". Each API handler resets it via `oe.switch(device)`, which works under concurrency only because every handler re-inits before use. This is an acknowledged design debt (§10) and a multi-device correctness risk.
- Device write operations are slow (the radio serialises; `add()` sleeps 8 s), so the system is intentionally not high-throughput.

---

## 10. Engineering practices, tech debt & known issues

**Working well**
- Careful reverse-engineering of the wire protocol with forgiving parsers.
- Everything device-facing sits behind one module — swapping in a mock or a new device protocol is a contained change.
- Uses `import_safe()` + runtime `pip install` for resilience on fresh boxes (see risks).

**Tech debt / issues (honest list)**
1. **Fragile response parsing** — station rows are string-split on quotes and pages/rows concatenated into ids (`str(page)+str(row)` with `"110"→"20"` special cases); `playing.php` is parsed via `.replace("'", '"')`.
2. **Malformed JSON** in several REST responses (hand-built strings): missing quotes, e.g. `/v1/1/fav/save-current` returns `"result": 200"`, and `/v1/{device}/status` had an unquoted `"offline` (fixed in this checkout).
3. **Silent error swallowing** — pervasive bare `except:` returns placeholder values, making failures hard to diagnose.
4. **Mutable globals as device-context** (see §9) — fragile under concurrency and multi-device.
5. **`os.system` / `subprocess.Popen(shell=True)` with string interpolation** for transcoders and the uvicorn launcher — a shell-injection surface for any attacker who can reach the API; also makes commands environment/locale dependent (e.g. ping's `"5 received"`).
6. **Hard-coded assumptions** — user `lee` in `oe.service`; tuner IP `192.168.2.221` and `192.168.0.211` inside `api.py`; uvicorn path `~/python-apps/oceaneyes/bin/uvicorn` in `main.py`.
7. **Version drift** — `install.sh` targets Python 3.9; the checkout runs 3.13 where `PyAudio==0.2.13` and `asyncio==3.4.3` no longer resolve (both commented out in `requirements.txt`). `pyradios` imports `pkg_resources`, which recent `setuptools` (≥81) removed — needs a `setuptools<81` pin or a vendored shim.
8. **Slow sequential scanning** — 254 hosts × up to 5 s ping; no threading.
9. **API surface gaps / latent bugs** — `info_cached()` ignores its `device` argument in some callers; `listen()` references an unbound `settings_ip`; `fav_add` may reference `station` before assignment in an error branch; the VLC streamability probe is currently bypassed in `fav_play`.
10. **No automated tests** — `testdb.py` is a tiny manual sanity helper.
11. **Privacy** — `settings.db` (with a real device IP/uuid) is not gitignored.

**Changes applied in this checkout**
- `requirements.txt`: added `requests` (was imported by every module but never declared — the original `ModuleNotFoundError`), commented out `asyncio==3.4.3` (stdlib) and `PyAudio==0.2.13` (unbuildable on 3.13, unused).
- `api.py`: fixed `/v1/{device}/status` — was checking `is_online()` against `0.0.0.0` and returning malformed JSON; now mirrors `/playing` and quotes properly.
- Added `play_all.py` (preview loop) and `favsync.py` (flat-file preset management) + `favsync.example.txt`.
- Deleted a corrupted preset on-device (truncated country code `3,17,-`).

---

## 11. Design decisions & rationale

| Decision | Rationale |
|---|---|
| TinyDB over SQLite | JSON on disk, zero deps/zero schema, fits config+cache workloads; exported files double as human-readable backups. |
| Hand-rolled HTTP client on the wire protocol | The device speaks custom text formats (JS-ish), so `requests` + targeted string parsing is simpler than a full serialisation layer. |
| Stateless REST endpoints that re-`switch()` per request | Avoids connection/session state with the device; enables concurrent handlers at the cost of global-state fragility. |
| Icecast as the universal output | Legacy radios decode MP3-over-HTTP; Icecast gives mount-points per feature and off-the-shelf `.m3u` handling. |
| `@background` + subprocess for stream sources | Long-running media pipelines shouldn't block the API; OS-level processes give natural process isolation / `kill` semantics. |
| 1-based public / 0-based wire indexing | User-friendly API, exact mapping to the device's `CI` convention. |
| Commented-out autoload behaviours in `main.py` | Safe-by-default daemon that does nothing until the operator opts in. |

---

## 12. Security & operational considerations

- **Trust model is "LAN + home"** — the API has no auth; anyone on the network can control the radio, delete presets, or trigger `yt-dlp`/`ffmpeg`/SDR processes. Restrict with a firewall if exposed beyond the home LAN.
- **Shell interpolation** → prefer argument lists over `shell=True`; validate numeric/`http`-prefixed inputs (partially done: `isfloat`, `isnumeric`, `http in url` checks).
- **Credential hygiene** — Icecast source password (`rdo`) is hard-coded; device account model is none (no auth by design of Skytune).
- **Operational** — scanning every boot if no IP configured; 20 s startup delay; device corrupt-record handling is manual (delete the record; `favsync.py` makes this scriptable).
- **Backups** — `stations_device{n}.db` survives device resets and vendor portal shutdowns; considered the project's core value (see README "Own your URLs").

---

## 13. Testing strategy (current & proposed)

**Current:** manual, on-device verification loops (this session exercised: discovery/scan, favourites list parsing, play-all preview, delete, add-at-slot algorithm, JSON responses).

**Proposed:**
1. **Unit tests** for the codec tables and `favList` parser with **recorded fixtures** (canned HTTP responses captured from a WR-336N) — no hardware needed.
2. **Mock device** — a tiny `http.server` that serves the endpoints from fixtures; open `testdevice.py` runs the whole CRUD suite against it.
3. **Deterministic tests** for `favsync.py` (parse/validation/resolution) and `get_list()` exports (golden files).
4. **Integration smoke** — `pytest` markers `@pytest.mark.hardware` for device-optional tests, gated by env.
5. **Restore `setuptools<81` or shim `pkg_resources`** for `pyradios` on Python 3.13 as part of CI setup.

---

## 14. Roadmap

- Adopt the mock-device test harness; make parsing well-typed (dataclasses for stations).
- Move to explicit device-context objects to retire mutable-global state.
- Add auth (API token / LAN-bound) and input validation via FastAPI's Pydantic models.
- Reduce scan latency (threaded sweep + ARP table lookups) and drop the ping-locale dependency.
- Reliable URL enrichment cache (Radio Browser mirror as SQLite) for masked stations.
- Favourites sync between devices and external playlists (Radio++, Rhythmbox, Volumio).
- Package as a proper installable module and pin a CI matrix for Python 3.10–3.13.