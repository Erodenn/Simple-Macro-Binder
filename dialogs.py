"""Reusable widgets and modal dialogs for binding configuration."""

from __future__ import annotations

import time as _time
import tkinter as tk
from tkinter import ttk

from typing import Callable

from pynput.keyboard import Listener as KeyboardListener, Key, KeyCode
from pynput.mouse import Listener as MouseListener, Button

from actions import (
    ACTION_NAMES, ACTION_DESCRIPTIONS, TARGET_NAMES, TARGET_MOUSE_BUTTONS,
    hides_interval,
)
from models import Binding, BindingManager, Macro, MacroStep, Profile
from theme import ToolTip, apply_dark_title_bar, flash_widgets, get_frame_bg, scale, Fonts


def _center_on_parent(window, parent) -> None:
    """Position a toplevel window centered on its parent."""
    window.update_idletasks()
    px = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
    py = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 2
    window.geometry(f"+{max(px, 0)}+{max(py, 0)}")


class HotkeyCapture(ttk.Frame):
    """A widget that captures a single keyboard key or mouse side button.

    Usage:
        cap = HotkeyCapture(parent)
        cap.pack()
        # Read captured value via cap.get() or cap.value_var
        # Set externally via cap.set("F9")
        # Check if listening via cap.is_listening
    """

    def __init__(
        self,
        parent,
        initial: str = "",
        on_change: Callable[[str], None] | None = None,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self.value_var = tk.StringVar(value=initial)
        self._on_change = on_change
        self._listening = False

        self._entry = ttk.Entry(self, textvariable=self.value_var, width=10, state="readonly")
        self._entry.pack(side="left")

        self._btn = ttk.Button(self, text="Set", width=4, command=self._start_listening, style="primary.Round.TButton")
        self._btn.pack(side="left", padx=(scale(4), 0))
        ToolTip(self._btn, text="Click to capture a key")

        # Keyboard capture while listening
        self._entry.bind("<Key>", self._on_key)

    # ── Public API ───────────────────────────────────────────

    @property
    def is_listening(self) -> bool:
        return self._listening

    def get(self) -> str:
        return self.value_var.get()

    def set(self, value: str):
        self._entry.config(state="normal")
        self.value_var.set(value)
        self._entry.config(state="readonly")

    def on_mouse_button(self, name: str):
        """Called by the app's mouse listener when a side button is pressed."""
        if not self._listening:
            return
        self._accept(name)

    # ── Internal ─────────────────────────────────────────────

    def _start_listening(self):
        self._listening = True
        self._prev_value = self.value_var.get()
        self._entry.config(state="normal")
        self.value_var.set("Press a key...")
        self._entry.config(state="readonly")
        self._btn.config(text="...", state="disabled")
        self._entry.focus_set()

    def _stop_listening(self):
        self._listening = False
        self._btn.config(text="Set", state="normal")

    def _accept(self, name: str):
        self._entry.config(state="normal")
        self.value_var.set(name)
        self._entry.config(state="readonly")
        self._stop_listening()
        if self._on_change:
            self._on_change(name)

    def _on_key(self, event):
        if not self._listening:
            return "break"
        keysym = event.keysym
        # Ignore bare modifiers
        if keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"):
            return "break"
        # Escape cancels — restore previous value
        if keysym == "Escape":
            self._entry.config(state="normal")
            self.value_var.set(self._prev_value)
            self._entry.config(state="readonly")
            self._stop_listening()
            return "break"
        self._accept(keysym)
        return "break"


# ── Macro Dialogs ─────────────────────────────────────────────


class StepEditorDialog(tk.Toplevel):
    """Modal dialog for creating or editing a single MacroStep."""

    STEP_TYPES = ["key_press", "key_release", "mouse_click", "delay"]

    def __init__(self, parent, step: MacroStep | None = None):
        super().__init__(parent)
        self.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self.transient(parent)
        self.grab_set()
        self.title("Edit Step" if step else "Add Step")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.result: MacroStep | None = None
        self._build_ui(step)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        apply_dark_title_bar(self)
        _center_on_parent(self, parent)

    def _build_ui(self, step: MacroStep | None):
        main = ttk.Frame(self, padding=scale(16))
        main.pack(fill="both", expand=True)

        # Step type selector
        ttk.Label(main, text="Type:").grid(row=0, column=0, sticky="w", pady=scale(6))
        self._type_var = tk.StringVar(
            value=step.step_type if step else self.STEP_TYPES[0]
        )
        ttk.Combobox(
            main, textvariable=self._type_var,
            values=self.STEP_TYPES, state="readonly", width=14,
        ).grid(row=0, column=1, sticky="ew", pady=scale(6))
        self._type_var.trace_add("write", self._on_type_changed)

        # Key field (for key_press / key_release)
        self._key_frame = ttk.Frame(main)
        self._key_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=scale(6))
        ttk.Label(self._key_frame, text="Key:").pack(side="left")
        self._key_var = tk.StringVar(value=step.key if step and step.key else "")
        self._key_entry = ttk.Entry(self._key_frame, textvariable=self._key_var, width=15)
        self._key_entry.pack(side="left", padx=(scale(6), 0))
        self._key_var.trace_add("write", self._validate)

        # Mouse fields (for mouse_click)
        self._mouse_frame = ttk.Frame(main)
        self._mouse_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=scale(6))
        ttk.Label(self._mouse_frame, text="X:").pack(side="left")
        self._x_var = tk.IntVar(value=step.x if step and step.x is not None else 0)
        ttk.Spinbox(
            self._mouse_frame, from_=0, to=99999, textvariable=self._x_var, width=6,
        ).pack(side="left", padx=(scale(3), scale(10)))
        ttk.Label(self._mouse_frame, text="Y:").pack(side="left")
        self._y_var = tk.IntVar(value=step.y if step and step.y is not None else 0)
        ttk.Spinbox(
            self._mouse_frame, from_=0, to=99999, textvariable=self._y_var, width=6,
        ).pack(side="left", padx=(scale(3), scale(10)))
        ttk.Label(self._mouse_frame, text="Button:").pack(side="left")
        self._btn_var = tk.StringVar(value=step.button if step else "left")
        ttk.Combobox(
            self._mouse_frame, textvariable=self._btn_var,
            values=["left", "right"], state="readonly", width=6,
        ).pack(side="left", padx=(scale(3), scale(10)))
        ttk.Label(self._mouse_frame, text="Clicks:").pack(side="left")
        self._clicks_var = tk.IntVar(value=step.click_count if step else 1)
        ttk.Spinbox(
            self._mouse_frame, from_=1, to=5, textvariable=self._clicks_var, width=3,
        ).pack(side="left", padx=scale(3))

        # Delay field
        self._delay_frame = ttk.Frame(main)
        self._delay_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=scale(6))
        ttk.Label(self._delay_frame, text="Delay (ms):").pack(side="left")
        self._delay_var = tk.IntVar(value=step.delay_ms if step else 100)
        ttk.Spinbox(
            self._delay_frame, from_=0, to=999999, textvariable=self._delay_var, width=8,
        ).pack(side="left", padx=scale(6))

        # OK / Cancel
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(scale(14), 0))
        self._ok_btn = ttk.Button(btn_frame, text="OK", width=8, command=self._ok, style="success.Round.TButton")
        self._ok_btn.pack(side="left", padx=scale(5))
        ToolTip(self._ok_btn, text="Save step")
        cancel_btn = ttk.Button(btn_frame, text="Cancel", width=8, command=self._cancel, style="secondary.Round.TButton")
        cancel_btn.pack(side="left", padx=scale(5))
        ToolTip(cancel_btn, text="Discard changes")

        self._on_type_changed()
        self._validate()

    def _on_type_changed(self, *_args):
        st = self._type_var.get()
        self._key_frame.grid() if st in ("key_press", "key_release") else self._key_frame.grid_remove()
        self._mouse_frame.grid() if st == "mouse_click" else self._mouse_frame.grid_remove()
        self._delay_frame.grid() if st == "delay" else self._delay_frame.grid_remove()
        self._validate()

    def _validate(self, *_args):
        st = self._type_var.get()
        if st in ("key_press", "key_release"):
            valid = bool(self._key_var.get().strip())
        else:
            valid = True
        self._ok_btn.configure(style="success.Round.TButton" if valid else "secondary.Round.TButton")

    def _ok(self):
        st = self._type_var.get()
        if st in ("key_press", "key_release"):
            key = self._key_var.get().strip()
            if not key:
                flash_widgets(self, [self._key_entry])
                return
            self.result = MacroStep(step_type=st, key=key)
        elif st == "mouse_click":
            self.result = MacroStep(
                step_type=st,
                x=self._x_var.get(), y=self._y_var.get(),
                button=self._btn_var.get(),
                click_count=self._clicks_var.get(),
            )
        elif st == "delay":
            self.result = MacroStep(step_type=st, delay_ms=max(self._delay_var.get(), 0))
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class MacroStepEditor(tk.Toplevel):
    """Modal dialog for viewing and editing macro steps.

    Usage:
        editor = MacroStepEditor(parent, macro=existing_macro_or_None)
        parent.wait_window(editor)
        result = editor.result  # Macro or None
    """

    def __init__(self, parent, macro: Macro | None = None):
        super().__init__(parent)
        self.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self.transient(parent)
        self.grab_set()
        self.title("Edit Macro Steps" if macro else "Create Macro")
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self.geometry(f"{scale(520)}x{scale(420)}")

        self.result: Macro | None = None
        self._macro_name = macro.name if macro else ""
        self._steps: list[MacroStep] = list(macro.steps) if macro else []

        self._build_ui()
        self._refresh_list()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        apply_dark_title_bar(self)
        _center_on_parent(self, parent)

    def _build_ui(self):
        main = ttk.Frame(self, padding=scale(12))
        main.pack(fill="both", expand=True)

        # Name field
        name_frame = ttk.Frame(main)
        name_frame.pack(fill="x", pady=(0, scale(6)))
        ttk.Label(name_frame, text="Name:").pack(side="left")
        self._name_var = tk.StringVar(value=self._macro_name)
        self._name_entry = ttk.Entry(name_frame, textvariable=self._name_var, width=30)
        self._name_entry.pack(side="left", padx=(scale(6), 0), fill="x", expand=True)
        self._name_var.trace_add("write", self._validate)

        # Step list (Treeview)
        list_frame = ttk.Frame(main)
        list_frame.pack(fill="both", expand=True, pady=scale(6))

        columns = ("index", "type", "details")
        self._tree = ttk.Treeview(
            list_frame, columns=columns, show="headings",
            selectmode="browse", height=12,
        )
        self._tree.heading("index", text="#")
        self._tree.heading("type", text="Type")
        self._tree.heading("details", text="Details")
        self._tree.column("index", width=scale(30), stretch=False)
        self._tree.column("type", width=scale(90), stretch=False)
        self._tree.column("details", width=scale(340), stretch=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=scrollbar.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Step action buttons
        step_btn_frame = ttk.Frame(main)
        step_btn_frame.pack(fill="x", pady=scale(6))
        add_step_btn = ttk.Button(step_btn_frame, text="Add Step", command=self._add_step, style="primary.Round.TButton")
        add_step_btn.pack(side="left", padx=scale(3))
        ToolTip(add_step_btn, text="Add a new step")
        edit_step_btn = ttk.Button(step_btn_frame, text="Edit", command=self._edit_step, style="info.Round.TButton")
        edit_step_btn.pack(side="left", padx=scale(3))
        ToolTip(edit_step_btn, text="Edit selected step")
        remove_step_btn = ttk.Button(step_btn_frame, text="Remove", command=self._remove_step, style="danger.Round.TButton")
        remove_step_btn.pack(side="left", padx=scale(3))
        ToolTip(remove_step_btn, text="Remove selected step")
        up_btn = ttk.Button(step_btn_frame, text="\u25b2 Up", command=self._move_up, style="secondary.Round.TButton")
        up_btn.pack(side="left", padx=scale(3))
        ToolTip(up_btn, text="Move step up")
        down_btn = ttk.Button(step_btn_frame, text="\u25bc Down", command=self._move_down, style="secondary.Round.TButton")
        down_btn.pack(side="left", padx=scale(3))
        ToolTip(down_btn, text="Move step down")

        # OK / Cancel
        btn_frame = ttk.Frame(main)
        btn_frame.pack(pady=(scale(10), 0))
        self._ok_btn = ttk.Button(btn_frame, text="OK", width=8, command=self._ok, style="success.Round.TButton")
        self._ok_btn.pack(side="left", padx=scale(5))
        ToolTip(self._ok_btn, text="Save macro")
        cancel_btn = ttk.Button(btn_frame, text="Cancel", width=8, command=self._cancel, style="secondary.Round.TButton")
        cancel_btn.pack(side="left", padx=scale(5))
        ToolTip(cancel_btn, text="Discard changes")

        self._validate()

    @staticmethod
    def _step_description(step: MacroStep) -> str:
        if step.step_type == "key_press":
            return f"Key Down: {step.key}"
        if step.step_type == "key_release":
            return f"Key Up: {step.key}"
        if step.step_type == "mouse_click":
            clicks = f"{step.click_count}x " if step.click_count > 1 else ""
            return f"{clicks}{step.button.title()} Click @ ({step.x}, {step.y})"
        if step.step_type == "delay":
            return f"{step.delay_ms} ms"
        return str(step)

    def _refresh_list(self):
        self._tree.delete(*self._tree.get_children())
        for i, step in enumerate(self._steps):
            self._tree.insert("", "end", iid=str(i), values=(
                i + 1,
                step.step_type.replace("_", " ").title(),
                self._step_description(step),
            ))

    def _get_selected_index(self) -> int | None:
        sel = self._tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _add_step(self):
        dialog = StepEditorDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            idx = self._get_selected_index()
            insert_at = (idx + 1) if idx is not None else len(self._steps)
            self._steps.insert(insert_at, dialog.result)
            self._refresh_list()

    def _edit_step(self):
        idx = self._get_selected_index()
        if idx is None:
            return
        dialog = StepEditorDialog(self, step=self._steps[idx])
        self.wait_window(dialog)
        if dialog.result:
            self._steps[idx] = dialog.result
            self._refresh_list()

    def _remove_step(self):
        idx = self._get_selected_index()
        if idx is None:
            return
        self._steps.pop(idx)
        self._refresh_list()

    def _move_up(self):
        idx = self._get_selected_index()
        if idx is None or idx == 0:
            return
        self._steps[idx], self._steps[idx - 1] = self._steps[idx - 1], self._steps[idx]
        self._refresh_list()
        self._tree.selection_set(str(idx - 1))

    def _move_down(self):
        idx = self._get_selected_index()
        if idx is None or idx >= len(self._steps) - 1:
            return
        self._steps[idx], self._steps[idx + 1] = self._steps[idx + 1], self._steps[idx]
        self._refresh_list()
        self._tree.selection_set(str(idx + 1))

    def _validate(self, *_args):
        valid = bool(self._name_var.get().strip())
        self._ok_btn.configure(style="success.Round.TButton" if valid else "secondary.Round.TButton")

    def _ok(self):
        name = self._name_var.get().strip()
        if not name:
            flash_widgets(self, [self._name_entry])
            return
        self.result = Macro(name=name, steps=self._steps)
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class MacroRecorder(tk.Toplevel):
    """Modal dialog that records keyboard and mouse events into a macro.

    Usage:
        recorder = MacroRecorder(parent, macro_name="MyMacro")
        parent.wait_window(recorder)
        result = recorder.result  # Macro or None
    """

    def __init__(self, parent, macro_name: str = ""):
        super().__init__(parent)
        self.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self.transient(parent)
        self.grab_set()
        self.title("Record Macro")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.result: Macro | None = None
        self._macro_name = macro_name
        self._steps: list[MacroStep] = []
        self._recording = False
        self._first_event = True
        self._last_timestamp: float | None = None
        self._kb_listener: KeyboardListener | None = None
        self._mouse_listener: MouseListener | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        apply_dark_title_bar(self)
        _center_on_parent(self, parent)

    def _build_ui(self):
        main = ttk.Frame(self, padding=scale(16))
        main.pack(fill="both", expand=True)

        self._status_var = tk.StringVar(value="Click Start, then perform actions.")
        ttk.Label(main, textvariable=self._status_var).pack(pady=(0, scale(10)))

        self._count_var = tk.StringVar(value="Steps: 0")
        ttk.Label(main, textvariable=self._count_var).pack(pady=(0, scale(10)))

        btn_frame = ttk.Frame(main)
        btn_frame.pack()

        self._start_btn = ttk.Button(btn_frame, text="Start", command=self._start, style="success.Round.TButton")
        self._start_btn.pack(side="left", padx=scale(5))
        ToolTip(self._start_btn, text="Start recording")

        self._stop_btn = ttk.Button(btn_frame, text="Stop", command=self._stop, state="disabled", style="danger.Round.TButton")
        self._stop_btn.pack(side="left", padx=scale(5))
        ToolTip(self._stop_btn, text="Stop recording")

        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self._cancel, style="secondary.Round.TButton")
        cancel_btn.pack(side="left", padx=scale(5))
        ToolTip(cancel_btn, text="Cancel recording")

    def _start(self):
        self._recording = True
        self._first_event = True
        self._last_timestamp = None
        self._steps = []
        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._status_var.set("Waiting for first input...")

        self._kb_listener = KeyboardListener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb_listener.daemon = True
        self._kb_listener.start()

        self._mouse_listener = MouseListener(on_click=self._on_mouse_click)
        self._mouse_listener.daemon = True
        self._mouse_listener.start()

    def _stop(self):
        self._recording = False
        if self._kb_listener:
            self._kb_listener.stop()
        if self._mouse_listener:
            self._mouse_listener.stop()
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")

        # Pop the last step if it is a mouse_click (the Stop button click itself)
        if self._steps and self._steps[-1].step_type == "mouse_click":
            self._steps.pop()
        # Also pop a trailing delay that preceded the Stop click
        if self._steps and self._steps[-1].step_type == "delay":
            self._steps.pop()

        if self._steps:
            self.result = Macro(name=self._macro_name, steps=self._steps)
            self.destroy()
        else:
            self._status_var.set("No events recorded. Try again or Cancel.")

    def _insert_delay(self):
        now = _time.perf_counter()
        if self._last_timestamp is not None:
            delay_ms = int((now - self._last_timestamp) * 1000)
            if delay_ms > 0:
                self._steps.append(MacroStep(step_type="delay", delay_ms=delay_ms))
        self._last_timestamp = now

    def _on_first_event(self):
        if self._first_event:
            self._first_event = False
            self._last_timestamp = _time.perf_counter()
            self.after(0, lambda: self._status_var.set("Recording..."))

    def _update_count(self):
        # Count only non-delay steps for a cleaner display
        count = sum(1 for s in self._steps if s.step_type != "delay")
        self.after(0, lambda c=count: self._count_var.set(f"Steps: {c}"))

    @staticmethod
    def _key_name(key) -> str | None:
        if isinstance(key, Key):
            return key.name
        if isinstance(key, KeyCode):
            if key.char is not None:
                return key.char
            if key.vk is not None:
                return str(key.vk)
        return None

    def _on_key_press(self, key):
        if not self._recording:
            return
        name = self._key_name(key)
        if name is None:
            return
        self._on_first_event()
        self._insert_delay()
        self._steps.append(MacroStep(step_type="key_press", key=name))
        self._update_count()

    def _on_key_release(self, key):
        if not self._recording:
            return
        name = self._key_name(key)
        if name is None:
            return
        if self._first_event:
            return  # ignore releases before first press
        self._insert_delay()
        self._steps.append(MacroStep(step_type="key_release", key=name))
        self._update_count()

    def _on_mouse_click(self, x, y, button, pressed):
        if not self._recording or not pressed:
            return
        if button == Button.left:
            btn_name = "left"
        elif button == Button.right:
            btn_name = "right"
        else:
            return
        self._on_first_event()
        self._insert_delay()
        self._steps.append(MacroStep(
            step_type="mouse_click", x=x, y=y,
            button=btn_name, click_count=1,
        ))
        self._update_count()

    def _cancel(self):
        self._recording = False
        if self._kb_listener:
            self._kb_listener.stop()
        if self._mouse_listener:
            self._mouse_listener.stop()
        self.result = None
        self.destroy()


