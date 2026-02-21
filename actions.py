"""Action classes for mouse/keyboard automation.

Provides versatile action types (Auto Click, Hold, Keyboard Macro, Mouse Macro)
that can target any mouse button or keyboard key.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import math
import threading
import time

from pynput.keyboard import Controller as KeyboardController, Key, KeyCode
from pynput.mouse import Button, Controller as MouseController

# Scroll sentinels (used as action targets by ClickAction)
SCROLL_UP = "__scroll_up__"
SCROLL_DOWN = "__scroll_down__"


class Action(ABC):
    """Base class for all executable actions."""

    @abstractmethod
    def start(self):
        ...

    @abstractmethod
    def stop(self):
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        ...


class ClickAction(Action):
    """Repeatedly presses + releases a target (mouse button or key) at a fixed interval."""

    def __init__(
        self,
        mouse: MouseController,
        keyboard: KeyboardController,
        target: Button | Key | KeyCode | str,
        interval_s: float,
    ):
        self._mouse = mouse
        self._keyboard = keyboard
        self._target = target
        self._interval = interval_s
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def _loop(self):
        while self._running:
            if self._target == SCROLL_UP:
                self._mouse.scroll(0, 1)
            elif self._target == SCROLL_DOWN:
                self._mouse.scroll(0, -1)
            elif isinstance(self._target, Button):
                self._mouse.click(self._target)
            else:
                self._keyboard.press(self._target)
                self._keyboard.release(self._target)
            time.sleep(self._interval)


class HoldAction(Action):
    """Holds a target (mouse button or key) down until stopped."""

    def __init__(
        self,
        mouse: MouseController,
        keyboard: KeyboardController,
        target: Button | Key | KeyCode,
    ):
        self._mouse = mouse
        self._keyboard = keyboard
        self._target = target
        self._running = False

    def start(self):
        self._running = True
        if isinstance(self._target, Button):
            self._mouse.press(self._target)
        else:
            self._keyboard.press(self._target)

    def stop(self):
        self._running = False
        if isinstance(self._target, Button):
            self._mouse.release(self._target)
        else:
            self._keyboard.release(self._target)

    @property
    def is_running(self) -> bool:
        return self._running


class MacroAction(Action):
    """Plays back a recorded macro sequence on a daemon thread."""

    def __init__(self, mouse: MouseController, steps, loop: bool):
        self._mouse = mouse
        self._keyboard = KeyboardController()
        self._steps = steps          # list of MacroStep objects (duck-typed)
        self._loop = loop
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        if not self._steps:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def _run(self):
        while self._running:
            for step in self._steps:
                if not self._running:
                    return
                self._execute_step(step)
            if not self._loop:
                self._running = False
                return

    def _execute_step(self, step):
        st = step.step_type
        if st == "delay":
            remaining = step.delay_ms / 1000.0
            while remaining > 0 and self._running:
                chunk = min(remaining, 0.05)
                time.sleep(chunk)
                remaining -= chunk
        elif st == "key_press":
            key = self._resolve_key(step.key)
            if key:
                self._keyboard.press(key)
        elif st == "key_release":
            key = self._resolve_key(step.key)
            if key:
                self._keyboard.release(key)
        elif st == "mouse_click":
            btn = Button.left if step.button == "left" else Button.right
            self._mouse.position = (step.x, step.y)
            self._mouse.click(btn, step.click_count)

    @staticmethod
    def _resolve_key(key_name: str | None):
        """Convert a key name string to a pynput Key or KeyCode."""
        if key_name is None:
            return None
        try:
            return Key[key_name]
        except (KeyError, AttributeError):
            pass
        if len(key_name) == 1:
            return KeyCode.from_char(key_name)
        return None


class MouseMacroAction(Action):
    """Mouse movement automation with sub-modes (jiggle, move, pattern)."""

    def __init__(self, mouse: MouseController, config: dict, loop: bool):
        self._mouse = mouse
        self._config = config
        self._loop = loop
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def _sleep_interruptible(self, duration: float):
        """Sleep in 50ms chunks, checking _running between chunks."""
        remaining = duration
        while remaining > 0 and self._running:
            chunk = min(remaining, 0.05)
            time.sleep(chunk)
            remaining -= chunk

    def _run(self):
        mode = self._config.get("mouse_move_type", "jiggle")
        while self._running:
            if mode == "jiggle":
                self._run_jiggle()
            elif mode == "move_to":
                self._run_move_to()
            elif mode == "pattern":
                self._run_pattern()
            else:
                self._running = False
                return
            if not self._loop:
                self._running = False
                return

    def _run_jiggle(self):
        radius = self._config.get("jiggle_radius", 5)
        interval = self._config.get("jiggle_interval_ms", 1000) / 1000.0
        self._mouse.move(radius, 0)
        self._sleep_interruptible(interval / 2)
        if not self._running:
            return
        self._mouse.move(-radius, 0)
        self._sleep_interruptible(interval / 2)

    def _run_move_to(self):
        x = self._config.get("move_x", 0)
        y = self._config.get("move_y", 0)
        smooth = self._config.get("move_smooth", False)
        click = self._config.get("move_click", False)

        if smooth:
            duration_s = self._config.get("move_duration_ms", 500) / 1000.0
            easing = self._config.get("move_easing", "linear")
            sx, sy = self._mouse.position
            steps = max(int(duration_s * 60), 1)
            dt = duration_s / steps
            for i in range(1, steps + 1):
                if not self._running:
                    return
                t = i / steps
                et = self._apply_easing(t, easing)
                nx = int(sx + (x - sx) * et)
                ny = int(sy + (y - sy) * et)
                self._mouse.position = (nx, ny)
                time.sleep(dt)
        else:
            self._mouse.position = (x, y)

        if click and self._running:
            btn_name = self._config.get("move_click_button", "left")
            btn = {"left": Button.left, "right": Button.right, "middle": Button.middle}.get(btn_name, Button.left)
            count = self._config.get("move_click_count", 1)
            self._mouse.click(btn, count)

    def _run_pattern(self):
        pattern = self._config.get("pattern_type", "circle")
        size = self._config.get("pattern_size", 50)
        speed = self._config.get("pattern_speed", 1.0)
        direction = self._config.get("pattern_direction", "cw")
        dir_sign = 1.0 if direction == "cw" else -1.0
        cx, cy = self._mouse.position

        if pattern == "circle":
            self._run_circle(cx, cy, size, speed, dir_sign)
        elif pattern == "square":
            self._run_square(cx, cy, size, speed)
        elif pattern == "triangle":
            self._run_triangle(cx, cy, size, speed)
        elif pattern == "zigzag":
            self._run_zigzag(cx, cy, size, speed)
        elif pattern == "figure8":
            self._run_figure8(cx, cy, size, speed, dir_sign)
        elif pattern == "spiral":
            end_radius = self._config.get("spiral_end_radius", 80)
            revolutions = self._config.get("spiral_revolutions", 3)
            self._run_spiral(cx, cy, speed, dir_sign, size, end_radius, revolutions)

    @staticmethod
    def _apply_easing(t: float, easing: str) -> float:
        if easing == "ease_in":
            return t * t
        elif easing == "ease_out":
            return 1 - (1 - t) ** 2
        elif easing == "ease_in_out":
            if t < 0.5:
                return 2 * t * t
            else:
                return 1 - 2 * (1 - t) ** 2
        return t  # linear

    def _interpolate_path(self, points: list[tuple[int, int]], speed: float):
        """Smoothly move through a list of (x,y) vertices at the given speed."""
        fps = 60
        dt = 1.0 / fps
        for i in range(len(points) - 1):
            if not self._running:
                return
            x0, y0 = points[i]
            x1, y1 = points[i + 1]
            dist = math.hypot(x1 - x0, y1 - y0)
            duration = max(dist / (speed * 200), dt)
            steps = max(int(duration * fps), 1)
            for s in range(1, steps + 1):
                if not self._running:
                    return
                t = s / steps
                nx = int(x0 + (x1 - x0) * t)
                ny = int(y0 + (y1 - y0) * t)
                self._mouse.position = (nx, ny)
                time.sleep(dt)

    def _run_circle(self, cx: int, cy: int, radius: int, speed: float, dir_sign: float):
        fps = 60
        dt = 1.0 / fps
        circumference = 2 * math.pi * radius
        duration = max(circumference / (speed * 200), 0.1)
        steps = max(int(duration * fps), 1)
        for i in range(steps):
            if not self._running:
                return
            angle = dir_sign * 2 * math.pi * i / steps
            nx = int(cx + radius * math.cos(angle))
            ny = int(cy + radius * math.sin(angle))
            self._mouse.position = (nx, ny)
            time.sleep(dt)
        # Snap to original center to prevent drift when looping
        # (the next cycle starts at cx + radius via i=0, same as the first cycle)
        if self._running:
            self._mouse.position = (cx, cy)

    def _run_square(self, ox: int, oy: int, size: int, speed: float):
        half = size // 2
        corners = [
            (ox - half, oy - half),
            (ox + half, oy - half),
            (ox + half, oy + half),
            (ox - half, oy + half),
            (ox - half, oy - half),
        ]
        self._interpolate_path(corners, speed)

    def _run_triangle(self, ox: int, oy: int, size: int, speed: float):
        h = int(size * math.sqrt(3) / 2)
        vertices = [
            (ox, oy - h // 2),
            (ox + size // 2, oy + h // 2),
            (ox - size // 2, oy + h // 2),
            (ox, oy - h // 2),
        ]
        self._interpolate_path(vertices, speed)

    def _run_zigzag(self, ox: int, oy: int, amplitude: int, speed: float):
        points = [(ox, oy)]
        num_zags = 6
        step_x = amplitude
        for i in range(num_zags):
            direction = 1 if i % 2 == 0 else -1
            points.append((ox + step_x * (i + 1), oy + amplitude * direction))
        # Append reversed path (excluding last point to avoid stutter) to bounce back
        points += list(reversed(points[:-1]))
        self._interpolate_path(points, speed)

    def _run_figure8(self, cx: int, cy: int, size: int, speed: float, dir_sign: float):
        fps = 60
        dt = 1.0 / fps
        duration = max(2 * math.pi * size / (speed * 200), 0.2)
        steps = max(int(duration * fps), 1)
        for i in range(steps):
            if not self._running:
                return
            t = dir_sign * 2 * math.pi * i / steps
            nx = int(cx + size * math.sin(t))
            ny = int(cy + size * math.sin(2 * t) / 2)
            self._mouse.position = (nx, ny)
            time.sleep(dt)
        # Snap to exact center to prevent drift when looping
        if self._running:
            self._mouse.position = (cx, cy)

    def _run_spiral(self, cx: int, cy: int, speed: float, dir_sign: float,
                    start_radius: int, end_radius: int, revolutions: int):
        fps = 60
        dt = 1.0 / fps
        total_angle = 2 * math.pi * revolutions
        avg_radius = (start_radius + end_radius) / 2
        arc_length = total_angle * avg_radius
        duration = max(arc_length / (speed * 200), 0.2)
        steps = max(int(duration * fps), 1)
        for i in range(steps):
            if not self._running:
                return
            t = i / steps
            angle = dir_sign * total_angle * t
            r = start_radius + (end_radius - start_radius) * t
            nx = int(cx + r * math.cos(angle))
            ny = int(cy + r * math.sin(angle))
            self._mouse.position = (nx, ny)
            time.sleep(dt)


# ── Action Constants ──────────────────────────────────────────

ACTION_NAMES: list[str] = ["Auto Click", "Hold", "Keyboard Macro", "Mouse Macro"]

ACTION_DESCRIPTIONS: dict[str, str] = {
    "Auto Click":      "Repeats press + release of the target at the set interval",
    "Hold":            "Holds the target down until toggled off",
    "Keyboard Macro":  "Plays a recorded macro sequence",
    "Mouse Macro":     "Mouse movement automation (jiggle, move, patterns)",
}

TARGET_MOUSE_BUTTONS: dict[str, Button | str] = {
    "Left Mouse":   Button.left,
    "Right Mouse":  Button.right,
    "Middle Mouse": Button.middle,
    "Scroll Up":    SCROLL_UP,
    "Scroll Down":  SCROLL_DOWN,
}

TARGET_NAMES: list[str] = list(TARGET_MOUSE_BUTTONS.keys())


def resolve_target(target_str: str) -> Button | Key | KeyCode | str | None:
    """Convert a target name string to a pynput Button, Key, KeyCode, or scroll sentinel.

    Checks mouse buttons / scroll sentinels first, then named keys, then single-char keys.
    Returns None on failure.
    """
    val = TARGET_MOUSE_BUTTONS.get(target_str)
    if val is not None:
        return val
    try:
        return Key[target_str]
    except (KeyError, AttributeError):
        pass
    if len(target_str) == 1:
        return KeyCode.from_char(target_str)
    return None


def hides_interval(action_type: str) -> bool:
    """Check if an action type should hide the interval controls."""
    return action_type in ("Hold", "Keyboard Macro", "Mouse Macro")


def create_action(
    action_type: str, mouse: MouseController, interval_ms: int,
    *, target_str: str = "Left Mouse", macro_steps: list | None = None, loop: bool = True,
    mouse_macro_config: dict | None = None,
) -> Action:
    """Factory: create the right Action subclass from action type and target."""
    if action_type == "Keyboard Macro":
        if not macro_steps:
            raise ValueError("Keyboard Macro action requires steps")
        return MacroAction(mouse, macro_steps, loop)

    if action_type == "Mouse Macro":
        if mouse_macro_config is None:
            raise ValueError("Mouse Macro action requires config")
        return MouseMacroAction(mouse, mouse_macro_config, loop)

    target = resolve_target(target_str)
    if target is None:
        # Fall back to left mouse if target can't be resolved
        target = Button.left

    keyboard = KeyboardController()

    if action_type == "Hold":
        return HoldAction(mouse, keyboard, target)

    # Auto Click
    return ClickAction(mouse, keyboard, target, max(interval_ms, 1) / 1000.0)
