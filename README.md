# Simple Macro Binder

A multi-binding mouse and keyboard automation tool for Windows. Auto-clicker, auto-hold, keyboard macros, mouse movement patterns, all triggered by global hotkeys and organized into switchable profiles.

Built with Python, ttkbootstrap, and pynput.

## Features

**Four action types, each targeting any mouse button, keyboard key, or scroll direction:**

- **Auto Click** repeats press+release of any target at a configurable interval. Works with mouse buttons, keyboard keys, and scroll wheel.
- **Hold** holds down any mouse button or keyboard key until toggled off.
- **Keyboard Macro** plays back a recorded sequence of key and mouse events with timing. Supports looping, manual step editing, and live recording.
- **Mouse Macro** automates mouse movement with multiple sub-modes: jiggle, move-to-position, and geometric patterns (circle, square, triangle, zigzag, figure-8, spiral).

**Profile system** for organizing bindings into named groups. Switch between profiles on the fly; each profile maintains its own set of bindings independently.

**Global hotkey triggers** using pynput, including mouse side buttons (Mouse4/Mouse5). A configurable kill-all hotkey stops every running action instantly.

**Toggle-based activation**: press the trigger key once to start an action, press it again to stop. No hold-to-activate.

## Install

### Binary (recommended)

Download `Simple.Macro.Binder.exe` from the [latest release](../../releases/latest) and run it. No installation or dependencies required.

Settings are stored in `%APPDATA%\SimpleMacroBinder\settings.json`.

**Note:** Windows Defender or other antivirus software may flag the exe because it uses global keyboard and mouse hooks (via pynput). This is a false positive. You can add an exception for the exe if needed.

### From source

Requires Windows and Python 3.10+.

```
pip install -r requirements.txt
python main.py
```

Dependencies: `pynput`, `ttkbootstrap`, `Pillow`

## Usage

1. Create a binding with the **+** button
2. Set a trigger key (click the capture field and press any key or mouse side button)
3. Choose an action type, configure the target and interval
4. Close the editor. The binding is now active.
5. Press the trigger key to start the action, press it again to stop.

Bindings, profiles, and settings are saved automatically on exit and loaded on startup. The default kill-all hotkey is **Escape**, which stops every running action at once.

## Project Structure

```
main.py          Entry point, App class, global input listeners, profile UI
actions.py       Action base class and all action implementations
models.py        Binding, Profile, BindingManager, MacroStep data classes
dialogs.py       Binding editor, macro recorder, hotkey capture widgets
binding_row.py   Individual binding row UI component
theme.py         Colors, fonts, spacing, dark title bar, rounded button styles
```

## License

[MIT](LICENSE)
