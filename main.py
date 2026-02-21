"""Simple Macro Binder — multi-binding mouse/keyboard automation tool."""

import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
except Exception:
    pass

import json
import os
import tkinter as tk
import uuid
from tkinter import ttk

import ttkbootstrap as ttkb
from ttkbootstrap.dialogs import Messagebox, Querybox

from pynput.mouse import Button, Controller as MouseController
from pynput.mouse import Listener as MouseListener
from pynput.keyboard import Listener as KeyboardListener

from models import Binding, BindingManager, MacroStep, Profile
from dialogs import BindingEditor, HotkeyCapture
from binding_row import create_binding_row
from theme import (
    Colors, Spacing, Fonts, ToolTip, StatusDot,
    apply_dark_title_bar, configure_styles, get_frame_bg,
    load_icon, load_tinted_icon,
)


# ── Key normalization ────────────────────────────────────────

KEY_ALIASES = {
    "return": "enter",
    "escape": "esc",
    "prior": "page_up",
    "next": "page_down",
    "delete": "delete",
    "back_space": "backspace",
}

MOUSE_BUTTON_NAMES = {
    Button.x1: "Mouse4",
    Button.x2: "Mouse5",
}


def normalize_key(name: str) -> str:
    return KEY_ALIASES.get(name.lower(), name.lower())


# ── Settings migration ────────────────────────────────────────

# Maps old ACTION_REGISTRY names to (new action_type, action_target)
_OLD_ACTION_MIGRATION: dict[str, tuple[str, str]] = {
    "Left Click":          ("Auto Click", "Left Mouse"),
    "Right Click":         ("Auto Click", "Right Mouse"),
    "Left Double Click":   ("Auto Click", "Left Mouse"),
    "Right Double Click":  ("Auto Click", "Right Mouse"),
    "Left Hold":           ("Hold", "Left Mouse"),
    "Right Hold":          ("Hold", "Right Mouse"),
    "Macro":               ("Keyboard Macro", "Left Mouse"),
}


def _migrate_binding_dict(bd: dict, macros_by_name: dict | None = None) -> dict:
    """Migrate a single binding dict's action type and inline macro steps."""
    action = bd.get("action_type", "")
    if action in _OLD_ACTION_MIGRATION:
        new_type, new_target = _OLD_ACTION_MIGRATION[action]
        bd["action_type"] = new_type
        bd.setdefault("action_target", new_target)
    # Ensure action_target exists
    bd.setdefault("action_target", "Left Mouse")
    # Inline macro steps from old macro_name reference
    if "macro_name" in bd and "macro_steps" not in bd and macros_by_name:
        macro_data = macros_by_name.get(bd["macro_name"])
        if macro_data:
            bd["macro_steps"] = macro_data.get("steps", [])
        bd.pop("macro_name", None)
    elif "macro_name" in bd:
        bd.pop("macro_name", None)
    return bd


def _migrate_settings(settings: dict) -> dict:
    """Migrate settings from old flat format to new profile-based format.

    Mutates and returns the dict. Forward-only migration.
    """
    # Build macro lookup from old-style separate macros list
    macros_by_name: dict = {}
    for m in settings.get("macros", []):
        if "name" in m:
            macros_by_name[m["name"]] = m

    if "bindings" in settings and "profiles" not in settings:
        # Old format: flat binding list -> wrap into Default profile
        binding_dicts = settings.pop("bindings", [])
        for bd in binding_dicts:
            _migrate_binding_dict(bd, macros_by_name)
        default_profile = {
            "name": "Default",
            "id": "default",
            "bindings": binding_dicts,
        }
        settings["profiles"] = [default_profile]
        settings.setdefault("active_profile", "default")

    # Even in new format, migrate any old action types within profiles
    for profile_dict in settings.get("profiles", []):
        for bd in profile_dict.get("bindings", []):
            _migrate_binding_dict(bd, macros_by_name)

    # Remove old macros key
    settings.pop("macros", None)

    return settings


# ── App ──────────────────────────────────────────────────────

