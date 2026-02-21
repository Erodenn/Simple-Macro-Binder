# SimpleMacroBinder

A multi-binding mouse/keyboard automation tool (auto-clicker / auto-hold / keyboard macro / mouse macro) with a ttkbootstrap GUI, global hotkey triggers, and a profile system.

## How to Run

- `pip install -r requirements.txt` (dependencies: `pynput`, `ttkbootstrap`, `Pillow`)
- `python main.py`

## Architecture

### File Responsibilities

- **main.py** — Entry point, `App` class, tkinter GUI, global input listeners (keyboard + mouse), settings persistence/migration, `BindingRow` widget, profile UI, rounded button style registration (`configure_rounded_styles`)
- **actions.py** — `Action` ABC and concrete subclasses (`ClickAction`, `HoldAction`, `MacroAction`, `MouseMacroAction`), `SCROLL_UP`/`SCROLL_DOWN` sentinels, `ACTION_NAMES`/`ACTION_DESCRIPTIONS`/`TARGET_MOUSE_BUTTONS` constants, `resolve_target()`, `create_action` factory
- **models.py** — `MacroStep`/`Macro` data classes, `Binding` dataclass (trigger/action_type/interval_ms/action_target/macro_steps + mouse macro fields), `Profile` dataclass, `BindingManager` (CRUD, toggle dispatch, start/stop lifecycle)
- **dialogs.py** — `HotkeyCapture` widget, `BindingEditor` modal (create/edit a binding with target selector, interval presets, inline macro recording), `MacroStepEditor`/`MacroRecorder`/`StepEditorDialog` modals

### Data Flow

1. `pynput` keyboard/mouse listeners in `main.py` fire on global key/button press
2. `App._dispatch()` normalizes the key name, checks kill-all hotkey, then calls `BindingManager.on_trigger()`
3. `BindingManager._toggle()` starts or stops the matching binding's `Action`
4. `Action` subclasses run on daemon threads (`ClickAction`, `MacroAction`, `MouseMacroAction`) or inline (`HoldAction`)
5. `ClickAction`/`HoldAction` accept any mouse button, keyboard key, or scroll sentinel as a target (dispatched via `isinstance` check)
6. Status dots poll every 100ms via `App._poll_status()`

### Action System

Four versatile action types:

- **Auto Click** — repeats press+release of any mouse button, keyboard key, or scroll wheel at a set interval
- **Hold** — holds any mouse button or keyboard key down until toggled off
- **Keyboard Macro** — plays a recorded sequence of key/mouse events with timing (formerly "Macro")
- **Mouse Macro** — mouse movement automation with sub-modes: Jiggle, Move to Position, Pattern (Circle, Square, Triangle, Zigzag, Figure-8, Spiral), and Path Recording (stub)

`resolve_target(target_str)` converts a target name string (e.g. "Left Mouse", "Scroll Up", "a", "space") to a pynput `Button`/`Key`/`KeyCode` or scroll sentinel string. Falls back to `Button.left` if unresolvable.

`SCROLL_UP`/`SCROLL_DOWN` are string sentinels used as click targets for scroll wheel automation.

### Profile System

Bindings are organized into `Profile` objects (name + id + binding list). The UI provides a combobox + New/Rename/Delete buttons. Switching profiles stops all active actions and rebuilds the binding row UI. At least one profile must exist at all times.

### Inline Macros

Macro steps are stored directly on each `Binding` (`macro_steps: list[MacroStep]`). There is no shared macro library — each macro binding owns its own step list. The `MacroRecorder` and `MacroStepEditor` dialogs write directly to the binding's steps.

### Settings

- Stored at `settings.json` in the script directory
- Saved on window close; loaded on startup
- Format:
  ```json
  {
    "profiles": [{"name": "Default", "id": "...", "bindings": [...]}],
    "active_profile": "profile_id",
    "kill_all_hotkey": "Escape",
    "always_on_top": true
  }
  ```
- `_migrate_settings()` handles forward-only migration from old formats (flat binding list, old action type names like "Left Click"/"Right Hold"/"Macro", separate macros list with `macro_name` references → inlined `macro_steps`)

### Rounded Button Styles

