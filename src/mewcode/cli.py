from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

WINDOWS_UTF8_CODE_PAGE = 65001


def configure_windows_console_encoding() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetConsoleCP(WINDOWS_UTF8_CODE_PAGE)
        kernel32.SetConsoleOutputCP(WINDOWS_UTF8_CODE_PAGE)
    except (AttributeError, OSError):
        pass

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue


configure_windows_console_encoding()

from mewcode.agent import SingleToolAgent
from mewcode.config import ConfigError, load_config
from mewcode.providers import ProviderError, create_provider
from mewcode.repl import MewCodeRepl
from mewcode.session import ChatSession
from mewcode.tools import ToolContext, default_registry


def main(argv: Sequence[str] | None = None) -> int:
    _ = argv
    configure_windows_console_encoding()
    try:
        config = load_config()
        provider = create_provider(config)
    except (ConfigError, ProviderError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    session = ChatSession()
    context = ToolContext(root_dir=Path.cwd(), timeout_seconds=config.timeout_seconds)
    agent = SingleToolAgent(provider=provider, registry=default_registry(), context=context)
    repl = MewCodeRepl(provider=provider, config=config, session=session, agent=agent)
    return repl.run()
