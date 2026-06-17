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
from mewcode.context import ContextManager
from mewcode.memory import MemoryContextManager
from mewcode.mcp import MCPManager
from mewcode.permissions import PermissionChecker, PermissionError
from mewcode.providers import ProviderError, create_provider
from mewcode.repl import MewCodeRepl
from mewcode.session import ChatSession
from mewcode.skills import SkillManager
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
    max_output_chars = max(12000, config.context.single_result_byte_threshold + config.context.preview_chars)
    context = ToolContext(
        root_dir=Path.cwd(),
        timeout_seconds=config.timeout_seconds,
        max_output_chars=max_output_chars,
    )
    registry = default_registry()
    context_manager = ContextManager(root_dir=context.root_dir, provider=provider, config=config.context)
    memory_manager = MemoryContextManager(project_root=context.root_dir, config=config.memory)
    memory_manager.attach_session(session)
    memory_manager.sessions.cleanup_expired()
    mcp_manager = MCPManager(config.mcp, timeout_seconds=config.timeout_seconds, cwd=context.root_dir)
    mcp_manager.register_tools(registry)
    skill_manager = SkillManager(
        project_root=context.root_dir,
        registry=registry,
        mcp_server_names=set(config.mcp.servers),
    )
    skill_manager.load()
    skill_manager.register_tools()
    for server_name, error in mcp_manager.errors.items():
        print(f"Warning: MCP server {server_name} skipped: {error}", file=sys.stderr)
    for issue in skill_manager.issues:
        print(f"Warning: Skill {issue.path} skipped: {issue.message}", file=sys.stderr)
    try:
        permission_checker = PermissionChecker.from_workspace(context, mode=config.permission_mode)
    except PermissionError as exc:
        mcp_manager.close()
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    permission_checker.add_read_tools(mcp_manager.read_tool_names)
    agent = SingleToolAgent(
        provider=provider,
        registry=registry,
        context=context,
        max_tool_steps=config.max_tool_steps,
        permission_checker=permission_checker,
        context_manager=context_manager,
        memory_manager=memory_manager,
        skill_manager=skill_manager,
    )
    repl = MewCodeRepl(
        provider=provider,
        config=config,
        session=session,
        agent=agent,
        mcp_status_provider=mcp_manager.status_counts,
        skill_manager=skill_manager,
    )
    try:
        return repl.run()
    finally:
        mcp_manager.close()
