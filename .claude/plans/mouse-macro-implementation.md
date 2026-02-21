# Implementation Plan: Mouse Macro Feature

## Context

SimpleMacroBinder currently has three action types: Auto Click, Hold, and Macro. We're adding comprehensive mouse movement automation via a new "Mouse Macro" action type with sub-modes (Jiggle, Move to Position, Pattern, Path Recording stub). We're also renaming "Macro" to "Keyboard Macro", adding scroll targets to Auto Click, fixing DPI awareness, and handling multi-monitor coordinates.

## Implementation Order

Changes have a dependency chain — each step builds on the previous:

```
1. main.py      — DPI awareness (must be before any pynput usage)
2. actions.py   — Rename constants, scroll sentinels, MouseMacroAction class
3. models.py    — New Binding fields, serialization, BindingManager wiring
4. main.py      — Settings migration for "Macro" → "Keyboard Macro"
5. binding_row.py — Compact display strings
6. dialogs.py   — Mouse Macro panel in BindingEditor (largest change)
7. Test & verify
```

---

## Step 1: main.py — DPI Awareness

**Location:** Top of file, after stdlib imports, before pynput imports (before line 12)

Insert:
```python
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
except Exception:
    pass
```

This fixes coordinate mismatch between pynput listener (physical pixels) and controller (logical pixels) on scaled displays. Also fixes existing Macro mouse_click playback.

---

## Step 2: actions.py — Core Changes

### 2a. Rename "Macro" → "Keyboard Macro"

| Location | Change |
|---|---|
| `ACTION_NAMES` (line 179) | `"Macro"` → `"Keyboard Macro"` |
| `ACTION_DESCRIPTIONS` (line 184) | Key `"Macro"` → `"Keyboard Macro"` |
| `hides_interval()` (line 216) | `== "Macro"` → `== "Keyboard Macro"`, also add `== "Mouse Macro"` |
| `create_action()` (line 224) | `== "Macro"` → `== "Keyboard Macro"` |

### 2b. Add "Mouse Macro" to constants

- Append `"Mouse Macro"` to `ACTION_NAMES`
- Add `"Mouse Macro": "Mouse movement automation (jiggle, move, patterns)"` to `ACTION_DESCRIPTIONS`
- `hides_interval()`: return True for `"Mouse Macro"` (interval is configured per sub-mode inside the panel)

### 2c. Scroll targets

Add sentinel constants and expand `TARGET_MOUSE_BUTTONS`:

```python
SCROLL_UP = "__scroll_up__"
SCROLL_DOWN = "__scroll_down__"

TARGET_MOUSE_BUTTONS: dict[str, Button | str] = {
    "Left Mouse": Button.left,
    "Right Mouse": Button.right,
    "Middle Mouse": Button.middle,
    "Scroll Up": SCROLL_UP,
    "Scroll Down": SCROLL_DOWN,
}
```

Update `resolve_target()` return type to `Button | Key | KeyCode | str | None` (strings pass through for scroll sentinels).

Update `ClickAction._loop()` to branch on scroll sentinels before the isinstance check:
- `SCROLL_UP` → `mouse.scroll(0, 1)`
- `SCROLL_DOWN` → `mouse.scroll(0, -1)`

Update `ClickAction.__init__` target type hint to accept `str` as well.

### 2d. New MouseMacroAction class

Insert after `MacroAction` class, before the constants block. Implements `Action` ABC with daemon thread.

**Structure:**
- `__init__(self, mouse, config: dict, loop: bool)` — config dict holds all sub-mode settings
- `_run()` — dispatches to sub-mode runner based on `config["mouse_move_type"]`
- `_run_jiggle()` — `mouse.move(radius, 0)` → sleep → `mouse.move(-radius, 0)` → sleep. Always loops.
- `_run_move_to()` — Smooth: interpolate from current position to (x,y) at ~60 steps/sec using easing. Instant: set position directly. Optional click on arrival. Auto-stops unless looping.
- `_run_pattern()` — Dispatches to specific pattern runner. All patterns start from current cursor position.
- `_apply_easing(t, easing)` — Static method. Linear: `t`, Ease In: `t²`, Ease Out: `1-(1-t)²`, Ease In-Out: piecewise quadratic.
- `_interpolate_path(points, speed)` — Shared helper for smooth edge tracing. Given a list of (x,y) vertices, smoothly interpolates between them at the given speed. Used by Square, Triangle, Zigzag.
- `_sleep_interruptible(duration)` — Chunked sleep (50ms chunks) checking `_running` between chunks.

