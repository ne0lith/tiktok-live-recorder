# Changelog

All notable changes in this fork since upstream `7.7.1`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [8.20.6] - 2026-08-03

### Added

- **Dashboard**: Recent activity sits under the top bar; Poll / Recording / Media / Telegram chips hide noisy event types (saved in `localStorage`)

### Changed

- **Dashboard summary strip**: filters and meta are two left-aligned rows (no right-floated meta chips)
- **Live status ops**: poll/convert summaries use a compact digest with count pills and capped name lists instead of a wrapping dump

### Fixed

- **Convert queue positions**: dashboard `#N` / "Next" labels are live 1-based ranks among currently waiting jobs (no stale duplicates or off-by-ones after jobs ahead finish)

## [8.20.5] - 2026-08-03

### Fixed

- **Convert vs recording**: post-record MP4 conversion no longer keeps a username "busy", so watchlist polling and a new live can start while prior sessions are still queued/converting
- **Per-user Check**: priority Check always re-hits TikTok (clears `checked_this_cycle`, nests during an in-progress poll, and checks paused users)
- **Per-user Check vs full poll**: Check pauses an in-progress watchlist poll, runs all queued Checks (spam-safe), then resumes the remaining users; only global Force check / recording-ended recheck aborts and restarts the cycle

### Changed

- **Dashboard / docs**: convert progress lives in the convert-queue / `media_jobs` strip; user rows show live recording state only

## [8.20.4] - 2026-08-02

### Fixed

- **Media library refresh**: manual Refresh always fetches a fresh library scan (no browser cache), clears deferred SSE state, and rebuilds the card list so deleted or missing files no longer linger as ghost cards

## [8.20.3] - 2026-08-02

### Fixed

- **Media library**: deleting a recording removes its card immediately instead of leaving a stale entry until refresh; fixes ghost cards after delete when the player was open or SSE had deferred a library update

## [8.20.2] - 2026-08-02

### Added

- **Dashboard -> Settings -> Application**: in-app update check and apply for git clone installs (`git pull` + `uv sync`)
- **Scope-aware updates**: dashboard-only changes hot-reload without restart; backend Python changes wait for recordings and converts to finish, then restart gracefully
- **Update API**: `GET /api/update`, `POST /api/update/check`, `POST /api/update/apply`, `GET /api/update/status`; progress via existing SSE status stream

### Changed

- **Version display**: dashboard cache-busting uses on-disk `pyproject.toml` version (`get_repo_version`); API reports both running and repo versions
- **Docs**: README and GUIDE cover in-app updates, Docker limitations, and Settings -> Application workflow

## [8.20.1] - 2026-08-02

### Added

- **Dashboard**: convert queue strip under Live status, summary chip, and **Media** activity entries when manual **Fix video** / **Convert** jobs are queued, started, and finished
- **Status API**: `media_jobs` lists in-flight manual repair/convert jobs with queue position

### Fixed

- **Manual repair**: log queue/start/finish events; track jobs for the full queue lifecycle (not only on completion)
- **Thumbnails**: clear unplayable-probe cache after a successful in-place MP4 repair so previews can regenerate

## [8.20.0] - 2026-08-02

### Added

- **Media player**: **Fix video** / **Convert** button when a recording has no thumbnail (broken MP4 or orphan `*_flv.mp4`); queues the in-app salvage pipeline via `POST /api/media/{username}/{filename}/repair`
- **Conversion**: `repair_mp4_file()` re-encodes unplayable MP4s in place through the same salvage passes used after recording

## [8.19.0] - 2026-08-02

### Added

- **Conversion queue**: every recording enqueues `_flv.mp4` -> final `.mp4` conversion with bounded concurrency (`max_concurrent_converts`, default 1); configurable via CLI (`-max-concurrent-converts`), web Settings, and persisted `config/runtime_settings.json`
- **Status API/UI**: `convert_queued` state, queue stats (`convert_queue`), and queue position while waiting for a convert slot

