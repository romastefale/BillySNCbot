from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from app.config.settings import CODE_OWNER_IDS
from app.services.allow_control import command_is_publicly_enabled, ensure_allow_runtime

logger = logging.getLogger(__name__)

_COMMAND_SYNC_ATTEMPTS = 3
_COMMAND_SYNC_RETRY_SECONDS = 0.5


class CommandMenuSyncError(RuntimeError):
    """Raised when Telegram does not confirm the expected command menu."""


@dataclass(frozen=True)
class CommandDef:
    command: str
    description: str


_PRIVATE_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("start", "Boas-vindas e conexão"),
    CommandDef("help", "Comandos disponíveis"),
    CommandDef("lastfm", "Conectar ou ver Last.fm"),
    CommandDef("lastfmoff", "Desconectar Last.fm"),
    CommandDef("login", "Conectar Spotify"),
    CommandDef("logout", "Desconectar Spotify"),
    CommandDef("playing", "Sua música tocando agora"),
    CommandDef("albnow", "Álbum da música atual"),
    CommandDef("tcanvas", "Canvas Spotify da música atual"),
    CommandDef("tstory", "Story da música atual"),
    CommandDef("tly", "Trecho de letra da música atual"),
    CommandDef("radiofm", "Buscar uma música"),
    CommandDef("nowp", "Enviar sua música para grupo"),
    CommandDef("tiddd", "Criar Track ID manual"),
    CommandDef("hitmo", "Converter vídeo em áudio de voz"),
    CommandDef("myself", "Menu de extratos pessoais"),
    CommandDef("weekfm", "Extrato semanal Last.fm"),
    CommandDef("monthfm", "Extrato mensal Last.fm"),
)

# Mantido como catálogo de capacidades de grupo para compatibilidade e auditoria.
# O menu slash de grupos é deliberadamente vazio; os comandos continuam
# executáveis manualmente quando estiverem liberados pelo /allow.
_GROUP_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("help", "Comandos musicais do grupo"),
    CommandDef("lastfm", "Conectar ou ver Last.fm"),
    CommandDef("lastfmoff", "Desconectar Last.fm"),
    CommandDef("playing", "Sua música no grupo"),
    CommandDef("albnow", "Álbum da música atual"),
    CommandDef("tcanvas", "Canvas Spotify da música atual"),
    CommandDef("tstory", "Story da música atual"),
    CommandDef("tly", "Trecho de letra da música atual"),
    CommandDef("radiofm", "Buscar uma música no grupo"),
    CommandDef("tnow", "Mosaico de ouvintes do grupo"),
    CommandDef("tiddd", "Criar Track ID manual no grupo"),
    CommandDef("hitmo", "Converter vídeo em áudio de voz"),
    CommandDef("god", "Ver permissões do bot no grupo"),
    CommandDef("myself", "Menu de extratos pessoais"),
    CommandDef("weekfm", "Extrato semanal Last.fm"),
    CommandDef("monthfm", "Extrato mensal Last.fm"),
    CommandDef("songcharts", "Ranking musical do grupo"),
)

_OWNER_ONLY_COMMANDS: tuple[CommandDef, ...] = (
    # /tnow também funciona como mosaico universal quando o owner o executa na DM.
    CommandDef("tnow", "Mosaico universal na DM"),
    CommandDef("tnowall", "Mosaico consolidado por DM"),
    CommandDef("songchartsall", "Ranking consolidado por DM"),
    CommandDef("weekall", "Ranking semanal consolidado"),
    CommandDef("monthall", "Ranking mensal consolidado"),
    CommandDef("tmn", "Cadastrar usuário Last.fm manualmente"),
    CommandDef("tpv", "Privacidade visual no mosaico"),
    CommandDef("lfmcheckauth", "Diagnosticar credenciais Last.fm"),
    CommandDef("lfmimportcsv", "Importar scrobbles Last.fm por CSV"),
    CommandDef("onoff", "Silenciar usuários comuns"),
    CommandDef("legacy", "Restringir logins antigos"),
    CommandDef("listening", "Exportar banco completo"),
)

_ALLOW_COMMAND = CommandDef("allow", "Disponibilidade dos recursos")
_OWNER_PRIVATE_COMMANDS: tuple[CommandDef, ...] = _PRIVATE_COMMANDS + _OWNER_ONLY_COMMANDS

# Compatibilidade com testes e scripts antigos: "public" representa os comandos
# comuns de DM. Os escopos reais são private, group e owner_private.
_PUBLIC_COMMANDS = _PRIVATE_COMMANDS


def _visible_commands(commands: tuple[CommandDef, ...]) -> tuple[CommandDef, ...]:
    return tuple(item for item in commands if command_is_publicly_enabled(item.command))


def _owner_menu_commands() -> tuple[CommandDef, ...]:
    visible = list(_visible_commands(_OWNER_PRIVATE_COMMANDS))
    if all(item.command != _ALLOW_COMMAND.command for item in visible):
        visible.append(_ALLOW_COMMAND)
    return tuple(visible)


def private_command_definitions(*, is_owner: bool) -> tuple[CommandDef, ...]:
    """Return exactly the command definitions published in a private chat."""
    return _owner_menu_commands() if is_owner else _visible_commands(_PRIVATE_COMMANDS)


