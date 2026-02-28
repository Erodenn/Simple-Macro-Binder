"""Theme, color, and style configuration for Simple Macro Binder."""

import ctypes
import os
import sys
import tkinter as tk
from tkinter import ttk, font as tkfont

import ttkbootstrap as ttkb
from ttkbootstrap.style import StyleBuilderTTK
from PIL import Image, ImageDraw, ImageTk
from ttkbootstrap.tooltip import ToolTip as _ToolTipBase


# ── DPI scaling ──────────────────────────────────────────────

_DESIGN_DPI: int = 96  # baseline: 100% Windows scale


def _detect_dpi() -> int:
    """Read physical DPI via GDI GetDeviceCaps (LOGPIXELSX=88).

    Must run after SetProcessDpiAwareness(2) is called.
    Falls back to 96 on non-Windows or on any error.
    """
    try:
        hdc = ctypes.windll.gdi32.CreateDCW("DISPLAY", None, None, None)
        if not hdc:
            return _DESIGN_DPI
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        ctypes.windll.gdi32.DeleteDC(hdc)
        return int(dpi) if dpi > 0 else _DESIGN_DPI
    except Exception:
        return _DESIGN_DPI


_SYSTEM_DPI: int = _detect_dpi()
_SCALE_FACTOR: float = _SYSTEM_DPI / _DESIGN_DPI


def scale(n: int | float) -> int:
    """Scale a pixel/pt value by the detected DPI factor.

    Returns 0 if n == 0, otherwise at least 1.
    At 96 DPI (100% scale) scale(n) == n for all integers.
    """
    if n == 0:
        return 0
    return max(1, round(n * _SCALE_FACTOR))


# ── Color Constants ──────────────────────────────────────────


class Colors:
    ACTIVE = "#2ecc71"
    INACTIVE = "#e74c3c"
    DISABLED = "#555555"
    MUTED = "#888888"


class Spacing:
    PAD_X = scale(6)
    PAD_Y = scale(6)
    SECTION_Y = scale(10)


class Fonts:
    _family: str | None = None

    @classmethod
    def _detect(cls) -> str:
        if cls._family is None:
            available = tkfont.families()
            if "Roboto" in available:
                cls._family = "Roboto"
            elif "Segoe UI" in available:
                cls._family = "Segoe UI"
            else:
                cls._family = ttkb.Style().lookup(".", "font") or "TkDefaultFont"
        return cls._family

    _MAIN_PT: int = 11
    _SMALL_PT: int = 9

    @classmethod
    def main(cls) -> tuple[str, int]:
        return (cls._detect(), scale(cls._MAIN_PT))

    @classmethod
    def small(cls) -> tuple[str, int]:
        return (cls._detect(), scale(cls._SMALL_PT))


# ── Helpers ──────────────────────────────────────────────────


def get_frame_bg() -> str:
    """Return the current theme's frame background color."""
    return ttk.Style().lookup("TFrame", "background") or "#2b2b2b"


def apply_dark_title_bar(window) -> None:
    """Use Windows DWM API to enable dark mode on a window's title bar."""
    if sys.platform != "win32":
        return
    try:
        window.update()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        # Attribute 20 works on Win10 18985+ / Win11; fall back to 19 for older
        hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value),
        )
        if hr != 0:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value),
            )
        # Force Windows to redraw the title bar with the new attribute
        window.withdraw()
        window.deiconify()
    except Exception:
        pass  # Unsupported Windows version or missing DWM — silently skip


# ── Rounded button helpers ───────────────────────────────────


