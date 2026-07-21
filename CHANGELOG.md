# Changelog

All notable changes in this fork since upstream `7.7.1`.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.2.0...HEAD
[8.2.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.1.0...v8.2.0
[8.1.0]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.0.1...v8.1.0
[8.0.1]: https://github.com/ne0lith/tiktok-live-recorder/compare/v8.0.0...v8.0.1
[8.0.0]: https://github.com/ne0lith/tiktok-live-recorder/releases/tag/v8.0.0