# ── Binding Editor ────────────────────────────────────────────


class BindingEditor(tk.Toplevel):
    """Modal dialog for creating or editing a Binding.

    Usage:
        editor = BindingEditor(parent, existing_binding_or_None, conflict_checker)
        parent.wait_window(editor)
        result = editor.result  # Binding or None if cancelled
    """

    # Target combobox options: mouse buttons + a "Keyboard Key" sentinel
    _TARGET_OPTIONS = TARGET_NAMES + ["Keyboard Key"]

    def __init__(
        self,
        parent,
        binding: Binding | None = None,
        conflict_checker: Callable[[str, str | None], bool] | None = None,
        kill_all_hotkey: str = "",
        recording_callback: Callable[[bool], None] | None = None,
    ):
        super().__init__(parent)
        self.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self.transient(parent)
        self.grab_set()
        self.title("Edit Binding" if binding else "Add Binding")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.result: Binding | None = None
        self._binding = binding
        self._conflict_checker = conflict_checker
        self._kill_all_hotkey = kill_all_hotkey
        self._recording_callback = recording_callback

        # Inline macro steps (copied from binding if editing)
        self._macro_steps: list[MacroStep] = list(binding.macro_steps) if binding else []

        # Track whether user has manually edited the name field
        self._user_edited_name = bool(binding and binding.name)

        self._hotkey_captures: list[HotkeyCapture] = []
        self._build_ui(binding)
        self.hotkey_capture = self._hotkey  # expose for external mouse listener

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        apply_dark_title_bar(self)
        _center_on_parent(self, parent)

    @property
    def all_hotkey_captures(self) -> list[HotkeyCapture]:
        """All HotkeyCapture widgets in this dialog (trigger + optional target key)."""
        return self._hotkey_captures

    def _build_ui(self, binding: Binding | None):
        main = ttk.Frame(self, padding=scale(16))
        main.pack(fill="both", expand=True)

        row = 0

        # ── Kill-all hotkey display ──
        if self._kill_all_hotkey:
            kill_lbl = ttk.Label(
                main, text=f"Kill All hotkey: {self._kill_all_hotkey}",
                foreground="#888888", style="Header.TLabel",
            )
            kill_lbl.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, scale(6)))
            row += 1

        # ── Name ──
        ttk.Label(main, text="Name:").grid(row=row, column=0, sticky="w", pady=scale(6))
        self._name_var = tk.StringVar(value=binding.name if binding else "")
        self._name_entry = ttk.Entry(main, textvariable=self._name_var, width=24)
        self._name_entry.grid(row=row, column=1, sticky="ew", pady=scale(6))
        self._name_entry.bind("<KeyRelease>", self._on_name_key)
        row += 1

        # ── Trigger ──
        ttk.Label(main, text="Trigger:").grid(row=row, column=0, sticky="w", pady=scale(6))
        self._hotkey = HotkeyCapture(
            main,
            initial=binding.trigger if binding else "",
            on_change=self._on_trigger_changed,
        )
        self._hotkey.grid(row=row, column=1, sticky="ew", pady=scale(6))
        self._hotkey_captures.append(self._hotkey)
        row += 1

        # ── Action Type (radio buttons) ──
        action_frame = ttk.LabelFrame(main, text="Action Type", padding=(scale(12), scale(8)))
        action_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(scale(10), scale(6)))

        self._action_var = tk.StringVar(value=binding.action_type if binding else ACTION_NAMES[0])
        for name in ACTION_NAMES:
            radio_row = ttk.Frame(action_frame)
            radio_row.pack(fill="x", pady=scale(2))
            ttk.Radiobutton(
                radio_row, text=name, variable=self._action_var, value=name,
                command=self._on_action_changed,
            ).pack(side="left")
            ttk.Label(
                radio_row, text=f"\u2014 {ACTION_DESCRIPTIONS[name]}",
                foreground="#888888",
            ).pack(side="left", padx=(scale(4), 0))
        row += 1

        # ── Target ──
        self._target_row = row
        self._target_frame = ttk.Frame(main)
        self._target_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=scale(6))

        ttk.Label(self._target_frame, text="Target:").pack(side="left")

        # Determine initial target combo value
        initial_target_combo = "Left Mouse"
        initial_key_capture = ""
        if binding:
            if binding.action_target in TARGET_MOUSE_BUTTONS:
                initial_target_combo = binding.action_target
            else:
                initial_target_combo = "Keyboard Key"
                initial_key_capture = binding.action_target

        self._target_combo_var = tk.StringVar(value=initial_target_combo)
        self._target_combo = ttk.Combobox(
            self._target_frame,
            textvariable=self._target_combo_var,
            values=self._TARGET_OPTIONS,
            state="readonly",
            width=14,
        )
        self._target_combo.pack(side="left", padx=(scale(6), scale(6)))
        self._target_combo_var.trace_add("write", self._on_target_changed)

        # Keyboard key capture (shown only when "Keyboard Key" selected)
        self._target_key_capture = HotkeyCapture(
            self._target_frame,
            initial=initial_key_capture,
            on_change=self._on_target_key_captured,
        )
        self._target_key_capture.pack(side="left", padx=(0, scale(4)))
        self._hotkey_captures.append(self._target_key_capture)
        row += 1

        # ── Interval ──
        self._interval_frame = ttk.LabelFrame(main, text="Interval", padding=(scale(10), scale(6)))
        self._interval_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(scale(10), scale(6)))

        interval_ms = binding.interval_ms if binding else 100

        # Single ms spinbox + label
        spin_row = ttk.Frame(self._interval_frame)
        spin_row.pack(fill="x", pady=(0, scale(6)))

        self._interval_var = tk.IntVar(value=interval_ms)
        self._interval_spin = ttk.Spinbox(
            spin_row, from_=1, to=86400000, increment=10,
            textvariable=self._interval_var, width=10,
        )
        self._interval_spin.pack(side="left")
        ttk.Label(spin_row, text="ms").pack(side="left", padx=(scale(6), scale(10)))

        self._interval_readable = tk.StringVar()
        ttk.Label(
            spin_row, textvariable=self._interval_readable,
            foreground="#888888", style="Header.TLabel",
        ).pack(side="left")

        self._interval_var.trace_add("write", self._update_interval_label)
        self._update_interval_label()

        # Preset buttons
        preset_row = ttk.Frame(self._interval_frame)
        preset_row.pack(fill="x")
        for label, ms in [("50ms", 50), ("100ms", 100), ("250ms", 250), ("500ms", 500), ("1s", 1000)]:
            preset_btn = ttk.Button(
                preset_row, text=label, width=5,
                command=lambda v=ms: self._interval_var.set(v),
                style="Round.TButton",
            )
            preset_btn.pack(side="left", padx=scale(3))
            ToolTip(preset_btn, text=f"Set interval to {label}")

        row += 1

        # ── Macro panel ──
        self._macro_panel = ttk.LabelFrame(main, text="Macro", padding=(scale(10), scale(6)))
        self._macro_panel.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(scale(10), scale(6)))

        # Step count display (tk.Label for flash_widgets background support)
        self._step_count_var = tk.StringVar()
        self._update_step_count_label()
        self._step_count_label = tk.Label(
            self._macro_panel, textvariable=self._step_count_var,
            bg=get_frame_bg(),
            fg=ttk.Style().lookup("TLabel", "foreground") or "#ffffff",
        )
        self._step_count_label.pack(anchor="w", pady=(0, scale(6)))

        # Macro action buttons
        macro_btn_frame = ttk.Frame(self._macro_panel)
        macro_btn_frame.pack(fill="x", pady=scale(3))
        record_btn = ttk.Button(macro_btn_frame, text="Record", command=self._on_record, style="danger.Round.TButton")
        record_btn.pack(side="left", padx=scale(3))
        ToolTip(record_btn, text="Record a new macro")
        edit_steps_btn = ttk.Button(macro_btn_frame, text="Edit Steps", command=self._on_edit_steps, style="info.Round.TButton")
        edit_steps_btn.pack(side="left", padx=scale(3))
        ToolTip(edit_steps_btn, text="Edit macro steps")

        # Loop toggle (for Keyboard Macro)
        self._kb_loop_var = tk.BooleanVar(value=binding.loop if binding else True)
        ttk.Checkbutton(
            self._macro_panel, text="Loop continuously", variable=self._kb_loop_var,
        ).pack(anchor="w", pady=(scale(6), 0))

        row += 1

        # ── Mouse Macro panel ──
        self._mm_panel = ttk.LabelFrame(main, text="Mouse Macro", padding=(scale(10), scale(6)))
        self._mm_panel.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(scale(10), scale(6)))

        # Sub-mode selector
        mode_row = ttk.Frame(self._mm_panel)
        mode_row.pack(fill="x", pady=(0, scale(6)))
        ttk.Label(mode_row, text="Mode:").pack(side="left")

        _MM_MODE_DISPLAY = ["Jiggle", "Move to Position", "Pattern", "Path (Coming Soon)"]
        self._MM_MODE_MAP = {"Jiggle": "jiggle", "Move to Position": "move_to", "Pattern": "pattern", "Path (Coming Soon)": "path"}
        self._MM_MODE_REVERSE = {v: k for k, v in self._MM_MODE_MAP.items()}

        initial_mm_mode = self._MM_MODE_REVERSE.get(
            binding.mouse_move_type if binding else "jiggle", "Jiggle"
        )
        self._mm_mode_var = tk.StringVar(value=initial_mm_mode)
        ttk.Combobox(
            mode_row, textvariable=self._mm_mode_var,
            values=_MM_MODE_DISPLAY, state="readonly", width=20,
        ).pack(side="left", padx=(scale(6), 0))
        self._mm_mode_var.trace_add("write", self._on_mm_mode_changed)

        # ── Jiggle sub-frame ──
        self._mm_jiggle_frame = ttk.Frame(self._mm_panel)
        self._mm_jiggle_frame.pack(fill="x", pady=scale(4))

        jiggle_r1 = ttk.Frame(self._mm_jiggle_frame)
        jiggle_r1.pack(fill="x", pady=scale(2))
        ttk.Label(jiggle_r1, text="Radius (px):").pack(side="left")
        self._mm_jiggle_radius_var = tk.IntVar(value=binding.jiggle_radius if binding else 5)
        ttk.Spinbox(jiggle_r1, from_=1, to=500, textvariable=self._mm_jiggle_radius_var, width=6).pack(side="left", padx=(scale(6), 0))

        jiggle_r2 = ttk.Frame(self._mm_jiggle_frame)
        jiggle_r2.pack(fill="x", pady=scale(2))
        ttk.Label(jiggle_r2, text="Interval (ms):").pack(side="left")
        self._mm_jiggle_interval_var = tk.IntVar(value=binding.jiggle_interval_ms if binding else 1000)
        ttk.Spinbox(jiggle_r2, from_=1, to=86400000, textvariable=self._mm_jiggle_interval_var, width=8).pack(side="left", padx=(scale(6), 0))

        self._mm_jiggle_readable = tk.StringVar()
        ttk.Label(jiggle_r2, textvariable=self._mm_jiggle_readable, foreground="#888888").pack(side="left", padx=(scale(6), 0))
        self._mm_jiggle_interval_var.trace_add("write", self._update_jiggle_interval_label)
        self._update_jiggle_interval_label()

        # ── Move to Position sub-frame ──
        self._mm_move_frame = ttk.Frame(self._mm_panel)
        self._mm_move_frame.pack(fill="x", pady=scale(4))

        coord_row = ttk.Frame(self._mm_move_frame)
        coord_row.pack(fill="x", pady=scale(2))
        ttk.Label(coord_row, text="X:").pack(side="left")
        self._mm_move_x_var = tk.IntVar(value=binding.move_x if binding else 0)
        ttk.Spinbox(coord_row, from_=-99999, to=99999, textvariable=self._mm_move_x_var, width=7).pack(side="left", padx=(scale(3), scale(10)))
        ttk.Label(coord_row, text="Y:").pack(side="left")
        self._mm_move_y_var = tk.IntVar(value=binding.move_y if binding else 0)
        ttk.Spinbox(coord_row, from_=-99999, to=99999, textvariable=self._mm_move_y_var, width=7).pack(side="left", padx=(scale(3), scale(10)))

        pick_btn = ttk.Button(coord_row, text="Pick from Screen", command=self._on_mm_pick_position, style="primary.Round.TButton")
        pick_btn.pack(side="left", padx=(scale(6), 0))
        ToolTip(pick_btn, text="Click to capture current mouse position")

        smooth_row = ttk.Frame(self._mm_move_frame)
        smooth_row.pack(fill="x", pady=scale(2))
        self._mm_smooth_var = tk.BooleanVar(value=binding.move_smooth if binding else False)
        ttk.Checkbutton(smooth_row, text="Smooth movement", variable=self._mm_smooth_var, command=self._on_mm_smooth_changed).pack(side="left")

        self._mm_smooth_detail = ttk.Frame(self._mm_move_frame)
        self._mm_smooth_detail.pack(fill="x", pady=scale(2))
        ttk.Label(self._mm_smooth_detail, text="Duration (ms):").pack(side="left")
        self._mm_duration_var = tk.IntVar(value=binding.move_duration_ms if binding else 500)
        ttk.Spinbox(self._mm_smooth_detail, from_=50, to=30000, textvariable=self._mm_duration_var, width=7).pack(side="left", padx=(scale(6), scale(10)))
        ttk.Label(self._mm_smooth_detail, text="Easing:").pack(side="left")
        _EASING_DISPLAY = ["Linear", "Ease In", "Ease Out", "Ease In-Out"]
        self._EASING_MAP = {"Linear": "linear", "Ease In": "ease_in", "Ease Out": "ease_out", "Ease In-Out": "ease_in_out"}
        self._EASING_REVERSE = {v: k for k, v in self._EASING_MAP.items()}
        initial_easing = self._EASING_REVERSE.get(binding.move_easing if binding else "linear", "Linear")
        self._mm_easing_var = tk.StringVar(value=initial_easing)
        ttk.Combobox(self._mm_smooth_detail, textvariable=self._mm_easing_var, values=_EASING_DISPLAY, state="readonly", width=12).pack(side="left", padx=(scale(6), 0))

        click_row = ttk.Frame(self._mm_move_frame)
        click_row.pack(fill="x", pady=scale(2))
        self._mm_click_var = tk.BooleanVar(value=binding.move_click if binding else False)
        ttk.Checkbutton(click_row, text="Click on arrival", variable=self._mm_click_var, command=self._on_mm_click_changed).pack(side="left")

        self._mm_click_detail = ttk.Frame(self._mm_move_frame)
        self._mm_click_detail.pack(fill="x", pady=scale(2))
        ttk.Label(self._mm_click_detail, text="Button:").pack(side="left")
        self._mm_click_btn_var = tk.StringVar(value=binding.move_click_button if binding else "left")
        ttk.Combobox(self._mm_click_detail, textvariable=self._mm_click_btn_var, values=["left", "right", "middle"], state="readonly", width=8).pack(side="left", padx=(scale(6), scale(10)))
        ttk.Label(self._mm_click_detail, text="Count:").pack(side="left")
        self._mm_click_count_var = tk.IntVar(value=binding.move_click_count if binding else 1)
        ttk.Spinbox(self._mm_click_detail, from_=1, to=10, textvariable=self._mm_click_count_var, width=3).pack(side="left", padx=(scale(6), 0))

        # ── Pattern sub-frame ──
        self._mm_pattern_frame = ttk.Frame(self._mm_panel)
        self._mm_pattern_frame.pack(fill="x", pady=scale(4))

        pat_r1 = ttk.Frame(self._mm_pattern_frame)
        pat_r1.pack(fill="x", pady=scale(2))
        ttk.Label(pat_r1, text="Pattern:").pack(side="left")
        _PATTERN_DISPLAY = ["Circle", "Square", "Triangle", "Zigzag", "Figure-8", "Spiral"]
        self._PATTERN_MAP = {"Circle": "circle", "Square": "square", "Triangle": "triangle", "Zigzag": "zigzag", "Figure-8": "figure8", "Spiral": "spiral"}
        self._PATTERN_REVERSE = {v: k for k, v in self._PATTERN_MAP.items()}
        initial_pattern = self._PATTERN_REVERSE.get(binding.pattern_type if binding else "circle", "Circle")
        self._mm_pattern_var = tk.StringVar(value=initial_pattern)
        ttk.Combobox(pat_r1, textvariable=self._mm_pattern_var, values=_PATTERN_DISPLAY, state="readonly", width=12).pack(side="left", padx=(scale(6), 0))
        self._mm_pattern_var.trace_add("write", self._on_mm_pattern_changed)

        pat_r2 = ttk.Frame(self._mm_pattern_frame)
        pat_r2.pack(fill="x", pady=scale(2))
        ttk.Label(pat_r2, text="Size (px):").pack(side="left")
        self._mm_pattern_size_var = tk.IntVar(value=binding.pattern_size if binding else 50)
        ttk.Spinbox(pat_r2, from_=1, to=2000, textvariable=self._mm_pattern_size_var, width=6).pack(side="left", padx=(scale(6), scale(10)))
        ttk.Label(pat_r2, text="Speed:").pack(side="left")
        self._mm_pattern_speed_var = tk.DoubleVar(value=binding.pattern_speed if binding else 1.0)
        ttk.Spinbox(pat_r2, from_=0.1, to=10.0, increment=0.1, textvariable=self._mm_pattern_speed_var, width=5).pack(side="left", padx=(scale(6), 0))

        # Direction radios
        self._mm_dir_frame = ttk.Frame(self._mm_pattern_frame)
        self._mm_dir_frame.pack(fill="x", pady=scale(2))
        ttk.Label(self._mm_dir_frame, text="Direction:").pack(side="left")
        self._mm_dir_var = tk.StringVar(value=binding.pattern_direction if binding else "cw")
        ttk.Radiobutton(self._mm_dir_frame, text="CW", variable=self._mm_dir_var, value="cw").pack(side="left", padx=(scale(6), scale(4)))
        ttk.Radiobutton(self._mm_dir_frame, text="CCW", variable=self._mm_dir_var, value="ccw").pack(side="left")

        # Spiral extras
        self._mm_spiral_frame = ttk.Frame(self._mm_pattern_frame)
        self._mm_spiral_frame.pack(fill="x", pady=scale(2))
        ttk.Label(self._mm_spiral_frame, text="End radius:").pack(side="left")
        self._mm_spiral_end_var = tk.IntVar(value=binding.spiral_end_radius if binding else 80)
        ttk.Spinbox(self._mm_spiral_frame, from_=1, to=2000, textvariable=self._mm_spiral_end_var, width=6).pack(side="left", padx=(scale(6), scale(10)))
        ttk.Label(self._mm_spiral_frame, text="Revolutions:").pack(side="left")
        self._mm_spiral_rev_var = tk.IntVar(value=binding.spiral_revolutions if binding else 3)
        ttk.Spinbox(self._mm_spiral_frame, from_=1, to=50, textvariable=self._mm_spiral_rev_var, width=4).pack(side="left", padx=(scale(6), 0))

        # ── Path sub-frame (stub) ──
        self._mm_path_frame = ttk.Frame(self._mm_panel)
        self._mm_path_frame.pack(fill="x", pady=scale(4))
        ttk.Label(self._mm_path_frame, text="Path recording coming in a future update", foreground="#888888").pack(anchor="w")
        path_btn = ttk.Button(self._mm_path_frame, text="Record Path", state="disabled", style="secondary.Round.TButton")
        path_btn.pack(anchor="w", pady=(scale(4), 0))
        ToolTip(path_btn, text="Not yet implemented")

        # ── Loop checkbox (shared for Mouse Macro: Move to Position + Pattern) ──
        self._mm_loop_var = tk.BooleanVar(value=binding.loop if binding else True)
        self._mm_loop_check = ttk.Checkbutton(
            self._mm_panel, text="Loop continuously", variable=self._mm_loop_var,
        )
        self._mm_loop_check.pack(anchor="w", pady=(scale(6), 0))

        row += 1

        # ── Conflict warning ──
        self._warning_var = tk.StringVar()
        self._warning_label = ttk.Label(main, textvariable=self._warning_var, foreground="#e74c3c")
        self._warning_label.grid(row=row, column=0, columnspan=2, sticky="w", pady=(scale(6), 0))
        row += 1

        # ── Buttons ──
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=(scale(14), 0))

        self._ok_btn = ttk.Button(btn_frame, text="OK", width=8, command=self._ok, style="success.Round.TButton")
        self._ok_btn.pack(side="left", padx=scale(5))
        ToolTip(self._ok_btn, text="Save binding")
        cancel_btn = ttk.Button(btn_frame, text="Cancel", width=8, command=self._cancel, style="secondary.Round.TButton")
        cancel_btn.pack(side="left", padx=scale(5))
        ToolTip(cancel_btn, text="Discard changes")

        # Initial state
        self._on_action_changed()
        self._on_target_changed()
        self._validate()

    # ── Name auto-fill ───────────────────────────────────────

    def _on_name_key(self, _event):
        """Mark that the user has manually edited the name."""
        if self._name_var.get().strip():
            self._user_edited_name = True
        else:
            self._user_edited_name = False

    def _auto_fill_name(self):
        """Auto-fill the name field if user hasn't manually edited it."""
        if self._user_edited_name:
            return
        trigger = self._hotkey.get()
        if not trigger or trigger == "Press a key...":
            return
        action = self._action_var.get()
        self._name_var.set(f"{action} - {trigger}")

    # ── Interval label ───────────────────────────────────────

    def _update_interval_label(self, *_args):
        """Update the human-readable interval label."""
        try:
            ms = self._interval_var.get()
        except (tk.TclError, ValueError):
            self._interval_readable.set("")
            return
        if ms <= 0:
            self._interval_readable.set("")
            return
        parts = []
        total = ms
        h = total // 3600000
        total %= 3600000
        m = total // 60000
        total %= 60000
        s = total / 1000.0
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        if s > 0:
            if s == int(s):
                parts.append(f"{int(s)}s")
            else:
                parts.append(f"{s:.1f}s")
        self._interval_readable.set(f"= {' '.join(parts)}" if parts else "")

    # ── Macro helpers ────────────────────────────────────────

    def _update_step_count_label(self):
        n = len(self._macro_steps)
        if n == 0:
            self._step_count_var.set("No steps recorded")
        else:
            # Count non-delay steps for a cleaner display
            actions = sum(1 for s in self._macro_steps if s.step_type != "delay")
            self._step_count_var.set(f"{actions} action{'s' if actions != 1 else ''} ({n} total steps)")

    def _on_record(self):
        if self._recording_callback:
            self._recording_callback(True)

        recorder = MacroRecorder(self, macro_name="recording")
        self.wait_window(recorder)

        if self._recording_callback:
            self._recording_callback(False)

        if recorder.result:
            self._macro_steps = list(recorder.result.steps)
            self._update_step_count_label()

    def _on_edit_steps(self):
        # Pass current steps as a Macro container for the step editor
        macro = Macro(name="steps", steps=list(self._macro_steps)) if self._macro_steps else None
        editor = MacroStepEditor(self, macro=macro)
        self.wait_window(editor)
        if editor.result:
            self._macro_steps = list(editor.result.steps)
            self._update_step_count_label()

    # ── Callbacks ────────────────────────────────────────────

    def _on_action_changed(self, *_args):
        action = self._action_var.get()
        # Interval visibility
        if hides_interval(action):
            self._interval_frame.grid_remove()
        else:
            self._interval_frame.grid()
        # Target visibility (Auto Click and Hold only)
        if action in ("Auto Click", "Hold"):
            self._target_frame.grid()
        else:
            self._target_frame.grid_remove()
        # Keyboard Macro panel visibility
        if action == "Keyboard Macro":
            self._macro_panel.grid()
        else:
            self._macro_panel.grid_remove()
        # Mouse Macro panel visibility
        if action == "Mouse Macro":
            self._mm_panel.grid()
            self._on_mm_mode_changed()
        else:
            self._mm_panel.grid_remove()
        # Auto-fill name
        self._auto_fill_name()
        # Re-validate
        self._validate()

    # ── Mouse Macro callbacks ────────────────────────────────

    def _on_mm_mode_changed(self, *_args):
        """Show/hide sub-frames based on selected mouse macro mode."""
        mode_display = self._mm_mode_var.get()
        mode = self._MM_MODE_MAP.get(mode_display, "jiggle")

        # Hide all sub-frames first
        self._mm_jiggle_frame.pack_forget()
        self._mm_move_frame.pack_forget()
        self._mm_pattern_frame.pack_forget()
        self._mm_path_frame.pack_forget()
        self._mm_loop_check.pack_forget()

        if mode == "jiggle":
            self._mm_jiggle_frame.pack(fill="x", pady=4)
            # Jiggle always loops, no loop checkbox needed
        elif mode == "move_to":
            self._mm_move_frame.pack(fill="x", pady=4)
            self._mm_loop_check.pack(anchor="w", pady=(6, 0))
            self._on_mm_smooth_changed()
            self._on_mm_click_changed()
        elif mode == "pattern":
            self._mm_pattern_frame.pack(fill="x", pady=4)
            self._mm_loop_check.pack(anchor="w", pady=(6, 0))
            self._on_mm_pattern_changed()
        elif mode == "path":
            self._mm_path_frame.pack(fill="x", pady=4)

    def _on_mm_smooth_changed(self):
        """Show/hide duration + easing when smooth toggle changes."""
        if self._mm_smooth_var.get():
            self._mm_smooth_detail.pack(fill="x", pady=2)
        else:
            self._mm_smooth_detail.pack_forget()

    def _on_mm_click_changed(self):
        """Show/hide click detail frame when click-on-arrival changes."""
        if self._mm_click_var.get():
            self._mm_click_detail.pack(fill="x", pady=2)
        else:
            self._mm_click_detail.pack_forget()

    def _on_mm_pattern_changed(self, *_args):
        """Show/hide spiral extras + direction based on pattern type."""
        pattern_display = self._mm_pattern_var.get()
        pattern = self._PATTERN_MAP.get(pattern_display, "circle")

        # Direction is relevant for circle, figure8, spiral
        if pattern in ("circle", "figure8", "spiral"):
            self._mm_dir_frame.pack(fill="x", pady=2)
        else:
            self._mm_dir_frame.pack_forget()

        # Spiral extras
        if pattern == "spiral":
            self._mm_spiral_frame.pack(fill="x", pady=2)
        else:
            self._mm_spiral_frame.pack_forget()

    def _on_mm_pick_position(self):
        """Capture current mouse position after a brief delay."""
        from pynput.mouse import Controller as _MC
        pos = _MC().position
        self._mm_move_x_var.set(int(pos[0]))
        self._mm_move_y_var.set(int(pos[1]))

    def _update_jiggle_interval_label(self, *_args):
        """Update the human-readable label for jiggle interval."""
        try:
            ms = self._mm_jiggle_interval_var.get()
        except (tk.TclError, ValueError):
            self._mm_jiggle_readable.set("")
            return
        if ms <= 0:
            self._mm_jiggle_readable.set("")
            return
        parts = []
        total = ms
        h = total // 3600000
        total %= 3600000
        m = total // 60000
        total %= 60000
        s = total / 1000.0
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        if s > 0:
            if s == int(s):
                parts.append(f"{int(s)}s")
            else:
                parts.append(f"{s:.1f}s")
        self._mm_jiggle_readable.set(f"= {' '.join(parts)}" if parts else "")

    def _on_target_changed(self, *_args):
        target = self._target_combo_var.get()
        if target == "Keyboard Key":
            self._target_key_capture.pack(side="left", padx=(0, 4))
        else:
            self._target_key_capture.pack_forget()
        self._auto_fill_name()
        self._validate()

    def _on_target_key_captured(self, _name: str):
        self._auto_fill_name()
        self._validate()

    def _on_trigger_changed(self, _name: str):
        self._validate()
        self._auto_fill_name()

    def _validate(self, *_args):
        trigger = self._hotkey.get()
        warning = ""
        ok_enabled = True

        if not trigger or trigger == "Press a key...":
            ok_enabled = False
        elif self._kill_all_hotkey and trigger.lower() == self._kill_all_hotkey.lower():
            warning = "Conflicts with Kill All hotkey"
            ok_enabled = False
        elif self._conflict_checker:
            exclude_id = self._binding.id if self._binding else None
            if self._conflict_checker(trigger, exclude_id):
                warning = "Trigger already used by another binding"
                ok_enabled = False

        # Target validation for Auto Click/Hold
        action = self._action_var.get()
        if ok_enabled and action in ("Auto Click", "Hold"):
            target = self._target_combo_var.get()
            if target == "Keyboard Key":
                key_val = self._target_key_capture.get()
                if not key_val or key_val == "Press a key...":
                    warning = "Select a keyboard key for the target"
                    ok_enabled = False

        self._warning_var.set(warning)
        self._ok_btn.configure(style="success.Round.TButton" if ok_enabled else "secondary.Round.TButton")

    # ── Results ──────────────────────────────────────────────

    def _get_interval_ms(self) -> int:
        try:
            return max(self._interval_var.get(), 1)
        except (tk.TclError, ValueError):
            return 100

    def _get_action_target(self) -> str:
        """Resolve the action target string from the UI."""
        action = self._action_var.get()
        if action in ("Keyboard Macro", "Mouse Macro"):
            return "Left Mouse"  # ignored for these action types
        target = self._target_combo_var.get()
        if target == "Keyboard Key":
            return self._target_key_capture.get()
        return target

    def _ok(self):
        trigger = self._hotkey.get()
        action_type = self._action_var.get()
        name = self._name_var.get().strip()

        # Flash empty trigger
        if not trigger or trigger == "Press a key...":
            flash_widgets(self, [self._hotkey._entry])
            return

        # Flash empty target key (Auto Click / Hold with Keyboard Key)
        if action_type in ("Auto Click", "Hold"):
            target_sel = self._target_combo_var.get()
            if target_sel == "Keyboard Key":
                key_val = self._target_key_capture.get()
                if not key_val or key_val == "Press a key...":
                    flash_widgets(self, [self._target_key_capture._entry])
                    return

        interval_ms = 0 if hides_interval(action_type) else self._get_interval_ms()
        action_target = self._get_action_target()

        # Block zero interval for click actions
        if not hides_interval(action_type) and interval_ms == 0:
            flash_widgets(self, [self._interval_spin])
            self._warning_var.set("Interval cannot be zero")
            return

        # Keyboard Macro validation
        loop = True
        macro_steps: list[MacroStep] = []
        if action_type == "Keyboard Macro":
            if not self._macro_steps:
                flash_widgets(self, [self._step_count_label])
                self._warning_var.set("Record or add macro steps first")
                return
            macro_steps = list(self._macro_steps)
            loop = self._kb_loop_var.get()

        if self._binding:
            b = self._binding
            b.trigger = trigger
            b.action_type = action_type
            b.interval_ms = interval_ms
            b.name = name
            b.loop = loop
            b.action_target = action_target
            b.macro_steps = macro_steps
            if action_type == "Mouse Macro":
                self._write_mm_fields_to_binding(b)
            self.result = b
        else:
            b = Binding(
                trigger=trigger,
                action_type=action_type,
                interval_ms=interval_ms,
                name=name,
                loop=loop,
                action_target=action_target,
                macro_steps=macro_steps,
            )
            if action_type == "Mouse Macro":
                self._write_mm_fields_to_binding(b)
            self.result = b
        self.destroy()

    def _write_mm_fields_to_binding(self, b: Binding):
        """Write all Mouse Macro UI values to a Binding object."""
        mode_display = self._mm_mode_var.get()
        b.mouse_move_type = self._MM_MODE_MAP.get(mode_display, "jiggle")
        b.loop = self._mm_loop_var.get()
        b.jiggle_radius = self._mm_jiggle_radius_var.get()
        b.jiggle_interval_ms = self._mm_jiggle_interval_var.get()
        b.move_x = self._mm_move_x_var.get()
        b.move_y = self._mm_move_y_var.get()
        b.move_smooth = self._mm_smooth_var.get()
        b.move_duration_ms = self._mm_duration_var.get()
        easing_display = self._mm_easing_var.get()
        b.move_easing = self._EASING_MAP.get(easing_display, "linear")
        b.move_click = self._mm_click_var.get()
        b.move_click_button = self._mm_click_btn_var.get()
        b.move_click_count = self._mm_click_count_var.get()
        pattern_display = self._mm_pattern_var.get()
        b.pattern_type = self._PATTERN_MAP.get(pattern_display, "circle")
        b.pattern_size = self._mm_pattern_size_var.get()
        b.pattern_speed = self._mm_pattern_speed_var.get()
        b.pattern_direction = self._mm_dir_var.get()
        b.spiral_end_radius = self._mm_spiral_end_var.get()
        b.spiral_revolutions = self._mm_spiral_rev_var.get()

    def _cancel(self):
        self.result = None
        self.destroy()


