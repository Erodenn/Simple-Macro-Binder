"""Binding model, Profile, and manager for hotkey->action mappings."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable

from pynput.mouse import Controller as MouseController

from actions import Action, create_action, hides_interval


# ── Macro data models ─────────────────────────────────────────


@dataclass
class MacroStep:
    """A single step in a macro sequence."""

    step_type: str                  # "key_press", "key_release", "mouse_click", "delay"
    key: str | None = None          # for key_press / key_release
    x: int | None = None            # for mouse_click
    y: int | None = None            # for mouse_click
    button: str = "left"            # for mouse_click ("left" / "right")
    click_count: int = 1            # for mouse_click
    delay_ms: int = 0               # for delay

    def to_dict(self) -> dict:
        d: dict = {"step_type": self.step_type}
        if self.step_type in ("key_press", "key_release"):
            d["key"] = self.key
        elif self.step_type == "mouse_click":
            d["x"] = self.x
            d["y"] = self.y
            d["button"] = self.button
            d["click_count"] = self.click_count
        elif self.step_type == "delay":
            d["delay_ms"] = self.delay_ms
        return d

    @classmethod
    def from_dict(cls, data: dict) -> MacroStep:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Macro:
    """A named, reusable macro (ordered list of steps)."""

    name: str
    steps: list[MacroStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Macro:
        return cls(
            name=data["name"],
            steps=[MacroStep.from_dict(s) for s in data.get("steps", [])],
        )


class MacroLibrary:
    """Manages the collection of named macros."""

    def __init__(self):
        self.macros: dict[str, Macro] = {}

    def add(self, macro: Macro):
        self.macros[macro.name] = macro

    def remove(self, name: str):
        self.macros.pop(name, None)

    def get(self, name: str) -> Macro | None:
        return self.macros.get(name)

    def rename(self, old_name: str, new_name: str) -> bool:
        if new_name in self.macros or old_name not in self.macros:
            return False
        macro = self.macros.pop(old_name)
        macro.name = new_name
        self.macros[new_name] = macro
        return True

    def names(self) -> list[str]:
        return sorted(self.macros.keys())

    def to_list(self) -> list[dict]:
        return [m.to_dict() for m in self.macros.values()]

    @classmethod
    def from_list(cls, data: list[dict]) -> MacroLibrary:
        lib = cls()
        for d in data:
            try:
                lib.add(Macro.from_dict(d))
            except (KeyError, ValueError):
                continue
        return lib


# ── Binding model ─────────────────────────────────────────────


@dataclass
class Binding:
    """A single hotkey->action mapping."""

    trigger: str          # "F9", "Mouse4", etc.
    action_type: str      # "Auto Click", "Hold", or "Macro"
    interval_ms: int = 1000
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""        # user-editable display name
    loop: bool = True     # whether macro loops or plays once
    action_target: str = "Left Mouse"  # target mouse button or key name
    macro_steps: list[MacroStep] = field(default_factory=list)  # inline macro steps
    # Mouse Macro fields
    mouse_move_type: str = "jiggle"
    move_x: int = 0
    move_y: int = 0
    move_smooth: bool = False
    move_duration_ms: int = 500
    move_easing: str = "linear"
    move_click: bool = False
    move_click_button: str = "left"
    move_click_count: int = 1
    jiggle_radius: int = 5
    jiggle_interval_ms: int = 1000
    pattern_type: str = "circle"
    pattern_size: int = 50
    pattern_speed: float = 1.0
    pattern_direction: str = "cw"
    spiral_end_radius: int = 80
    spiral_revolutions: int = 3
    mouse_path: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "trigger": self.trigger,
            "action_type": self.action_type,
            "interval_ms": self.interval_ms,
            "enabled": self.enabled,
            "name": self.name,
            "action_target": self.action_target,
        }
        if self.action_type == "Keyboard Macro":
            d["macro_steps"] = [s.to_dict() for s in self.macro_steps]
            d["loop"] = self.loop
        elif self.action_type == "Mouse Macro":
            d["loop"] = self.loop
            d["mouse_move_type"] = self.mouse_move_type
            d["move_x"] = self.move_x
            d["move_y"] = self.move_y
            d["move_smooth"] = self.move_smooth
            d["move_duration_ms"] = self.move_duration_ms
            d["move_easing"] = self.move_easing
            d["move_click"] = self.move_click
            d["move_click_button"] = self.move_click_button
            d["move_click_count"] = self.move_click_count
            d["jiggle_radius"] = self.jiggle_radius
            d["jiggle_interval_ms"] = self.jiggle_interval_ms
            d["pattern_type"] = self.pattern_type
            d["pattern_size"] = self.pattern_size
            d["pattern_speed"] = self.pattern_speed
            d["pattern_direction"] = self.pattern_direction
            d["spiral_end_radius"] = self.spiral_end_radius
            d["spiral_revolutions"] = self.spiral_revolutions
            d["mouse_path"] = self.mouse_path
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Binding:
        steps = [MacroStep.from_dict(s) for s in data.get("macro_steps", [])]
        return cls(
            trigger=data["trigger"],
            action_type=data["action_type"],
            interval_ms=data.get("interval_ms", 1000),
            enabled=data.get("enabled", True),
            name=data.get("name", ""),
            loop=data.get("loop", True),
            action_target=data.get("action_target", "Left Mouse"),
            macro_steps=steps,
            mouse_move_type=data.get("mouse_move_type", "jiggle"),
            move_x=data.get("move_x", 0),
            move_y=data.get("move_y", 0),
            move_smooth=data.get("move_smooth", False),
            move_duration_ms=data.get("move_duration_ms", 500),
            move_easing=data.get("move_easing", "linear"),
            move_click=data.get("move_click", False),
            move_click_button=data.get("move_click_button", "left"),
            move_click_count=data.get("move_click_count", 1),
            jiggle_radius=data.get("jiggle_radius", 5),
            jiggle_interval_ms=data.get("jiggle_interval_ms", 1000),
            pattern_type=data.get("pattern_type", "circle"),
            pattern_size=data.get("pattern_size", 50),
            pattern_speed=data.get("pattern_speed", 1.0),
            pattern_direction=data.get("pattern_direction", "cw"),
            spiral_end_radius=data.get("spiral_end_radius", 80),
            spiral_revolutions=data.get("spiral_revolutions", 3),
            mouse_path=data.get("mouse_path", []),
        )

    def format_action(self) -> str:
        """Display string for the action (e.g. 'Auto Click (Left Mouse)')."""
        if self.action_type == "Keyboard Macro":
            n = len(self.macro_steps)
            return f"Keyboard Macro ({n} step{'s' if n != 1 else ''})"
        if self.action_type == "Mouse Macro":
            return f"Mouse Macro ({self.mouse_move_type.replace('_', ' ').title()})"
        return f"{self.action_type} ({self.action_target})"

    def format_interval(self) -> str:
        """Human-readable interval string, or '--' for hold/macro actions."""
        if hides_interval(self.action_type):
            return "--"
        total = self.interval_ms
        parts = []
        h = total // 3600000
        total %= 3600000
        m = total // 60000
        total %= 60000
        s = total // 1000
        ms = total % 1000
        if h:
            parts.append(f"{h}h")
        if m:
            parts.append(f"{m}m")
        if s:
            parts.append(f"{s}s")
        if ms or not parts:
            parts.append(f"{ms}ms")
        return " ".join(parts)


# ── Profile ───────────────────────────────────────────────────


@dataclass
class Profile:
    """A named group of bindings that can be switched between."""

    name: str
    bindings: list[Binding] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "id": self.id,
            "bindings": [b.to_dict() for b in self.bindings],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Profile:
        return cls(
            name=data["name"],
            id=data.get("id", uuid.uuid4().hex[:8]),
            bindings=[Binding.from_dict(b) for b in data.get("bindings", [])],
        )


# ── Binding Manager ──────────────────────────────────────────


class BindingManager:
    """Manages a list of bindings and their running actions."""

    def __init__(self, mouse: MouseController):
        self.bindings: list[Binding] = []
        self._active: dict[str, Action] = {}  # binding.id -> running Action
        self._mouse = mouse
        self.on_status_change: Callable[[], None] | None = None

    # ── Lookup ───────────────────────────────────────────────

    def is_active(self, binding_id: str) -> bool:
        return binding_id in self._active

    def has_conflict(self, trigger: str, exclude_id: str | None = None) -> bool:
        """Check if a trigger is already used by another enabled binding."""
        norm = trigger.lower()
        for b in self.bindings:
            if b.id != exclude_id and b.enabled and b.trigger.lower() == norm:
                return True
        return False

    @staticmethod
    def check_conflict(trigger: str, bindings: list[Binding]) -> bool:
        """Check if a trigger conflicts with any enabled binding in a list.

        Args:
            trigger: The trigger string to check
            bindings: List of bindings to check against

        Returns:
            True if trigger is already used by an enabled binding
        """
        norm = trigger.lower()
        for b in bindings:
            if b.enabled and b.trigger.lower() == norm:
                return True
        return False

    # ── Dispatch ─────────────────────────────────────────────

    def on_trigger(self, trigger_name: str):
        """Called by the global listener when a key/button is pressed."""
        norm = trigger_name.lower()
        for binding in self.bindings:
            if binding.enabled and binding.trigger.lower() == norm:
                self._toggle(binding)

    def _toggle(self, binding: Binding):
        if binding.id in self._active:
            self.stop_binding(binding)
        else:
            self.start_binding(binding)

    # ── Start / Stop ─────────────────────────────────────────

    def start_binding(self, binding: Binding):
        if binding.id in self._active:
            return
        if binding.action_type == "Keyboard Macro" and not binding.macro_steps:
            return  # no steps recorded, refuse to start
        if binding.action_type == "Mouse Macro" and binding.mouse_move_type == "path":
            return  # path recording stub, refuse to start

        mouse_macro_config: dict | None = None
        if binding.action_type == "Mouse Macro":
            mouse_macro_config = {
                "mouse_move_type": binding.mouse_move_type,
                "move_x": binding.move_x,
                "move_y": binding.move_y,
                "move_smooth": binding.move_smooth,
                "move_duration_ms": binding.move_duration_ms,
                "move_easing": binding.move_easing,
                "move_click": binding.move_click,
                "move_click_button": binding.move_click_button,
                "move_click_count": binding.move_click_count,
                "jiggle_radius": binding.jiggle_radius,
                "jiggle_interval_ms": binding.jiggle_interval_ms,
                "pattern_type": binding.pattern_type,
                "pattern_size": binding.pattern_size,
                "pattern_speed": binding.pattern_speed,
                "pattern_direction": binding.pattern_direction,
                "spiral_end_radius": binding.spiral_end_radius,
                "spiral_revolutions": binding.spiral_revolutions,
            }

        action = create_action(
            binding.action_type, self._mouse, binding.interval_ms,
            target_str=binding.action_target,
            macro_steps=binding.macro_steps, loop=binding.loop,
            mouse_macro_config=mouse_macro_config,
        )
        action.start()
        self._active[binding.id] = action
        if self.on_status_change:
            self.on_status_change()

    def stop_binding(self, binding: Binding):
        action = self._active.pop(binding.id, None)
        if action:
            action.stop()
            if self.on_status_change:
                self.on_status_change()

    def stop_all(self):
        for action in self._active.values():
            action.stop()
        self._active.clear()
        if self.on_status_change:
            self.on_status_change()

    # ── List management ──────────────────────────────────────

    def set_bindings(self, bindings: list[Binding]):
        """Replace the binding list (stops all active actions first)."""
        self.stop_all()
        self.bindings = bindings

    def add(self, binding: Binding):
        self.bindings.append(binding)

    def remove(self, binding_id: str):
        # Stop if active
        action = self._active.pop(binding_id, None)
        if action:
            action.stop()
        # In-place removal to preserve shared Profile reference
        for i, b in enumerate(self.bindings):
            if b.id == binding_id:
                self.bindings.pop(i)
                break
        if self.on_status_change:
            self.on_status_change()

    def update(self, binding_id: str, **kwargs):
        """Update fields on an existing binding. Stops it first if active."""
        action = self._active.pop(binding_id, None)
        if action:
            action.stop()
        for b in self.bindings:
            if b.id == binding_id:
                for k, v in kwargs.items():
                    setattr(b, k, v)
                break
        if self.on_status_change:
            self.on_status_change()

    def get(self, binding_id: str) -> Binding | None:
        for b in self.bindings:
            if b.id == binding_id:
                return b
        return None
