from tiktok_live_recorder.updater import (
    GITHUB_RELEASES,
    compare_versions,
    fetch_remote_version,
)


def check_updates() -> bool:
    """
    Check if a newer version is available and print upgrade instructions.

    Returns:
        bool: Always False. Updates are notify-only; local files are not modified.
    """
    from tiktok_live_recorder.utils.version import get_version

    remote_version = fetch_remote_version()
    if remote_version is None:
        print("Unable to check for updates.")
        return False

    local_version = get_version()
    if compare_versions(remote_version, local_version) <= 0:
        return False

    print(f"Current version: {local_version}")
    print(f"New version available: {remote_version}")
    print("\nTo upgrade:")
    print("  git pull")
    print("  uv sync")
    print(f"\nOr download the latest release: {GITHUB_RELEASES}")
    return False