**Pattern runners** (all use smooth interpolation, `speed` parameter controls trace rate):
- `_run_circle(cx, cy, radius, speed, dir_sign)` — sin/cos loop, ~60 position updates per second
- `_run_square(ox, oy, size, speed)` — 4 edges, smooth interpolation along each edge via `_interpolate_path`
- `_run_triangle(ox, oy, size, speed)` — 3 edges, equilateral, smooth interpolation
- `_run_zigzag(ox, oy, amplitude, speed)` — Triangular wave, smooth interpolation between peaks
- `_run_figure8(cx, cy, size, speed, dir_sign)` — Lissajous curve (2:1 frequency ratio)
- `_run_spiral(cx, cy, speed, dir_sign)` — Expanding radius from start_radius to end_radius over N revolutions

### 2e. Update create_action() factory

Add `mouse_macro_config: dict | None = None` parameter. Add branch:
```python
if action_type == "Mouse Macro":
    return MouseMacroAction(mouse, mouse_macro_config, loop)
```

---

## Step 3: models.py — Data Model

### 3a. New Binding fields (after `macro_steps` field, line 123)

```python
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
```

Note: `jiggle_interval_ms` is separate from the main `interval_ms` because the interval frame is hidden for Mouse Macro — the jiggle sub-panel has its own interval control.

### 3b. Binding.to_dict() — line 134

- Change `== "Macro"` to `== "Keyboard Macro"`
- Add `elif self.action_type == "Mouse Macro":` block serializing all mouse macro fields + `loop`

### 3c. Binding.from_dict() — line 139

- Add `.get()` calls for all new fields with matching defaults

### 3d. Binding.format_action() — line 153

- `"Keyboard Macro"` → `f"Keyboard Macro ({n} step{'s' if n != 1 else ''})"`
- `"Mouse Macro"` → `f"Mouse Macro ({self.mouse_move_type.replace('_', ' ').title()})"`

### 3e. BindingManager.start_binding() — line 272

- Change guard `== "Macro"` to `== "Keyboard Macro"`
- Add guard: `if binding.action_type == "Mouse Macro" and binding.mouse_move_type == "path": return` (stub)
- Build config dict from binding fields when `action_type == "Mouse Macro"`, pass as `mouse_macro_config` to `create_action()`

---

## Step 4: main.py — Settings Migration

### 4a. _OLD_ACTION_MIGRATION (line 50)

Add entry:
```python
"Macro": ("Keyboard Macro", "Left Mouse"),
```

The existing `_migrate_binding_dict()` will pick this up and rename `action_type` in old settings.

---

## Step 5: binding_row.py — Compact Display

### _format_action_compact() — line 128

- Change `== "Macro"` to `== "Keyboard Macro"`, display as `"KbMacro ({step_count})"`
- Add `elif action_type == "Mouse Macro":` → `f"Mouse ({self.binding.mouse_move_type})"`

---

## Step 6: dialogs.py — Mouse Macro Panel

This is the largest change. All within the `BindingEditor` class.

### 6a. _build_ui() — New Mouse Macro panel

Insert after the existing macro panel (after ~line 815), before the warning label.

**`self._mm_panel` (LabelFrame "Mouse Macro")** containing:

1. **Sub-mode selector row**: Label "Mode:" + Combobox with values `["Jiggle", "Move to Position", "Pattern", "Path (Coming Soon)"]`. Variable: `_mm_mode_var`.

2. **Jiggle sub-frame** (`_mm_jiggle_frame`):
   - Radius spinbox (1-500, default 5)
   - Interval spinbox in ms (1-86400000, default 1000) + human-readable label

