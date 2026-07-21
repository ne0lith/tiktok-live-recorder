import os
from pathlib import Path
import requests
import zipfile
import shutil

GITHUB_REPO = "ne0lith/tiktok-live-recorder"
GITHUB_BRANCH = "main"

URL_PYPROJECT = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/pyproject.toml"
)
URL_ENUMS = (
    f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/src/utils/enums.py"
)
URL_REPO = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.zip"
FILE_TEMP_PYPROJECT = "pyproject_temp.toml"
FILE_TEMP = "enums_temp.py"
FILE_NAME_UPDATE = URL_REPO.split("/")[-1]


def delete_tmp_file():
    for name in (FILE_TEMP, FILE_TEMP_PYPROJECT):
        try:
            os.remove(name)
        except OSError:
            pass


def check_file(path: str) -> bool:
    """
    Check if a file exists at the given path.

    Args:
        path (str): Path to the file.

    Returns:
        bool: True if the file exists, False otherwise.
    """
    return Path(path).exists()


def download_file(url: str, file_name: str) -> None:
    """
    Download a file from a URL and save it locally.

    Args:
        url (str): URL to download the file from.
        file_name (str): Name of the file to save.
    """
    response = requests.get(url, stream=True, timeout=30)

    if response.status_code == 200:
        with open(file_name, "wb") as file:
            for chunk in response.iter_content(1024):
                file.write(chunk)
    else:
        print("Error downloading the file.")


def _read_version_from_pyproject(path: str | Path) -> str:
    import tomllib

    with open(path, "rb") as f:
        return tomllib.load(f)["project"]["version"]


def check_updates() -> bool:
    """
    Check if there is a new version available and update if necessary.

    Returns:
        bool: True if the update was successful, False otherwise.
    """
    download_file(URL_PYPROJECT, FILE_TEMP_PYPROJECT)

    if not check_file(FILE_TEMP_PYPROJECT):
        delete_tmp_file()
        print("The temporary file does not exist.")
        return False

    from utils.version import get_version

    def _parse_version(v):
        try:
            return (float(str(v)),)
        except ValueError:
            return tuple(int(x) for x in str(v).split("."))

    remote_version = _read_version_from_pyproject(FILE_TEMP_PYPROJECT)
    local_version = get_version()

    if _parse_version(remote_version) == _parse_version(local_version):
        delete_tmp_file()
        return False

    download_file(URL_ENUMS, FILE_TEMP)

    if not check_file(FILE_TEMP):
        delete_tmp_file()
        print("The temporary file does not exist.")
        return False

    try:
        from enums_temp import Info
    except ImportError:
        print("Error importing the file or missing module.")
        delete_tmp_file()
        return False

    print(
        f"Current version: {local_version}\n"
        f"New version available: {remote_version}"
    )
    print("\nNew features:")
    for feature in Info.NEW_FEATURES:
        print("*", feature)

    download_file(URL_REPO, FILE_NAME_UPDATE)

    dir_path = Path(__file__).parent
    temp_update_dir = dir_path / "update_temp"

    # Extract content from zip to a temporary update directory
    with zipfile.ZipFile(dir_path / FILE_NAME_UPDATE, "r") as zip_ref:
        zip_ref.extractall(temp_update_dir)

    # Find the extracted folder (it will have the name 'tiktok-live-recorder-main')
    extracted_root = temp_update_dir / "tiktok-live-recorder-main"
    extracted_folder = extracted_root / "src"

    # Copy all files and folders from the extracted folder to the main directory
    files_to_preserve = {"check_updates.py"}
    for item in extracted_folder.iterdir():
        source = item
        destination = dir_path / item.name

        # Skip overwriting the files we want to preserve
        if source.name in files_to_preserve or source.suffix == ".session":
            continue

        # If it's a file, overwrite it
        if source.is_file():
            shutil.copy2(source, destination)
        # If it's a directory, copy its contents file by file
        elif source.is_dir():
            for sub_item in source.rglob("*"):
                sub_destination = destination / sub_item.relative_to(source)
                if sub_item.is_file():
                    sub_destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(sub_item, sub_destination)

    # Update config templates only; never overwrite user config/*.json files.
    extracted_config = extracted_root / "config"
    config_dest = dir_path.parent / "config"
    if extracted_config.is_dir():
        config_dest.mkdir(parents=True, exist_ok=True)
        for item in extracted_config.iterdir():
            if item.is_file() and item.name.endswith(".example"):
                shutil.copy2(item, config_dest / item.name)

    # Delete the temporary files and folders
    shutil.rmtree(temp_update_dir)
    try:
        Path(FILE_TEMP).unlink()
    except Exception as e:
        print(f"Failed to remove the temporary file {FILE_TEMP}: {e}")

    delete_tmp_file()

    try:
        Path(FILE_NAME_UPDATE).unlink()
    except Exception as e:
        print(f"Failed to remove the temporary file {FILE_NAME_UPDATE}: {e}")

    return True
