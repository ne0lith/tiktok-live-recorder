# Guide

- [Configuration directory](#configuration-directory)
- [How to set cookies](#how-to-set-cookies)
- [How to set up the watchlist](#how-to-set-up-the-watchlist)
- [How to get room_id](#how-to-get-room_id)
- [How to enable upload to Telegram](#how-to-enable-upload-to-telegram)
- [Web dashboard](#web-dashboard)
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

### Live status

- Per-user state (recording, offline, paused, error, …), room ID, elapsed time, file size, and active output path
- Last-poll summary: finished, skipped, and errors from the most recent check
- **Force check** - poll immediately
- **Stop** - graceful shutdown for an active recording
- **Watchlist only:** add/remove users; pause/resume (pause state in `config/watchlist_state.json`)

### User profiles

Click a `@handle` to filter status and recordings to that user. Each profile includes a TikTok link and a shareable URL: `http://localhost:8787/#user/<username>`. Use **<- All users** to clear the filter.

### Media library

- MP4s grouped by username (includes `output/<username>/legacy/`)
- Search, collapsible sections, shared in-browser player
- Download or delete files (delete requires confirmation)

### Settings

Opens under the top bar:

- **Runtime** - poll interval (minutes) and Telegram upload on/off (no restart)
- **Record now** - start recording by username and/or room ID
- **Cookies / Telegram** - edit `cookies.json` and `telegram.json` in the browser
- **Recent Telegram uploads** - when uploads are enabled

### Mode comparison

| Feature | Watchlist | Followers | Automatic | Manual |
|---------|-----------|-----------|-----------|--------|
| Dashboard | Yes | Yes | Yes | No |
| Add/remove users | Yes | No | No | - |
| Pause/resume | Yes | Yes | Yes | - |
| Force check | Yes | Yes | Yes | - |
| Record now | Yes | Yes | Yes | - |

## Restricted Countries

TikTok live may be blocked or restricted in:

1. Italy
2. Hong Kong
3. UK

Use a VPN or `-proxy` if you are in a restricted region. Valid cookies in `config/cookies.json` also help for followers mode and private accounts.

## Unrestricted Countries

Live access generally works without extra steps in:

Switzerland, Australia, Austria, Belgium, Brazil, Bulgaria, Canada, Czech Republic, Denmark, Estonia, Finland, France, Germany, Ireland, Israel, Japan, Latvia, Luxembourg, Moldova, Netherlands, New Zealand, North Macedonia, Norway, Poland, Portugal, Romania, Serbia, Singapore, Slovakia, Spain, Sweden, USA
