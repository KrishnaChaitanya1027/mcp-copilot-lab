"""
Textual-based TUI chat sketch (fixed)
- Fix: Removed invalid `Static.Message` subclassing; now uses `textual.message.Message`.
- Fix: Renamed `ToolsPanel.log` -> `richlog` to avoid attribute conflict.
- Hardening: History view no longer references private `.document` internals; maintains its own text buffer.
- Added: `--self-test` mode with basic tests for the message pipeline and history compaction.

Run:
  pip install textual rich
  python tui_chat.py            # launch TUI
  python tui_chat.py --self-test  # run basic tests (no UI)

Notes:
- The ModelClient here is a stub that simulates streaming tokens; replace with your real streaming client.
- Ctrl+Enter (or click Send) posts a message; F2 toggles Tools panel; F5 compacts history.
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Header,
    Footer,
    Static,
    Input,
    Button,
    Markdown,
    RichLog,
    Label,
)
from textual.message import Message
from mcp.server.fastmcp import FastMCP
from tools import config


# -----------------------------
# Model client (stub)
# -----------------------------

@dataclass
class StreamChunk:
    delta: str
    done: bool = False


class ModelClient:
    """Simulates an async streaming LLM client.
    Replace `stream()` with your actual HTTP streaming call.
    """

    def __init__(self, delay: float = 0.02):
        self.delay = delay

    async def stream(self, prompt: str) -> AsyncGenerator[StreamChunk, None]:
        tokens = prompt.split()
        for i, tok in enumerate(tokens):
            await asyncio.sleep(self.delay)
            suffix = "" if i == len(tokens) - 1 else " "
            yield StreamChunk(delta=tok + suffix)
        yield StreamChunk(delta="", done=True)


# -----------------------------
# Widgets
# -----------------------------

class StatusBar(Static):
    latency_ms = reactive("-")
    tokens = reactive(0)
    model = reactive("gpt-5")
    mode = reactive("chat")

    def render(self):
        return (
            f"Latency: {self.latency_ms} ms  |  Tokens: {self.tokens}  |  "
            f"Model: {self.model}  |  Mode: {self.mode}"
        )


class HistoryView(Static):
    """Scrollable conversation history rendered as Markdown."""

    def __init__(self):
        super().__init__()
        self._md = Markdown("")
        self._content = ""
        self.can_focus = True

    def compose(self) -> ComposeResult:
        yield self._md

    def append_markdown(self, md: str) -> None:
        if self._content and not self._content.endswith(""):
            self._content += ""
        self._content += md
        self._md.update(self._content)

    def compact(self, max_chars: int = 8000) -> None:
        if len(self._content) <= max_chars:
            return
        self._content = (
            "[dim](earlier conversation summarized)[/dim]" + self._content[-max_chars:]
        )
        self._md.update(self._content)


class ComposeBox(Static):
    """Bottom compose area with input and Send button."""

    BINDINGS = [
        ("ctrl+enter", "send", "Send"),
        ("escape", "blur", "Blur"),
    ]

    class Submit(Message):
        """Message emitted when the user presses Send.
        Note: In current Textual versions, `Message.__init__` takes no sender arg.
        """
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def compose(self) -> ComposeResult:
        yield Label("Message (Ctrl+Enter to send)", id="compose-label")
        self.input = Input(placeholder="Type here… Use /help for commands", id="compose-input")
        self.input.cursor_blink = True
        self.input.password = False
        self.input.tooltip = "Ctrl+Enter to send."
        yield self.input
        yield Button("Send", id="send-btn", variant="primary")

    @on(Button.Pressed, "#send-btn")
    def on_send_click(self):
        self.post_message(self.Submit(self.input.value))

    def action_send(self):
        self.post_message(self.Submit(self.input.value))



class ToolsPanel(Static):
    """Right-side tools/logs panel with RichLog."""

    def __init__(self):
        super().__init__()
        # Avoid shadowing Static.log (logger). Use a distinct name.
        self.richlog = RichLog(markup=True, wrap=True, highlight=True)

    def compose(self) -> ComposeResult:
        yield Label("Tools & Logs", id="tools-title")
        yield self.richlog

    def add_log(self, text: str):
        self.richlog.write(text)


# -----------------------------
# App
# -----------------------------

class ChatTUI(App):
    """Three-pane TUI: History | Compose | Tools."""

    BINDINGS = [
        ("ctrl+l", "clear_chat", "Clear Chat"),
        ("f2", "toggle_tools", "Toggle Tools"),
        ("f5", "compact_history", "Compact History"),
    ]

    def __init__(self):
        super().__init__()
        self.model = ModelClient()
        self.status = StatusBar()
        self.history = HistoryView()
        self.tools = ToolsPanel()
        self.compose_box = ComposeBox()
        self._tools_visible = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="content-vertical"):
            with Horizontal(id="content-row"):
                yield self.history
                yield self.tools
            yield self.compose_box
        yield Footer()

    def on_mount(self) -> None:
        # Layout sizing
        self.query_one("#content-row").styles.height = "1fr"
        self.history.styles.width = "70%"
        self.tools.styles.width = "30%"
        self.compose_box.styles.height = 7
        # Initial content
        self.history.append_markdown("**Welcome!** Type a message and press `Ctrl+Enter` to send. Use `/help` for commands.")

    # -----------------------------
    # Actions / commands
    # -----------------------------

    def action_clear_chat(self) -> None:
        self.history._content = ""
        self.history._md.update("")
        self.tools.richlog.clear()
        self.refresh()

    def action_toggle_tools(self) -> None:
        self._tools_visible = not self._tools_visible
        self.tools.display = self._tools_visible
        self.refresh()

    def action_compact_history(self) -> None:
        self.history.compact(max_chars=6000)

    # -----------------------------
    # Compose submit
    # -----------------------------

    @on(ComposeBox.Submit)
    async def handle_submit(self, event: ComposeBox.Submit) -> None:
        text = (event.text or "").strip()
        if not text:
            return

        # Clear input quickly for responsiveness
        self.compose_box.input.value = ""

        # Handle slash commands locally
        if text.startswith("/"):
            await self._handle_command(text)
            return

        # Render user message
        self.history.append_markdown(f"**You:** {text}")

        # Kick off streaming response
        await self._stream_response(text)

    async def _handle_command(self, cmd: str) -> None:
    # No stray quote lines, proper indentation
        if cmd in {"/help", "/?"}:
            help_md = (
                "**Commands**\n\n"
                "- `/help` – show this help\n"
                "- `/clear` – clear chat\n"
                "- `/compact` – compact history\n"
                "- `/model <name>` – set model label\n"
            )
            self.history.append_markdown(help_md)
        elif cmd.startswith("/clear"):
            self.action_clear_chat()
        elif cmd.startswith("/compact"):
            self.action_compact_history()
        elif cmd.startswith("/model"):
            parts = cmd.split(maxsplit=1)
            if len(parts) == 2:
                self.status.model = parts[1].strip()
                self.tools.add_log(f"[bold green]Model set to[/]: {self.status.model}")
            else:
                self.tools.add_log("[yellow]Usage:[/] /model gpt-5")
        else:
            self.tools.add_log(f"[yellow]Unknown command:[/] {cmd}")

    # -----------------------------
    # Streaming response pipeline
    # -----------------------------

    async def _stream_response(self, prompt: str) -> None:
        start = time.perf_counter()
        self.tools.add_log("[bold cyan]→ Sending to model…[/]")

        # Display assistant header immediately
        self.history.append_markdown("**Assistant:** ")

        # Accumulator for the currently streaming assistant message
        buffer = []
        last_flush = time.perf_counter()
        FLUSH_EVERY = 0.04  # ~25fps

        async for chunk in self.model.stream(prompt):
            if chunk.delta:
                buffer.append(chunk.delta)
            now = time.perf_counter()
            if (now - last_flush) >= FLUSH_EVERY or chunk.done:
                if buffer:
                    self.history.append_markdown("".join(buffer))
                    self.status.tokens += 1
                    buffer.clear()
                last_flush = now

        latency = int((time.perf_counter() - start) * 1000)
        self.status.latency_ms = str(latency)
        self.tools.add_log(f"[bold green]✓ Response complete[/] ({latency} ms)")


# -----------------------------
# Self-tests (non-UI)
# -----------------------------

def _self_test() -> None:
    """Basic tests to ensure message & history plumbing works without launching Textual."""
    # Test ModelClient streaming order
    async def t_stream():
        mc = ModelClient(delay=0)
        seen = []
        async for ch in mc.stream("hello world"):
            seen.append(ch.delta)
        joined = "".join(seen).strip()
        assert joined == "hello world", f"stream mismatch: {joined!r}"

    asyncio.run(t_stream())

    # Test HistoryView compaction boundaries
    hv = HistoryView()
    hv.append_markdown("A" * 10)
    assert "A" * 10 in hv._content
    hv.append_markdown("B" * 10)
    hv.compact(max_chars=8)
    assert hv._content.startswith("[dim]") and len(hv._content) >= 8

    # Test ComposeBox.Submit message shape (no sender argument)
    cb = ComposeBox()
    msg = ComposeBox.Submit("hi")
    assert isinstance(msg, Message) and getattr(msg, "text", None) == "hi"

    print("Self-tests passed.")


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        _self_test()
    else:
        app = ChatTUI()
        app.run()

    if "--self-test" in sys.argv:
        _self_test()
    else:
        app = ChatTUI()
        app.run()