class App:
    SETTINGS_DIR = os.path.dirname(os.path.abspath(__file__))
    SETTINGS_FILE = os.path.join(SETTINGS_DIR, "settings.json")

    def __init__(self):
        self.mouse = MouseController()
        self.manager = BindingManager(self.mouse)
        self.manager.on_status_change = self._update_status_dots

        self._hotkey_captures: list[HotkeyCapture] = []
        self._binding_rows: dict[str, BindingRow] = {}
        self._recording_active = False

        # Profiles
        self._profiles: list[Profile] = []
        self._active_profile: Profile | None = None

        # Load settings
        settings = self._load_settings()
        settings = _migrate_settings(settings)

        # Build GUI
        self.root = ttkb.Window(
            title="Simple Macro Binder",
            themename="darkly",
            resizable=(False, False),
            iconphoto=None,
        )

        # Font & style configuration
        style = ttkb.Style()
        style.configure(".", font=Fonts.main())
        self.root.option_add("*Font", Fonts.main())
        configure_styles(style)

        # Load icons
        self._icons = {
            "plus": load_icon("icon_plus_white.png", 14),
            "edit": load_icon("icon_Edit_white.png", 14),
            "close": load_icon("icon_Close_white.png", 14),
            "close_red": load_tinted_icon("icon_Close_white.png", 14, (231, 76, 60)),
        }

        # Dark title bar via Windows DWM API
        apply_dark_title_bar(self.root)

        # Window + taskbar icon
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)

        self._always_on_top = tk.BooleanVar(value=settings.get("always_on_top", True))
        self.root.attributes("-topmost", self._always_on_top.get())

        self._strip_mode = tk.BooleanVar(value=settings.get("strip_mode", False))

        self._build_ui(settings)
        self._load_profiles(settings)
        self._setup_listeners()
        self._poll_status()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    # ── Settings ─────────────────────────────────────────────

    def _load_settings(self) -> dict:
        try:
            with open(self.SETTINGS_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_settings(self):
        # Get kill-all key from capture widget or stored value
        if hasattr(self, '_kill_all_capture') and self._kill_all_capture.winfo_exists():
            self._kill_all_key = self._kill_all_capture.get()

        data = {
            "profiles": [p.to_dict() for p in self._profiles],
            "active_profile": self._active_profile.id if self._active_profile else "",
            "kill_all_hotkey": self._kill_all_key,
            "always_on_top": self._always_on_top.get(),
            "strip_mode": self._strip_mode.get(),
        }
        os.makedirs(self.SETTINGS_DIR, exist_ok=True)
        with open(self.SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def _load_profiles(self, settings: dict):
        """Parse profiles from settings, activate the saved one, build UI rows."""
        profile_dicts = settings.get("profiles", [])
        self._profiles = []
        for pd in profile_dicts:
            try:
                self._profiles.append(Profile.from_dict(pd))
            except (KeyError, ValueError):
                continue

        # Ensure at least one profile
        if not self._profiles:
            self._profiles.append(Profile(name="Default", id="default"))

        # Activate saved profile
        active_id = settings.get("active_profile", "")
        self._active_profile = self._profiles[0]  # fallback
        for p in self._profiles:
            if p.id == active_id:
                self._active_profile = p
                break

        # Wire up manager to active profile's bindings
        self.manager.set_bindings(self._active_profile.bindings)

        # Build binding rows
        for b in self._active_profile.bindings:
            self._add_binding_row(b)

        # Update profile combobox
        self._refresh_profile_combo()

    # ── UI ───────────────────────────────────────────────────

    def _build_ui(self, settings: dict):
        self.main = ttk.Frame(self.root, padding=(14, 10))
        self.main.pack(fill="both", expand=True)

        # Store initial kill-all key from settings
        self._kill_all_key = settings.get("kill_all_hotkey", "Escape")
        self._profile_var = tk.StringVar()

        # Build UI sections
        self._build_profile_section()
        self._build_bindings_section()
        self._build_action_bar()
        self._build_bottom_bar()

    def _build_profile_section(self):
        """Build (or rebuild) the profile selector with current strip mode."""
        self.profile_lf = ttk.LabelFrame(self.main, text="Profile", padding=(8, 6))
        self.profile_lf.pack(fill="x", pady=(0, 10))

        profile_row = ttk.Frame(self.profile_lf)
        profile_row.pack(fill="x")

        # Always recreate the combobox
        self._profile_combo = ttk.Combobox(
            profile_row,
            textvariable=self._profile_var,
            state="readonly",
            width=20,
        )
        self._profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)
        self._profile_combo.pack(side="left", padx=(0, 6))

        # Only show edit buttons in normal mode
        if not self._strip_mode.get():
            new_prof_btn = ttk.Button(
                profile_row, image=self._icons["plus"], width=3,
                command=self._new_profile, style="success.Round.TButton",
            )
            new_prof_btn.pack(side="left", padx=3)
            ToolTip(new_prof_btn, text="New profile")

            rename_prof_btn = ttk.Button(
                profile_row, image=self._icons["edit"], width=3,
                command=self._rename_profile, style="info.Round.TButton",
            )
            rename_prof_btn.pack(side="left", padx=3)
            ToolTip(rename_prof_btn, text="Rename profile")

            del_prof_btn = ttk.Button(
                profile_row, image=self._icons["close"], width=3,
                command=self._delete_profile, style="danger.Round.TButton",
            )
            del_prof_btn.pack(side="left", padx=3)
            ToolTip(del_prof_btn, text="Delete profile")

            copy_from_btn = ttk.Button(
                profile_row, image=self._icons["edit"], width=3,
                command=self._copy_from_profile_ui, style="secondary.Round.TButton",
            )
            copy_from_btn.pack(side="left", padx=3)
            ToolTip(copy_from_btn, text="Copy from another profile")

    def _build_action_bar(self):
        """Build (or rebuild) the action bar."""
        self.action_bar = ttk.Frame(self.main)
        self.action_bar.pack(fill="x", pady=(0, 10))

        add_btn = ttk.Button(
            self.action_bar, text=" Add Binding", image=self._icons["plus"],
            compound="left", command=self._add_binding, style="success.Round.TButton",
        )
        add_btn.pack(side="left")
        ToolTip(add_btn, text="Add a new binding")

        stop_btn = ttk.Button(
            self.action_bar, text="Stop All", command=self._stop_all,
            style="danger.Round.TButton"
        )
        stop_btn.pack(side="right")
        ToolTip(stop_btn, text="Stop all running actions")

    def _build_bottom_bar(self):
        """Build (or rebuild) the bottom bar with current strip mode."""
        self.bottom_bar = ttk.Frame(self.main)
        self.bottom_bar.pack(fill="x")

        small_font = Fonts.small()

        if self._strip_mode.get():
            # Strip mode: vertical layout, smaller font, no editing controls
            # Kill All - just show current key as label
            kill_row = ttk.Frame(self.bottom_bar)
            kill_row.pack(fill="x", pady=(0, 2))
            ttk.Label(kill_row, text="Kill All:", font=small_font).pack(side="left")
            ttk.Label(
                kill_row, text=self._kill_all_key, font=small_font,
                foreground="#888888"
            ).pack(side="left", padx=(6, 0))

            # Strip Mode checkbox
            ttk.Checkbutton(
                self.bottom_bar,
                text="Strip Mode",
                variable=self._strip_mode,
                command=self._toggle_strip_mode,
                style="small.TCheckbutton",
            ).pack(anchor="w", pady=(0, 2))

            # Always on Top checkbox
            ttk.Checkbutton(
                self.bottom_bar,
                text="Always on Top",
                variable=self._always_on_top,
                command=self._toggle_on_top,
                style="small.TCheckbutton",
            ).pack(anchor="w")

        else:
            # Normal mode: horizontal layout with HotkeyCapture
            ttk.Label(self.bottom_bar, text="Kill All:").pack(side="left")

            # Recreate HotkeyCapture if needed
            if hasattr(self, '_kill_all_capture'):
                # Remove from hotkey captures list
                if self._kill_all_capture in self._hotkey_captures:
                    self._hotkey_captures.remove(self._kill_all_capture)

            self._kill_all_capture = HotkeyCapture(
                self.bottom_bar, initial=self._kill_all_key
            )
            self._kill_all_capture.pack(side="left", padx=(6, 14))
            self._hotkey_captures.append(self._kill_all_capture)

            # Strip Mode checkbox
            ttk.Checkbutton(
                self.bottom_bar,
                text="Strip Mode",
                variable=self._strip_mode,
                command=self._toggle_strip_mode,
                style="small.TCheckbutton",
            ).pack(side="left", padx=(0, 10))

            # Always on Top checkbox
            ttk.Checkbutton(
                self.bottom_bar,
                text="Always on Top",
                variable=self._always_on_top,
                command=self._toggle_on_top,
                style="small.TCheckbutton",
            ).pack(side="right")

    def _build_bindings_section(self):
        """Build (or rebuild) the bindings LabelFrame with current strip mode."""
        self.bindings_lf = ttk.LabelFrame(self.main, text="Bindings", padding=(8, 6))
        self.bindings_lf.pack(fill="both", expand=True, pady=(0, 10))

        # Build header (conditional on strip mode)
        self._build_bindings_header()

        # Separator
        ttk.Separator(self.bindings_lf, orient="horizontal").pack(fill="x", pady=3)

        # Scrollable binding rows container
        self._rows_frame = ttk.Frame(self.bindings_lf)
        self._rows_frame.pack(fill="both", expand=True)

    def _build_bindings_header(self):
        """Build header row based on current strip mode."""
        header = ttk.Frame(self.bindings_lf)
        header.pack(fill="x")
        hdr_font = Fonts.small()

        if self._strip_mode.get():
            # Strip mode: minimal header
            ttk.Label(header, text="On", width=3, anchor="w", font=hdr_font).grid(
                row=0, column=0, padx=(6, 0)
            )
            ttk.Label(header, text="", width=2).grid(row=0, column=1, padx=(2, 2))
            ttk.Label(header, text="Binding", anchor="w", font=hdr_font).grid(
                row=0, column=2, sticky="w", padx=5
            )
        else:
            # Normal mode: full header
            header.columnconfigure(5, weight=1)
            ttk.Label(header, text="On", width=3, anchor="w", font=hdr_font).grid(
                row=0, column=0, padx=(6, 0)
            )
            ttk.Label(header, text="", width=2).grid(row=0, column=1, padx=(2, 2))
            ttk.Label(header, text="Name", width=12, anchor="w", font=hdr_font).grid(
                row=0, column=2, padx=5
            )
            ttk.Label(header, text="Trigger", width=8, anchor="w", font=hdr_font).grid(
                row=0, column=3, padx=5
            )
            ttk.Label(header, text="Action", width=20, anchor="w", font=hdr_font).grid(
                row=0, column=4, padx=5
            )
            ttk.Label(header, text="Interval", width=10, anchor="w", font=hdr_font).grid(
                row=0, column=5, padx=5
            )

    def _add_binding_row(self, binding: Binding):
        row = create_binding_row(
            parent=self._rows_frame,
            binding=binding,
            on_edit=self._edit_binding,
            on_remove=self._remove_binding,
            on_copy=self._on_copy_binding,
            on_toggle=self._on_toggle_binding,
            compact=self._strip_mode.get(),
            icon_edit=self._icons["edit"],
            icon_close_red=self._icons["close_red"],
        )
        row.pack(fill="x", pady=2)
        self._binding_rows[binding.id] = row

    def _refresh_row(self, binding: Binding):
        row = self._binding_rows.get(binding.id)
        if row:
            row.refresh()

    # ── Profile UI ───────────────────────────────────────────

    def _refresh_profile_combo(self):
        """Update the profile combobox values and selection."""
        names = [p.name for p in self._profiles]
        self._profile_combo.config(values=names)
        if self._active_profile:
            self._profile_var.set(self._active_profile.name)

    def _on_profile_selected(self, _event):
        """Handle profile combobox selection."""
        selected_name = self._profile_var.get()
        for p in self._profiles:
            if p.name == selected_name:
                if p is not self._active_profile:
                    self._switch_profile(p)
                return

    def _switch_profile(self, profile: Profile):
        """Switch to a different profile."""
        # Stop all running actions
        self.manager.stop_all()

        # Destroy all current binding rows
        for row in self._binding_rows.values():
            row.destroy()
        self._binding_rows.clear()

        # Set new active profile
        self._active_profile = profile
        self.manager.set_bindings(profile.bindings)

        # Rebuild binding rows
        for b in profile.bindings:
            self._add_binding_row(b)

        # Update combobox
        self._profile_var.set(profile.name)

    def _new_profile(self):
        """Create a new profile."""
        name = Querybox.get_string(
            prompt="Enter profile name:",
            title="New Profile",
            parent=self.root,
        )
        if not name or not name.strip():
            return
        name = name.strip()

        # Check for duplicates
        if any(p.name == name for p in self._profiles):
            Messagebox.show_warning(
                f'A profile named "{name}" already exists.',
                title="Duplicate Name", parent=self.root,
            )
            return

        profile = Profile(name=name)
        self._profiles.append(profile)
        self._refresh_profile_combo()
        self._switch_profile(profile)

    def _rename_profile(self):
        """Rename the active profile."""
        if not self._active_profile:
            return
        name = Querybox.get_string(
            prompt="Enter new name:",
            title="Rename Profile",
            initialvalue=self._active_profile.name,
            parent=self.root,
        )
        if not name or not name.strip():
            return
        name = name.strip()

        if name == self._active_profile.name:
            return

        # Check for duplicates
        if any(p.name == name for p in self._profiles):
            Messagebox.show_warning(
                f'A profile named "{name}" already exists.',
                title="Duplicate Name", parent=self.root,
            )
            return

        self._active_profile.name = name
        self._refresh_profile_combo()

    def _delete_profile(self):
        """Delete the active profile."""
        if not self._active_profile:
            return
        if len(self._profiles) <= 1:
            Messagebox.show_warning(
                "Cannot delete the last profile.",
                title="Delete Profile", parent=self.root,
            )
            return

        name = self._active_profile.name
        if Messagebox.yesno(
            f'Delete profile "{name}" and all its bindings?',
            title="Delete Profile", parent=self.root,
        ) != "Yes":
            return

        self._profiles.remove(self._active_profile)
        self._switch_profile(self._profiles[0])
        self._refresh_profile_combo()

    def _copy_from_profile(self, selections: list[tuple[Binding, str | None]]) -> int:
        """Copy selected bindings to the active profile.

        Args:
            selections: List of (source_binding, new_trigger_or_None) tuples.

        Returns: Number of bindings copied.
        """
        if not self._active_profile:
            return 0

        copied = 0
        for binding, new_trigger in selections:
            copy_dict = binding.to_dict()
            new_binding = Binding.from_dict(copy_dict)
            new_binding.id = uuid.uuid4().hex[:8]
            new_binding.enabled = False
            if new_trigger:
                new_binding.trigger = new_trigger

            self._active_profile.bindings.append(new_binding)
            self._add_binding_row(new_binding)
            copied += 1

        return copied

    def _copy_from_profile_ui(self):
        """Handle 'Copy from...' button click."""
        from dialogs import BulkCopyDialog

        if not self._active_profile:
            return

        # Track HotkeyCapture registrations from the dialog
        dialog_caps: list = []

        def on_caps_changed(new_caps):
            for c in dialog_caps:
                if c in self._hotkey_captures:
                    self._hotkey_captures.remove(c)
            dialog_caps.clear()
            for c in new_caps:
                self._hotkey_captures.append(c)
            dialog_caps.extend(new_caps)

        dialog = BulkCopyDialog(
            self.root,
            self._active_profile.id,
            self._profiles,
            dest_bindings=self._active_profile.bindings,
            kill_all_hotkey=self._kill_all_key,
            on_captures_changed=on_caps_changed,
        )
        self.root.wait_window(dialog)

        # Unregister any remaining captures
        for c in dialog_caps:
            if c in self._hotkey_captures:
                self._hotkey_captures.remove(c)

        if not dialog.result:
            return

        self._copy_from_profile(dialog.result)

    # ── Binding CRUD ─────────────────────────────────────────

    def _open_editor(self, binding: Binding | None = None) -> Binding | None:
        """Open a BindingEditor modal and return the result."""
        # Update kill-all key from capture widget if it exists
        if hasattr(self, '_kill_all_capture') and self._kill_all_capture.winfo_exists():
            self._kill_all_key = self._kill_all_capture.get()

        editor = BindingEditor(
            self.root,
            binding=binding,
            conflict_checker=self.manager.has_conflict,
            kill_all_hotkey=self._kill_all_key,
            recording_callback=self._set_recording_active,
        )
        # Register all the dialog's capture widgets so mouse side buttons work
        for cap in editor.all_hotkey_captures:
            self._hotkey_captures.append(cap)
        self.root.wait_window(editor)
        # Unregister (dialog is destroyed, but clean up the list)
        for cap in editor.all_hotkey_captures:
            if cap in self._hotkey_captures:
                self._hotkey_captures.remove(cap)
        return editor.result

    def _add_binding(self):
        result = self._open_editor()
        if result:
            self.manager.add(result)
            self._add_binding_row(result)

    def _edit_binding(self, binding: Binding):
        self.manager.stop_binding(binding)
        result = self._open_editor(binding)
        if result:
            self._refresh_row(binding)

    def _remove_binding(self, binding: Binding):
        display = binding.name or f"{binding.trigger} \u2192 {binding.format_action()}"
        if Messagebox.yesno(f'Remove "{display}"?', title="Remove Binding", parent=self.root) != "Yes":
            return
        self.manager.remove(binding.id)
        row = self._binding_rows.pop(binding.id, None)
        if row:
            row.destroy()

    def _copy_binding(self, binding: Binding, target_profile_ids: list[str]) -> dict[str, tuple[int, int]]:
        """Copy a binding to multiple target profiles.

        Returns: Dict mapping profile_id -> (copied_count, skipped_count)
        """
        results = {}
        for profile_id in target_profile_ids:
            # Find target profile
            target_profile = next((p for p in self._profiles if p.id == profile_id), None)
            if not target_profile:
                continue

            # Check conflict
            if BindingManager.check_conflict(binding.trigger, target_profile.bindings):
                results[profile_id] = (0, 1)  # skipped
                continue

            # Create deep copy with new ID
            copy_dict = binding.to_dict()
            new_binding = Binding.from_dict(copy_dict)
            new_binding.id = uuid.uuid4().hex[:8]
            new_binding.enabled = False  # Safety: disable by default

            # Add to target profile
            target_profile.bindings.append(new_binding)
            results[profile_id] = (1, 0)  # copied

            # If target is active profile, add UI row
            if target_profile is self._active_profile:
                self._add_binding_row(new_binding)

        return results

    def _on_copy_binding(self, binding: Binding):
        """Handle copy button click on a binding row."""
        from dialogs import ProfileSelectorDialog

        source_profile_id = self._active_profile.id if self._active_profile else ""

        # Open dialog
        dialog = ProfileSelectorDialog(self.root, source_profile_id, self._profiles, binding)
        self.root.wait_window(dialog)

        if not dialog.result:
            return  # Canceled

        # Copy to selected profiles
        results = self._copy_binding(binding, dialog.result)

        # Show summary
        total_copied = sum(c for c, _ in results.values())
        total_skipped = sum(s for _, s in results.values())

        msg = f"Copied '{binding.name or binding.trigger}' to {total_copied} profile(s)."
        if total_skipped > 0:
            msg += f"\n{total_skipped} profile(s) skipped due to conflicts."

        Messagebox.show_info(msg, title="Copy Complete", parent=self.root)

    def _on_toggle_binding(self, binding: Binding):
        """Handle enable/disable toggle — stop the binding if it was disabled while active."""
        if not binding.enabled:
            self.manager.stop_binding(binding)

    def _stop_all(self):
        self.manager.stop_all()

    def _toggle_on_top(self):
        self.root.attributes("-topmost", self._always_on_top.get())

    def _toggle_strip_mode(self):
        """Rebuild UI sections with current strip mode setting."""
        # Stop all running actions (to avoid state issues during rebuild)
        self.manager.stop_all()

        # Save kill-all key before rebuilding bottom bar
        if hasattr(self, '_kill_all_capture') and self._kill_all_capture.winfo_exists():
            self._kill_all_key = self._kill_all_capture.get()

        # Clear binding rows dict
        self._binding_rows.clear()

        # Destroy all sections first to reset pack order
        if hasattr(self, 'profile_lf') and self.profile_lf.winfo_exists():
            self.profile_lf.destroy()
        if hasattr(self, 'bindings_lf') and self.bindings_lf.winfo_exists():
            self.bindings_lf.destroy()
        if hasattr(self, 'action_bar') and self.action_bar.winfo_exists():
            self.action_bar.destroy()
        if hasattr(self, 'bottom_bar') and self.bottom_bar.winfo_exists():
            self.bottom_bar.destroy()

        # Rebuild all sections in correct order
        self._build_profile_section()
        self._build_bindings_section()
        self._build_action_bar()
        self._build_bottom_bar()

        # Restore profile combobox state
        self._refresh_profile_combo()

        # Rebuild all binding rows with new layout
        for binding in self._active_profile.bindings:
            self._add_binding_row(binding)

    # ── Status polling ───────────────────────────────────────

    def _update_status_dots(self):
        for bid, row in self._binding_rows.items():
            row.set_active(self.manager.is_active(bid))

    def _poll_status(self):
        self._update_status_dots()
        self.root.after(100, self._poll_status)

    # ── Global listeners ─────────────────────────────────────

    def _any_capture_listening(self) -> bool:
        return any(cap.is_listening for cap in self._hotkey_captures)

    def _setup_listeners(self):
        self._kb_listener = KeyboardListener(on_press=self._on_global_key)
        self._kb_listener.daemon = True
        self._kb_listener.start()

        self._mouse_listener = MouseListener(on_click=self._on_global_mouse)
        self._mouse_listener.daemon = True
        self._mouse_listener.start()

    def _set_recording_active(self, active: bool):
        """Callback for MacroRecorder to suppress/resume global dispatch."""
        self._recording_active = active

    def _dispatch(self, key_name: str):
        """Route a trigger to kill-all check, then binding manager."""
        if self._recording_active:
            return
        normalized = normalize_key(key_name)

        # Kill-all hotkey
        if self._kill_all_key and normalize_key(self._kill_all_key) == normalized:
            self.root.after(0, self._stop_all)
            return

        self.root.after(0, self.manager.on_trigger, key_name)

    def _on_global_key(self, key):
        if self._any_capture_listening():
            return
        try:
            key_name = key.name if hasattr(key, "name") else key.char
        except AttributeError:
            return
        if key_name is None:
            return
        self._dispatch(key_name)

    def _on_global_mouse(self, _x, _y, button, pressed):
        if button not in MOUSE_BUTTON_NAMES or not pressed:
            return
        name = MOUSE_BUTTON_NAMES[button]

        # If any hotkey capture widget is listening, feed it the mouse button
        if self._any_capture_listening():
            for cap in self._hotkey_captures:
                if cap.is_listening:
                    self.root.after(0, cap.on_mouse_button, name)
            return

        self._dispatch(name)

    # ── Cleanup ──────────────────────────────────────────────

    def _on_close(self):
        self.manager.stop_all()
        self._save_settings()
        self._kb_listener.stop()
        self._mouse_listener.stop()
        self.root.destroy()


if __name__ == "__main__":
    App()