def private_help_text(*, is_owner: bool) -> str:
    """Render /help from the same definitions used by Telegram's private menu."""
    commands = private_command_definitions(is_owner=is_owner)
    lines = ["<b>Comandos da sua DM</b>", ""]
    lines.extend(
        f"<code>/{item.command}</code> — {item.description}."
        for item in commands
    )
    return "\n".join(lines)


def _to_bot_commands(commands: tuple[CommandDef, ...]) -> list[BotCommand]:
    return [BotCommand(command=item.command, description=item.description[:256]) for item in commands]


def _command_signature(commands: list[BotCommand] | tuple[BotCommand, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((item.command, item.description) for item in commands)


async def _verify_scope(bot: Bot, *, scope, expected: list[BotCommand], label: str) -> None:
    actual = await bot.get_my_commands(scope=scope)
    expected_signature = _command_signature(expected)
    actual_signature = _command_signature(actual)
    if actual_signature != expected_signature:
        raise CommandMenuSyncError(
            f"Telegram command menu mismatch for {label}: "
            f"expected={expected_signature!r} actual={actual_signature!r}"
        )


async def _publish_and_verify(
    bot: Bot,
    *,
    private_commands: list[BotCommand],
    owner_commands: list[BotCommand],
) -> None:
    default_scope = BotCommandScopeDefault()
    private_scope = BotCommandScopeAllPrivateChats()
    group_scope = BotCommandScopeAllGroupChats()

    # Sem comandos default, grupos não herdam o catálogo privado ao abrir "/".
    await bot.delete_my_commands(scope=default_scope)
    await bot.set_my_commands(private_commands, scope=private_scope)
    await bot.delete_my_commands(scope=group_scope)

    # A API pode aceitar a chamada sem que o estado observado corresponda ao
    # esperado. Ler os escopos de volta elimina falso positivo no startup e no
    # painel /allow.
    await _verify_scope(bot, scope=default_scope, expected=[], label="default")
    await _verify_scope(bot, scope=private_scope, expected=private_commands, label="private")
    await _verify_scope(bot, scope=group_scope, expected=[], label="groups")

    for owner_id in sorted(int(value) for value in CODE_OWNER_IDS):
        owner_scope = BotCommandScopeChat(chat_id=owner_id)
        await bot.set_my_commands(owner_commands, scope=owner_scope)
        await _verify_scope(
            bot,
            scope=owner_scope,
            expected=owner_commands,
            label=f"owner:{owner_id}",
        )


def command_scope_summary() -> dict[str, object]:
    visible_private = [item.command for item in private_command_definitions(is_owner=False)]
    visible_owner = [item.command for item in private_command_definitions(is_owner=True)]
    return {
        # Catálogos históricos preservados para testes e scripts existentes.
        "public": [item.command for item in _PUBLIC_COMMANDS],
        "private": [item.command for item in _PRIVATE_COMMANDS],
        "group": [item.command for item in _GROUP_COMMANDS],
        "owner_private": [item.command for item in _OWNER_PRIVATE_COMMANDS],
        "owner_only": [item.command for item in _OWNER_ONLY_COMMANDS],
        # Estado efetivamente publicado pelo Telegram nesta versão.
        "visible_private": visible_private,
        "group_menu": [],
        "visible_owner_private": visible_owner,
    }


async def setup_bot_commands(
    bot: Bot,
    *,
    attempts: int = _COMMAND_SYNC_ATTEMPTS,
    raise_on_error: bool = False,
) -> bool:
    """Publish command menus and confirm the exact state returned by Telegram.

    Startup uses the default non-raising mode so a transient menu failure does
    not take the webhook offline. Interactive /allow operations use
    ``raise_on_error=True`` and only confirm success after Telegram readback.
    """
    ensure_allow_runtime()
    private_commands = _to_bot_commands(private_command_definitions(is_owner=False))
    owner_commands = _to_bot_commands(private_command_definitions(is_owner=True))
    total_attempts = max(1, int(attempts))
    last_error: Exception | None = None

    for attempt in range(1, total_attempts + 1):
        try:
            await _publish_and_verify(
                bot,
                private_commands=private_commands,
                owner_commands=owner_commands,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "BOT_COMMANDS_SYNC_ATTEMPT_FAILED attempt=%s/%s error=%s",
                attempt,
                total_attempts,
                f"{type(exc).__name__}: {exc}",
                exc_info=True,
            )
            if attempt < total_attempts:
                await asyncio.sleep(_COMMAND_SYNC_RETRY_SECONDS * attempt)
            continue

        logger.info(
            "BOT_COMMANDS_SYNC_VERIFIED | private=%s group=0 owner_ids=%s attempt=%s",
            len(private_commands),
            len(CODE_OWNER_IDS),
            attempt,
        )
        return True

    error = CommandMenuSyncError(
        f"Telegram command menu was not synchronized after {total_attempts} attempt(s)"
    )
    if last_error is not None:
        error.__cause__ = last_error
    logger.error("BOT_COMMANDS_SYNC_FAILED attempts=%s", total_attempts, exc_info=last_error)
    if raise_on_error:
        raise error
    return False
