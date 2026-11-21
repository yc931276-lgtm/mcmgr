"""Use the operating system's language for the game by default.

Minecraft always starts in English (``en_us``) unless ``options.txt`` contains
a ``lang`` entry.  This module detects the system locale, maps it onto the
language that the installed version actually ships, and writes that entry.

Two things make the mapping version dependent:

* up to 1.12.2 the language files are ``assets/minecraft/lang/zh_CN.lang``
  and the codes keep an upper-case region (``zh_CN``);
* from 1.13 on the files are ``zh_cn.json`` and the codes are lower case
  (``zh_cn``).

The available codes are read from the version's asset index, so the right
spelling is used for every version.  If the index has not been downloaded yet
the style is derived from the version number instead, which covers the common
languages without touching the network.
"""

from __future__ import annotations

import json
import locale as localemod
import os
import re
import sys
from pathlib import Path

from . import meta, mirror, net
from .paths import Store

LANG_PREFIX = "minecraft/lang/"
LEGACY_SWITCH = (1, 13)
OPTIONS_NAME = "options.txt"

#: Default region used when the locale only names a language (``zh``,
#: ``en``, ...).  Values are the regions used by Minecraft's language codes.
DEFAULT_REGIONS = {
    "en": "us",
    "zh": "cn",
    "ja": "jp",
    "ko": "kr",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "pt": "br",
    "ru": "ru",
    "it": "it",
    "nl": "nl",
    "pl": "pl",
    "tr": "tr",
    "sv": "se",
    "da": "dk",
    "fi": "fi",
    "nb": "no",
    "nn": "no",
    "cs": "cz",
    "sk": "sk",
    "hu": "hu",
    "ro": "ro",
    "bg": "bg",
    "el": "gr",
    "uk": "ua",
    "be": "by",
    "sr": "sp",
    "hr": "hr",
    "sl": "si",
    "lt": "lt",
    "lv": "lv",
    "et": "ee",
    "is": "is",
    "ga": "ie",
    "cy": "gb",
    "mk": "mk",
    "sq": "al",
    "bs": "ba",
    "he": "il",
    "ar": "sa",
    "fa": "ir",
    "hi": "in",
    "th": "th",
    "vi": "vn",
    "id": "id",
    "ms": "my",
    "tl": "ph",
    "ca": "es",
}

SYSTEM_KEYWORDS = {"system", "auto", "default", "os"}

_CODE_RE = re.compile(r"^[A-Za-z]{2,3}(?:_[A-Za-z0-9]{2,})?$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")


class LangError(RuntimeError):
    """The requested language could not be mapped to this version."""


# -- locale detection -----------------------------------------------------


def _clean_locale(value: str) -> str:
    """Turn ``zh_CN.UTF-8@euro`` into ``zh_CN`` and normalise separators."""
    value = value.strip().split(":", 1)[0]
    value = value.split(".", 1)[0]
    value = value.split("@", 1)[0]
    return value.replace("-", "_")


def system_locale() -> str | None:
    """Best guess for the user's locale, e.g. ``zh_CN`` or ``en_US``."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG"):
        raw = os.environ.get(name)
        if not raw:
            continue
        for part in raw.split(":"):
            code = _clean_locale(part)
            if code and code.upper() not in ("C", "POSIX"):
                return code
    if sys.platform == "win32":
        try:
            import ctypes

            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            name = localemod.windows_locale.get(langid)
            if name:
                return _clean_locale(name)
        except (ImportError, AttributeError, OSError):
            pass
    try:
        value = localemod.getdefaultlocale()[0]
    except (ValueError, OSError):
        value = None
    if value:
        cleaned = _clean_locale(value)
        if cleaned.upper() not in ("C", "POSIX"):
            return cleaned
    return None


# -- language codes -------------------------------------------------------


def _version_tuple(version_id: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.match(version_id)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def is_legacy(version_id: str) -> bool:
    """True for versions that still use upper-case language codes (pre-1.13)."""
    parsed = _version_tuple(version_id)
    if parsed is None:
        return False
    return parsed < LEGACY_SWITCH


def default_code(locale: str, version_id: str) -> str | None:
    """Map a locale onto Minecraft's spelling for *version_id* without I/O."""
    value = _clean_locale(locale)
    if not value:
        return None
    language, _, region = value.partition("_")
    language = language.lower()
    if not language.isalpha() or len(language) < 2:
        return None
    if not region:
        region = DEFAULT_REGIONS.get(language)
        if not region:
            return None
    if is_legacy(version_id):
        return f"{language}_{region.upper()}"
    return f"{language}_{region.lower()}"


def pick(locale: str, available_codes: list[str]) -> str | None:
    """Choose the closest code from *available_codes* for *locale*."""
    if not available_codes:
        return None
    wanted = _clean_locale(locale).lower()
    if not wanted:
        return None
    by_lower = {code.lower(): code for code in available_codes}
    if wanted in by_lower:
        return by_lower[wanted]
    language = wanted.split("_", 1)[0]
    same_language = [code for code in available_codes if code.lower().startswith(language + "_")]
    if not same_language:
        return None
    preferred = DEFAULT_REGIONS.get(language)
    if preferred:
        candidate = f"{language}_{preferred}".lower()
        if candidate in by_lower:
            return by_lower[candidate]
    return sorted(same_language, key=str.lower)[0]


