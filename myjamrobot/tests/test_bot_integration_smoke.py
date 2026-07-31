"""Smoke tests: verifica que tiddd.py e hitmo.py sobem sem erros de importação,
que os estados FSM estão corretamente registrados e que o Dockerfile instala o
ffmpeg necessário para /hitmo.

Estes testes NÃO precisam de token Telegram nem de banco de dados — são
estáticos (leitura de source) ou de importação pura de módulo.
"""
from __future__ import annotations

from pathlib import Path

# ── caminhos ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]
TIDDD_SRC = (ROOT / "app" / "bot" / "tiddd.py").read_text(encoding="utf-8")
HITMO_SRC = (ROOT / "app" / "bot" / "hitmo.py").read_text(encoding="utf-8")
MAIN_SRC = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")


# ── importação dos módulos ────────────────────────────────────────────────────

def test_tiddd_module_imports_without_error() -> None:
    """app.bot.tiddd deve importar sem ImportError nem AttributeError."""
    from app.bot import tiddd  # noqa: F401  — basta não lançar exceção
    assert hasattr(tiddd, "router"), "tiddd.router deve existir após a importação"
    assert hasattr(tiddd, "TidddFlow"), "tiddd.TidddFlow deve existir após a importação"


def test_hitmo_module_imports_without_error() -> None:
    """app.bot.hitmo deve importar sem ImportError nem AttributeError."""
    from app.bot import hitmo  # noqa: F401
    assert hasattr(hitmo, "router"), "hitmo.router deve existir após a importação"
    assert hasattr(hitmo, "HitmoFlow"), "hitmo.HitmoFlow deve existir após a importação"


# ── StatesGroup: estados corretos ─────────────────────────────────────────────

def test_tidddflow_states_are_registered() -> None:
    """TidddFlow deve registrar coleta, preview e publicação em grupo."""
    from app.bot.tiddd import TidddFlow
    from aiogram.fsm.state import StatesGroup

    assert issubclass(TidddFlow, StatesGroup)
    state_names = {s.state.split(":")[1] for s in TidddFlow.__states__}
    assert state_names == {"musica", "album", "artista", "capa", "preview", "publicar"}, (
        f"Estados inesperados em TidddFlow: {state_names}"
    )


def test_hitmoflow_states_are_registered() -> None:
    """HitmoFlow deve ter exatamente o estado aguardando_video."""
    from app.bot.hitmo import HitmoFlow
    from aiogram.fsm.state import StatesGroup

    assert issubclass(HitmoFlow, StatesGroup)
    state_names = {s.state.split(":")[1] for s in HitmoFlow.__states__}
    assert state_names == {"aguardando_video"}, (
        f"Estados inesperados em HitmoFlow: {state_names}"
    )


# ── routers registrados no dispatcher (main.py) ───────────────────────────────

def test_tiddd_router_imported_and_included_in_main() -> None:
    """main.py deve importar o router do tiddd e incluí-lo no dispatcher."""
    assert "from app.bot.tiddd import router as tiddd_router" in MAIN_SRC, (
        "Importação de tiddd_router ausente em main.py"
    )
    assert "dispatcher.include_router(tiddd_router)" in MAIN_SRC, (
        "dispatcher.include_router(tiddd_router) ausente em main.py"
    )


def test_hitmo_router_imported_and_included_in_main() -> None:
    """main.py deve importar o router do hitmo e incluí-lo no dispatcher."""
    assert "from app.bot.hitmo import router as hitmo_router" in MAIN_SRC, (
        "Importação de hitmo_router ausente em main.py"
    )
    assert "dispatcher.include_router(hitmo_router)" in MAIN_SRC, (
        "dispatcher.include_router(hitmo_router) ausente em main.py"
    )


def test_tiddd_and_hitmo_routers_included_before_register_handlers() -> None:
    """tiddd e hitmo devem ser incluídos ANTES de _register_handlers para que os
    filtros de estado FSM tenham prioridade sobre handlers genéricos de texto."""
    tiddd_pos = MAIN_SRC.index("dispatcher.include_router(tiddd_router)")
    hitmo_pos = MAIN_SRC.index("dispatcher.include_router(hitmo_router)")
    register_pos = MAIN_SRC.index("_register_handlers(dispatcher)")
    assert tiddd_pos < register_pos
    assert hitmo_pos < register_pos


# ── integração estática específica ────────────────────────────────────────────

def test_dockerfile_installs_ffmpeg() -> None:
    assert "ffmpeg" in DOCKERFILE


def test_tiddd_router_has_group_publish_state_handler() -> None:
    assert "TidddFlow.publicar" in TIDDD_SRC
    assert "tiddd_recv_forward" in TIDDD_SRC
