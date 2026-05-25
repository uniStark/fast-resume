"""Modal dialogs for the TUI."""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

from .styles import DELETE_MODAL_CSS, RENAME_MODAL_CSS, YOLO_MODAL_CSS


class YoloModeModal(ModalScreen[bool]):
    """Modal to choose yolo mode for resume."""

    BINDINGS = [
        Binding("y", "select_yolo", "Yolo Mode", show=False),
        Binding("n", "select_normal", "Normal", show=False),
        Binding("escape", "dismiss", "Cancel", show=False),
        Binding("enter", "select_focused", "Select", show=False),
        Binding("left", "focus_normal", "Left", show=False),
        Binding("right", "focus_yolo", "Right", show=False),
    ]

    CSS = YOLO_MODAL_CSS

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Resume with yolo mode?", id="title")
            with Horizontal(id="buttons"):
                yield Button("No", id="normal-btn")
                yield Button("Yolo", id="yolo-btn")

    def on_mount(self) -> None:
        """Focus the first button when modal opens."""
        self.query_one("#normal-btn", Button).focus()

    def action_toggle_focus(self) -> None:
        """Toggle focus between the two buttons."""
        if self.focused and self.focused.id == "yolo-btn":
            self.query_one("#normal-btn", Button).focus()
        else:
            self.query_one("#yolo-btn", Button).focus()

    def action_focus_normal(self) -> None:
        """Focus the normal button."""
        self.query_one("#normal-btn", Button).focus()

    def action_focus_yolo(self) -> None:
        """Focus the yolo button."""
        self.query_one("#yolo-btn", Button).focus()

    def action_select_focused(self) -> None:
        """Select whichever button is currently focused."""
        focused = self.focused
        if focused and focused.id == "yolo-btn":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_select_yolo(self) -> None:
        self.dismiss(True)

    def action_select_normal(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#yolo-btn")
    def on_yolo_pressed(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#normal-btn")
    def on_normal_pressed(self) -> None:
        self.dismiss(False)


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
            yield Label(f"[{self._agent}] {self._title}", classes="delete-detail")
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
        self.query_one("#delete-cancel-btn", Button).focus()

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