# ── Copy Dialogs ──────────────────────────────────────────────


class ProfileSelectorDialog(tk.Toplevel):
    """Modal dialog for selecting target profiles to copy a binding to."""

    def __init__(self, parent, source_profile_id: str, all_profiles: list[Profile], binding: Binding):
        super().__init__(parent)
        self.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self.transient(parent)
        self.grab_set()
        self.title("Copy Binding")
        self.resizable(False, False)
        self.attributes("-topmost", True)

        self.result: list[str] | None = None  # List of selected profile IDs

        # Find available target profiles (exclude source)
        self._available_profiles = [p for p in all_profiles if p.id != source_profile_id]
        self._binding = binding

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        apply_dark_title_bar(self)
        _center_on_parent(self, parent)

    def _build_ui(self):
        main = ttk.Frame(self, padding=scale(16))
        main.pack(fill="both", expand=True)

        # Header showing binding info
        display_name = self._binding.name or self._binding.trigger
        ttk.Label(
            main, text=f"Copy '{display_name}' to:",
            font=(Fonts._detect(), scale(10), "bold"),
        ).pack(anchor="w", pady=(0, scale(10)))

        # Check if there are any available profiles
        if not self._available_profiles:
            ttk.Label(
                main, text="No other profiles available.",
                foreground="#888888",
            ).pack(pady=scale(10))
            cancel_btn = ttk.Button(main, text="OK", width=8, command=self._cancel, style="secondary.Round.TButton")
            cancel_btn.pack(pady=(scale(10), 0))
            ToolTip(cancel_btn, text="Close dialog")
            return

        # Checkbox frame (wrapped in tk.Frame for flash support)
        self._flash_border = tk.Frame(main, background=get_frame_bg(), padx=scale(2), pady=scale(2))
        self._flash_border.pack(fill="both", expand=True, pady=(0, scale(10)))
        checkbox_frame = ttk.Frame(self._flash_border)
        checkbox_frame.pack(fill="both", expand=True)

        self._checkbox_vars: dict[str, tk.BooleanVar] = {}
        for profile in self._available_profiles:
            var = tk.BooleanVar(value=False)
            self._checkbox_vars[profile.id] = var
            cb = ttk.Checkbutton(
                checkbox_frame,
                text=profile.name,
                variable=var,
                command=self._validate,
            )
            cb.pack(anchor="w", pady=scale(2))

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(pady=(scale(10), 0))

        self._ok_btn = ttk.Button(btn_frame, text="OK", width=8, command=self._ok, style="secondary.Round.TButton")
        self._ok_btn.pack(side="left", padx=scale(5))
        ToolTip(self._ok_btn, text="Copy to selected profiles")

        cancel_btn = ttk.Button(btn_frame, text="Cancel", width=8, command=self._cancel, style="secondary.Round.TButton")
        cancel_btn.pack(side="left", padx=scale(5))
        ToolTip(cancel_btn, text="Cancel copy")

    def _validate(self):
        """Switch OK button style based on whether at least one checkbox is selected."""
        any_selected = any(var.get() for var in self._checkbox_vars.values())
        self._ok_btn.configure(style="success.Round.TButton" if any_selected else "secondary.Round.TButton")

    def _ok(self):
        """Collect selected profile IDs and close."""
        selected = [pid for pid, var in self._checkbox_vars.items() if var.get()]
        if not selected:
            flash_widgets(self, [self._flash_border])
            return
        self.result = selected
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


