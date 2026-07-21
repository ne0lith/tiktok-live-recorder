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
- [Configuration](#configuration)
- [Recording Behavior](#recording-behavior)
- [Troubleshooting](#troubleshooting)
- [Changelog](CHANGELOG.md)
- [Guide](#guide)
- [Contributing](#contributing)
- [Community](#community)
- [Legal](#legal)

## Quick Start

**Prerequisites:** [Git](https://git-scm.com), [Python 3.11+](https://www.python.org/downloads/), [FFmpeg](https://ffmpeg.org/download.html), [uv](https://docs.astral.sh/uv/getting-started/installation/)

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
uv run python src/main.py -mode watchlist
```

Recordings are saved to `output/<username>/` by default.

## What's Different in This Fork

This fork adds reliability and workflow improvements on top of the upstream project:

- **Watchlist mode** - poll many users in one process; each live user records in a background thread
- **`config/` directory** - secrets and watchlists live outside `src/` with committed `.example` templates
- **WAF / restricted-live fallback** - when the API returns `4003110`, stream URLs are scraped from the live page HTML
- **Recording reliability** - stale ended rooms are rejected, CDN URLs are retried, and empty responses are skipped
- **Instance lock** - prevents two recorder processes from writing to the same output directory
- **Early watchlist re-poll** - when a recording ends, the watchlist is rechecked immediately instead of waiting for the full poll interval
- **`-ffmpeg-path`** - point at a custom FFmpeg binary

## Installation

<details>
<summary>Windows</summary>

Install [FFmpeg](https://ffmpeg.org/download.html) and add it to your `PATH`, then:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
git clone https://github.com/ne0lith/tiktok-live-recorder
cd tiktok-live-recorder
uv sync
uv run python src/main.py -h
```

</details>

<details>
<summary>Linux</summary>

```bash
sudo apt-get update && sudo apt-get install -y ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/ne0lith/tiktok-live-recorder
cd tiktok-live-recorder
uv sync
uv run python src/main.py -h
```

</details>

<details>
<summary>macOS</summary>

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
brew install ffmpeg
git clone https://github.com/ne0lith/tiktok-live-recorder
cd tiktok-live-recorder
uv sync
uv run python src/main.py -h
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
uv run python src/main.py -h
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
  -v ./output:/output \
  -v ./config:/app/config \
  tiktok-live-recorder \
  -output /output \
  -mode watchlist
```

The image ships only `config/*.example` templates. Mount `./config` so your real `cookies.json`, `users.json`, and `telegram.json` persist on the host.

</details>

## Command-Line Usage

```bash
uv run python src/main.py [options]
# or, after install:
uv run tiktok-live-recorder [options]
```

### Options

| Flag | Description |
|------|-------------|
| `-user <USERNAME>` | Username(s) to record. Separate multiple with commas. |
| `-users-file <PATH>` | JSON watchlist for watchlist mode (defaults to `config/users.json`). |
| `-url <URL>` | TikTok live URL to record from. |
| `-room_id <ROOM_ID>` | Room ID to record from. |
| `-mode <MODE>` | Recording mode: `manual`, `automatic`, `watchlist`, `followers`. |
| `-automatic_interval <MIN>` | Polling interval in minutes for automatic, watchlist, and followers modes (default: 5). |
| `-output <DIRECTORY>` | Output directory. Defaults to `output/<username>/` per user. |
| `-duration <SECONDS>` | Stop recording after this many seconds. |
| `-proxy <URL>` | HTTP proxy to bypass regional restrictions. |
| `-bitrate <BITRATE>` | Output bitrate for post-processing (e.g. `1M`, `1000k`). |
| `-ffmpeg-path <PATH>` | Path to a custom FFmpeg binary (default: `ffmpeg` on `PATH`). |
| `-telegram` | Upload the recording to Telegram when done. Requires `config/telegram.json`. |
| `-no-update-check` | Skip the automatic update check on startup. |
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
uv run python src/main.py -user creator1
```

Record from a live URL or room ID:

```powershell
uv run python src/main.py -url https://www.tiktok.com/@creator1/live
uv run python src/main.py -room_id 1234567890
```

### Automatic Examples

Poll one user every 5 minutes and record when they go live:

```powershell
uv run python src/main.py -mode automatic -user creator1
```

Change the poll interval to 10 minutes:

```powershell
uv run python src/main.py -mode automatic -user creator1 -automatic_interval 10
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
uv run python src/main.py -mode watchlist
```

Or pass users on the command line:

```powershell
uv run python src/main.py -mode watchlist -user creator1,creator2,creator3
```

Change the poll interval (minutes):

```powershell
uv run python src/main.py -mode watchlist -automatic_interval 3
```

Each poll cycle logs every user's status (`offline`, `recording`, `live -> starting`). When multiple streams run at once, log lines are prefixed with `[@username]`.

When using `config/users.json` or `-users-file`, edits to the watchlist are picked up on the next poll cycle - no restart needed. Users removed from the file stop being polled; any active recording for them finishes first. A CLI `-user` list is fixed for that run and is not reloaded.

## Configuration

User-specific files live in [`config/`](config/):

| File | Purpose |
|------|---------|
| `cookies.json` | TikTok session cookies (gitignored) |
| `users.json` | Watchlist usernames (gitignored) |
| `telegram.json` | Telegram upload credentials (gitignored) |

Committed `*.example` templates are copied automatically on first use. Override the config directory with the `TIKTOK_RECORDER_CONFIG_DIR` environment variable.

See [docs/GUIDE.md](docs/GUIDE.md) for step-by-step setup instructions.

## Recording Behavior

### Output paths

- **Default:** `output/<username>/TK_<username>_<timestamp>_flv.mp4` (converted to `.mp4` after recording)
- **Custom `-output`:** files are saved directly in that directory; the username is still included in the filename

### Watchlist threading

Watchlist mode runs one polling loop in the main thread. When a user goes live, a background thread starts their recording. The poll loop keeps checking other users and skips anyone already being recorded.

When a recording ends, the watchlist is rechecked immediately instead of waiting for the full `-automatic_interval`.

### Watchlist file reload

If the watchlist comes from `config/users.json` or `-users-file`, you can edit that file while the recorder is running. The next poll cycle reloads the list automatically. Users passed via `-user` on the command line are not reloaded.

### Instance lock

Only one recorder process can use a given output directory at a time. If you see an error about another recorder already running, stop the existing process first or use a different `-output` path.

### Reliability features

- Rejects ended TikTok rooms that still expose stale stream URLs
- Tries alternate stream URLs when a CDN pull fails
- Skips empty CDN responses
- Falls back to page HTML parsing when the API is blocked by WAF (`4003110`)

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

Install FFmpeg and ensure it is on your `PATH`, or pass `-ffmpeg-path` with the full path to the binary.

## Guide

- [How to set cookies](docs/GUIDE.md#how-to-set-cookies)
- [How to set up the watchlist](docs/GUIDE.md#how-to-set-up-the-watchlist)
- [How to get room_id](docs/GUIDE.md#how-to-get-room_id)
- [How to enable upload to Telegram](docs/GUIDE.md#how-to-enable-upload-to-telegram)
- [Restricted countries](docs/GUIDE.md#restricted-countries)

## Contributing

Contributions are welcome! Open an [issue](https://github.com/ne0lith/tiktok-live-recorder/issues) or [pull request](https://github.com/ne0lith/tiktok-live-recorder/pulls). See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## Community

- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security Policy](SECURITY.md) — report vulnerabilities privately

When a newer version is available, the recorder prints a notification with upgrade instructions (`git pull` or re-clone). It does not modify your local files automatically.

## Legal

This code is in no way affiliated with, authorized, maintained, sponsored or endorsed by TikTok or any of its affiliates or subsidiaries. Use at your own risk.
