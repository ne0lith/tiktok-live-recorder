# Guide

- [Configuration directory](#configuration-directory)
- [FFmpeg and HEVC](#ffmpeg-and-hevc)
- [How to set cookies](#how-to-set-cookies)
- [How to set up the watchlist](#how-to-set-up-the-watchlist)
- [How to get room_id](#how-to-get-room_id)
- [How to enable upload to Telegram](#how-to-enable-upload-to-telegram)
- [Web dashboard](#web-dashboard)
- [Salvaging leftover recordings](#salvaging-leftover-recordings)
- [Log viewer](#log-viewer)
- [Restricted countries](#restricted-countries)
- [Unrestricted countries](#unrestricted-countries)

## Configuration Directory

All user-specific settings live in `config/` at the project root:

| File | Template | Purpose |
|------|----------|---------|
| `cookies.json` | `cookies.json.example` | TikTok session cookies |
| `users.json` | `users.json.example` | Watchlist usernames |
| `watchlist_state.json` | `watchlist_state.json.example` | Paused users (auto-managed by the dashboard) |
| `telegram.json` | `telegram.json.example` | Telegram API credentials |

Real config files are gitignored. Only the `*.example` templates are committed.

On first use, the recorder copies the matching `.example` file if the real file does not exist yet.

Override the config location with the `TIKTOK_RECORDER_CONFIG_DIR` environment variable.

## FFmpeg and HEVC

TikTok often serves live video as **HEVC inside legacy FLV** (codec id 12). Many distro FFmpeg packages (e.g. Debian/Ubuntu 7.1) cannot demux this format, which breaks MP4 conversion after recording.

### Startup probe (all platforms)

Before any recording starts, the recorder resolves and probes FFmpeg:

1. **Explicit path** - `-ffmpeg-path` if you passed one
2. **`ffmpeg` on `PATH`** - default (skipped when not installed)
3. **Linux vendor install** - when no capable candidate was found (missing ffmpeg, too old, or explicit path fails the probe)

Startup logs show the resolved binary and whether it is **capable for TikTok HEVC FLV**. All conversions use this resolved path for the lifetime of the process. The probe uses a synthetic legacy HEVC FLV test file - not a live TikTok stream.

### Linux automatic install

When running on Linux and no capable binary is found - including when **no ffmpeg is installed at all** - the recorder downloads **BtbN FFmpeg n8.1** (GPL static) into:

```text
.vendor/ffmpeg/n8.1-<arch>/bin/ffmpeg
```

(`linux64` or `linuxarm64`; directory is gitignored.)

- Happens **once at startup**, before watchlist polling or conversions - not mid-recording.
- Requires outbound HTTPS to GitHub releases; first run may pause for the download (~100 MB).
- Cached on disk: later starts reuse the vendor binary if it still passes the probe.
- A distro `ffmpeg` package is **optional**; if present but too old (e.g. Debian 7.1), the vendor build is used instead.
- Supported architectures: `linux64` and `linuxarm64` only. Other Linux arches must supply their own `-ffmpeg-path`.
- If the vendor download fails (network, checksum, unsupported arch), startup exits with install hints when no other ffmpeg is available; if an old system ffmpeg exists, startup may continue with a **NOT capable** warning and conversions may fail until you fix FFmpeg.

To use your own build instead: `uv run tiktok-live-recorder -ffmpeg-path /path/to/ffmpeg ...`

### Fallback rewriter

If demux still fails after install, the recorder attempts a legacy FLV tag rewrite (codec 12 -> Enhanced `hvc1`) before giving up. Check logs for conversion errors if a recording stays on **`convert_failed`**.

### Windows and macOS

Install FFmpeg manually ([ffmpeg.org](https://ffmpeg.org/download.html), Homebrew, Chocolatey, etc.). There is no automatic vendor download on these platforms - use FFmpeg **8.0+** for best HEVC FLV compatibility, or pass `-ffmpeg-path`.

## How To Set Cookies

Login-required, private, and age-restricted lives need TikTok session cookies.

1. Go to https://www.tiktok.com/ and log in.
2. Open Developer Tools - `Ctrl+Shift+I` (Windows/Linux) or `Cmd+Option+I` (macOS).
3. Switch to the **Application** tab.

![image](https://github.com/user-attachments/assets/7a7cb64b-41fe-49ed-9d85-bc00d451b9ef)

4. Copy the **values** of these cookies from Application -> Cookies -> `https://www.tiktok.com`:
   - `sessionid`
   - `sessionid_ss`
   - `tt-target-idc` (e.g. `useast2a`, `useast1a`)

5. Paste them into `config/cookies.json`:

```json
{
  "sessionid": "your_sessionid_value",
  "sessionid_ss": "your_sessionid_ss_value",
  "tt-target-idc": "useast2a"
}
```

For restricted or age-gated lives, `sessionid` is often required in addition to `sessionid_ss`. If you still get WAF/4003110 errors, export more browser cookies (e.g. `msToken`, `sid_tt`) into the same file.

Cookies are required for **followers** mode and for recording private or restricted accounts. You can also edit `cookies.json` from the dashboard **Settings** panel while the recorder is running.

## How To Set Up the Watchlist

Watchlist mode polls multiple creators in one process and records each one that goes live.

1. Edit `config/users.json`:

```json
{
  "users": [
    "creator1",
    "creator2",
    "creator3"
  ]
}
```

A plain JSON array also works: `["creator1", "creator2"]`.

2. Start watchlist mode:

```bash
uv run tiktok-live-recorder -mode watchlist
```

3. (Optional) Set the poll interval in minutes (default 5):

```bash
uv run tiktok-live-recorder -mode watchlist -automatic_interval 3
```

**CLI alternatives** (fixed for that run - not live-reloaded):

```bash
uv run tiktok-live-recorder -mode watchlist -user creator1,creator2
uv run tiktok-live-recorder -mode watchlist -users-file /path/to/my-list.json
```

**While running:** edits to `config/users.json` or a `-users-file` path are picked up on the next poll cycle. Removed users stop being polled; any in-progress recording for them finishes first. You can also add/remove users and pause/resume from the [web dashboard](#web-dashboard) in watchlist mode.

When a recording ends, the watchlist is rechecked immediately instead of waiting for the full poll interval.

## How To Get Room_ID

1. Go to https://www.tiktok.com/@username/live
2. Open Developer Tools - `Ctrl+Shift+I` (Windows/Linux) or `Cmd+Option+I` (macOS)
3. Search for `room_id` with `Ctrl+F`

![image](https://user-images.githubusercontent.com/31160531/202849647-922d75d6-570c-43fe-a4b3-fcb795d39f92.png)

Record from the CLI:

```bash
uv run tiktok-live-recorder -room_id <ROOM_ID>
```

Or use **Settings -> Record now** in the [web dashboard](#web-dashboard) with a username and/or room ID when the user is live.

## How to Enable Upload To Telegram

1. Go to https://my.telegram.org and log in with your number (`+{country code}{number}`).

   ![image](https://github.com/user-attachments/assets/f591b9d2-4189-4bfe-9180-f4484625eea2)

2. Open **API Development Tools** and create an app if needed.

   ![image](https://github.com/user-attachments/assets/89900d60-851e-4c6c-a20a-892dd99f7e24)

   ![image](https://github.com/user-attachments/assets/3e61e39d-81d9-4c93-ae26-c6bccf6a509c)

3. Copy `api_id` and `api_hash` into `config/telegram.json`:

```json
{
  "api_id": "your_api_id",
  "api_hash": "your_api_hash",
  "chat_id": "me"
}
```

   ![image](https://github.com/user-attachments/assets/b0a7fe9a-cb9b-413f-a5bf-2434146c63b3)

4. Enable uploads:

| Method | How |
|--------|-----|
| CLI | Pass `-telegram` when recording: `uv run tiktok-live-recorder -user creator1 -telegram` |
| Dashboard | **Settings -> Runtime** -> enable **Upload finished recordings to Telegram** -> save |

Credentials live in `telegram.json` (editable in the dashboard **Settings** panel). When uploads are enabled, finished MP4s are sent after conversion; recent status appears under **Settings**.

## Web Dashboard

The dashboard starts automatically in **watchlist**, **followers**, and **automatic** mode at `http://localhost:8787` (default bind `0.0.0.0:8787`). It is **not** available in **manual** mode.

There is no login. If the host is reachable from other machines, protect it with a firewall or reverse proxy.

| Flag | Purpose |
|------|---------|
| `-no-web` | Disable the dashboard |
| `-web-host` | Bind address (default `0.0.0.0`) |
| `-web-port` | Port (default `8787`) |

The UI updates live via **Server-Sent Events** (`GET /api/events`) with polling fallback. If the API is unreachable, a **connection banner** appears with **Retry now**.

### Summary strip and filters

The sticky summary strip shows live/recording/offline/paused/error counts, poll timing, app version, and (when focused) the selected user. **Click a chip** to filter the status list (All / Live / Recording / Offline / Paused / Errors). Recording users sort first; large watchlists show a **Show all users** control.

### Live status

- Per-user state: `offline`, `recording`, `converting`, `stopping`, `paused`, `convert_failed`, errors, etc.
- Room ID, elapsed time, file size, and active output path
- Last-poll summary: finished, skipped, and errors from the most recent check
- **Force check** - poll immediately (shows loading while a poll is in progress)
- **Stop** - graceful shutdown for an active recording
- **Watchlist only:** add/remove users (top bar); pause/resume (pause state in `config/watchlist_state.json`)
- **Mobile:** status cards replace the table on narrow viewports

### Recent activity

A feed of recent polls, recording starts/stops, and Telegram uploads (when enabled).

### User focus

Click a `@handle` to filter status and the media library to that user. Each profile includes a TikTok link and shareable URL: `http://localhost:8787/#user/<username>`. Press **Esc** or use **<- All users** to clear the filter.

### Media library

- Finished **MP4** files grouped by username under `output/<username>/`
- **Legacy recordings** (`output/<username>/legacy/`) are **hidden by default**; enable **Settings -> Runtime -> Legacy recordings** to show them (saved in `localStorage`)
- Sort: Newest, Oldest, Largest, A-Z user (preference saved in `localStorage`)
- Search by username or filename (`/` focuses search)
- Thumbnail previews for finished recordings (lazy load with IndexedDB cache)
- In-progress recordings and orphan `*_flv.mp4` files pinned and styled (`in progress`, `needs convert`); legacy items show a `legacy` tag when visible
- Docked in-browser player above the scrollable list (playback is not interrupted by library refreshes)
- Download or delete files (delete requires confirmation)
- **Convert leftover FLV** - convert orphan `*_flv.mp4` files that were never finalized (badge shows count). Skips files that belong to an active recording. See [Salvaging leftover recordings](#salvaging-leftover-recordings).

### Settings

Opens in a modal overlay (shortcut **`s`**):

- **Runtime** - poll interval (minutes), Telegram upload on/off (no restart), and **Legacy recordings** visibility in the media library (browser `localStorage`, off by default)
- **Record now** - start recording by username and/or room ID
- **Cookies / Telegram** - edit `cookies.json` and `telegram.json` in the browser
- **Recent Telegram uploads** - when uploads are enabled

### Keyboard shortcuts

Press **`?`** for the full list. Defaults:

| Key | Action |
|-----|--------|
| `/` | Focus media search |
| `Esc` | Close modal or clear user focus |
| `l` | Open logs |
| `s` | Open settings |

### Mode comparison

| Feature | Watchlist | Followers | Automatic | Manual |
|---------|-----------|-----------|-----------|--------|
| Dashboard | Yes | Yes | Yes | No |
| Add/remove users | Yes | No | No | - |
| Pause/resume | Yes | Yes | Yes | - |
| Force check | Yes | Yes | Yes | - |
| Record now | Yes | Yes | Yes | - |
| Convert leftover FLV | Yes | Yes | Yes | - |
| Logs / Settings modals | Yes | Yes | Yes | - |

## Salvaging Leftover Recordings

During recording, output is written to `TK_<user>_<timestamp>_flv.mp4`. When the stream ends, FFmpeg converts it to `TK_<user>_<timestamp>.mp4` and removes the `*_flv.mp4` on success.

If conversion fails (common with old FFmpeg on HEVC streams), the `*_flv.mp4` remains and the user may show **`convert_failed`** in live status.

**Fix FFmpeg first** ([FFmpeg and HEVC](#ffmpeg-and-hevc)), then salvage:

1. Open the dashboard **Media library**.
2. Click **Convert leftover FLV** (badge shows how many orphan files were found).
3. Confirm - conversion runs in the background; the badge updates when done.

Orphan files are `*_flv.mp4` on disk that are **not** the active output of a current recording. Active recordings are never touched.

## Log Viewer

Open **Logs** from the top bar (shortcut **`l`**). The modal tails `tiktok-recorder.log` via `GET /api/logs`.

| Control | Purpose |
|---------|---------|
| **Lines** | How many tail lines to load (100-1000) |
| **Level** | Minimum log level filter |
| **Auto-refresh** | Poll every 3 seconds |
| **Refresh** | Reload now |
| **Clear log** | Truncate the log file and delete rotation backups (`.1`, `.2`, `.3`) on demand |

**Log file location:** `tiktok-recorder.log` in the process working directory by default. Override with:

```bash
export TIKTOK_RECORDER_LOG_FILE=/var/log/tiktok-recorder.log
```

The file handler rotates at **5 MB** and keeps **3** backups. Rotation is automatic; **Clear log** is manual when you need to reclaim disk space. Clearing uses the open log handle (no separate file lock) so it is safe while the recorder is running. If the file cannot be cleared (e.g. permission error), the API returns an error toast.

## Restricted Countries

TikTok live may be blocked or restricted in:

1. Italy
2. Hong Kong
3. UK

Use a VPN or `-proxy` if you are in a restricted region. Valid cookies in `config/cookies.json` also help for followers mode and private accounts.

## Unrestricted Countries

Live access generally works without extra steps in:

Switzerland, Australia, Austria, Belgium, Brazil, Bulgaria, Canada, Czech Republic, Denmark, Estonia, Finland, France, Germany, Ireland, Israel, Japan, Latvia, Luxembourg, Moldova, Netherlands, New Zealand, North Macedonia, Norway, Poland, Portugal, Romania, Serbia, Singapore, Slovakia, Spain, Sweden, USA