### Changed

- **Conversion**: recording threads no longer run ffmpeg inline; all post-record converts go through the shared queue
- **Runtime settings**: `automatic_interval_minutes`, `use_telegram`, and `max_concurrent_converts` persist across restarts
- **Docs**: README and GUIDE cover conversion queue, runtime settings, and in-app salvage pipeline

### Fixed

- **Conversion**: multi-pass salvage pipeline (discard-corrupt input, timestamp reset, audio fallbacks, HEVC rewrite, MKV intermediate) with ffprobe validation before deleting `*_flv.mp4`
- **Conversion**: ignore ffmpeg progress lines with `out_time_us=N/A` so long encodes do not crash mid-run
- **Watchlist/status**: keep entries visible through `convert_queued` / `converting` after the recording thread exits

## [8.18.1] - 2026-08-01

### Changed

- **Docs/scripts**: use ASCII hyphens instead of em dashes in changelog, guide, and `fix-mp4s` failure output

## [8.18.0] - 2026-08-01

### Added

- **Dashboard**: **Hide paused** toggle on the status summary strip (persisted in `localStorage`; paused users stay visible when a profile is focused)
- **Media player**: watchlist user actions (Stop, Pause, Check, etc.) and **Delete** while a file is playing

### Changed

- **Dashboard**: **Move leftover FLVs** replaces **Convert leftover FLV** - orphan `*_flv.mp4` files are moved to repo-root `to_fix/` (flat) instead of converted in-app; button is hidden when none are found. API: `GET /api/media/leftover-flv`, `POST /api/media/move-leftover-flv` (replaces `pending-convert` / `convert-pending`).
- **Scripts**: `fix-mp4s` - timestamp reset, full-range JPEG (`yuvj420p`) handling, audio encode fallbacks, and failure logs under `_fix-mp4s-failures/`

### Fixed

- **Watchlist**: priority checks (add user, per-user Check) and Force check now interrupt an in-progress poll between user checks instead of waiting for the full cycle to finish

## [8.17.0] - 2026-07-30

### Added

- **Scripts**: `scripts/fix-mp4s.ps1` batch re-encode for dashboard-playable H.264 (NVENC by default)
- **Scripts**: `scripts/resolve-fix-mp4s-paths.ps1` shared `-InputDir` / `-OutputDir` prompting and validation
- **Dev tooling**: `poethepoet` tasks `fix-mp4s` and `delete-verified-sources` (`uv run poe <task> …`)

### Changed

- **Scripts**: `fix-mp4s` and `delete-verified-sources` use `-InputDir` / `-OutputDir` (replacing `-Dir` / `-OutRoot`)
- **Scripts**: `delete-verified-sources` uses shared routing/path helpers; no hardcoded drive paths


### Added

- **Media library**: card grid layout with portrait thumbnails so more recordings fit on screen
- **Live status**: watchlist rows show finalized library size per user (excludes in-progress and orphan FLV)
- **Scripts**: shared `fix-mp4s` output routing for TikTok (`TK_*`) and phone export (`*_IMG_*`) filenames, plus verified-source cleanup helper

### Changed

- **Media player**: Close button stays inside the player panel; username is the primary heading with a subtler "Now playing" label
- **Media library**: centered empty-state message when a profile filter has no recordings

## [8.15.5] - 2026-07-29

### Added

- **Watchlist**: per-user **Check** button in the live status table runs a priority poll for that user only (full **Force check** still polls everyone)
- **Watchlist**: adding a user from the dashboard checks only that user instead of triggering a full watchlist poll

## [8.15.4] - 2026-07-29

### Changed

- **Watchlist poll**: shuffle user order each cycle and wait 0.5s between users to reduce API burst load; poll plan logged at INFO (count, spacing) and full order at DEBUG

## [8.15.3] - 2026-07-29

### Fixed

