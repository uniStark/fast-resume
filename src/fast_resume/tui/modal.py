"""Modal dialogs for the TUI."""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from .styles import DELETE_MODAL_CSS, RENAME_MODAL_CSS


class RenameModal(ModalScreen[str | None]):
    """Modal to rename a session's title.

    Dismisses with the new title string on Enter (empty string means
    "clear/restore"), or None on Escape (cancel, no change).
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = RENAME_MODAL_CSS

    def __init__(self, current_title: str = "") -> None:
        super().__init__()
        self._current_title = current_title

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Rename session", id="rename-title")
            yield Input(value=self._current_title, id="rename-input")
            yield Label(
                "Enter to save · empty to restore original · Esc to cancel",
                id="rename-hint",
            )

    def on_mount(self) -> None:
        inp = self.query_one("#rename-input", Input)
        inp.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#rename-input")
    def on_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)


class DeleteConfirmModal(ModalScreen[bool]):
    """Confirm permanent deletion of a session's underlying file.

    Dismisses True (delete) on `y`/Enter or the Delete button; False (cancel)
    on `n`/Escape or the Cancel button.
    """

    BINDINGS = [
        Binding("y", "confirm", "Delete", show=False),
        Binding("enter", "confirm", "Delete", show=False),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = DELETE_MODAL_CSS

    def __init__(self, title: str, agent: str, path: str) -> None:
        super().__init__()
        self._title = title
        self._agent = agent
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Delete this session permanently?", id="delete-title")
            # markup=False: agent/title are data (titles are user content and
            # may contain brackets) — show them literally, don't parse as markup.
            yield Label(
                f"[{self._agent}] {self._title}",
                classes="delete-detail",
                markup=False,
            )
            yield Label(
                f"This will delete the file: {self._path}"
                if self._path
                else "This will delete the session file.",
                id="delete-path",
            )
            with Horizontal(id="delete-buttons"):
                yield Button("Cancel", id="delete-cancel-btn")
                yield Button("Delete", id="delete-confirm-btn", variant="error")

    def on_mount(self) -> None:
        # Focus the Delete button so Enter confirms (matches `y`); the focus
        # ring then truthfully reflects what Enter does. n/Esc still cancel.
        self.query_one("#delete-confirm-btn", Button).focus()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#delete-confirm-btn")
    def on_confirm_pressed(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#delete-cancel-btn")
    def on_cancel_pressed(self) -> None:
        self.dismiss(False)