class BulkCopyDialog(tk.Toplevel):
    """Modal dialog for selecting individual bindings from a source profile to copy."""

    def __init__(
        self,
        parent,
        current_profile_id: str,
        all_profiles: list[Profile],
        dest_bindings: list[Binding],
        kill_all_hotkey: str = "",
        on_captures_changed: Callable[[list[HotkeyCapture]], None] | None = None,
    ):
        super().__init__(parent)
        self.configure(bg=ttk.Style().lookup("TFrame", "background"))
        self.transient(parent)
        self.grab_set()
        self.title("Copy from Profile")
        self.resizable(True, True)
        self.minsize(scale(500), scale(300))
        self.attributes("-topmost", True)

        self.result: list[tuple[Binding, str | None]] | None = None

        self._dest_bindings = dest_bindings
        self._kill_all_hotkey = kill_all_hotkey
        self._on_captures_changed = on_captures_changed
        self._available_profiles = [p for p in all_profiles if p.id != current_profile_id]
        self._rows: list[dict] = []
        self._hotkey_captures: list[HotkeyCapture] = []
        self._updating_select_all = False

        self._build_ui()
        self.geometry(f"{scale(600)}x{scale(450)}")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        apply_dark_title_bar(self)
        _center_on_parent(self, parent)

    @property
    def all_hotkey_captures(self) -> list[HotkeyCapture]:
        return list(self._hotkey_captures)

    # ── UI construction ──────────────────────────────────────

    def _build_ui(self):
        main = ttk.Frame(self, padding=scale(16))
        main.pack(fill="both", expand=True)

        if not self._available_profiles:
            ttk.Label(
                main, text="No other profiles available.",
                foreground="#888888",
            ).pack(pady=scale(10))
            cancel_btn = ttk.Button(main, text="OK", width=8, command=self._cancel, style="secondary.Round.TButton")
            cancel_btn.pack(pady=(scale(10), 0))
            ToolTip(cancel_btn, text="Close dialog")
            return

        # Profile selector
        ttk.Label(main, text="Select a profile to copy bindings from:").pack(anchor="w", pady=(0, scale(6)))
        self._profile_var = tk.StringVar()
        self._profile_combo = ttk.Combobox(
            main, textvariable=self._profile_var,
            values=[p.name for p in self._available_profiles],
            state="readonly", width=30,
        )
        self._profile_combo.pack(fill="x", pady=(0, scale(10)))
        self._profile_combo.bind("<<ComboboxSelected>>", self._on_profile_changed)

        ttk.Separator(main, orient="horizontal").pack(fill="x", pady=(0, scale(6)))

        # Select All checkbox
        self._select_all_var = tk.BooleanVar(value=False)
        self._select_all_cb = ttk.Checkbutton(
            main, text="Select All", variable=self._select_all_var,
            command=self._on_select_all,
        )
        self._select_all_cb.pack(anchor="w", pady=(0, scale(4)))

        # Scrollable binding checklist
        self._flash_border = tk.Frame(main, background=get_frame_bg(), padx=scale(2), pady=scale(2))
        self._flash_border.pack(fill="both", expand=True, pady=(0, scale(6)))

        canvas_frame = ttk.Frame(self._flash_border)
        canvas_frame.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(
            canvas_frame, highlightthickness=0, bg=get_frame_bg(),
            width=scale(560), height=10,
        )
        self._scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self._canvas.yview)
        self._inner = ttk.Frame(self._canvas)
        self._canvas_window = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.pack(side="left", fill="both", expand=True)

        # Empty state label (shown when profile has no bindings)
        self._empty_label = ttk.Label(
            self._flash_border, text="No bindings in selected profile.",
            foreground="#888888",
        )

        # OK / Cancel
        btn_frame = ttk.Frame(main)
        btn_frame.pack(pady=(scale(10), 0))
        self._ok_btn = ttk.Button(btn_frame, text="OK", width=8, command=self._ok, style="secondary.Round.TButton")
        self._ok_btn.pack(side="left", padx=scale(5))
        ToolTip(self._ok_btn, text="Copy selected bindings")
        cancel_btn = ttk.Button(btn_frame, text="Cancel", width=8, command=self._cancel, style="secondary.Round.TButton")
        cancel_btn.pack(side="left", padx=scale(5))
        ToolTip(cancel_btn, text="Cancel copy")

        # Auto-select first profile and populate checklist
        if self._available_profiles:
            self._profile_combo.current(0)
            self._on_profile_changed()

    # ── Scrollable frame helpers ─────────────────────────────

    def _on_inner_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._canvas.itemconfigure(self._canvas_window, width=self._inner.winfo_reqwidth())
        self._update_scroll()

    def _update_scroll(self):
        max_h = scale(300)
        req_h = self._inner.winfo_reqheight()
        h = min(req_h, max_h) if req_h > 0 else scale(40)
        self._canvas.configure(height=h)
        if req_h > max_h:
            self._scrollbar.pack(side="right", fill="y")
        else:
            self._scrollbar.pack_forget()

    def _on_mousewheel(self, event):
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    # ── Profile / row management ─────────────────────────────

    def _on_profile_changed(self, _event=None):
        # Clear existing rows and captures
        for row in self._rows:
            row["frame"].destroy()
        self._rows.clear()
        self._hotkey_captures.clear()
        if self._on_captures_changed:
            self._on_captures_changed(list(self._hotkey_captures))

        # Find selected profile
        name = self._profile_var.get()
        profile = next((p for p in self._available_profiles if p.name == name), None)

        if not profile or not profile.bindings:
            self._empty_label.pack(pady=10)
            self._select_all_var.set(False)
            self._validate()
            return

        self._empty_label.pack_forget()
        self._build_binding_rows(profile)

        # Default: select all non-conflicting
        self._updating_select_all = True
        enabled_rows = [r for r in self._rows if not r["conflict"]]
        self._select_all_var.set(bool(enabled_rows))
        self._updating_select_all = False
        self._validate()

    def _build_binding_rows(self, profile: Profile):
        for i, binding in enumerate(profile.bindings):
            conflict = self._check_trigger_conflict(binding.trigger)
            row = self._create_row(binding, i, conflict)
            self._rows.append(row)

    def _check_trigger_conflict(self, trigger: str) -> bool:
        if BindingManager.check_conflict(trigger, self._dest_bindings):
            return True
        if self._kill_all_hotkey and trigger.lower() == self._kill_all_hotkey.lower():
            return True
        return False

    def _create_row(self, binding: Binding, index: int, conflict: bool) -> dict:
        frame = ttk.Frame(self._inner)
        frame.pack(fill="x", padx=scale(4), pady=scale(2))
        frame.columnconfigure(2, weight=1)

        var = tk.BooleanVar(value=not conflict)
        cb = ttk.Checkbutton(frame, variable=var, command=self._on_checkbox_changed)
        cb.grid(row=0, column=0, padx=(0, scale(4)))
        if conflict:
            cb.configure(state="disabled")

        trigger_label = ttk.Label(frame, text=binding.trigger, width=8, anchor="w")
        trigger_label.grid(row=0, column=1, padx=(0, scale(6)))

        desc = binding.format_action()
        if binding.name:
            desc += f'  "{binding.name}"'
        ttk.Label(frame, text=desc, anchor="w").grid(row=0, column=2, sticky="ew")

        conflict_frame = ttk.Frame(frame)
        conflict_frame.grid(row=0, column=3, padx=(scale(6), 0))

        row_data: dict = {
            "binding": binding,
            "var": var,
            "frame": frame,
            "conflict": conflict,
            "cb": cb,
            "trigger_label": trigger_label,
            "conflict_frame": conflict_frame,
            "capture": None,
            "new_trigger": None,
        }

        if conflict:
            warn_label = ttk.Label(conflict_frame, text="Conflict", foreground="#e74c3c")
            warn_label.pack(side="left", padx=(0, scale(4)))
            rebind_btn = ttk.Button(
                conflict_frame, text="Rebind", width=6,
                command=lambda idx=index: self._on_rebind(idx),
                style="primary.Round.TButton",
            )
            rebind_btn.pack(side="left")
            ToolTip(rebind_btn, text="Assign a different trigger key")

        return row_data

    # ── Rebind (inline HotkeyCapture) ────────────────────────

    def _on_rebind(self, index: int):
        row = self._rows[index]
        for w in row["conflict_frame"].winfo_children():
            w.destroy()

        capture = HotkeyCapture(
            row["conflict_frame"],
            initial=row["binding"].trigger,
            on_change=lambda name, idx=index: self._on_rebind_changed(idx, name),
        )
        capture.pack(side="left")
        row["capture"] = capture

        self._hotkey_captures.append(capture)
        if self._on_captures_changed:
            self._on_captures_changed(list(self._hotkey_captures))

    def _on_rebind_changed(self, index: int, new_trigger: str):
        row = self._rows[index]

        # Check against dest bindings and kill-all
        if self._check_trigger_conflict(new_trigger):
            flash_widgets(self, [row["capture"]._entry])
            return

        # Check against other selected/rebound triggers in the checklist
        for i, other in enumerate(self._rows):
            if i == index:
                continue
            effective = other.get("new_trigger") or other["binding"].trigger
            if other["var"].get() and effective.lower() == new_trigger.lower():
                flash_widgets(self, [row["capture"]._entry])
                return

        # Valid — enable and auto-check the row
        row["new_trigger"] = new_trigger
        row["conflict"] = False
        row["cb"].configure(state="normal")
        row["var"].set(True)
        row["trigger_label"].configure(text=new_trigger)
        self._on_checkbox_changed()

    # ── Select All / validation ──────────────────────────────

    def _on_select_all(self):
        if self._updating_select_all:
            return
        val = self._select_all_var.get()
        self._updating_select_all = True
        for row in self._rows:
            if not row["conflict"]:
                row["var"].set(val)
        self._updating_select_all = False
        self._validate()

    def _on_checkbox_changed(self):
        if self._updating_select_all:
            return
        enabled_rows = [r for r in self._rows if not r["conflict"]]
        if enabled_rows:
            all_checked = all(r["var"].get() for r in enabled_rows)
            self._updating_select_all = True
            self._select_all_var.set(all_checked)
            self._updating_select_all = False
        self._validate()

    def _validate(self):
        any_selected = any(r["var"].get() for r in self._rows)
        self._ok_btn.configure(style="success.Round.TButton" if any_selected else "secondary.Round.TButton")

    # ── Results ──────────────────────────────────────────────

    def _ok(self):
        selected = [
            (row["binding"], row.get("new_trigger"))
            for row in self._rows if row["var"].get()
        ]
        if not selected:
            flash_widgets(self, [self._flash_border])
            return
        self.result = selected
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()
