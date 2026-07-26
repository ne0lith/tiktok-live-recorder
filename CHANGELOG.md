# Changelog

All notable changes in this fork since upstream `7.7.1`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.4.2...HEAD
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