- **Watchlist poll**: euler fallback treats offline users as offline (not Room ID errors); retries transient network failures; falls back when signed TikTok fetch fails; logs one tikrec-unavailable warning per poll cycle
- **Watchlist poll**: network errors are labeled `(network error)` in the poll summary
- **Thumbnails**: skip `*_flv.mp4` recordings; ffprobe pre-check with negative cache for corrupt/incomplete MP4s (avoids repeated `moov atom not found` warnings)
- **Logging**: disable logger propagation to avoid duplicate console lines when a parent handler is present

## [8.15.2] - 2026-07-29

### Changed

- **Media library**: active in-progress recordings are hidden from the library; orphan `*_flv.mp4` files still appear as `needs convert`

## [8.15.1] - 2026-07-26

### Fixed

- **Media thumbnails**: fix FFmpeg temp output path (`.thumb.tmp.jpg` instead of `.thumb.jpg.tmp`) so JPEG muxer is detected and server-side previews generate correctly

## [8.15.0] - 2026-07-26

### Added

- **Media library thumbnails**: server-generated JPEG previews cached on disk next to each recording (`*.thumb.jpg`); shared across browsers and sessions via `/media/.../thumb` endpoints

## [8.14.5] - 2026-07-26

### Fixed

- **Dashboard boot**: fix broken module import that prevented the page from loading after the legacy-recordings setting was added

## [8.14.4] - 2026-07-26

### Added

- **Media library**: Settings toggle to show or hide legacy recordings (`output/<user>/legacy/`); hidden by default, persisted in browser `localStorage`

### Changed

- **Docs**: align README and GUIDE with current dashboard media library and legacy visibility setting

## [8.14.3] - 2026-07-26

### Fixed

- **Media library profile filter**: clicking a user in Live status again filters the library to that user's recordings (clear via the focus chip or Esc)

## [8.14.2] - 2026-07-26

### Fixed

- **Now playing header**: show `@username` prominent with filename as smaller secondary text
- **Player close control**: float outside the card instead of crowding the header
- **Media library scroll**: clip list scrolling to rounded container corners

## [8.14.1] - 2026-07-26

### Fixed

- **Dashboard polish**: replace the card grid and spreadsheet-style media table with clean divider lists (thumbnails + row metadata); keep scroll containment and docked player without nested bordered boxes
- **Media thumbnails**: restore preview images with lazy load, in-memory reuse, and IndexedDB cache keyed by file URL + modified time so library refreshes do not re-probe every recording

## [8.14.0] - 2026-07-26

### Changed

- **Media library UX overhaul**: flat scrollable table (no collapsible user accordions or per-section "show more"); player docks beside the list instead of sticky overlay; list scroll is contained so playback no longer scrolls content behind the video; profile focus no longer hijacks library view
- **Live status board**: replace the tall single-column table with grouped active cards + compact idle tiles in a bounded scroll area

## [8.13.2] - 2026-07-26

### Fixed

- **Settings FFmpeg panel**: embed resolved FFmpeg info in the dashboard HTML at request time (inline sync before ES modules load); fix invalid `<dl>` markup that could drop `#ffmpeg-source` nodes in some browsers; scope panel updates to `#ffmpeg-info`

## [8.13.1] - 2026-07-26

### Fixed

- **Settings FFmpeg panel stayed empty**: `loadSettings()` used `Promise.all`, so a cookies/telegram fetch failure skipped `syncFfmpegInfo`; FFmpeg now loads via dedicated `GET /api/ffmpeg` with `allSettled` and populates on first dashboard load
- Stale module cache: `/js/*` and CSS are served with `Cache-Control: no-cache`

### Added

- **Copy** button on the recorder log panel (copies visible lines to clipboard)

### Changed

- FFmpeg block moved to the bottom of Settings (after configuration file editors)

## [8.13.0] - 2026-07-26

### Changed

- **Linux vendor FFmpeg is trusted without runtime HEVC probes**: BtbN **n8.1** is installed when checksum + runnable `ffmpeg`/`ffprobe` pass; no synthetic codec-12, enhanced, or roundtrip tests on the pinned build (system FFmpeg on Windows/macOS is still probed)

