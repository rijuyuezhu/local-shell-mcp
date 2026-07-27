"""Public remote-worker command-line contract."""

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from ..agent_bridge.redaction import _redact_text

_MAX_INVITE_BYTES = 16 * 1024


def _add_invite_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--invite", default=None)
    group.add_argument(
        "--invite-stdin",
        action="store_true",
        help="Read the one-time invite from bounded UTF-8 stdin",
    )


def _add_enrollment_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server", required=True)
    _add_invite_args(parser)
    parser.add_argument("--name", default=None)
    parser.add_argument("--workdir", default=None)
    parser.add_argument(
        "--profile",
        default=None,
        help="Store and run this enrollment as an independent worker profile",
    )


def _read_invite(args: argparse.Namespace) -> str:
    if args.invite is not None:
        invite = str(args.invite)
    else:
        if sys.stdin.isatty():
            raise ValueError("--invite-stdin refuses interactive TTY input")
        payload = sys.stdin.buffer.read(_MAX_INVITE_BYTES + 1)
        if len(payload) > _MAX_INVITE_BYTES:
            raise ValueError("worker invite exceeds stdin size limit")
        try:
            invite = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("worker invite stdin must be UTF-8") from exc
        if invite.endswith("\r\n"):
            invite = invite[:-2]
        elif invite.endswith("\n"):
            invite = invite[:-1]
    if not invite:
        raise ValueError("worker invite is empty")
    return invite


def _safe_identity(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "server": str(identity.get("server") or ""),
        "name": str(identity.get("name") or ""),
        "workdir": str(identity.get("workdir") or ""),
        "profile_id": str(identity.get("profile_id") or ""),
        "enrolled": bool(identity.get("access")),
    }


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True))


