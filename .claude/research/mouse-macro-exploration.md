# Mouse Macro Exploration

**Date:** 2026-02-21

## Summary

Adding a "Mouse Macro" action type to SimpleMacroBinder for comprehensive mouse movement automation. Also renaming "Macro" to "Keyboard Macro" and adding scroll targets to Auto Click.

---

## Changes Overview

| Change | Scope |
|---|---|
| Rename "Macro" -> "Keyboard Macro" | String change + settings migration |
| New "Mouse Macro" action type | Jiggle, Move to Position, Pattern, Path Recording (stubbed) |
| Scroll targets in Auto Click | Add Scroll Up/Down to existing target system |
| DPI awareness fix | `SetProcessDpiAwareness(2)` at startup |
| Multi-monitor coordinate handling | Unified virtual desktop coords, screen bounds detection |

## Mouse Macro Sub-modes

### Jiggle
- Anti-idle, small repeated movements
- Config: radius, interval
- Implementation: `mouse.move(N, 0)` -> sleep -> `mouse.move(-N, 0)` -> sleep

### Move to Position
- Smooth or instant move to (x, y) with easing, optional click on arrival (toggle)
- Config: x, y, smooth toggle, duration, easing preset, click toggle (button + count)
- Easing presets: Linear, Ease In, Ease Out, Ease In-Out (all quadratic)
- Auto-stops after arrival (like non-looping macro), optional loop mode

### Pattern
Preset geometric shapes, all starting from current mouse position as center point.

| Pattern | Parameters | Math |
|---|---|---|
| Circle | radius, speed, direction (CW/CCW) | sin/cos |
| Square | size, speed | 4 line segments |
| Triangle | size, speed | 3 line segments |
| Zigzag | amplitude, width, repetitions | triangular wave |
| Figure-8 | radius, speed | Lissajous curve (2:1 frequency ratio) |
| Spiral | start radius, end radius, revolutions, speed | expanding/contracting sin/cos |

Shared parameters: speed (duration per cycle), loop (count or infinite).

### Path Recording (Deferred)
- Record and replay full mouse movement + clicks
- Data structure: `mouse_path: list[dict]` with x, y, timestamp
- UI: stubbed with disabled record button or "Coming soon"
- Implementation deferred to future update

## Auto Click Scroll Expansion

Add `Scroll Up` / `Scroll Down` as target options in `TARGET_MOUSE_BUTTONS` alongside Left/Right/Middle Mouse. `ClickAction._loop()` branches to call `mouse.scroll(0, dy)` instead of `mouse.click()`. Interval controls repeat rate naturally. ~15 lines of code.

## Technical Details

### pynput Mouse Controller
- `mouse.position = (x, y)` — absolute move (instant teleport)
- `mouse.move(dx, dy)` — relative move (instant)
- `mouse.scroll(dx, dy)` — scroll wheel
- `mouse.click(button, count)` — click
- `mouse.press(button)` / `mouse.release(button)` — hold
- **No built-in smooth movement** — must manually interpolate with a step loop

### Smooth Movement
- ~50 steps at 5ms delay = 250ms total, ~200 FPS equivalent
- Human perception needs ~60+ updates/sec for smooth appearance
- Runs naturally on daemon threads like existing ClickAction

### Easing Presets

| Preset | Formula (t = 0->1) | Feel |
|---|---|---|
| Linear | `t` | Constant speed |
| Ease In | `t^2` | Slow start, accelerates |
| Ease Out | `1 - (1-t)^2` | Fast start, decelerates |
| Ease In-Out | Piecewise quadratic | Slow at both ends |

### DPI Awareness (Critical)
On Windows with display scaling != 100%:
- pynput listener returns physical (unscaled) pixel coordinates
- pynput controller works in scaled (logical) coordinates
- Recorded coordinates will be wrong on playback without fix

**Fix:** Call once at startup before any pynput usage:
```python
import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
```

This also fixes the existing Macro mouse_click step playback.

### Multi-Monitor
- pynput uses unified virtual desktop coordinates
- Primary monitor top-left = (0, 0)
- Monitors to the left/above have negative coordinates (user's setup: primary + left secondary)
- Screen bounds via `ctypes.windll.user32.GetSystemMetrics`:
  - `SM_XVIRTUALSCREEN` (76) / `SM_YVIRTUALSCREEN` (77) — virtual desktop origin
  - `SM_CXVIRTUALSCREEN` (78) / `SM_CYVIRTUALSCREEN` (79) — virtual desktop size
- Coordinate inputs must accept negative values
- Pattern movements should clamp to virtual desktop bounds

### Sleep Precision on Windows
- `time.sleep()` historically ~15ms granularity, Python 3.11+ improved
- For 5ms intervals (mouse animation), `time.sleep` is accurate enough on modern Python
- Busy-wait with `time.perf_counter()` available for sub-ms precision if needed

## Architecture Decisions

- **Single action type with sub-modes** — one `MouseMacroAction` class, sub-mode selector in BindingEditor panel, internal dispatch based on config
- **All patterns relative to current position** — no absolute coordinate config for patterns, they start where the cursor is
- **Move to Position is the precision tool** — covers both "just move" and "move + click" via toggle
- **Scroll lives in Auto Click** — natural fit, interval controls repeat, minimal code change
- **No pyautogui dependency** — pynput handles everything, manual interpolation for smooth movement

## Integration Touch Points

| File | Changes |
|---|---|
| `actions.py` | `MouseMacroAction` subclass, scroll handling in `ClickAction`, constants, factory |
| `models.py` | New `Binding` fields for mouse macro config, serialization, format methods |
| `dialogs.py` | Mouse Macro panel in `BindingEditor` with sub-mode selector and dynamic sub-panels |
| `binding_row.py` | Compact display string for Mouse Macro |
| `main.py` | DPI awareness call, "Macro" -> "Keyboard Macro" migration, scroll targets |

## Sources
- [pynput Mouse Controller docs](https://pynput.readthedocs.io/en/latest/mouse.html)
- [pynput DPI scaling issue #153](https://github.com/moses-palmer/pynput/issues/153)
- [pynput multi-monitor issue #350](https://github.com/moses-palmer/pynput/issues/350)
- [Win32 GetSystemMetrics](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getsystemmetrics)
- [SendInput / MOUSEINPUT docs](https://learn.microsoft.com/en-us/windows/win32/api/winuser/ns-winuser-mouseinput)
- [PyAutoGUI easing reference](https://pyautogui.readthedocs.io/en/latest/mouse.html)