## [8.12.9] - 2026-07-26

### Fixed

- **Vendor BtbN n8.1 install no longer rejected when only roundtrip passes**: synthetic codec-12 fixtures can fail on the real BtbN build while libx265 FLV roundtrip succeeds; pinned vendor FFmpeg accepts roundtrip, system FFmpeg still requires legacy or enhanced demux

## [8.12.8] - 2026-07-26

### Fixed

- **Linux no longer sticks with incapable system FFmpeg**: Debian/Ubuntu 7.x builds that only pass the libx265 roundtrip probe are rejected for TikTok HEVC FLV; the resolver installs or prefers BtbN **n8.1** vendor FFmpeg when legacy/enhanced codec-12 probes fail
- `hevc_capable` in status/settings now requires legacy or enhanced demux (roundtrip alone is informational only)

### Changed

- **Linux startup hard-fails without capable FFmpeg**: the recorder exits before watching or recording when vendor **n8.1** cannot be installed/verified (no fallback to system FFmpeg); errors are written to `tiktok-recorder.log` with fix steps
- Vendor FFmpeg is verified once at install (saved to `.hevc-probes.json`); startup and the dashboard reuse that result instead of re-running probes

## [8.12.7] - 2026-07-26

### Fixed

- **Settings FFmpeg panel stayed at dashes**: `status.js` called `syncRuntimeControls` / `renderTelegramUploads` without importing them, so `renderStatus()` threw and Settings never received FFmpeg data; UI helpers moved to `runtime-ui.js` with correct imports
- `GET /api/settings/runtime` now includes `ffmpeg` so the panel populates even when status refresh fails

## [8.12.6] - 2026-07-26

### Fixed

- **FFmpeg vendor verification was broken**: `ffprobe_for()` used `.replace("ffmpeg", "ffprobe")` on the full path, turning `.vendor/ffmpeg/.../ffmpeg` into `.vendor/ffprobe/...` so every HEVC probe failed and the app fell back to incapable system FFmpeg
- `ffprobe_for()` now only swaps the binary basename (`ffmpeg` -> `ffprobe`, `ffmpeg.exe` -> `ffprobe.exe`); conversion uses the same helper

## [8.12.5] - 2026-07-26

### Fixed

- Vendor FFmpeg verification now includes a real **libx265 -> FLV -> demux roundtrip** on the installed binary; synthetic codec-12 fixtures alone were failing on BtbN 8.1 while the build is otherwise capable
- Capable when legacy, enhanced, or roundtrip probe passes; dashboard probe tooltip includes roundtrip status

## [8.12.4] - 2026-07-26

### Fixed

- FFmpeg capability is now verified with real demux probes (not version/path assumptions): both legacy codec-12 and Enhanced `hvc1` synthetic FLV fixtures must pass `ffprobe`/`ffmpeg -i`, and paired `ffprobe` must execute
- Vendor install logs which probes passed (`legacy` / `enhanced`); dashboard Settings shows probe results on the HEVC FLV field

### Removed

- Version-only trust for `.vendor/ffmpeg/` builds (8.12.3); incapable binaries are rejected again

## [8.12.3] - 2026-07-26

### Fixed

- Linux vendor FFmpeg (BtbN n8.1 under `.vendor/ffmpeg/`) is now accepted when it runs FFmpeg 8+, even if the synthetic HEVC FLV probe fails on the host (fixes false reject and fallback to Debian 7.1)

## [8.12.2] - 2026-07-26

### Fixed

- Settings **FFmpeg** panel now refreshes from live status when opened (no longer stuck at dashes)
- Vendor FFmpeg capability check uses an `ffmpeg -i` fallback when `ffprobe` cannot detect legacy HEVC FLV (fixes false reject of BtbN n8.1 builds)
- SIGTERM/SIGINT handler no longer logs inside the signal handler (avoids reentrant stderr errors on shutdown)