def _index_path(store: Store, version_id: str) -> tuple[Path | None, str]:
    version = meta.get_version_json(store, version_id)
    index = version.get("assetIndex") or {}
    index_id = index.get("id")
    if not index_id:
        return None, ""
    return store.index_path(index_id), str(index.get("url") or "")


def available(store: Store, version_id: str, *, fetch: bool = False) -> list[str]:
    """Language codes shipped by this version, read from its asset index."""
    try:
        path, url = _index_path(store, version_id)
    except (meta.VersionNotFound, OSError):
        return []
    if path is None:
        return []
    if not path.is_file() and fetch and url:
        urls = mirror.candidates(store.mirror, url, version_id=version_id)
        try:
            net.download(urls[0], path, alternates=urls[1:], retries=1)
        except net.DownloadError:
            return []
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return []
    codes: set[str] = set()
    for key in (data.get("objects") or {}):
        if not key.startswith(LANG_PREFIX):
            continue
        name = key[len(LANG_PREFIX):]
        stem, dot, suffix = name.rpartition(".")
        if dot and suffix in ("json", "lang") and stem:
            codes.add(stem)
    return sorted(codes, key=str.lower)


# -- options.txt ----------------------------------------------------------


def options_path(store: Store, version_id: str) -> Path:
    return store.instance_dir(version_id) / OPTIONS_NAME


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text("utf-8").splitlines()
    except FileNotFoundError:
        return []


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(lines) + "\n", "utf-8")
    temporary.replace(path)


def _find_lang(lines: list[str]) -> tuple[int | None, str]:
    for index, line in enumerate(lines):
        if line.startswith("lang:"):
            return index, line[len("lang:"):].strip()
    return None, ""


def current(store: Store, version_id: str) -> str | None:
    """The language currently written in options.txt, if any."""
    index, value = _find_lang(_read_lines(options_path(store, version_id)))
    return value if index is not None and value else None


def clear(store: Store, version_id: str) -> bool:
    """Remove the lang entry so the game falls back to its own default."""
    path = options_path(store, version_id)
    lines = _read_lines(path)
    remaining = [line for line in lines if not line.startswith("lang:")]
    if len(remaining) == len(lines):
        return False
    _write_lines(path, remaining)
    return True


def write(store: Store, version_id: str, code: str) -> None:
    path = options_path(store, version_id)
    lines = _read_lines(path)
    index, _ = _find_lang(lines)
    line = f"lang:{code}"
    if index is None:
        lines.append(line)
    else:
        lines[index] = line
    _write_lines(path, lines)


def canonical(code: str, version_id: str, codes: list[str] | None = None) -> str:
    """Normalise an explicit code to the spelling used by this version."""
    value = code.strip()
    if not value or not _CODE_RE.match(value):
        raise LangError(f"invalid language code {code!r}; expected something like en_us or zh_cn")
    if codes:
        by_lower = {item.lower(): item for item in codes}
        if value.lower() in by_lower:
            return by_lower[value.lower()]
        sample = ", ".join(sorted(codes, key=str.lower)[:8])
        raise LangError(f"unsupported language {value!r} for this version (examples: {sample}; use --list)")
    mapped = default_code(value, version_id)
    if mapped:
        return mapped
    raise LangError(f"invalid language code {code!r}")


def detect(store: Store, version_id: str, *, fetch: bool = False) -> tuple[str | None, str | None]:
    """Return ``(language_code, system_locale)`` for this version."""
    locale = system_locale()
    if not locale:
        return None, None
    codes = available(store, version_id, fetch=fetch)
    code = pick(locale, codes) if codes else default_code(locale, version_id)
    return code, locale


def set_language(store: Store, version_id: str, value: str, *, fetch: bool = True) -> str:
    """Set an explicit code, or ``system`` to use the detected locale."""
    if value.strip().lower() in SYSTEM_KEYWORDS:
        codes = available(store, version_id, fetch=fetch)
        locale = system_locale()
        if not locale:
            raise LangError("could not detect the system language (LC_ALL/LANG are unset or C/POSIX)")
        code = pick(locale, codes) if codes else default_code(locale, version_id)
        if not code:
            raise LangError(f"the system language {locale!r} has no Minecraft counterpart for {version_id}")
    else:
        codes = available(store, version_id, fetch=fetch)
        code = canonical(value, version_id, codes)
    write(store, version_id, code)
    return code


def ensure_default(store: Store, version_id: str) -> tuple[str, str] | None:
    """Set the language from the system locale only if options.txt lacks one."""
    if current(store, version_id):
        return None
    try:
        code, locale = detect(store, version_id)
    except (LangError, meta.VersionNotFound, OSError):
        return None
    if not code or not locale:
        return None
    try:
        write(store, version_id, code)
    except OSError:
        return None
    return code, locale


def info(store: Store, version_id: str, *, fetch: bool = False) -> dict:
    codes = available(store, version_id, fetch=fetch)
    locale = system_locale()
    suggested = pick(locale, codes) if (locale and codes) else (default_code(locale, version_id) if locale else None)
    return {
        "version": version_id,
        "options": str(options_path(store, version_id)),
        "language": current(store, version_id),
        "system_locale": locale,
        "suggested": suggested,
        "available": len(codes),
        "codes": codes,
        "legacy_codes": is_legacy(version_id),
    }
