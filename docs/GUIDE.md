# Guide

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

5. Paste them into `config/cookies.json` (created automatically from `config/cookies.json.example` on first run):

```json
{
  "sessionid": "your_sessionid_value",
  "sessionid_ss": "your_sessionid_ss_value",
  "tt-target-idc": "useast2a"
}
```

For restricted or age-gated lives, `sessionid` is often required in addition to `sessionid_ss`. If you still get WAF/4003110 errors, export more browser cookies (e.g. `msToken`, `sid_tt`) into the same file.

Cookies are required for **followers** mode and for recording private or restricted accounts.

## How To Set Up the Watchlist

Watchlist mode polls multiple creators in one process and records each one that goes live.

1. Edit `config/users.json` (created from `config/users.json.example` on first run):

```json
{
  "users": [
    "creator1",
    "creator2",
    "creator3"
  ]
}
```

You can also use a plain JSON array:

```json
["creator1", "creator2"]
```

2. Run watchlist mode:

```bash
uv run tiktok-live-recorder -mode watchlist
```

3. (Optional) Change the poll interval in minutes (default 5):

```bash
uv run tiktok-live-recorder -mode watchlist -automatic_interval 3
```

**Alternatives to editing the file:**

```bash
# Comma-separated usernames
uv run tiktok-live-recorder -mode watchlist -user creator1,creator2

# Custom watchlist file
uv run tiktok-live-recorder -mode watchlist -users-file /path/to/my-list.json
```

When a recording ends, the watchlist is rechecked immediately instead of waiting for the next poll interval.

**Live reload:** if you use `config/users.json` or `-users-file`, you can add or remove usernames while the recorder is running. Changes apply on the next poll cycle. Removed users are no longer checked for new lives, but an in-progress recording for them is allowed to finish.

## How To Get Room_ID

1. Go to https://www.tiktok.com/@username/live
2. Open Developer Tools - `Ctrl+Shift+I` (Windows/Linux) or `Cmd+Option+I` (macOS)
3. Search for `room_id` with `Ctrl+F`

![image](https://user-images.githubusercontent.com/31160531/202849647-922d75d6-570c-43fe-a4b3-fcb795d39f92.png)

Then record with:

```bash
uv run tiktok-live-recorder -room_id <ROOM_ID>
```

## How to Enable Upload To Telegram

1. Go to https://my.telegram.org
2. Log in with your Telegram number in the format `+{country code}{your_number}`

   ![image](https://github.com/user-attachments/assets/f591b9d2-4189-4bfe-9180-f4484625eea2)

3. Click **API Development Tools**

   ![image](https://github.com/user-attachments/assets/89900d60-851e-4c6c-a20a-892dd99f7e24)

4. Create a new app (skip if you already have one)

   ![image](https://github.com/user-attachments/assets/3e61e39d-81d9-4c93-ae26-c6bccf6a509c)

5. Copy `api_id` and `api_hash` into `config/telegram.json` (created from `config/telegram.json.example` on first run):

```json
{
  "api_id": "your_api_id",
  "api_hash": "your_api_hash",
  "chat_id": "me"
}
```

   ![image](https://github.com/user-attachments/assets/b0a7fe9a-cb9b-413f-a5bf-2434146c63b3)

6. Record with the `-telegram` flag:

```bash
uv run tiktok-live-recorder -user creator1 -telegram
```

## Configuration Directory

All user-specific settings live in `config/` at the project root:

| File | Template | Purpose |
|------|----------|---------|
| `cookies.json` | `cookies.json.example` | TikTok session cookies |
| `users.json` | `users.json.example` | Watchlist usernames |
| `telegram.json` | `telegram.json.example` | Telegram API credentials |

Real config files are gitignored. Only the `*.example` templates are committed.

On first use, the recorder copies the matching `.example` file if the real file does not exist yet.

Override the config location with the `TIKTOK_RECORDER_CONFIG_DIR` environment variable.

## Restricted Countries

TikTok live may be blocked or restricted in:

1. Italy
2. Hong Kong
3. UK

Use a VPN or `-proxy` if you are in a restricted region. Valid cookies in `config/cookies.json` also help for followers mode and private accounts.

## Unrestricted Countries

Live access generally works without extra steps in:

Switzerland, Australia, Austria, Belgium, Brazil, Bulgaria, Canada, Czech Republic, Denmark, Estonia, Finland, France, Germany, Ireland, Israel, Japan, Latvia, Luxembourg, Moldova, Netherlands, New Zealand, North Macedonia, Norway, Poland, Portugal, Romania, Serbia, Singapore, Slovakia, Spain, Sweden, USA