3. **Move to Position sub-frame** (`_mm_move_frame`):
   - X spinbox (`from_=-99999, to=99999`) — negative values for left-of-primary monitors
   - Y spinbox (`from_=-99999, to=99999`)
   - "Pick from Screen" button (optional enhancement — captures current mouse position on click)
   - Smooth movement checkbox
   - Duration spinbox (shown when smooth=True, 50-30000ms, default 500)
   - Easing dropdown (shown when smooth=True, values: Linear/Ease In/Ease Out/Ease In-Out)
   - "Click on arrival" checkbox
   - Click detail sub-frame (shown when click=True): button dropdown (left/right/middle) + count spinbox (1-10)

4. **Pattern sub-frame** (`_mm_pattern_frame`):
   - Pattern type dropdown: Circle, Square, Triangle, Zigzag, Figure-8, Spiral
   - Size/radius spinbox (1-2000, default 50)
   - Speed spinbox (0.1-10.0, default 1.0)
   - Direction radios: CW / CCW (shown for Circle, Figure-8, Spiral)
   - Spiral extras frame (shown when pattern=Spiral): end radius spinbox, revolutions spinbox

5. **Path sub-frame** (`_mm_path_frame`):
   - Label: "Path recording coming in a future update"
   - Disabled record button placeholder

6. **Loop checkbox** (shared, shown for Move to Position and Pattern sub-modes)

### 6b. New internal callbacks

- `_on_mm_mode_changed()` — Shows/hides sub-frames based on selected mode. Maps display names to internal values ("Jiggle"→"jiggle", "Move to Position"→"move_to", "Pattern"→"pattern", "Path"→"path").
- `_on_mm_smooth_changed()` — Shows/hides duration + easing when smooth is toggled
- `_on_mm_click_changed()` — Shows/hides click detail frame
- `_on_mm_pattern_changed()` — Shows/hides spiral extras + direction radios based on pattern type

### 6c. _on_action_changed() — line 924

- Change `== "Macro"` to `== "Keyboard Macro"`
- Add `if action == "Mouse Macro": self._mm_panel.grid() else: self._mm_panel.grid_remove()`

### 6d. _get_action_target() — line 1000

- Change `== "Macro"` to include `"Keyboard Macro"` and `"Mouse Macro"` (both return dummy "Left Mouse")

### 6e. _validate() — line 963

- No additional validation needed for Mouse Macro beyond existing trigger checks
- Path sub-mode will be blocked from starting by the BindingManager guard, not the dialog

### 6f. _ok() — line 1010

- Change Macro validation block to check `"Keyboard Macro"`
- Add Mouse Macro field extraction: read all `_mm_*_var` values, write to binding via `_write_mm_fields_to_binding()` helper
- Helper method `_write_mm_fields_to_binding(self, b: Binding)` sets all mouse macro fields from UI variables

---

## Verification Plan

1. **Launch app**: `python main.py` — verify it starts without errors
2. **DPI check**: Verify no coordinate issues on scaled displays
3. **Rename check**: Existing "Macro" bindings should load as "Keyboard Macro" via migration
4. **Auto Click scroll**: Create a binding with "Scroll Up" or "Scroll Down" target, verify scrolling works at interval
5. **Mouse Macro — Jiggle**: Create binding, trigger it, verify cursor jiggles, trigger again to stop
6. **Mouse Macro — Move to Position**: Test instant move, smooth move with each easing, click on arrival, negative coordinates
7. **Mouse Macro — Pattern**: Test each of the 6 patterns, verify smooth edge tracing, verify speed parameter works, verify CW/CCW
8. **Mouse Macro — Path**: Verify stub UI shows placeholder, binding cannot start
9. **Settings persistence**: Create a Mouse Macro binding, close app, reopen — verify all settings load correctly
10. **Kill-all hotkey**: Verify it stops Mouse Macro actions
11. **Profile switching**: Verify Mouse Macro bindings survive profile switch
12. **Strip mode**: Verify compact display strings for new action types
