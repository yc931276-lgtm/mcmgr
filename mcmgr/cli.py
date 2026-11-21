"""Command line interface for mcmgr."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__, doctor, lang as langmod, meta, mirror, skin as skinmod
from .installer import installed_versions, install_version, remove_version, verify_version
from .java import discover as discover_java
from .launch import LaunchError, build_command, launch, normalize_uuid, offline_uuid
from .net import DownloadError
from .paths import Store
from .settings import SCALAR_FIELDS, LaunchSettings

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_INTERRUPTED = 130


def _store(args: argparse.Namespace) -> Store:
    return Store(args.root, mirror=args.mirror)


def _human_time(timestamp: int | None) -> str:
    if not timestamp:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GiB"


def _parse_memory(text: str) -> str:
    """Normalise ``2G`` / ``2048m`` / ``512`` into a ``-Xmx`` value."""
    cleaned = text.strip().upper()
    if not cleaned:
        raise argparse.ArgumentTypeError("memory size is empty")
    if cleaned.isdigit():
        return f"{cleaned}M"
    if cleaned[-1] in {"M", "G"} and cleaned[:-1].isdigit():
        return cleaned
    raise argparse.ArgumentTypeError(f"bad memory size {text!r}; use e.g. 2G or 2048M")


def _resolve(store: Store, version_id: str) -> str:
    manifest = meta.get_manifest(store)
    resolved = meta.resolve_version_id(manifest, version_id)
    if meta.find_version(manifest, resolved) is None:
        raise SystemExit(f"mcmgr: unknown version {version_id!r}\n  try `mcmgr versions --search {version_id}`")
    return resolved


def cmd_versions(args: argparse.Namespace) -> int:
    store = _store(args)
    manifest = meta.get_manifest(store, force=args.refresh)
    versions = meta.list_versions(manifest, kind=args.type, search=args.search)
    if args.limit:
        versions = versions[: args.limit]

    if args.json:
        print(json.dumps(versions, indent=2))
        return EXIT_OK

    latest = manifest.get("latest", {})
    print(f"latest release: {latest.get('release', '?')}    latest snapshot: {latest.get('snapshot', '?')}")
    print(f"{len(versions)} version(s):")
    for entry in versions:
        print(f"  {entry['id']:<20} {entry.get('type', '?'):<10} {entry.get('releaseTime', '')[:10]}")
    if not versions:
        print("  (none matched)")
    return EXIT_OK


def cmd_install(args: argparse.Namespace) -> int:
    store = _store(args)
    version_id = _resolve(store, args.version)
    print(f"installing {version_id} into {store.root}")
    if store.mirror != "official":
        print(f"source: {mirror.describe(store.mirror)}")
    try:
        result = install_version(
            store,
            version_id,
            with_assets=not args.no_assets,
            jobs=args.jobs,
            threads=args.threads,
            force=args.force,
        )
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    print(result.summary())
    if result.errors:
        for destination, message in result.errors[:5]:
            print(f"  failed: {destination}: {message}", file=sys.stderr)
        if len(result.errors) > 5:
            print(f"  ... and {len(result.errors) - 5} more", file=sys.stderr)
        return EXIT_ERROR
    print(f"done. launch it with: mcmgr launch {version_id}")
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    store = _store(args)
    versions = installed_versions(store)
    if args.json:
        print(json.dumps(versions, indent=2))
        return EXIT_OK
    if not versions:
        print(f"no versions installed in {store.root}")
        return EXIT_OK
    print(f"installed in {store.root}:")
    print(f"  {'VERSION':<22} {'TYPE':<10} {'INSTALLED':<17} {'JAVA':<5} {'ASSETS':>7}")
    for record in versions:
        assets = record.get("assets")
        print(
            f"  {record['id']:<22} {(record.get('type') or '?'):<10} "
            f"{_human_time(record.get('installed_at')):<17} "
            f"{str(record.get('java_major') or '-'):<5} "
            f"{(assets if assets is not None else '-'):>7}"
        )
    return EXIT_OK


def _effective_launch(
    settings: LaunchSettings, args: argparse.Namespace
) -> tuple[str, str | None, str | None, str | None, int | None, int | None, list[str], list[str]]:
    """Combine saved settings with command line overrides (CLI wins)."""
    username = args.username or settings.username or "Player"
    uuid_value = args.uuid if args.uuid is not None else settings.uuid
    memory = args.memory or settings.memory
    java = args.java or settings.java
    width = args.width if args.width is not None else settings.width
    height = args.height if args.height is not None else settings.height
    jvm_args = list(settings.jvm_args) + list(args.jvm_arg or [])
    game_args = list(settings.game_args) + list(args.game_args or [])
    return username, uuid_value, memory, java, width, height, jvm_args, game_args


def _print_settings(version_id: str, settings: LaunchSettings, path: Path) -> None:
    username = settings.username or "Player"
    custom_uuid = settings.uuid if settings.uuid and settings.uuid != "offline" else None
    uuid_line = custom_uuid or f"offline ({offline_uuid(username)})"
    memory = settings.memory or "(default)"
    java = settings.java or "(auto-detect)"
    window = f"{settings.width}x{settings.height}" if settings.width and settings.height else "(default)"
    jvm_args = " ".join(settings.jvm_args) or "(none)"
    game_args = " ".join(settings.game_args) or "(none)"
    state = "saved" if path.is_file() else "not saved yet"
    print(f"launch settings for {version_id} ({state}: {path})")
    print(f"  username  : {username}")
    print(f"  uuid      : {uuid_line}")
    print(f"  memory    : {memory}")
    print(f"  java      : {java}")
    print(f"  window    : {window}")
    print(f"  jvm args  : {jvm_args}")
    print(f"  game args : {game_args}")


def cmd_launch(args: argparse.Namespace) -> int:
    store = _store(args)
    version_id = _resolve(store, args.version)
    config_path = store.launch_config(version_id)
    settings = LaunchSettings.load(config_path)
    try:
        username, uuid_value, memory, java, width, height, jvm_args, game_args = _effective_launch(settings, args)
        if uuid_value is not None:
            uuid_value = normalize_uuid(uuid_value)
        if args.save:
            LaunchSettings(
                username=username,
                uuid=uuid_value,
                memory=memory,
                java=java,
                width=width,
                height=height,
                jvm_args=jvm_args,
                game_args=game_args,
            ).save(config_path)
            print(f"saved launch settings to {config_path}")
        plan = build_command(
            store,
            version_id,
            username=username,
            uuid_override=uuid_value,
            java=java,
            memory=memory,
            width=width,
            height=height,
            jvm_args=jvm_args or None,
            game_args=game_args or None,
        )
    except LaunchError as error:
        print(f"mcmgr: {error}", file=sys.stderr)
        return EXIT_ERROR

    for warning in plan.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    try:
        if args.dry_run:
            code, detected = langmod.detect(store, version_id)
            if code:
                print(f"language: {code} (system locale {detected}; not written in dry-run)")
        else:
            applied = langmod.ensure_default(store, version_id)
            if applied:
                code, detected = applied
                print(f"language: {code} (system locale {detected})")
    except (langmod.LangError, OSError):
        pass

    if args.dry_run:
        print(f"java: {plan.java} (major {plan.java_major})")
        print(f"cwd:  {plan.cwd}")
        print(plan.command_line())
        return EXIT_OK

    uuid_note = f", uuid {uuid_value}" if uuid_value and uuid_value != "offline" else ""
    print(f"launching {version_id} as {username}{uuid_note} (Java {plan.java_major}) in {plan.cwd}")
    try:
        return launch(store, version_id, plan=plan)
    except FileNotFoundError:
        print(f"mcmgr: cannot execute {plan.java}", file=sys.stderr)
        return EXIT_ERROR


def cmd_config(args: argparse.Namespace) -> int:
    store = _store(args)
    version_id = _resolve(store, args.version)
    path = store.launch_config(version_id)
    settings = LaunchSettings.load(path)
    if args.reset:
        settings = LaunchSettings()
    changed = bool(args.reset)
    try:
        if args.username is not None:
            settings.username = args.username
            changed = True
        if args.uuid is not None:
            settings.uuid = normalize_uuid(args.uuid)
            changed = True
        if args.memory is not None:
            settings.memory = args.memory
            changed = True
        if args.java is not None:
            settings.java = args.java
            changed = True
        if args.width is not None:
            settings.width = args.width
            changed = True
        if args.height is not None:
            settings.height = args.height
            changed = True
    except LaunchError as error:
        print(f"mcmgr: {error}", file=sys.stderr)
        return EXIT_ERROR
    for name in args.unset or []:
        setattr(settings, name, None)
        changed = True
    if args.clear_jvm_args:
        settings.jvm_args = []
        changed = True
    if args.clear_game_args:
        settings.game_args = []
        changed = True
    if args.jvm_arg:
        settings.jvm_args.extend(args.jvm_arg)
        changed = True
    if args.game_arg:
        settings.game_args.extend(args.game_arg)
        changed = True

    if changed:
        settings.save(path)
        print(f"saved launch settings to {path}")
    _print_settings(version_id, settings, path)
    return EXIT_OK


def _print_skin(version_id: str, info: dict, *, installed: bool = False) -> None:
    width, height = info.get("image_size") or ("?", "?")
    state = "enabled" if info.get("enabled") else "not enabled in options.txt"
    print(f"default character skin for {version_id}")
    print(f"  image   : {info.get('image')} ({width}x{height}, sha1 {str(info.get('image_sha1'))[:12]})")
    print(f"  pack    : {info.get('pack')} (format {info.get('pack_format')}, model {info.get('model')})")
    print(f"  layout  : {info.get('layout')} ({info.get('textures', '?')} texture files)")
    print(f"  options : {state}")
    if installed:
        print(f"start the game with: mcmgr launch {version_id}")


def cmd_skin(args: argparse.Namespace) -> int:
    store = _store(args)
    version_id = args.version
    if args.clear:
        removed = skinmod.remove(store, version_id)
        if removed:
            print(f"removed the custom default-character skin for {version_id}")
        else:
            print(f"no custom default-character skin for {version_id}")
        return EXIT_OK
    if args.show or not args.file:
        info = skinmod.info(store, version_id)
        if info is None:
            print(f"no custom default-character skin for {version_id}")
            return EXIT_OK
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            _print_skin(version_id, info)
        return EXIT_OK
    try:
        info = skinmod.install(store, version_id, Path(args.file).expanduser(), model=args.model)
    except skinmod.SkinError as error:
        print(f"mcmgr: {error}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        _print_skin(version_id, info, installed=True)
    return EXIT_OK


def _print_lang(info: dict) -> None:
    print(f"language : {info.get('language') or '(not set; game default en_us)'}")
    system = info.get("system_locale") or "(unknown locale)"
    suggested = info.get("suggested") or "(no matching language)"
    print(f"system   : {system} -> {suggested}")
    if info.get("available"):
        style = "legacy .lang, upper-case regions" if info.get("legacy_codes") else "json, lower-case codes"
        print(f"available: {info['available']} language(s) ({style})")
    else:
        print("available: (asset index not downloaded; code style derived from the version number)")
    print(f"options  : {info['options']}")


def cmd_lang(args: argparse.Namespace) -> int:
    store = _store(args)
    version_id = args.version
    try:
        if args.clear:
            removed = langmod.clear(store, version_id)
            if removed:
                print(f"removed the language override for {version_id}; the game uses its own default again")
            else:
                print(f"no language override for {version_id}")
            return EXIT_OK
        if args.lang_set:
            code = langmod.set_language(store, version_id, args.lang_set)
            print(f"language for {version_id}: {code}")
            return EXIT_OK
        if args.lang_list:
            codes = langmod.available(store, version_id, fetch=True)
            if not codes:
                print(f"mcmgr: no language list available for {version_id}", file=sys.stderr)
                return EXIT_ERROR
            for code in codes:
                print(code)
            return EXIT_OK
        info = langmod.info(store, version_id)
    except (langmod.LangError, meta.VersionNotFound, OSError) as error:
        print(f"mcmgr: {error}", file=sys.stderr)
        return EXIT_ERROR
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        _print_lang(info)
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    store = _store(args)
    version_id = _resolve(store, args.version)
    problems = verify_version(store, version_id)
    if not problems:
        print(f"{version_id}: all files verified")
        return EXIT_OK
    print(f"{version_id}: {len(problems)} problem(s)")
    for problem in problems[:20]:
        print(f"  {problem}")
    if len(problems) > 20:
        print(f"  ... and {len(problems) - 20} more")
    print(f"fix with: mcmgr install {version_id} --force")
    return EXIT_ERROR


def cmd_remove(args: argparse.Namespace) -> int:
    store = _store(args)
    version_id = _resolve(store, args.version)
    removed = remove_version(store, version_id, keep_instance=not args.all_files)
    if not removed:
        print(f"{version_id} is not installed")
        return EXIT_OK
    for path in removed:
        print(f"removed {path}")
    if not args.all_files:
        print(f"kept instance data in {store.instance_dir(version_id)} (use --all-files to delete)")
    return EXIT_OK


def cmd_env(args: argparse.Namespace) -> int:
    store = _store(args)
    report = doctor.collect(store)
    if args.json:
        print(json.dumps(report, indent=2))
        return EXIT_OK
    print(doctor.render(report))
    return EXIT_OK


def cmd_javas(args: argparse.Namespace) -> int:
    candidates = discover_java()
    if not candidates:
        print("no Java runtime found")
        return EXIT_ERROR
    print(f"{len(candidates)} Java runtime(s):")
    for path, major in candidates:
        print(f"  Java {major:<3} {path}")
    return EXIT_OK


def cmd_info(args: argparse.Namespace) -> int:
    store = _store(args)
    version_id = _resolve(store, args.version)
    version = meta.get_version_json(store, version_id)
    assets = (version.get("assetIndex") or {}).get("id")
    print(f"id:        {version.get('id')}")
    print(f"type:      {version.get('type')}")
    print(f"released:  {version.get('releaseTime')}")
    print(f"main:      {version.get('mainClass')}")
    print(f"java:      {(version.get('javaVersion') or {}).get('majorVersion', '?')}+")
    print(f"libraries: {len(version.get('libraries', []))}")
    print(f"asset idx: {assets}")
    print(f"installed: {'yes' if store.install_record(version_id).is_file() else 'no'}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcmgr",
        description="Download, install and run vanilla Minecraft (Java Edition).",
    )
    parser.add_argument("--root", help="store directory (default: $MCMGR_HOME or ~/.mcmgr)")
    parser.add_argument(
        "--mirror",
        choices=list(mirror.MODES),
        help=(
            "download source: official (Mojang CDN), bmclapi (China mirror), "
            "auto = official with mirror fallback (default: $MCMGR_MIRROR or auto)"
        ),
    )
    parser.add_argument("--version", action="version", version=f"mcmgr {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    versions = subparsers.add_parser("versions", help="list versions from the Mojang manifest")
    versions.add_argument("--type", choices=["release", "snapshot", "old", "all"], default="release")
    versions.add_argument("--search", help="filter by substring")
    versions.add_argument("--limit", type=int, default=20)
    versions.add_argument("--refresh", action="store_true", help="ignore the cached manifest")
    versions.add_argument("--json", action="store_true")
    versions.set_defaults(func=cmd_versions)

    install = subparsers.add_parser("install", help="install a version")
    install.add_argument("version", help="version id, or latest/latest-snapshot")
    install.add_argument("--no-assets", action="store_true", help="skip asset objects (game will look broken)")
    install.add_argument(
        "--jobs",
        type=int,
        default=8,
        metavar="N",
        help="files downloaded in parallel (default: 8)",
    )
    install.add_argument(
        "--threads",
        type=int,
        default=4,
        metavar="N",
        help="connections per large file, split with HTTP ranges (default: 4, 1 = off)",
    )
    install.add_argument("--force", action="store_true", help="re-fetch the version json")
    install.set_defaults(func=cmd_install)

    listing = subparsers.add_parser("list", help="list installed versions")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    run = subparsers.add_parser("launch", help="launch an installed version offline")
    run.add_argument("version")
    run.add_argument(
        "-u", "--username", "--name", dest="username",
        help="offline player name (default: saved value or Player)",
    )
    run.add_argument("--uuid", help="player UUID (8-4-4-4-12 or 32 hex); 'offline' derives it from the username")
    run.add_argument("-m", "--memory", type=_parse_memory, help="heap size, e.g. 2G")
    run.add_argument("--java", help="path to a java executable")
    run.add_argument("--width", type=int)
    run.add_argument("--height", type=int)
    run.add_argument(
        "--jvm-arg",
        dest="jvm_arg",
        action="append",
        metavar="ARG",
        help="extra JVM flag, repeatable (spell it --jvm-arg=-Dkey=value)",
    )
    run.add_argument(
        "--game-arg",
        dest="game_args",
        action="append",
        metavar="ARG",
        help="extra game argument, repeatable",
    )
    run.add_argument("--save", action="store_true", help="remember these options for the next launch")
    run.add_argument("--dry-run", action="store_true", help="print the command instead of running it")
    run.set_defaults(func=cmd_launch)

    config = subparsers.add_parser("config", help="remember launch options for a version")
    config.add_argument("version")
    config.add_argument("-u", "--username", "--name", dest="username", help="offline player name")
    config.add_argument("--uuid", help="player UUID (8-4-4-4-12 or 32 hex); 'offline' derives it from the username")
    config.add_argument("-m", "--memory", type=_parse_memory, help="heap size, e.g. 2G")
    config.add_argument("--java", help="path to a java executable")
    config.add_argument("--width", type=int)
    config.add_argument("--height", type=int)
    config.add_argument(
        "--jvm-arg",
        dest="jvm_arg",
        action="append",
        metavar="ARG",
        help="append an extra JVM flag, repeatable (spell it --jvm-arg=-Dkey=value)",
    )
    config.add_argument(
        "--game-arg",
        dest="game_arg",
        action="append",
        metavar="ARG",
        help="append an extra game argument, repeatable",
    )
    config.add_argument("--clear-jvm-args", action="store_true", help="forget all extra JVM flags")
    config.add_argument("--clear-game-args", action="store_true", help="forget all extra game arguments")
    config.add_argument(
        "--unset",
        action="append",
        choices=list(SCALAR_FIELDS),
        metavar="FIELD",
        help="forget one field (username, uuid, memory, java, width, height), repeatable",
    )
    config.add_argument("--reset", action="store_true", help="forget everything saved for this version")
    config.add_argument("--show", action="store_true", help="print the settings (default when nothing changes)")
    config.set_defaults(func=cmd_config)

    skin = subparsers.add_parser("skin", help="use a custom default-character skin (offline players)")
    skin.add_argument("version")
    skin.add_argument("-f", "--file", help="64x64 (or legacy 64x32) PNG skin image")
    skin.add_argument(
        "--model",
        choices=list(skinmod.MODELS),
        default="both",
        help="default models to replace: classic, slim, or both (default: both)",
    )
    skin.add_argument("--show", action="store_true", help="print the installed skin (default when --file is omitted)")
    skin.add_argument("--clear", action="store_true", help="remove the skin pack")
    skin.add_argument("--json", action="store_true")
    skin.set_defaults(func=cmd_skin)

    lang_parser = subparsers.add_parser("lang", help="use the system language for the game")
    lang_parser.add_argument("version")
    lang_parser.add_argument(
        "--set",
        dest="lang_set",
        metavar="CODE|system",
        help="language code such as zh_cn, or 'system' for the detected locale",
    )
    lang_parser.add_argument("--show", action="store_true", help="print the current language (default)")
    lang_parser.add_argument("--list", dest="lang_list", action="store_true", help="list the languages shipped by this version")
    lang_parser.add_argument("--clear", action="store_true", help="remove the lang entry")
    lang_parser.add_argument("--json", action="store_true")
    lang_parser.set_defaults(func=cmd_lang)

    verify = subparsers.add_parser("verify", help="check installed files against their hashes")
    verify.add_argument("version")
    verify.set_defaults(func=cmd_verify)

    remove = subparsers.add_parser("remove", help="delete an installed version")
    remove.add_argument("version")
    remove.add_argument("--all-files", action="store_true", help="also delete the instance/game directory")
    remove.set_defaults(func=cmd_remove)

    env = subparsers.add_parser("env", help="show version, build, store and environment details")
    env.add_argument("--json", action="store_true")
    env.set_defaults(func=cmd_env)

    javas = subparsers.add_parser("javas", help="list detected Java runtimes")
    javas.set_defaults(func=cmd_javas)

    info = subparsers.add_parser("info", help="show a version's metadata")
    info.add_argument("version")
    info.set_defaults(func=cmd_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, extras = parser.parse_known_args(argv)
    if args.command == "launch":
        if extras and extras[0] == "--":
            extras = extras[1:]
        args.game_args = list(args.game_args or []) + extras
    elif extras:
        parser.error("unrecognized arguments: " + " ".join(extras))
    try:
        return int(args.func(args))
    except meta.VersionNotFound as error:
        print(f"mcmgr: {error}", file=sys.stderr)
        return EXIT_ERROR
    except DownloadError as error:
        print(f"mcmgr: download failed: {error}", file=sys.stderr)
        print("  (already downloaded files are verified and skipped next time)", file=sys.stderr)
        return EXIT_ERROR
    except OSError as error:
        print(f"mcmgr: {error}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