## [8.12.1] - 2026-07-26

### Fixed

- Media library toolbar no longer shows a solid background band behind the view/sort controls
- Focused user sections and active media rows no longer use a left accent stripe (highlight uses title color and row background only)

## [8.12.0] - 2026-07-26

### Added

- Dashboard **FFmpeg** panel in Settings and summary chip: resolved binary path, source (vendor/system/custom), version, and HEVC FLV capability (`GET /api/status` -> `ffmpeg`)

### Fixed

- Recent activity feed: time, kind, and message columns now align across all entries (shared grid layout)

## [8.11.0] - 2026-07-26

### Added

- MP4 conversion progress in the dashboard: live status shows percent and ETA while `converting`; **Convert leftover FLV** shows per-file progress during batch salvage

### Fixed

- SSE and media polling no longer rebuild the media library while the sticky player is open (updates are deferred until the player closes)

## [8.10.1] - 2026-07-26

### Fixed

- Live status table keeps recording size + filename on two lines; long filenames use a smaller font instead of wrapping to a third line

## [8.10.0] - 2026-07-26

### Added

- Dashboard **Clear log** button (`POST /api/logs/clear`) to truncate `tiktok-recorder.log` and remove rotation backups on demand

### Changed

- README and GUIDE updated for FFmpeg/HEVC auto-install, leftover FLV salvage, log viewer, and current dashboard features
- Linux startup no longer requires any system `ffmpeg` on `PATH`; vendor BtbN n8.1 is fetched when missing or incapable

## [8.9.0] - 2026-07-26

### Added

- Automatic Linux install of BtbN FFmpeg n8.1 (GPL static) into `.vendor/ffmpeg/` when the system binary cannot demux TikTok legacy HEVC-in-FLV (codec id 12)
- FFmpeg capability probe at startup with clear capable / not-capable logging
- Legacy FLV codec-12 -> Enhanced `hvc1` rewrite fallback before MP4 conversion
- Dashboard **Convert leftover FLV** action with `GET /api/media/pending-convert` and `POST /api/media/convert-pending` for orphan `*_flv.mp4` files
- Media library distinguishes active recordings from leftover FLVs (`needs_convert` vs `in_progress`)

### Fixed

- MP4 conversion failures on TikTok HEVC streams no longer mark recordings as finished; status becomes `convert_failed` when the final `.mp4` is missing
- CDN URL retry thrashing when signed query parameters rotate (normalize URL identity before tracking failures)
- Stop recording after repeated CDN URL gone events with no new bytes written

## [8.8.0] - 2026-07-26

### Added

- Live dashboard updates via Server-Sent Events (`GET /api/events`) with polling fallback
- Recent activity feed (polls, recordings, Telegram uploads) on the operator dashboard
- Connection error banner with manual retry when the API is unreachable
- Keyboard shortcuts (`/` search, `Esc` clear focus, `?` help, `l` logs, `s` settings)
- Video thumbnail previews in the media library (metadata frame from finished recordings)
- Per-user storage share bars in library sections
- Focus chip in the summary strip (replaces separate profile panel)
- Status table row limit with "Show all users" for large watchlists
- Incremental status table DOM updates during live refresh
- `poll_in_progress` and `activity` fields on `GET /api/status`

### Changed

- Summary strip is now the single filter surface (All / Live / Recording / …) - duplicate filter bar removed
- Summary strip and media toolbar stick while scrolling
- Force check shows loading state; "Poll running…" chip while a poll is active
- User focus model keeps full dashboard visible (no profile view swap)

## [8.7.0] - 2026-07-26

### Added