def _make_rounded_rect(w: int, h: int, r: int, fill: str) -> Image.Image:
    """Create a rounded rectangle RGBA image."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle([0, 0, w - 1, h - 1], r, fill=fill)
    return img


def _lighter(hex_color: str, amount: int = 25) -> str:
    """Lighten a hex color by an amount (0-255)."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    r = min(r + amount, 255)
    g = min(g + amount, 255)
    b = min(b + amount, 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def _darker(hex_color: str, amount: int = 30) -> str:
    """Darken a hex color by an amount (0-255)."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    r = max(r - amount, 0)
    g = max(g - amount, 0)
    b = max(b - amount, 0)
    return f"#{r:02x}{g:02x}{b:02x}"


# ── StyleBuilderTTK monkey-patch ─────────────────────────────
# Prevents ttkbootstrap from crashing on our custom "Round*" style names.

def _noop_builder(self, *_a, **_kw):
    pass

StyleBuilderTTK.create_round_button_style = _noop_builder  # type: ignore[attr-defined]
StyleBuilderTTK.create_roundoutline_button_style = _noop_builder  # type: ignore[attr-defined]


# ── Style configuration ─────────────────────────────────────


def configure_styles(style: ttkb.Style):
    """Configure all custom styles: rounded buttons, link buttons, widget overrides."""
    colors = style.colors
    radius = scale(8)
    # Image size for 9-slice; border = radius so corners don't stretch
    w, h = radius * 3, radius * 3
    border = (radius, radius, radius, radius)

    # Keep references to PhotoImages so they aren't garbage-collected
    _images: list[ImageTk.PhotoImage] = []

    # Use base ttk.Style methods to bypass ttkbootstrap's name interception
    _configure = ttk.Style.configure
    _map = ttk.Style.map
    base_font = style.lookup(".", "font")

    def _register(color_key: str, base_color: str, fg: str = "#ffffff"):
        """Create a rounded button style with normal/hover/pressed/disabled states."""
        normal = ImageTk.PhotoImage(_make_rounded_rect(w, h, radius, base_color))
        hover = ImageTk.PhotoImage(_make_rounded_rect(w, h, radius, _lighter(base_color)))
        pressed = ImageTk.PhotoImage(_make_rounded_rect(w, h, radius, _darker(base_color)))
        disabled = ImageTk.PhotoImage(_make_rounded_rect(w, h, radius, _lighter(base_color, 10)))
        _images.extend([normal, hover, pressed, disabled])

        el_name = f"round_{color_key}_border"
        style.element_create(
            el_name, "image", normal,
            ("pressed", "!disabled", pressed),
            ("active", "!disabled", hover),
            ("disabled", disabled),
            border=border, sticky="nsew",
        )

        style_name = f"{color_key}.Round.TButton"
        style.layout(style_name, [
            (el_name, {"sticky": "nsew", "children": [
                ("Button.padding", {"sticky": "nsew", "children": [
                    ("Button.label", {"sticky": ""}),
                ]}),
            ]}),
        ])
        _configure(style, style_name, foreground=fg, anchor="center", padding=(scale(4), scale(1)), borderwidth=0, font=base_font)
        _map(style, style_name, foreground=[("disabled", "#888888")])

    # Solid button variants
    _register("success", colors.success)
    _register("danger", colors.danger)
    _register("info", colors.info)
    _register("secondary", colors.secondary, fg="#dddddd")
    _register("primary", colors.primary)

    # Outline variant — transparent bg with colored border
    def _outline_img(bc: str, fill: str = "#00000000"):
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, w - 1, h - 1], radius, fill=fill, outline=bc, width=2)
        return img

    normal = ImageTk.PhotoImage(_outline_img(colors.fg))
    hover = ImageTk.PhotoImage(_outline_img(_lighter(colors.fg), fill=_darker(colors.fg, 50) + "40"))
    pressed = ImageTk.PhotoImage(_outline_img(_darker(colors.fg)))
    disabled = ImageTk.PhotoImage(_outline_img("#555555"))
    _images.extend([normal, hover, pressed, disabled])

    style.element_create(
        "round_outline_border", "image", normal,
        ("pressed", "!disabled", pressed),
        ("active", "!disabled", hover),
        ("disabled", disabled),
        border=border, sticky="nsew",
    )
    style.layout("Round.TButton", [
        ("round_outline_border", {"sticky": "nsew", "children": [
            ("Button.padding", {"sticky": "nsew", "children": [
                ("Button.label", {"sticky": ""}),
            ]}),
        ]}),
    ])
    _configure(style, "Round.TButton", foreground=colors.fg, anchor="center", padding=(scale(4), scale(1)), borderwidth=0, font=base_font)
    _map(style, "Round.TButton", foreground=[("disabled", "#555555")])

    # Store image refs on the style object to prevent GC
    style._round_btn_images = _images  # type: ignore[attr-defined]

    # ── Widget style overrides ──────────────────────────────
    FONT = Fonts.main()
    FONT_SMALL = Fonts.small()

    # Small link-style buttons for row actions (edit/remove)
    style.configure("info-link.TButton", padding=(scale(2), 0), borderwidth=0)
    style.configure("danger-link.TButton", padding=(scale(2), 0), borderwidth=0)

    # LabelFrame header font
    style.configure("TLabelframe.Label", font=FONT)
    style.configure("TLabelframe", borderwidth=1)

    # Combobox / Spinbox / Entry
    style.configure("TCombobox", padding=(scale(6), scale(4)))
    style.configure("TSpinbox", padding=(scale(6), scale(4)))
    style.configure("TEntry", padding=(scale(6), scale(4)))

    # Flash styles for required-field validation
    input_bg = style.lookup("TEntry", "fieldbackground") or "#4a4a4a"
    style._input_bg = input_bg  # used by flash_widgets() to restore
    _configure(style, "Flash.TEntry", fieldbackground=Colors.INACTIVE, padding=(scale(6), scale(4)))
    _map(style, "Flash.TEntry", fieldbackground=[
        ("readonly", Colors.INACTIVE), ("disabled", Colors.INACTIVE),
    ])
    _configure(style, "Flash.TSpinbox", fieldbackground=Colors.INACTIVE, padding=(scale(6), scale(4)))

    # Header row style
    style.configure("Header.TLabel", font=FONT_SMALL)

    # Compact tooltip style
    style.configure("tooltip.TLabel", font=FONT_SMALL, padding=scale(2))

    # Small checkbutton style
    style.configure("small.TCheckbutton", font=FONT_SMALL)


# ── Flash validation utility ─────────────────────────────────


def flash_widgets(
    host: tk.Misc,
    widgets: list[tk.Widget],
    pulses: int = 3,
    interval_ms: int = 150,
) -> None:
    """Flash widget backgrounds red to indicate empty required fields.

    Handles ttk.Entry (style swap), ttk.Spinbox (style swap), and
    tk.Frame / tk.Label (direct background config).
    """
    targets: list[tuple[tk.Widget, str, str]] = []  # (widget, set_cmd, restore_cmd)

    for w in widgets:
        if not w.winfo_viewable():
            continue
        if isinstance(w, ttk.Spinbox):
            orig_style = str(w.cget("style")) or "TSpinbox"
            targets.append((w, "Flash.TSpinbox", orig_style))
        elif isinstance(w, ttk.Entry):
            orig_style = str(w.cget("style")) or "TEntry"
            targets.append((w, "Flash.TEntry", orig_style))
        else:
            # tk.Frame, tk.Label, etc. — direct background
            try:
                orig_bg = w.cget("background")
            except tk.TclError:
                continue
            targets.append((w, Colors.INACTIVE, orig_bg))

    if not targets:
        return

    def _apply(flash_on: bool):
        for widget, flash_val, restore_val in targets:
            if isinstance(widget, (ttk.Entry, ttk.Spinbox)):
                widget.configure(style=flash_val if flash_on else restore_val)
            else:
                widget.configure(background=flash_val if flash_on else restore_val)

    def _pulse(remaining: int):
        if remaining <= 0:
            _apply(False)  # ensure restored
            return
        _apply(True)
        host.after(interval_ms, lambda: _off(remaining))

    def _off(remaining: int):
        _apply(False)
        host.after(interval_ms, lambda: _pulse(remaining - 1))

    _pulse(pulses)


# ── Icon loading ─────────────────────────────────────────────

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")

_icon_cache: dict[tuple[str, int, tuple | None], ImageTk.PhotoImage] = {}


def load_icon(filename: str, size: int) -> ImageTk.PhotoImage:
    """Load a PNG icon, resize to size×size, and return a PhotoImage.

    Results are cached to prevent garbage collection.
    """
    key = (filename, size, None)
    if key in _icon_cache:
        return _icon_cache[key]
    img = Image.open(os.path.join(ICON_DIR, filename)).resize(
        (size, size), Image.LANCZOS,
    )
    photo = ImageTk.PhotoImage(img)
    _icon_cache[key] = photo
    return photo


def load_tinted_icon(
    filename: str, size: int, color_rgb: tuple[int, int, int],
) -> ImageTk.PhotoImage:
    """Load a PNG icon, replace RGB channels with color_rgb, preserve alpha."""
    key = (filename, size, color_rgb)
    if key in _icon_cache:
        return _icon_cache[key]
    img = Image.open(os.path.join(ICON_DIR, filename)).resize(
        (size, size), Image.LANCZOS,
    ).convert("RGBA")
    r, g, b, a = img.split()
    tinted = Image.merge("RGBA", (
        r.point(lambda _: color_rgb[0]),
        g.point(lambda _: color_rgb[1]),
        b.point(lambda _: color_rgb[2]),
        a,
    ))
    photo = ImageTk.PhotoImage(tinted)
    _icon_cache[key] = photo
    return photo


# ── Status Dot Widget ────────────────────────────────────────


class StatusDot(tk.Canvas):
    """A small canvas-drawn circle used as a status indicator."""

    _SIZE = scale(12)
    _RADIUS = scale(4)

    def __init__(self, parent, **kwargs):
        bg = ttk.Style().lookup("TFrame", "background") or "#2b2b2b"
        super().__init__(
            parent, width=self._SIZE, height=self._SIZE,
            highlightthickness=0, borderwidth=0, bg=bg, **kwargs,
        )
        cx, cy = self._SIZE // 2, self._SIZE // 2
        r = self._RADIUS
        self._dot = self.create_oval(cx - r, cy - r, cx + r, cy + r)
        self._blink_on = False
        self.set_idle()

    def set_disabled(self):
        """Grey hollow dot."""
        self._blink_on = False
        self.itemconfig(self._dot, fill="", outline="#555555", width=scale(1.5))

    def set_idle(self):
        """Red filled dot."""
        self._blink_on = False
        self.itemconfig(self._dot, fill="#e74c3c", outline="#e74c3c", width=scale(1))

    def set_active(self):
        """Green blinking dot — toggles filled/hollow each call."""
        self._blink_on = not self._blink_on
        if self._blink_on:
            self.itemconfig(self._dot, fill="#2ecc71", outline="#2ecc71", width=scale(1))
        else:
            self.itemconfig(self._dot, fill="", outline="#2ecc71", width=scale(1.5))


# ── Topmost-aware ToolTip ────────────────────────────────────


class ToolTip(_ToolTipBase):
    """ToolTip subclass that renders above always-on-top windows with compact sizing."""

    def __init__(self, widget, text="widget info", padding=scale(2), **kwargs):
        kwargs.setdefault("wraplength", scale(200))
        super().__init__(widget, text=text, padding=padding, **kwargs)

    def show_tip(self, *args):
        super().show_tip(*args)
        if self.toplevel:
            self.toplevel.attributes("-topmost", True)
