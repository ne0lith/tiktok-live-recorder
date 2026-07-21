import argparse
import re

from utils.custom_exceptions import ArgsParseError
from utils.enums import Mode, Regex
from utils.utils import default_output_base
from utils.version import get_version


def parse_args():
    """
    Parse command line arguments.
    """
    parser = argparse.ArgumentParser(
        description="TikTok Live Recorder - A tool for recording live TikTok sessions.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {get_version()}",
    )

    parser.add_argument(
        "-url",
        dest="url",
        help="Record a live session from the TikTok URL.",
        action="store",
    )

    parser.add_argument(
        "-user",
        dest="user",
        help="Record a live session from the TikTok username.",
        action="store",
    )

    parser.add_argument(
        "-room_id",
        dest="room_id",
        help="Record a live session from the TikTok room ID.",
        action="store",
    )

    parser.add_argument(
        "-mode",
        dest="mode",
        help=(
            "Recording mode: (manual, automatic, watchlist, followers) [Default: manual]\n"
            "[manual] => Manual live recording.\n"
            "[automatic] => Poll one user and record when they go live.\n"
            "[watchlist] => Poll a list of users (comma-separated -user, -users-file,\n"
            "  or config/users.json) in one process; record each live user in a thread.\n"
            "[followers] => Automatic live recording of followed users."
        ),
        default="manual",
        action="store",
    )

    parser.add_argument(
        "-automatic_interval",
        dest="automatic_interval",
        help=(
            "Polling interval in minutes for automatic, watchlist, and followers modes. "
            "[Default: 5]"
        ),
        type=int,
        default=5,
        action="store",
    )

    parser.add_argument(
        "-users-file",
        dest="users_file",
        help=(
            "Path to a JSON file with a watchlist of usernames for watchlist mode.\n"
            "Defaults to config/users.json when -user is not provided."
        ),
        default=None,
        action="store",
    )

    parser.add_argument(
        "-proxy",
        dest="proxy",
        help=(
            "Use HTTP proxy to bypass login restrictions in some countries.\n"
            "Example: -proxy http://127.0.0.1:8080"
        ),
        action="store",
    )

    parser.add_argument(
        "-output",
        dest="output",
        help=(
            "Output directory for recordings (files saved directly here).\n"
            f"If omitted, defaults to {default_output_base()}/<username>/."
        ),
        action="store",
    )

    parser.add_argument(
        "-duration",
        dest="duration",
        help="Specify the duration in seconds to record the live session [Default: None].",
        type=int,
        default=None,
        action="store",
    )

    parser.add_argument(
        "-telegram",
        dest="telegram",
        action="store_true",
        help="Activate the option to upload the video to Telegram at the end "
        "of the recording.\nRequires configuring config/telegram.json",
    )

    parser.add_argument(
        "-bitrate",
        dest="bitrate",
        help="Specify the bitrate for the output file (e.g. 1000k, 1M). Default: None (keep original)",
        action="store",
    )

    parser.add_argument(
        "-ffmpeg-path",
        dest="ffmpeg_path",
        help="Specify a custom path to the ffmpeg binary. [Default: 'ffmpeg']",
        default=None,
        action="store",
    )

    parser.add_argument(
        "-no-update-check",
        dest="update_check",
        action="store_false",
        help=(
            "Disable the check for updates before running the program. "
            "By default, update checking is enabled."
        ),
    )

    args = parser.parse_args()

    return args


def validate_and_parse_args():
    from utils.utils import read_users, users_file_path

    args = parse_args()

    if not args.mode:
        raise ArgsParseError(
            "Missing mode value. Please specify the mode "
            "(manual, automatic, watchlist, or followers)."
        )
    if args.mode not in ["manual", "automatic", "watchlist", "followers"]:
        raise ArgsParseError(
            "Incorrect mode value. Choose between 'manual', 'automatic', "
            "'watchlist', or 'followers'."
        )

    if args.user:
        args.user = [u.lstrip("@").strip() for u in args.user.split(",") if u.strip()]

    if args.mode == "automatic":
        if args.user and len(args.user) > 1:
            raise ArgsParseError(
                "Multiple usernames require -mode watchlist. "
                "Automatic mode records one user at a time."
            )
        if args.users_file:
            raise ArgsParseError(
                "-users-file is for watchlist mode. Use -mode watchlist."
            )
        if not args.user and not args.room_id and not args.url:
            raise ArgsParseError(
                "Missing URL, username, or room ID for automatic mode. "
                "Please provide one of these parameters."
            )

    if args.mode == "manual" and not args.user and not args.room_id and not args.url:
        raise ArgsParseError(
            "Missing URL, username, or room ID. Please provide one of these parameters."
        )

    if args.mode == "watchlist":
        if not args.user:
            users_path = args.users_file or users_file_path()
            loaded_users = read_users(users_path)
            if not loaded_users:
                raise ArgsParseError(
                    "Missing username(s) for watchlist mode. Provide -user, -users-file, "
                    "or add usernames to config/users.json"
                )
            args.user = loaded_users
            args.users_file = users_path
        else:
            args.users_file = None

    if args.user and len(args.user) > 1 and (args.room_id or args.url):
        raise ArgsParseError(
            "When using multiple usernames, do not provide room_id or url."
        )

    if args.url and not re.match(str(Regex.IS_TIKTOK_LIVE), args.url):
        raise ArgsParseError(
            "The provided URL does not appear to be a valid TikTok live URL."
        )

    if (
        (args.user and args.room_id)
        or (args.user and args.url)
        or (args.room_id and args.url)
    ):
        raise ArgsParseError("Please provide only one among username, room ID, or URL.")

    # Keep watchlist users as a list; collapse single user for other modes.
    if args.mode != "watchlist" and args.user and len(args.user) == 1:
        args.user = args.user[0]

    if (
        (isinstance(args.user, str) and args.user and args.room_id)
        or (isinstance(args.user, str) and args.user and args.url)
        or (args.room_id and args.url)
    ):
        raise ArgsParseError("Please provide only one among username, room ID, or URL.")

    if args.automatic_interval < 1:
        raise ArgsParseError(
            "Incorrect automatic_interval value. Must be one minute or more."
        )

    if args.mode == "manual":
        mode = Mode.MANUAL
    elif args.mode == "automatic":
        mode = Mode.AUTOMATIC
    elif args.mode == "watchlist":
        mode = Mode.WATCHLIST
    elif args.mode == "followers":
        mode = Mode.FOLLOWERS

    return args, mode
