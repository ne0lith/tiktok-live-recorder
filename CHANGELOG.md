# Changelog

All notable changes in this fork since upstream `7.7.1`. Entries follow [Conventional Commits](https://www.conventionalcommits.org/).

## [8.0.0] - 2026-07-21

Fork maintained at [ne0lith/tiktok-live-recorder](https://github.com/ne0lith/tiktok-live-recorder).

### feat

- add watchlist mode to poll many users in one process with per-user recording threads
- add `-users-file` flag and `config/users.json` watchlist support
- add project `config/` directory with committed `*.example` templates and first-run bootstrap
- add `TIKTOK_RECORDER_CONFIG_DIR` environment variable to override the config location
- add WAF `4003110` fallback that scrapes stream URLs from live page HTML (`SIGI_STATE` / embedded JSON)
- add `-ffmpeg-path` flag for a custom FFmpeg binary
- add instance lock to prevent two recorder processes from using the same output directory
- add early watchlist re-poll when a recording ends instead of waiting for the full poll interval
- reload watchlist users from file on each poll cycle without restarting the process
- add cookie status logging at startup (`sessionid`, `sessionid_ss`, `tt-target-idc`)
- add default per-user output layout at `output/<username>/`
- add centralized version helper reading from `pyproject.toml`

### fix

- reject ended TikTok rooms that still expose stale stream URLs
- try alternate stream URLs when a CDN pull fails or returns empty data
- resolve room IDs before country checks for manual username recordings
- validate live rooms with stream info to avoid fake recordings
- improve FLV-to-MP4 conversion and video post-processing behavior
- restrict automatic mode to a single username; multiple users require watchlist mode

### refactor

- move `cookies.json`, `users.json`, and `telegram.json` out of `src/` into `config/`
- centralize config, output, and app-root path helpers in `utils.py`
- update auto-updater to preserve user `config/*.json` files and refresh only `*.example` templates
- point update checks at `ne0lith/tiktok-live-recorder` instead of upstream

### chore

- bump version to `8.0.0`
- repoint `pyproject.toml` repository URLs to `ne0lith/tiktok-live-recorder`
- remove `.github/FUNDING.yml`
- remove `bump-my-version` tooling
- gitignore `config/*.json` instead of `src/cookies.json` and `src/users.json`
- ship `config/*.example` templates in the Docker image

### test

- add `tests/test_config_paths.py` for config bootstrap and path resolution
- add `tests/test_output_paths.py` for default output directory behavior
- add `tests/test_version.py` and `tests/test_waf_utils.py`
- expand recorder, API, and CLI validation test coverage