`configure_rounded_styles(style)` in `main.py` generates PIL-based 9-slice rounded rectangle images and registers custom ttk element styles (`RoundSuccess.TButton`, `RoundDanger.TButton`, etc.). Uses `ttk.Style.configure` (not `ttkb.Style.configure`) to bypass ttkbootstrap's style name interception. Image references are stored on the style object to prevent garbage collection.

## Extension Pattern: Adding a New Action Type

1. In `actions.py`: create a new `Action` subclass (implement `start`, `stop`, `is_running`)
2. In `actions.py`: add the display name to `ACTION_NAMES` list and `ACTION_DESCRIPTIONS` dict
3. In `actions.py`: handle the new type in `create_action()` factory
4. In `dialogs.py`: update `BindingEditor._on_action_changed()` to show/hide relevant panels for the new type

## Key Design Decisions

- **Toggle-based bindings** — pressing a trigger key starts the action; pressing it again stops it (no hold-to-activate)
- **Versatile targets** — `ClickAction`/`HoldAction` accept `Button | Key | KeyCode | str` via `isinstance` dispatch; any mouse button, keyboard key, or scroll direction can be a target
- **DPI awareness** — `ctypes.windll.shcore.SetProcessDpiAwareness(2)` called at top of `main.py` before pynput imports to fix coordinate mismatch on scaled displays
- **Mouse Macro sub-modes** — `MouseMacroAction` dispatches to jiggle/move_to/pattern runners; all sub-mode config stored as flat fields on `Binding` and passed as a dict to the action
- **pynput for input** — global keyboard + mouse listeners; runs as daemon threads
- **ttkbootstrap GUI** — "darkly" theme with custom PIL-rendered rounded buttons; dark title bar via Windows DWM API (`apply_dark_title_bar`)
- **Separate mouse listener** — required because tkinter `<Key>` bindings don't capture mouse side buttons (X1/X2); `pynput.mouse.Listener` fills that gap
- **HotkeyCapture widget** — reused for trigger capture, kill-all hotkey, and target key capture; `App._hotkey_captures` list tracks all active captures so the mouse listener can route side button presses to whichever capture is listening
- **Conflict checking** — `BindingManager.has_conflict()` prevents duplicate triggers; editor also checks against the kill-all hotkey
- **Profile-scoped bindings** — `BindingManager.set_bindings()` swaps the binding list reference when switching profiles; `remove()` uses in-place `list.pop(i)` to preserve the shared Profile reference
- **Inline macros** — macro steps stored directly on `Binding.macro_steps`, no separate library; simplifies the data model and UI
- **Settings migration** — `_migrate_settings()` is forward-only and handles: flat→profile format, old action type names→new names (including "Macro"→"Keyboard Macro"), `macro_name` references→inlined `macro_steps`

## Gotchas

- **Pyright false positives** — sibling imports (`from actions import ...`), ttkbootstrap `bootstyle` param, and `isinstance`-guarded union type dispatch all trigger Pyright warnings that are correct at runtime
- **ttkbootstrap style name interception** — `ttkb.Style.configure()` parses style names and tries to call builder methods; custom styles must use `ttk.Style.configure()` (the base class method) to avoid `AttributeError`
- **Mouse side buttons (Mouse4/Mouse5)** — only X1 and X2 are captured via `pynput.mouse.Listener`; standard left/middle/right clicks are intentionally ignored (they would conflict with click actions)
- **HotkeyCapture mouse routing** — mouse side button presses during hotkey capture are routed from `App._on_global_mouse` into `HotkeyCapture.on_mouse_button()` via `root.after(0, ...)` to stay on the tkinter thread
- **Key normalization** — `KEY_ALIASES` in `main.py` maps platform-specific key names (e.g. `Return` → `enter`); triggers are compared case-insensitively
- **Interval minimum** — `create_action` clamps interval to at least 1ms (`max(interval_ms, 1)`)
- **Dark title bar** — `apply_dark_title_bar` must call `window.update()` before `winfo_id()`, tries DWM attribute 20 then 19, and forces redraw via `withdraw()`/`deiconify()`
- **Modal centering** — `_center_on_parent()` in `dialogs.py` positions all modals centered on their parent; `_apply_dark_title_bar` and centering are called after UI is fully built
- **No package/`__init__.py`** — flat module structure, run directly with `python main.py`