- Settings and Logs open in modal overlays so Live status and Media library stay in view
- Operator summary strip with live/recording/offline counts, poll timing, version, and click-to-filter
- Status filter bar (All / Live / Recording / Offline / Paused / Errors) with recording-first default sort
- Media library sort (Newest, Oldest, Largest, A-Z user) with view mode remembered in `localStorage`
- In-progress recordings pinned to the top of sorted lists with distinct styling
- Sticky media player while scrolling the library
- Mobile status cards (table hidden on narrow viewports)
- `GET /api/version` endpoint
- Dashboard frontend split into ES modules under `static/js/`

### Changed

- Profile view auto-expands the selected user's media section

## [8.6.3] - 2026-07-26

### Fixed

- Dashboard assets are cache-busted by app version so HTML/JS mismatches after upgrades no longer leave the UI stuck on "Loading…" until Force check / Refresh
- Dashboard boot runs before optional panel bindings so a later UI script error cannot block the initial status/media load
- Log viewer Lines/Level controls restored to native dropdowns with dark-theme styling (custom menus were blocked by the log panel layout)
- Log viewer toolbar keeps Refresh on the same row as Lines, Level, and Auto-refresh on typical desktop widths

## [8.6.2] - 2026-07-26

### Fixed

- Log viewer Lines/Level filters use custom dark-theme menus instead of native `<select>` dropdowns (fixes unreadable white option lists on Windows)

## [8.6.1] - 2026-07-26

### Fixed

- Log viewer dropdown menus use dark-theme option colors so the list is readable when opened
- Log viewer auto-refresh control uses the same toggle switch as Settings

## [8.6.0] - 2026-07-26

### Added

- Web dashboard **Logs** panel: tail `tiktok-recorder.log` with line/level filters and auto-refresh (`GET /api/logs`)
- Optional `TIKTOK_RECORDER_LOG_FILE` env var to point the recorder (and log viewer) at a custom log path

### Changed

- Settings panel reworked: Operations vs Configuration sections, aligned cards, compact poll interval row, Telegram switch toggle, and Close button

## [8.5.0] - 2026-07-26

### Added

- Media library **Most recent** view: flat list of all recordings across users, sorted newest first (toggle next to search)

### Fixed

- Live status table shows recording size and filename on separate lines so long filenames do not wrap awkwardly
- Elapsed and room columns no longer break across two lines on narrow layouts

## [8.4.3] - 2026-07-26

### Fixed

- Watchlist poll no longer hangs indefinitely on TikTok/tikrec API calls during DNS or network outages (`get_room_id_from_user`, `is_room_alive`, and signing now use the same HTTP timeouts as `check_alive`)
- Per-user network errors during a poll are logged and counted as errors instead of stalling the whole loop
- Dashboard no longer shows users stuck on **finished** when their recording thread has already ended but the next poll has not run yet
- Force recheck / add-user now take effect once the current poll step completes (timeouts prevent multi-minute blocking)

## [8.4.2] - 2026-07-26

### Fixed

- Web dashboard stays responsive during CDN/TikTok network blips: `check_alive` uses HTTP timeouts, active recordings assume still-live on transient API errors, and status API no longer blocks recording threads on disk stat
- Dashboard API requests time out with a clear toast instead of hanging indefinitely

## [8.4.1] - 2026-07-26

### Changed

- README and GUIDE deduplicated: README is overview/CLI reference; GUIDE is the authoritative dashboard and setup walkthrough (through 8.4.0)

## [8.4.0] - 2026-07-26

### Added

- Web dashboard user profiles: click a handle to filter live status and recordings to that user, with a profile banner, TikTok profile link, and shareable `#user/<username>` URL
- Last-poll summary strip (finished / skipped / errors) and active recording output path in status
- Media library download and delete actions (with confirmation)
- Runtime settings API and UI: editable poll interval and Telegram upload toggle
- Telegram upload status history in settings (when uploads are enabled)
- Manual **Record now** API and settings form (username and/or room ID)
- Web dashboard available in **automatic** mode

### Changed

- Settings panel opens directly under the top bar (scrolls into view) instead of at the bottom of the page
- Mode-aware toolbar: add/remove user controls hidden outside watchlist mode
- Settings reload when opened; API error toasts show FastAPI `detail` messages
- Finished recordings trigger Telegram upload when `use_telegram` is enabled (with status tracking)

