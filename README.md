<div align="center">

# TikTok Live Recorder

_A tool for recording TikTok live streams._

![Python](https://img.shields.io/badge/python-3.11+-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
[![Licence](https://img.shields.io/github/license/ne0lith/tiktok-live-recorder?style=for-the-badge)](./LICENSE)
[![Pytest](https://img.shields.io/github/actions/workflow/status/ne0lith/tiktok-live-recorder/pytest.yml?branch=main&style=for-the-badge&label=tests)](https://github.com/ne0lith/tiktok-live-recorder/actions/workflows/pytest.yml)
[![Ruff](https://img.shields.io/github/actions/workflow/status/ne0lith/tiktok-live-recorder/ruff.yml?branch=main&style=for-the-badge&label=ruff)](https://github.com/ne0lith/tiktok-live-recorder/actions/workflows/ruff.yml)

Record TikTok live streams to disk with support for watchlists, restricted/WAF-blocked lives, and reliable long-running polling.

Forked from [Michele0303/tiktok-live-recorder](https://github.com/Michele0303/tiktok-live-recorder).

</div>

## Table of Contents

- [Quick Start](#quick-start)
- [What's Different in This Fork](#whats-different-in-this-fork)
- [Installation](#installation)
- [Command-Line Usage](#command-line-usage)
  - [Web dashboard](#web-dashboard)
- [Configuration](#configuration)
- [Recording Behavior](#recording-behavior)
- [Troubleshooting](#troubleshooting)
- [Changelog](CHANGELOG.md)
- [Guide](#guide)
- [Contributing](#contributing)
- [Community](#community)
- [Legal](#legal)

## Quick Start

**Prerequisites:** [Git](https://git-scm.com), [Python 3.11+](https://www.python.org/downloads/), [uv](https://docs.astral.sh/uv/getting-started/installation/), and **FFmpeg** on Windows/macOS/Termux (Linux: **optional** - a capable build is installed automatically on first run; see [FFmpeg and HEVC](docs/GUIDE.md#ffmpeg-and-hevc))

```powershell
git clone https://github.com/ne0lith/tiktok-live-recorder
cd tiktok-live-recorder
uv sync
```

On first run, the recorder creates blank config files from the committed `*.example` templates in [`config/`](config/).

1. Add usernames to `config/users.json`
2. (Optional) Add TikTok cookies to `config/cookies.json` for login-required or restricted lives
3. Start watchlist mode:

```powershell
uv run tiktok-live-recorder -mode watchlist
```

Recordings are saved to `output/<username>/` by default. The [web dashboard](docs/GUIDE.md#web-dashboard) opens automatically in watchlist, followers, and automatic mode.

## What's Different in This Fork

This fork adds reliability and workflow improvements on top of the upstream project:

- **Conversion queue** - every finished recording enqueues `_flv.mp4` -> `.mp4` conversion with bounded concurrency (default 1); no inline ffmpeg in recording threads ([details](docs/GUIDE.md#conversion-queue-and-post-processing))
- **In-app salvage pipeline** - multi-pass convert with ffprobe validation before deleting `*_flv.mp4`; keeps broken intermediates when recovery fails
- **Persisted runtime settings** - poll interval, Telegram uploads, max concurrent converts, and experimental identity tracking survive restarts via `config/runtime_settings.json`
- **Web dashboard** - live operator UI on port `8787` with SSE updates, activity feed, media library, logs, and settings ([details](docs/GUIDE.md#web-dashboard))
- **In-app updates** - git clone installs can check and apply updates from **Settings -> Application** with scope-aware hot reload or graceful restart ([details](docs/GUIDE.md#updating-the-application))
- **Watchlist mode** - poll many users in one process; each live user records in a background thread
- **`config/` directory** - secrets and watchlists live outside `src/` with committed `.example` templates
- **TikTok HEVC FLV support** - startup FFmpeg capability probe; on Linux, automatic BtbN FFmpeg n8.1 install into `.vendor/ffmpeg/` when ffmpeg is missing or too old ([details](docs/GUIDE.md#ffmpeg-and-hevc))
- **Salvage leftover FLVs** - dashboard action to move orphan `*_flv.mp4` files into `to_fix/` for external conversion with `fix-mp4s` ([details](docs/GUIDE.md#salvaging-leftover-recordings))
- **WAF / restricted-live fallback** - when the API returns `4003110`, stream URLs are scraped from the live page HTML
- **Recording reliability** - stale ended rooms are rejected, CDN URLs are retried (with signed-query normalization), and empty responses are skipped
- **Instance lock** - prevents two recorder processes from writing to the same output directory
- **Early watchlist re-poll** - when a recording ends, the watchlist is rechecked immediately instead of waiting for the full poll interval
- **`-ffmpeg-path`** - point at a custom FFmpeg binary (resolved and probed at startup)

## Installation

<details>
<summary>Windows</summary>

Install [FFmpeg](https://ffmpeg.org/download.html) and add it to your `PATH`, then:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
git clone https://github.com/ne0lith/tiktok-live-recorder
cd tiktok-live-recorder
uv sync
uv run tiktok-live-recorder -h
```

</details>

<details>
<summary>Linux</summary>

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/ne0lith/tiktok-live-recorder
cd tiktok-live-recorder
uv sync
uv run tiktok-live-recorder -h
```

**FFmpeg is not required before first run.** On startup the app probes for a capable binary; if none is found (or distro FFmpeg is too old for TikTok HEVC), it downloads BtbN FFmpeg n8.1 into `.vendor/ffmpeg/` (gitignored, ~100 MB one-time; requires outbound HTTPS). You can still `apt install ffmpeg` if you prefer a system package - the vendor build is used when the probe fails. See [FFmpeg and HEVC](docs/GUIDE.md#ffmpeg-and-hevc).

</details>

<details>
<summary>macOS</summary>

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
brew install ffmpeg
git clone https://github.com/ne0lith/tiktok-live-recorder
cd tiktok-live-recorder
uv sync
uv run tiktok-live-recorder -h
```

</details>

<details>
<summary>Android - Termux</summary>

Install Termux from [F-Droid](https://f-droid.org/packages/com.termux/) (avoid the Play Store version).

```bash
pkg update && pkg upgrade
pkg install git ffmpeg uv tur-repo
pkg uninstall python
pkg install python3.11
git clone https://github.com/ne0lith/tiktok-live-recorder
cd tiktok-live-recorder
uv sync
uv run tiktok-live-recorder -h
```

</details>

<details>
<summary>Docker</summary>

Build the image locally:

```bash
git clone https://github.com/ne0lith/tiktok-live-recorder
cd tiktok-live-recorder
docker build -t tiktok-live-recorder .
```

Run with mounted output and config directories:

```bash
docker run \
  -p 8787:8787 \
  -v ./output:/output \
  -v ./config:/app/config \
  tiktok-live-recorder \
  -output /output \
  -mode watchlist
```

The image ships only `config/*.example` templates. Mount `./config` so your real `cookies.json`, `users.json`, `runtime_settings.json`, and `telegram.json` persist on the host. Expose port **8787** for the dashboard (see [Web dashboard](docs/GUIDE.md#web-dashboard)).

The container image does not need a capable distro FFmpeg. On first start the same Linux vendor install runs into `/app/.vendor/ffmpeg/` when needed. Persist that directory with a volume if you want to avoid re-downloading after container recreation.

In-app updates from the dashboard are **not** supported inside Docker - rebuild the image and recreate the container when upgrading ([updating guide](docs/GUIDE.md#updating-the-application)).

</details>

## Command-Line Usage

```bash
uv run tiktok-live-recorder [options]
# or:
uv run python -m tiktok_live_recorder [options]
```

### Options

| Flag | Description |
|------|-------------|
| `-user <USERNAME>` | Username(s) to record. Separate multiple with commas. |
| `-users-file <PATH>` | JSON watchlist for watchlist mode (defaults to `config/users.json`). |
| `-url <URL>` | TikTok live URL to record from. |
| `-room_id <ROOM_ID>` | Room ID to record from. |
| `-mode <MODE>` | Recording mode: `manual`, `automatic`, `watchlist`, `followers`. |
| `-automatic_interval <MIN>` | Polling interval in minutes for automatic, watchlist, and followers modes. Default: from `config/runtime_settings.json`, else **5**. |
| `-max-concurrent-converts <N>` | Max parallel FLV->MP4 jobs when streams end (default: from `runtime_settings.json`, else **1**). |
| `-output <DIRECTORY>` | Output directory. Defaults to `output/<username>/` per user. |
| `-duration <SECONDS>` | Stop recording after this many seconds. |
| `-proxy <URL>` | HTTP proxy to bypass regional restrictions. |
| `-bitrate <BITRATE>` | Output bitrate for post-processing (e.g. `1M`, `1000k`). |
| `-ffmpeg-path <PATH>` | Custom FFmpeg binary. Probed at startup; on Linux, vendor BtbN n8.1 is installed automatically when ffmpeg is missing or the chosen binary cannot demux TikTok HEVC FLV. Default: `ffmpeg` on `PATH`. |
| `-telegram` | Upload finished recordings to Telegram. Requires `config/telegram.json`. Can also be toggled from the dashboard. |
| `-no-identity-tracking` | Force off experimental `use_identity_tracking` for this run (legacy username-only polling). Identity tracking is experimental and not guaranteed to be developed further. |
| `-no-update-check` | Skip the automatic update check on startup. |
| `-web-host <HOST>` | Dashboard bind address (default: `0.0.0.0`). Available in watchlist, followers, and automatic modes. |
| `-web-port <PORT>` | Dashboard port (default: `8787`). |
| `-no-web` | Disable the built-in web dashboard. |
| `--version`, `-V` | Print the installed version and exit. |

### Recording Modes

| Mode | Behavior |
|------|----------|
| **`manual`** *(default)* | Record immediately if the user is currently live. |
| **`automatic`** | Poll **one** user at regular intervals and record when they go live. |
| **`watchlist`** | Poll a list of users forever. Each live user records in a background thread while the main loop keeps checking the rest. |
| **`followers`** | Poll all TikTok accounts you follow. Requires valid `config/cookies.json`. |

**`automatic` vs `watchlist`:** use `automatic` for a single creator. Use `watchlist` when you want many usernames in one process.

### Manual Examples

Record a user who is live right now:

```powershell
uv run tiktok-live-recorder -user creator1
```

Record from a live URL or room ID:

```powershell
uv run tiktok-live-recorder -url https://www.tiktok.com/@creator1/live
uv run tiktok-live-recorder -room_id 1234567890
```

### Automatic Examples

Poll one user every 5 minutes and record when they go live:

```powershell
uv run tiktok-live-recorder -mode automatic -user creator1
```

Change the poll interval to 10 minutes:

```powershell
uv run tiktok-live-recorder -mode automatic -user creator1 -automatic_interval 10
```

The dashboard is available in automatic mode so you can adjust the poll interval or trigger **Record now** without restarting.

### Followers Examples

Poll accounts you follow (requires `config/cookies.json`):

```powershell
uv run tiktok-live-recorder -mode followers
```

### Watchlist Examples

Edit `config/users.json`:

```json
{
  "users": ["creator1", "creator2", "creator3"]
}
```

Run watchlist mode:

```powershell
uv run tiktok-live-recorder -mode watchlist
```

Or pass users on the command line:

```powershell
uv run tiktok-live-recorder -mode watchlist -user creator1,creator2,creator3
```

Change the poll interval (minutes):

```powershell
uv run tiktok-live-recorder -mode watchlist -automatic_interval 3
```

Each poll cycle logs every user's status (`offline`, `recording`, `live -> starting`). When multiple streams run at once, log lines are prefixed with `[@username]`.

See [Watchlist file reload](#watchlist-file-reload) for live edits to `config/users.json`.

### Web dashboard

Runs in **watchlist**, **followers**, and **automatic** mode at `http://localhost:8787` by default (`-web-host` / `-web-port` to change). **No authentication** - restrict access on shared networks.

Use it to monitor live status, manage recordings, move leftover FLVs to `to_fix/`, tail/clear logs, adjust runtime settings, and apply updates (git clone installs) without editing files by hand. Full feature list, keyboard shortcuts, FFmpeg notes, and workflow details: **[Web dashboard guide](docs/GUIDE.md#web-dashboard)**.

Disable with `-no-web`.

## Configuration

User-specific files live in [`config/`](config/):

| File | Purpose |
|------|---------|
| `cookies.json` | TikTok session cookies (gitignored) |
| `users.json` | Watchlist usernames (gitignored) |
| `watchlist_state.json` | Paused users - auto-managed by the dashboard (gitignored) |
| `runtime_settings.json` | Poll interval, Telegram uploads, max concurrent converts, experimental identity tracking (gitignored) |
| `user_identities.json` | Experimental watchlist identity map (auto-managed; gitignored) |
| `telegram.json` | Telegram upload credentials (gitignored) |

Committed `*.example` templates are copied automatically on first use. Override the config directory with the `TIKTOK_RECORDER_CONFIG_DIR` environment variable. Override the log file path with `TIKTOK_RECORDER_LOG_FILE` (see [Log viewer](docs/GUIDE.md#log-viewer)).

Step-by-step setup: [docs/GUIDE.md](docs/GUIDE.md).

## Recording Behavior

### Output paths

- **Default:** `output/<username>/TK_<username>_<timestamp>_flv.mp4` while recording, then converted to `TK_<username>_<timestamp>.mp4`
- **Custom `-output`:** files are saved directly in that directory; the username is still included in the filename
- **Legacy folder:** older recordings may live under `output/<username>/legacy/`; the dashboard hides them by default (**Settings -> Runtime -> Legacy recordings**)

### Post-recording conversion

When a stream ends, the recorder **always** enqueues conversion on a shared queue (recording threads never call ffmpeg directly). A worker runs the full `_flv.mp4` -> `.mp4` pipeline, including multi-pass salvage when the first encode is not dashboard-playable (H.264 + `yuv420p`). The `*_flv.mp4` is deleted only after ffprobe validation succeeds.

Convert jobs are tracked in the dashboard **convert-queue strip** (queued / converting with percent). At most **N** ffmpeg jobs run at once (`-max-concurrent-converts` or **Settings -> Runtime -> Max concurrent converts**; default **1**). Conversion does **not** block polling or recording the same user again if they go live.

If every pass fails, the `*_flv.mp4` is kept; use **Move leftover FLVs** ([salvage guide](docs/GUIDE.md#salvaging-leftover-recordings)).

### Watchlist threading

Watchlist mode runs one polling loop in the main thread. When a user goes live, a background thread starts their recording. The poll loop keeps checking other users and skips anyone already being recorded (same room id / active recording only - not converts).

When a recording ends, the watchlist is rechecked immediately instead of waiting for the full `-automatic_interval`.

### Watchlist file reload

If the watchlist comes from `config/users.json` or `-users-file`, you can edit that file while the recorder is running. The next poll cycle reloads the list automatically. In watchlist mode you can also add or remove users from the [dashboard](docs/GUIDE.md#web-dashboard). Users passed via `-user` on the command line are not reloaded.

### Instance lock

Only one recorder process can use a given output directory at a time. If you see an error about another recorder already running, stop the existing process first or use a different `-output` path.

### Reliability features

- Rejects ended TikTok rooms that still expose stale stream URLs
- Tries alternate stream URLs when a CDN pull fails; normalizes signed query params so URL rotation does not cause endless retries
- Prefers origin/source FLV (from the audio-only SDK URL with `only_audio` removed) over advertised `hd` 720p, and falls back to `hd`/`or4` if that URL fails or has no video
- Stops recording after repeated CDN failures with no new bytes written
- Skips empty CDN responses
- Falls back to page HTML parsing when the API is blocked by WAF (`4003110`)
- Sets **`convert_failed`** when a recording ends but final `.mp4` conversion did not succeed

## Troubleshooting

### Login-required or private lives

Set `sessionid`, `sessionid_ss`, and `tt-target-idc` in `config/cookies.json`. See [How to set cookies](docs/GUIDE.md#how-to-set-cookies).

If cookies are loaded but access is still denied, your session may be expired - refresh the values from your browser.

### WAF / 4003110 errors

The recorder automatically tries to parse stream URLs from the live page HTML when the API is blocked. This works best when:

- Valid cookies are set in `config/cookies.json`
- You are recording by username (not room ID alone)

If problems persist, try a VPN or `-proxy`, or export additional browser cookies (`msToken`, `sid_tt`) into `config/cookies.json`.

### "Another recorder is already running"

Another process is using the same output directory. Stop it, or point this run at a different `-output` path.

### Watchlist shows no users

Make sure `config/users.json` has at least one username, or pass `-user` / `-users-file` on the command line.

### FFmpeg not found

On **Linux**, FFmpeg is installed automatically at startup when missing or incapable ([FFmpeg and HEVC](docs/GUIDE.md#ffmpeg-and-hevc)). If the vendor download fails (network, unsupported architecture), startup exits with install hints.

On **Windows, macOS, and Termux**, install FFmpeg and ensure it is on your `PATH`, or pass `-ffmpeg-path` with the full path to the binary.

### HEVC / conversion failed (`convert_failed`)

Many TikTok lives use **HEVC in legacy FLV** (codec id 12). The in-app pipeline tries standard encode, then salvage passes (corrupt-input discard, timestamp reset, audio fallbacks, HEVC rewrite, MKV intermediate) before giving up.

1. Restart the recorder and check startup logs for `capable for TikTok HEVC FLV` vs `NOT capable`.
2. On Linux, let the automatic BtbN install complete (first run may pause while downloading).
3. Check the convert-queue strip for queued/converting jobs - conversion may still be in progress; raise **Max concurrent converts** in Settings if many streams ended at once.
4. For leftover `*_flv.mp4` files after **`convert_failed`**, use the dashboard **Move leftover FLVs** button ([guide](docs/GUIDE.md#salvaging-leftover-recordings)), then run `fix-mp4s` against `to_fix/` (NVENC by default, or `-AppPipeline` for the same salvage the recorder uses).
5. Or pass `-ffmpeg-path` to FFmpeg 8.0+ that supports legacy HEVC FLV.

### Log file growing large

The recorder writes `tiktok-recorder.log` (rotates at 5 MB, keeps 3 backups). Override the path with `TIKTOK_RECORDER_LOG_FILE`. To reclaim disk space on demand, open **Logs** in the dashboard and click **Clear log** ([log viewer guide](docs/GUIDE.md#log-viewer)).

### In-app update unavailable or failed

In-app apply requires a **git clone** with **`git`** and **`uv`** on `PATH` and a writable project directory. Docker installs must rebuild manually. If **Update now** is missing, use `git pull`, `uv sync`, and restart from the shell ([updating guide](docs/GUIDE.md#updating-the-application)).

If a restart-scope update times out while waiting for converts, active ffmpeg jobs may still be running - wait for them to finish or stop the recorder, then upgrade manually. Do not force-kill during conversion if you want to keep partial `*_flv.mp4` files for salvage.

## Guide

- [Web dashboard](docs/GUIDE.md#web-dashboard)
- [Updating the application](docs/GUIDE.md#updating-the-application)
- [Conversion queue and post-processing](docs/GUIDE.md#conversion-queue-and-post-processing)
- [FFmpeg and HEVC](docs/GUIDE.md#ffmpeg-and-hevc)
- [Salvaging leftover recordings](docs/GUIDE.md#salvaging-leftover-recordings)
- [Log viewer](docs/GUIDE.md#log-viewer)
- [How to set cookies](docs/GUIDE.md#how-to-set-cookies)
- [How to set up the watchlist](docs/GUIDE.md#how-to-set-up-the-watchlist)
- [How to get room_id](docs/GUIDE.md#how-to-get-room_id)
- [How to enable upload to Telegram](docs/GUIDE.md#how-to-enable-upload-to-telegram)
- [Restricted countries](docs/GUIDE.md#restricted-countries)

## Contributing

Contributions are welcome! Open an [issue](https://github.com/ne0lith/tiktok-live-recorder/issues) or [pull request](https://github.com/ne0lith/tiktok-live-recorder/pulls). See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## Community

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security Policy](SECURITY.md) - report vulnerabilities privately

When a newer version is available, the recorder prints a notification on startup with upgrade instructions (`git pull` + `uv sync`). Git clone installs can also check and apply updates from the [dashboard](docs/GUIDE.md#updating-the-application). Docker and other non-git installs must rebuild or update manually.

## Legal

This code is in no way affiliated with, authorized, maintained, sponsored or endorsed by TikTok or any of its affiliates or subsidiaries. Use at your own risk.
