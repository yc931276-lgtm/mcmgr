"""Mojang rule evaluation (``libraries[].rules`` / ``arguments[].rules``)."""

from __future__ import annotations

import platform
import re

_ARCH_ALIASES = {
    "amd64": "x86_64",
    "x86_64": "x86_64",
    "x64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "i386": "x86",
    "i486": "x86",
    "i586": "x86",
    "i686": "x86",
    "x86": "x86",
}


def os_name() -> str:
    """Mojang's ``os.name`` value for this machine."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "osx"
    return system or "linux"


def os_arch() -> str:
    machine = platform.machine().lower()
    return _ARCH_ALIASES.get(machine, machine)


def os_version() -> str:
    """Best-effort equivalent of Java's ``os.version`` system property."""
    if platform.system() == "Windows":
        return platform.version()
    return platform.release()


def rule_matches(rule: dict, features: dict | None = None) -> bool:
    """Whether a single rule's conditions apply here."""
    os_rule = rule.get("os")
    if os_rule:
        name = os_rule.get("name")
        if name and name != os_name():
            return False
        arch = os_rule.get("arch")
        if arch and arch != os_arch():
            return False
        version = os_rule.get("version")
        if version and not re.search(version, os_version()):
            return False

    feature_rule = rule.get("features")
    if feature_rule:
        have = features or {}
        for key, wanted in feature_rule.items():
            if bool(have.get(key, False)) != bool(wanted):
                return False

    return True


def rules_allow(rules: list[dict] | None, features: dict | None = None) -> bool:
    """Whether a rule list allows the element on this machine.

    No rules means allowed.  Otherwise the last matching rule wins, with
    "nothing matched" meaning disallowed.
    """
    if not rules:
        return True
    allowed = False
    for rule in rules:
        if rule_matches(rule, features):
            allowed = rule.get("action") == "allow"
    return allowed


def native_classifier_suffix() -> str:
    """The ``natives-<os>`` classifier suffix used by legacy versions."""
    return f"natives-{os_name()}"