def _run_async(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        print("\nStatus: disconnected by user.", file=sys.stderr, flush=True)
        raise SystemExit(130) from None
    except Exception as exc:
        print(
            f"Status: worker command failed: {_redact_text(str(exc))}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from None


def _mark_worker_runtime() -> None:
    os.environ.setdefault("LOCAL_SHELL_MCP_REMOTE_WORKER_RUNTIME", "1")


def _invite_or_exit(args: argparse.Namespace) -> str:
    try:
        return _read_invite(args)
    except Exception as exc:
        print(
            f"Status: worker command failed: {_redact_text(str(exc))}",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from None


def _enroll_from_args(args: argparse.Namespace) -> None:
    from .worker import enroll_worker

    _mark_worker_runtime()
    enroll_args = (
        args.server,
        _invite_or_exit(args),
        args.name,
        args.workdir,
    )
    identity = _run_async(
        enroll_worker(*enroll_args)
        if args.profile is None
        else enroll_worker(*enroll_args, args.profile)
    )
    _print_json(_safe_identity(identity))


def _connect_from_args(args: argparse.Namespace) -> None:
    from .worker import run_worker

    _mark_worker_runtime()
    run_args = (
        args.server,
        _invite_or_exit(args),
        args.name,
        args.workdir,
    )
    _run_async(
        run_worker(*run_args)
        if args.profile is None
        else run_worker(*run_args, args.profile)
    )


def _run_stored_from_args(args: argparse.Namespace) -> None:
    from .service import prepare_worker_service_environment
    from .worker import run_stored_worker

    prepare_worker_service_environment()
    _mark_worker_runtime()
    _run_async(
        run_stored_worker()
        if args.profile is None
        else run_stored_worker(args.profile)
    )


def _load_identity(profile_id: str | None = None) -> dict[str, Any]:
    from .worker import load_worker_identity

    return (
        load_worker_identity()
        if profile_id is None
        else load_worker_identity(profile_id)
    )


def _migrate_from_args(_args: argparse.Namespace) -> None:
    from .lifecycle import worker_run_lock
    from .migration import migrate_legacy_worker_state

    with worker_run_lock():
        result = migrate_legacy_worker_state()
    if result is None:
        raise ValueError("no legacy worker identity is available to migrate")
    _print_json(result)


def _install_service_from_args(args: argparse.Namespace) -> None:
    from .service import install_service, service_manager, status_json

    if service_manager() == "unsupported":
        install_service({}, start=not args.no_start)
    profile_id = getattr(args, "profile", None)
    identity = (
        _load_identity()
        if profile_id is None
        else _load_identity(str(profile_id))
    )
    _print_raw(status_json(install_service(identity, start=not args.no_start)))


def _uninstall_service_from_args(_args: argparse.Namespace) -> None:
    from .service import status_json, uninstall_service

    _print_raw(status_json(uninstall_service()))


def _start_from_args(_args: argparse.Namespace) -> None:
    from .service import start_service, status_json

    _print_raw(status_json(start_service()))


def _stop_from_args(_args: argparse.Namespace) -> None:
    from .service import status_json, stop_service

    _print_raw(status_json(stop_service()))


def _restart_from_args(_args: argparse.Namespace) -> None:
    from .service import restart_service, status_json

    _print_raw(status_json(restart_service()))


def _status_from_args(_args: argparse.Namespace) -> None:
    from .service import service_status, status_json

    _print_raw(status_json(service_status()))


def _logs_from_args(args: argparse.Namespace) -> None:
    from .service import service_logs

    service_logs(lines=args.lines, follow=args.follow)


def _update_from_args(args: argparse.Namespace) -> None:
    from .profiles import read_worker_profile, update_worker_profile
    from .runtime import update_installed_runtime
    from .service import (
        refresh_installed_service_definition,
        restart_service,
        service_status,
    )

    requested_profile = getattr(args, "profile", None)
    identity = (
        _load_identity()
        if requested_profile is None
        else _load_identity(str(requested_profile))
    )
    profile_id = str(identity.get("profile_id") or "") or None
    before = service_status()
    if profile_id is None:
        result = update_installed_runtime(
            str(identity["server"]), force=bool(args.force)
        )
    else:
        profile = read_worker_profile(profile_id)
        current_version = str(profile.get("runtime_version") or "")
        if not current_version:
            raise ValueError("worker profile runtime version is unavailable")
        result = update_installed_runtime(
            str(identity["server"]),
            force=bool(args.force),
            current_version=current_version,
        )
    digest = str(result.get("sha256") or "")
    version = str(result.get("version") or "")
    if profile_id is not None:
        update_worker_profile(
            profile_id,
            runtime_sha256=digest,
            runtime_version=version,
            server=str(identity["server"]),
            name=str(identity["name"]),
            workdir=str(identity["workdir"]),
        )
    definition_changed = refresh_installed_service_definition(
        identity,
        digest or None,
    )
    restarted = False
    if before.running and (result.get("updated") or definition_changed):
        restart_service()
        restarted = True
    _print_json(
        {
            "schema_version": 1,
            "action": "update",
            "updated": bool(result.get("updated")),
            "version": str(result.get("version") or ""),
            "sha256": str(result.get("sha256") or ""),
            "service_restarted": restarted,
        }
    )


def _print_raw(value: str) -> None:
    print(value)


def _service_handler(handler: Any) -> Any:
    def wrapped(args: argparse.Namespace) -> None:
        try:
            handler(args)
        except KeyboardInterrupt:
            raise SystemExit(130) from None
        except Exception as exc:
            _print_json(
                {
                    "schema_version": 1,
                    "ok": False,
                    "error": type(exc).__name__,
                }
            )
            raise SystemExit(1) from None

    return wrapped


def register_worker_cli(subparsers: Any) -> argparse.ArgumentParser:
    """Register the breaking-clean worker subcommand tree."""
    worker = subparsers.add_parser(
        "worker",
        help="Enroll, connect, or manage this machine as a remote worker",
        description="Manage or run a local-shell-mcp remote worker.",
    )
    add_worker_subcommands(worker)
    return worker


def add_worker_subcommands(parser: argparse.ArgumentParser) -> None:
    """Add worker actions to a root or nested parser."""
    subparsers = parser.add_subparsers(dest="worker_command", required=True)

    enroll = subparsers.add_parser(
        "enroll", help="Enroll and store worker identity"
    )
    _add_enrollment_args(enroll)
    enroll.set_defaults(handler=_enroll_from_args)

    connect = subparsers.add_parser(
        "connect", help="Enroll or resume and run in the foreground"
    )
    _add_enrollment_args(connect)
    connect.set_defaults(handler=_connect_from_args)

    run = subparsers.add_parser("run", help="Run using stored worker identity")
    run.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Optional profile id; omitted to migrate or run the legacy identity",
    )
    run.set_defaults(handler=_run_stored_from_args)

    migrate = subparsers.add_parser(
        "migrate",
        help="Migrate the legacy single-worker identity into a profile",
    )
    migrate.set_defaults(handler=_service_handler(_migrate_from_args))

    install = subparsers.add_parser(
        "install-service", help="Install the native per-user worker service"
    )
    install.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Optional profile id to bind to the single native worker service",
    )
    install.add_argument("--no-start", action="store_true")
    install.set_defaults(handler=_service_handler(_install_service_from_args))

    uninstall = subparsers.add_parser(
        "uninstall-service", help="Remove the native per-user worker service"
    )
    uninstall.set_defaults(
        handler=_service_handler(_uninstall_service_from_args)
    )

    start = subparsers.add_parser("start", help="Start the worker user service")
    start.set_defaults(handler=_service_handler(_start_from_args))

    stop = subparsers.add_parser("stop", help="Stop the worker user service")
    stop.set_defaults(handler=_service_handler(_stop_from_args))

    restart = subparsers.add_parser(
        "restart", help="Restart the worker user service"
    )
    restart.set_defaults(handler=_service_handler(_restart_from_args))

    status = subparsers.add_parser(
        "status", help="Print worker service JSON status"
    )
    status.set_defaults(handler=_service_handler(_status_from_args))

    logs = subparsers.add_parser("logs", help="Read worker service logs")
    logs.add_argument("--lines", type=int, default=100)
    logs.add_argument("--follow", action="store_true")
    logs.set_defaults(handler=_service_handler(_logs_from_args))

    update = subparsers.add_parser(
        "update", help="Install the latest verified worker runtime"
    )
    update.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Optional profile id whose runtime and service binding are updated",
    )
    update.add_argument("--force", action="store_true")
    update.set_defaults(handler=_service_handler(_update_from_args))


def run_worker_cli(argv: list[str] | None = None) -> None:
    """Run the standalone worker-only parser used by source bundles."""
    parser = argparse.ArgumentParser(
        prog="local-shell-mcp worker",
        description="Manage or run a local-shell-mcp remote worker",
    )
    add_worker_subcommands(parser)
    args = parser.parse_args(argv)
    args.handler(args)