### Fixed

- Live status action buttons use fixed slots so Stop / Pause / Remove stay column-aligned across rows

## [8.3.2] - 2026-07-25

### Changed

- Web dashboard media library uses collapsible user sections, compact file lists, search, and a single shared player instead of dozens of inline video cards
- Topbar add-user control aligned with other toolbar buttons (shared height and pill styling)

## [8.3.1] - 2026-07-25

### Fixed

- Web dashboard media library no longer resets video playback during background refresh
- CI Ruff workflow pinned to 0.15.4 (avoids new 0.16.x rule failures on existing code)

## [8.3.0] - 2026-07-25

### Added

- Built-in web dashboard for **watchlist** and **followers** modes (default `http://0.0.0.0:8787`, no auth)
- Live status view: recording/offline/paused state, elapsed time, file size, room ID
- Media library grouped by username with in-browser MP4 playback (HTTP Range support)
- Dashboard controls: add/remove users, pause/resume, force poll now, graceful per-user stop
- Settings panel to edit `cookies.json` and `telegram.json` from the browser
- Auto-managed `config/watchlist_state.json` for paused users (no `users.json` migration required)
- CLI flags: `-web-host`, `-web-port`, `-no-web`

### Changed

- Watchlist add/remove via dashboard preserves the existing `users.json` format (array or object)

### Fixed

- Web dashboard media library includes playable MP4s from `output/<username>/legacy/`

## [8.2.0] - 2026-07-21

### Changed

- Upgrade GitHub Actions to Node 24-compatible versions (`checkout@v5`, `setup-uv@v9.0.0`, `ruff-action@v4.1.0`, `action-gh-release@v3`)
- Install FFmpeg on Windows CI via Chocolatey instead of the deprecated Node 20 `setup-ffmpeg` action
- Restructure application code into the `tiktok_live_recorder` package and remove `sys.path` hacks
- Docker image now installs the project with `uv sync` and runs the `tiktok-live-recorder` console script
- Documentation and CI use `uv run tiktok-live-recorder` as the primary invocation

### Removed

- `python src/main.py` entry path; use `uv run tiktok-live-recorder` or `uv run python -m tiktok_live_recorder`

## [8.1.0] - 2026-07-21

### Added

- `SECURITY.md` security policy and private vulnerability reporting
- GitHub issue and pull request templates
- CI status badges, `--version` / `-V` CLI flag
- Dependabot for dependency and GitHub Actions updates
- pytest coverage reporting in CI
- `.dockerignore` and non-root Docker runtime user

### Changed

