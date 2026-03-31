"""Left-column navigation widget with Standard / Custom / Actions sections.

Uses render() to return Rich Text directly, avoiding Static/compose issues.
"""
from __future__ import annotations

from rich.text import Text

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from devpipe.ui.state import NavItem, NavSection


class NavList(Widget, can_focus=True):
    """Vertical navigation list with section headers."""

    DEFAULT_CSS = """
    NavList {
        width: 1fr;
        min-width: 28;
        max-width: 40;
        background: $surface;
        border-right: solid $primary-darken-3;
        padding: 1 0;
    }
    """

    selected_index: reactive[int] = reactive(0)

    class ItemSelected(Message):
        """Emitted when a nav item is selected."""
        def __init__(self, item: NavItem, index: int) -> None:
            super().__init__()
            self.item = item
            self.index = index

    class ItemActivated(Message):
        """Emitted when Enter is pressed on a nav item."""
        def __init__(self, item: NavItem, index: int) -> None:
            super().__init__()
            self.item = item
            self.index = index

    def __init__(self, items: list[NavItem] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._items: list[NavItem] = items or []
        self._profile: str = ""

    _SECTION_COLORS: dict = {
        "Standard": "#7aa2f7",
        "Custom": "#9ece6a",
        "Actions": "#e0af68",
    }

    def render(self) -> Text:
        """Render the nav list as Rich Text."""
        text = Text()
        current_section = None
        first_section = True

        for i, item in enumerate(self._items):
            if item.section != current_section:
                current_section = item.section
                if not first_section:
                    text.append("\n")
                first_section = False
                color = self._SECTION_COLORS.get(current_section.value, "dim")
                label = "GENERAL" if current_section.value == "Standard" else current_section.value.upper()
                text.append(f"◆ {label}\n", style=f"bold {color}")

            label = item.label
            if item.badge:
                label += f"  {item.badge}"

            if i == self.selected_index:
                text.append("▶ ", style="bold #7aa2f7")
                text.append(f"{label}\n", style="bold #7aa2f7")
            elif item.is_action:
                text.append(f"  {label}\n", style="#e0af68")
            else:
                text.append(f"  {label}\n", style="white")

        if not self._items:
            text.append("  (no items)\n", style="dim")

        return text

    def set_items(self, items: list[NavItem], profile: str = "") -> None:
        """Update the navigation items and re-render."""
        self._items = items
        self._profile = profile
        if self.selected_index >= len(items):
            self.selected_index = max(0, len(items) - 1)
        self.refresh()

    def watch_selected_index(self, new_value: int) -> None:
        self.refresh()
        if 0 <= new_value < len(self._items):
            self.post_message(self.ItemSelected(self._items[new_value], new_value))

    def move_up(self) -> None:
        if self.selected_index > 0:
            self.selected_index -= 1

    def move_down(self) -> None:
        if self.selected_index < len(self._items) - 1:
            self.selected_index += 1

    def activate_current(self) -> None:
        if 0 <= self.selected_index < len(self._items):
            self.post_message(self.ItemActivated(
                self._items[self.selected_index], self.selected_index
            ))

    @property
    def current_item(self) -> NavItem | None:
        if 0 <= self.selected_index < len(self._items):
            return self._items[self.selected_index]
        return None
