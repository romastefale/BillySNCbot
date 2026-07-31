from __future__ import annotations

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


async def setup_bot_commands(bot: Bot) -> None:
    ensure_allow_runtime()
    private_commands = _to_bot_commands(private_command_definitions(is_owner=False))
    owner_commands = _to_bot_commands(private_command_definitions(is_owner=True))
    try:
        # Sem comandos default, grupos não herdam o catálogo privado ao abrir "/".
        await bot.delete_my_commands(scope=BotCommandScopeDefault())
        await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
        await bot.delete_my_commands(scope=BotCommandScopeAllGroupChats())
        logger.info(
            "BOT_COMMANDS_ALLOW_SET | private=%s group=0 owner_ids=%s",
            len(private_commands),
            len(CODE_OWNER_IDS),
        )
    except Exception:
        logger.warning("BOT_COMMANDS_ALLOW_FAILED", exc_info=True)
        return

    for owner_id in CODE_OWNER_IDS:
        try:
            await bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=owner_id))
        except Exception:
            logger.warning("BOT_OWNER_COMMANDS_SET_FAILED owner_id=%s", owner_id, exc_info=True)
        else:
            logger.info("BOT_OWNER_COMMANDS_SET | owner_id=%s count=%s", owner_id, len(owner_commands))
