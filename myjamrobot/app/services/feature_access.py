from __future__ import annotations

from collections.abc import Iterable

from app.services.ops_control import get_state_bool, set_state_bool

FEATURE_ORDER: tuple[str, ...] = (
    "tnow",
    "songcharts",
    "weekfm",
    "monthfm",
    "tcanvas",
    "login",
    "albnow",
    "myself",
    "legacy",
)

FEATURE_LABELS: dict[str, str] = {
    "tnow": "tnow",
    "songcharts": "songcharts",
    "weekfm": "weekfm",
    "monthfm": "monthfm",
    "tcanvas": "tcanvas",
    "login": "login",
    "albnow": "albnow",
    "myself": "myself",
    "legacy": "legacy",
}

_COMMAND_FEATURES: dict[str, str] = {
    "tnow": "tnow",
    "tnowall": "tnow",
    "tnowuniversal": "tnow",
    "songcharts": "songcharts",
    "songchartsall": "songcharts",
    "songchartsuniversal": "songcharts",
    "weekall": "songcharts",
    "monthall": "songcharts",
    "weekfm": "weekfm",
    "monthfm": "monthfm",
    "tcanvas": "tcanvas",
    "login": "login",
    "albnow": "albnow",
    "myself": "myself",
    "legacy": "legacy",
}

_CALLBACK_FEATURE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("songcharts:", "songcharts"),
    ("myself:w:", "weekfm"),
    ("myself:m:", "monthfm"),
)

_INLINE_KIND_FEATURES: dict[str, str] = {
    "week": "weekfm",
    "weekfm": "weekfm",
    "weekly": "weekfm",
    "semana": "weekfm",
    "semanal": "weekfm",
    "month": "monthfm",
    "monthfm": "monthfm",
    "monthly": "monthfm",
    "mes": "monthfm",
    "mês": "monthfm",
    "mensal": "monthfm",
    "tcanvas": "tcanvas",
    "canvas": "tcanvas",
    "tnow": "tnow",
    "mosaic": "tnow",
    "mosaico": "tnow",
}


def _state_key(feature: str) -> str:
    normalized = str(feature or "").strip().lower()
    if normalized not in FEATURE_ORDER:
        raise ValueError(f"Unknown allow feature: {feature}")
    return f"allow_feature_{normalized}_enabled"


def is_feature_enabled(feature: str) -> bool:
    return get_state_bool(_state_key(feature), default=True)


def set_feature_enabled(feature: str, enabled: bool, *, owner_user_id: int | None = None) -> None:
    set_state_bool(_state_key(feature), bool(enabled), owner_user_id=owner_user_id)


def feature_states() -> dict[str, bool]:
    return {feature: is_feature_enabled(feature) for feature in FEATURE_ORDER}


def command_feature(command: str | None) -> str | None:
    normalized = str(command or "").strip().lower().lstrip("/").split("@", 1)[0]
    return _COMMAND_FEATURES.get(normalized)


def callback_feature(callback_data: str | None) -> str | None:
    value = str(callback_data or "")
    for prefix, feature in _CALLBACK_FEATURE_PREFIXES:
        if value.startswith(prefix):
            return feature
    return None


def inline_feature(query: str | None) -> str | None:
    value = str(query or "").strip()
    if not value:
        return None
    first = value.split(maxsplit=1)[0].casefold()
    return _INLINE_KIND_FEATURES.get(first)


def filter_enabled_commands(commands: Iterable[object]) -> tuple[object, ...]:
    output: list[object] = []
    for item in commands:
        command = getattr(item, "command", "")
        feature = command_feature(command)
        if feature is None or is_feature_enabled(feature):
            output.append(item)
    return tuple(output)
