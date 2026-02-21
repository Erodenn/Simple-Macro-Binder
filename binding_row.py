"""Binding row widgets for normal and compact display modes."""

import tkinter as tk
from tkinter import ttk
from typing import Callable

from models import Binding
from theme import StatusDot, ToolTip


class BindingRow(ttk.Frame):
    """A single row in the binding list with conditional layout based on compact mode."""

    def __init__(
        self,
        parent,
        binding: Binding,
        on_edit: Callable,
        on_remove: Callable,
        on_copy: Callable,
        on_toggle: Callable,
        compact: bool = False,
        icon_edit=None,
        icon_copy=None,
        icon_close_red=None,
    ):
        super().__init__(parent)
        self.binding = binding
        self._on_edit = on_edit
        self._on_remove = on_remove
        self._on_copy = on_copy
        self._on_toggle = on_toggle
        self._compact = compact

        self._enabled_var = tk.BooleanVar(value=binding.enabled)

        # Status dot (used in both modes)
        self.status_dot = StatusDot(self)

        # Build layout based on mode
        if compact:
            self._build_compact_row()
        else:
            self._build_normal_row(icon_edit, icon_copy, icon_close_red)

    def _build_normal_row(self, icon_edit, icon_copy, icon_close_red):
        """Build full-width row with all columns."""
        self.columnconfigure(5, weight=1)

        # Enabled checkbox
        self._checkbox = ttk.Checkbutton(
            self, variable=self._enabled_var, command=self._toggle_enabled
        )
        self._checkbox.grid(row=0, column=0, padx=(6, 0))

        # Status dot
        self.status_dot.grid(row=0, column=1, padx=(3, 3))

        # Name
        self.name_label = ttk.Label(self, text=self.binding.name, width=12, anchor="w")
        self.name_label.grid(row=0, column=2, padx=5)

        # Trigger
        self.trigger_label = ttk.Label(self, text=self.binding.trigger, width=8, anchor="w")
        self.trigger_label.grid(row=0, column=3, padx=5)

        # Action type
        self.action_label = ttk.Label(
            self, text=self.binding.format_action(), width=20, anchor="w"
        )
        self.action_label.grid(row=0, column=4, padx=5)

        # Interval
        self.interval_label = ttk.Label(
            self, text=self.binding.format_interval(), width=10, anchor="w"
        )
        self.interval_label.grid(row=0, column=5, padx=5)

        # Edit button
        edit_btn_kwargs = {"text": "\u270e", "width": 3}
        if icon_edit:
            edit_btn_kwargs = {"image": icon_edit}
        edit_btn = ttk.Button(self, command=self._edit, bootstyle="info-link", **edit_btn_kwargs)
        edit_btn.grid(row=0, column=6, padx=3)
        ToolTip(edit_btn, text="Edit binding")

        # Copy button
        copy_btn_kwargs = {"text": "\u2398", "width": 3}
        if icon_copy:
            copy_btn_kwargs = {"image": icon_copy}
        copy_btn = ttk.Button(self, command=self._copy, bootstyle="info-link", **copy_btn_kwargs)
        copy_btn.grid(row=0, column=7, padx=3)
        ToolTip(copy_btn, text="Copy to other profiles")

        # Remove button
        remove_btn_kwargs = {"text": "\u2715", "width": 3}
        if icon_close_red:
            remove_btn_kwargs = {"image": icon_close_red}
        remove_btn = ttk.Button(
            self, command=self._remove, bootstyle="danger-link", **remove_btn_kwargs
        )
        remove_btn.grid(row=0, column=8, padx=(3, 6))
        ToolTip(remove_btn, text="Remove binding")

        self._update_appearance()

    def _build_compact_row(self):
        """Build narrow row with minimal info."""
        # Enabled checkbox
        self._checkbox = ttk.Checkbutton(
            self, variable=self._enabled_var, command=self._toggle_enabled
        )
        self._checkbox.grid(row=0, column=0, padx=(6, 0), sticky="w")

        # Status dot
        self.status_dot.grid(row=0, column=1, padx=(3, 3))

        # Combined "Trigger: Action" label
        trigger_name = self.binding.trigger
        action_desc = self._format_action_compact()
        combined_text = f"{trigger_name}: {action_desc}"

        self.combined_label = ttk.Label(self, text=combined_text, anchor="w")
        self.combined_label.grid(row=0, column=2, sticky="w", padx=(5, 10))

        self._update_appearance()

    def _format_action_compact(self) -> str:
        """Return abbreviated action description for compact mode."""
        action_type = self.binding.action_type
        target = self.binding.action_target or ""

        if action_type == "Auto Click":
            if "left" in target.lower():
                return "Click (L)"
            elif "right" in target.lower():
                return "Click (R)"
            elif "middle" in target.lower():
                return "Click (M)"
            else:
                # Keyboard key target - abbreviate if long
                return f"Click ({target[:3] if len(target) > 3 else target})"

        elif action_type == "Hold":
            if "left" in target.lower():
                return "Hold (L)"
            elif "right" in target.lower():
                return "Hold (R)"
            elif "middle" in target.lower():
                return "Hold (M)"
            else:
                return f"Hold ({target[:3] if len(target) > 3 else target})"

        elif action_type == "Keyboard Macro":
            step_count = len(self.binding.macro_steps)
            return f"KbMacro ({step_count})"

        elif action_type == "Mouse Macro":
            return f"Mouse ({self.binding.mouse_move_type})"

        return action_type

    def refresh(self):
        """Update labels from the binding's current data."""
        self._enabled_var.set(self.binding.enabled)

        if self._compact:
            # Update combined label
            trigger_name = self.binding.trigger
            action_desc = self._format_action_compact()
            combined_text = f"{trigger_name}: {action_desc}"
            self.combined_label.config(text=combined_text)
        else:
            # Update individual labels
            self.name_label.config(text=self.binding.name)
            self.trigger_label.config(text=self.binding.trigger)
            self.action_label.config(text=self.binding.format_action())
            self.interval_label.config(text=self.binding.format_interval())

        self._update_appearance()

    def set_active(self, active: bool):
        if not self.binding.enabled:
            self.status_dot.set_disabled()
        elif active:
            self.status_dot.set_active()
        else:
            self.status_dot.set_idle()

    def _toggle_enabled(self):
        self.binding.enabled = self._enabled_var.get()
        self._update_appearance()
        self._on_toggle(self.binding)

    def _update_appearance(self):
        fg = "" if self.binding.enabled else "#555555"

        if self._compact:
            self.combined_label.config(foreground=fg)
        else:
            for lbl in (self.name_label, self.trigger_label, self.action_label, self.interval_label):
                lbl.config(foreground=fg)

        if not self.binding.enabled:
            self.status_dot.set_disabled()
        else:
            self.status_dot.set_idle()

    def _edit(self):
        self._on_edit(self.binding)

    def _copy(self):
        self._on_copy(self.binding)

    def _remove(self):
        self._on_remove(self.binding)


def create_binding_row(
    parent,
    binding: Binding,
    on_edit: Callable,
    on_remove: Callable,
    on_copy: Callable,
    on_toggle: Callable,
    compact: bool = False,
    icon_edit=None,
    icon_copy=None,
    icon_close_red=None,
) -> BindingRow:
    """Factory function to create binding rows in normal or compact mode."""
    return BindingRow(
        parent,
        binding,
        on_edit,
        on_remove,
        on_copy,
        on_toggle,
        compact,
        icon_edit,
        icon_copy,
        icon_close_red,
    )