- `CHANGELOG.md` restructured to [Keep a Changelog](https://keepachangelog.com/) format
- `CONTRIBUTING.md` cleaned up with PR workflow and CI expectations
- `CODE_OF_CONDUCT.md` updated to Contributor Covenant 2.1
- Auto-update check is now notify-only (no longer overwrites local `src/` files)
- CI uses `uv sync --frozen` for reproducible installs
- Ruff lint is enforced in CI alongside format checks

### Fixed

- CLI now exits with code 1 on fatal errors instead of silently succeeding

## [8.0.1] - 2026-07-21

### Added

- FFmpeg path logging at startup when the binary is found

### Changed

- Bumped version to `8.0.1`

### Removed

- Docker Hub publish workflow (local `docker build` only)
- Unused `develop` branch triggers from pytest CI

## [8.0.0] - 2026-07-21

Fork maintained at [ne0lith/tiktok-live-recorder](https://github.com/ne0lith/tiktok-live-recorder).

### Added

- Watchlist mode to poll many users in one process with per-user recording threads
- `-users-file` flag and `config/users.json` watchlist support
- Project `config/` directory with committed `*.example` templates and first-run bootstrap
- `TIKTOK_RECORDER_CONFIG_DIR` environment variable to override the config location
- WAF `4003110` fallback that scrapes stream URLs from live page HTML (`SIGI_STATE` / embedded JSON)
- `-ffmpeg-path` flag for a custom FFmpeg binary
- Instance lock to prevent two recorder processes from using the same output directory
- Early watchlist re-poll when a recording ends instead of waiting for the full poll interval
- Reload watchlist users from file on each poll cycle without restarting the process
- Cookie status logging at startup (`sessionid`, `sessionid_ss`, `tt-target-idc`)
- Default per-user output layout at `output/<username>/`
- Centralized version helper reading from `pyproject.toml`

### Fixed

- Reject ended TikTok rooms that still expose stale stream URLs
- Try alternate stream URLs when a CDN pull fails or returns empty data
- Resolve room IDs before country checks for manual username recordings
- Validate live rooms with stream info to avoid fake recordings
- Improve FLV-to-MP4 conversion and video post-processing behavior
- Restrict automatic mode to a single username; multiple users require watchlist mode

### Changed

- Move `cookies.json`, `users.json`, and `telegram.json` out of `src/` into `config/`
- Centralize config, output, and app-root path helpers in `utils.py`
- Update auto-updater to preserve user `config/*.json` files and refresh only `*.example` templates
- Point update checks at `ne0lith/tiktok-live-recorder` instead of upstream

### Removed

- `.github/FUNDING.yml`
- `bump-my-version` tooling

### Security

- Gitignore `config/*.json` instead of `src/cookies.json` and `src/users.json`

### Added (tests)

- `tests/test_config_paths.py` for config bootstrap and path resolution
- `tests/test_output_paths.py` for default output directory behavior
- `tests/test_version.py` and `tests/test_waf_utils.py`
- Expanded recorder, API, and CLI validation test coverage

[Unreleased]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.20.6...HEAD
[8.20.6]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.20.5...v8.20.6
[8.20.5]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.20.4...v8.20.5
[8.20.4]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.20.3...v8.20.4
[8.20.3]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.20.2...v8.20.3
[8.20.2]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.20.1...v8.20.2
[8.20.1]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.20.0...v8.20.1
[8.20.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.19.0...v8.20.0
[8.19.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.18.1...v8.19.0
[8.18.1]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.18.0...v8.18.1
[8.18.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.17.0...v8.18.0
[8.17.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.16.0...v8.17.0
[8.16.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.15.5...v8.16.0
[8.15.5]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.15.4...v8.15.5
[8.15.4]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.15.3...v8.15.4
[8.15.3]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.15.2...v8.15.3
[8.15.2]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.15.1...v8.15.2
[8.15.1]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.15.0...v8.15.1
[8.15.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.14.5...v8.15.0
[8.14.5]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.14.4...v8.14.5
[8.14.4]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.14.3...v8.14.4
[8.12.6]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.12.5...v8.12.6
[8.12.5]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.12.4...v8.12.5
[8.12.4]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.12.3...v8.12.4
[8.12.3]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.12.2...v8.12.3
[8.12.2]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.12.1...v8.12.2
[8.12.1]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.12.0...v8.12.1
[8.12.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.11.0...v8.12.0
[8.11.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.10.1...v8.11.0
[8.10.1]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.10.0...v8.10.1
[8.10.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.9.0...v8.10.0
[8.9.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.8.0...v8.9.0
[8.8.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.7.0...v8.8.0
[8.4.2]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.4.1...v8.4.2
[8.4.1]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.4.0...v8.4.1
[8.4.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.3.2...v8.4.0
[8.3.2]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.3.1...v8.3.2
[8.3.1]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.3.0...v8.3.1
[8.3.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.2.0...v8.3.0
[8.2.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.1.0...v8.2.0
[8.1.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.0.1...v8.1.0
[8.0.1]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.0.0...v8.0.1
[8.0.0]: https://github.com/ne0lith/tiktok-live-recorder/releases/tag/v8.0.0
