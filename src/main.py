import sys
import os
import multiprocessing

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def record_user(config):
    from core.tiktok_recorder import TikTokRecorder
    from utils.logger_manager import logger

    try:
        TikTokRecorder(config).run()
    except Exception as e:
        logger.error(f"{e}", exc_info=True)


def _build_config(args, mode, cookies, user=None, users=None):
    from utils.recorder_config import RecorderConfig

    return RecorderConfig(
        url=args.url,
        user=user,
        users=users,
        users_file=getattr(args, "users_file", None),
        room_id=args.room_id,
        mode=mode,
        automatic_interval=args.automatic_interval,
        cookies=cookies,
        proxy=args.proxy,
        output=args.output,
        duration=args.duration,
        use_telegram=args.telegram,
        bitrate=args.bitrate,
        ffmpeg_path=args.ffmpeg_path,
    )


def run_recordings(args, mode, cookies):
    from utils.enums import Mode

    if mode == Mode.WATCHLIST:
        users = args.user if isinstance(args.user, list) else [args.user]
        config = _build_config(args, mode, cookies, users=users)
        record_user(config)
    elif isinstance(args.user, list):
        processes = []
        for user in args.user:
            config = _build_config(args, mode, cookies, user=user)
            p = multiprocessing.Process(target=record_user, args=(config,))
            p.start()
            processes.append(p)
        try:
            for p in processes:
                p.join()
        except KeyboardInterrupt:
            print("\n[!] Ctrl-C detected.")
            try:
                for p in processes:
                    p.join()
            except KeyboardInterrupt:
                print("\n[!] Forcefully terminating all processes.")
                for p in processes:
                    if p.is_alive():
                        p.terminate()
    else:
        config = _build_config(args, mode, cookies, user=args.user)
        record_user(config)


def main():
    from utils.args_handler import validate_and_parse_args
    from utils.utils import read_cookies, log_cookie_status, InstanceLock, default_output_base
    from utils.logger_manager import logger
    from utils.custom_exceptions import TikTokRecorderError
    from utils.dependencies import check_ffmpeg
    from check_updates import check_updates

    instance_lock = None
    try:
        # validate and parse command line arguments
        args, mode = validate_and_parse_args()

        # check ffmpeg binary (supports custom path via -ffmpeg-path)
        check_ffmpeg(args.ffmpeg_path or "ffmpeg")

        # check for updates
        if args.update_check is True:
            logger.info("Checking for updates...\n")
            if check_updates():
                exit()
        else:
            logger.info("Skipped update check\n")

        # read cookies from the config file
        cookies = read_cookies()
        log_cookie_status(cookies)

        instance_lock = InstanceLock(str(args.output or default_output_base()))
        instance_lock.acquire()

        # run the recordings based on the parsed arguments
        run_recordings(args, mode, cookies)

    except TikTokRecorderError as ex:
        logger.error(f"Application Error: {ex}")

    except Exception as ex:
        logger.critical(f"Generic Error: {ex}", exc_info=True)

    finally:
        if instance_lock is not None:
            instance_lock.release()


if __name__ == "__main__":
    # print the banner
    from utils.utils import banner

    banner()

    # check and install dependencies
    from utils.dependencies import check_and_install_dependencies

    check_and_install_dependencies()

    # set up signal handling for graceful shutdown
    multiprocessing.freeze_support()

    # run
    main()
