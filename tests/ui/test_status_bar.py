from __future__ import annotations

import asyncio
import re

from textual.app import App, ComposeResult

from devpipe.ui.widgets.status_bar import RunStatusBar, StatusBar
from devpipe.ui.state import StatusBarState


class _StatusBarApp(App[None]):
    def __init__(self, show_prompt: bool) -> None:
        super().__init__()
        self._show_prompt = show_prompt

    def compose(self) -> ComposeResult:
        yield RunStatusBar(show_prompt=self._show_prompt, id="run-status")


def test_run_status_bar_places_prompt_marker_near_right_edge() -> None:
    async def run() -> None:
        app = _StatusBarApp(show_prompt=True)

        async with app.run_test() as pilot:
            await pilot.pause()
            screenshot = app.export_screenshot()

        match = re.search(r'<text[^>]* x="([0-9.]+)"[^>]*>[^<]*⬥</text>', screenshot)
        assert match is not None
        assert float(match.group(1)) > 800

    asyncio.run(run())


def test_config_status_bar_places_prompt_marker_near_right_edge() -> None:
    class _ConfigStatusBarApp(App[None]):
        def compose(self) -> ComposeResult:
            bar = StatusBar(show_prompt=True, id="status-bar")
            bar.update_state(
                StatusBarState(
                    left_text="navigate",
                    center_text="1 error(s)",
                    right_text="NOT READY",
                    is_ready=False,
                )
            )
            yield bar

    async def run() -> None:
        app = _ConfigStatusBarApp()

        async with app.run_test() as pilot:
            await pilot.pause()
            screenshot = app.export_screenshot()

        match = re.search(r'<text[^>]* x="([0-9.]+)"[^>]*>[^<]*⬥</text>', screenshot)
        assert match is not None
        assert float(match.group(1)) > 800

    asyncio.run(run())
