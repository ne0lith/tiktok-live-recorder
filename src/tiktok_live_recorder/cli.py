import multiprocessing
import sys


def record_user(config):
    from tiktok_live_recorder.core.tiktok_recorder import TikTokRecorder
    from tiktok_live_recorder.utils.enums import Mode
    from tiktok_live_recorder.utils.logger_manager import logger

    web_server = None
    try:
        recorder = TikTokRecorder(config)
        if (
            config.mode in (Mode.WATCHLIST, Mode.FOLLOWERS, Mode.AUTOMATIC)
            and not config.no_web
        ):
            from tiktok_live_recorder.web.server import start_web_server

            web_server = start_web_server(recorder, config)
        recorder.run()
    except Exception as e:
        logger.error(f"{e}", exc_info=True)
    finally:
        if web_server is not None:
            web_server.stop()


def _build_config(args, mode, cookies, user=None, users=None):
    from tiktok_live_recorder.utils.recorder_config import RecorderConfig

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
        web_host=args.web_host,
        web_port=args.web_port,
        no_web=args.no_web,
    )


def run_recordings(args, mode, cookies):
    from tiktok_live_recorder.utils.enums import Mode

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


def main() -> int:
    from tiktok_live_recorder.check_updates import check_updates
    from tiktok_live_recorder.utils.args_handler import validate_and_parse_args
    from tiktok_live_recorder.utils.custom_exceptions import (
        FfmpegRequirementError,
        TikTokRecorderError,
    )
    from tiktok_live_recorder.utils.dependencies import check_ffmpeg
    from tiktok_live_recorder.utils.logger_manager import logger
    from tiktok_live_recorder.utils.utils import (
        InstanceLock,
        default_output_base,
        log_cookie_status,
        read_cookies,
    )

    instance_lock = None
    exit_code = 0
    try:
        args, mode = validate_and_parse_args()

        resolved_ffmpeg = check_ffmpeg(args.ffmpeg_path)
        args.ffmpeg_path = resolved_ffmpeg

        if args.update_check is True:
            logger.info("Checking for updates...\n")
            check_updates()
        else:
            logger.info("Skipped update check\n")

        cookies = read_cookies()
        log_cookie_status(cookies)

        instance_lock = InstanceLock(str(args.output or default_output_base()))
        instance_lock.acquire()

        run_recordings(args, mode, cookies)

    except FfmpegRequirementError as ex:
        logger.error(f"FFmpeg requirement not met: {ex}")
        exit_code = 1

    except TikTokRecorderError as ex:
        logger.error(f"Application Error: {ex}")
        exit_code = 1

    except Exception as ex:
        logger.critical(f"Generic Error: {ex}", exc_info=True)
        exit_code = 1

    finally:
        if instance_lock is not None:
            instance_lock.release()

    return exit_code


def run() -> None:
    """Console entry point with startup banner and dependency checks."""
    from tiktok_live_recorder.utils.dependencies import check_and_install_dependencies
    from tiktok_live_recorder.utils.utils import banner

    banner()
    check_and_install_dependencies()
    multiprocessing.freeze_support()
    sys.exit(main())
