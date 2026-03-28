# =============================================================================
#  fl_discord_rpc.py — FL Studio Discord Rich Presence
#  Standalone script. Convert to .exe with:
#      pip install pyinstaller
#      pyinstaller --onefile --noconsole --icon=icon.ico fl_discord_rpc.py
#
#  No FL Studio scripts, no loopMIDI, no manual installs.
#  Just run it and it lives in your system tray.
# =============================================================================

DISCORD_CLIENT_ID = "YOUR_CLIENT_ID_HERE"  # <-- paste your Discord App ID here
VERSION = "1.2.0"
GITHUB_REPO = "absxl/FL-Discord"

LARGE_IMAGE = "fl_logo"  # art asset key you uploaded to Discord dev portal
SMALL_IMAGE_PLAY = "icon_play"
SMALL_IMAGE_PAUSE = "icon_pause"
SMALL_IMAGE_REC = "icon_record"

POLL_INTERVAL = 1.0  # seconds between FL Studio window checks
CLEAR_AFTER = 10.0  # seconds after FL closes before presence clears

# =============================================================================
#  Bootstrap — silently install missing packages before anything else imports
# =============================================================================
import os
import subprocess
import sys


def _pip_install(pkg, import_name=None):
    import_name = import_name or pkg
    try:
        __import__(import_name)
        return True
    except ImportError:
        pass
    print(f"Installing {pkg}...")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", pkg, "--quiet", "--user"],
        capture_output=True,
    )
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


# Ensure all deps exist before the real imports below
for _pkg, _imp in [
    ("pypresence", "pypresence"),
    ("pystray", "pystray"),
    ("Pillow", "PIL"),
    ("pywin32", "win32gui"),
    ("keyboard", "keyboard"),
]:
    if not _pip_install(_pkg, _imp):
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            f"Failed to install required package: {_pkg}\n"
            "Please run:  pip install " + _pkg,
            "FL Discord RPC — Setup Error",
            0x10,
        )
        sys.exit(1)

# =============================================================================
#  Real imports (all guaranteed to be installed now)
# =============================================================================
import ctypes
import logging
import re
import struct
import threading
import time
from ctypes import wintypes

import psutil
import pystray
import win32api
import win32con
import win32gui
import win32process
from PIL import Image, ImageDraw
from pypresence import DiscordNotFound, InvalidID, InvalidPipe, Presence

try:
    import keyboard

    HAS_KEYBOARD = True
except:
    HAS_KEYBOARD = False

# =============================================================================
#  Logging (to file in %APPDATA%)
# =============================================================================
_log_dir = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "FLDiscordRPC")
os.makedirs(_log_dir, exist_ok=True)
_config_file = os.path.join(_log_dir, "config.json")
_log_file = os.path.join(_log_dir, "fl_discord_rpc.log")


def _check_log_size():
    try:
        if os.path.exists(_log_file):
            size = os.path.getsize(_log_file)
            if size > 1024 * 1024:
                os.remove(_log_file)
                log.info("Log file deleted (exceeded 1MB)")
    except:
        pass


_check_log_size()

logging.basicConfig(
    filename=_log_file,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("fl_rpc")
log.info("=" * 60)
log.info("FL Discord RPC v1.0 starting...")
log.info("Log file: %s", _log_file)

# =============================================================================
#  Config persistence
# =============================================================================
import json

STATUS_PRESETS = [
    "Mixing",
    "Mastering",
    "Sound Design",
    "Arranging",
    "Producing",
]


def load_config():
    try:
        with open(_config_file, "r") as f:
            data = json.load(f)
            log.debug("Configuration loaded from %s: %s", _config_file, data)
            return data
    except FileNotFoundError:
        log.debug("No configuration file found, using defaults")
        return {}
    except json.JSONDecodeError as e:
        log.warning("Failed to parse config file: %s", e)
        return {}
    except Exception as e:
        log.warning("Failed to load config: %s", e)
        return {}


def get_all_statuses():
    config = load_config()
    return STATUS_PRESETS + config.get("custom_statuses", [])[:3]


def save_config(new_config):
    try:
        existing = load_config()
        existing.update(new_config)
        with open(_config_file, "w") as f:
            json.dump(existing, f, indent=2)
        log.debug("Configuration saved to %s: %s", _config_file, new_config)
    except Exception as e:
        log.error("Failed to save config: %s", e)


def _get_startup_path():
    import winreg

    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_READ,
    )
    try:
        value, _ = winreg.QueryValueEx(key, "FLDiscordRPC")
        winreg.CloseKey(key)
        log.debug("Startup entry found: %s", value)
        return True
    except FileNotFoundError:
        winreg.CloseKey(key)
        log.debug("No startup entry found")
        return False
    except Exception as e:
        winreg.CloseKey(key)
        log.warning("Error checking startup: %s", e)
        return False


def _set_startup(enable):
    import winreg

    log.info("Setting run at startup: %s", "enabled" if enable else "disabled")
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_WRITE,
    )
    try:
        if enable:
            exe_path = sys.executable
            script_path = os.path.abspath(__file__)
            startup_cmd = f'"{exe_path}" "{script_path}"'
            winreg.SetValueEx(key, "FLDiscordRPC", 0, winreg.REG_SZ, startup_cmd)
            log.info("Startup enabled successfully. Command: %s", startup_cmd)
        else:
            try:
                winreg.DeleteValue(key, "FLDiscordRPC")
                log.info("Startup disabled successfully")
            except FileNotFoundError:
                log.debug("Startup entry did not exist")
        winreg.CloseKey(key)
    except PermissionError as e:
        log.error(
            "Permission denied when setting startup. Run as administrator may be required: %s",
            e,
        )
        winreg.CloseKey(key)
    except Exception as e:
        log.error("Failed to set startup: %s", e)
        winreg.CloseKey(key)


# =============================================================================
#  FL Studio window reader
#  Title format: "FL Studio 21 - <Username> - <ProjectName>"
#  or just:      "FL Studio 21 - <Username>"  (no project loaded)
# =============================================================================

FL_TITLE_RE = re.compile(
    r"(.+?)\s*-\s*FL Studio",  # "ProjectName - FL Studio 21"
    re.IGNORECASE,
)


def _find_fl_window():
    """Return (hwnd, title) for the FL Studio main window, or (None, None)."""
    result = [None, None]

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if " - FL Studio" in title:
            log.debug("Found FL Studio window: '%s'", title)
            result[0] = hwnd
            result[1] = title

    win32gui.EnumWindows(_cb, None)
    return result[0], result[1]


def _get_fl_pid(hwnd) -> int | None:
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return None


def _read_fl_state(hwnd, title: str) -> dict:
    m = FL_TITLE_RE.match(title.strip())
    project = (m.group(1) or "").strip() if m else ""
    if not project:
        project = "Unnamed"
        log.debug("No project name found in title: '%s'", title)
    else:
        log.debug("Parsed project from title '%s': '%s'", title, project)

    return {
        "project": project,
    }


# =============================================================================
#  Discord RPC wrapper
# =============================================================================


class DiscordRPC:
    def __init__(self, client_id: str):
        self._id = client_id
        self._rpc = None
        self._connected = False
        self._last_kwargs = {}
        self._last_retry = 0.0
        log.info("DiscordRPC initialized with client ID: %s", client_id)

    def _connect(self):
        log.info("Attempting to connect to Discord...")
        try:
            self._rpc = Presence(self._id)
            self._rpc.connect()
            self._connected = True
            log.info("Discord RPC connected successfully!")
        except DiscordNotFound:
            log.warning(
                "Discord is not running. Please start Discord to enable Rich Presence."
            )
            self._rpc = None
            self._connected = False
        except InvalidID as e:
            log.error("Invalid Discord Client ID: %s", e)
            self._rpc = None
            self._connected = False
        except Exception as e:
            log.warning("Discord connect failed: %s", e)
            self._rpc = None
            self._connected = False

    def _ensure_connected(self):
        if self._connected:
            return True
        log.debug("Not connected, attempting to reconnect...")
        now = time.monotonic()
        if now - self._last_retry < 10.0:
            return False
        self._last_retry = now
        self._connect()
        return self._connected

    def update(self, force=False, **kwargs):
        if not self._ensure_connected():
            log.debug("Skipping update - not connected")
            return
        if kwargs == self._last_kwargs and not force:
            log.debug("Skipping update - kwargs unchanged")
            return
        try:
            self._rpc.update(**kwargs)
            self._last_kwargs = kwargs
            log.info(
                "Discord presence updated - Project: '%s' | Status: '%s' | Playing: %s",
                kwargs.get("details", "?"),
                kwargs.get("state", "?"),
                "Yes" if kwargs.get("start") else "No",
            )
        except InvalidPipe as e:
            log.error("Discord pipe error: %s (Discord may be closed)", e)
            self._connected = False
        except Exception as e:
            log.warning("Discord update failed: %s", e)
            self._connected = False

    def clear(self):
        self._last_kwargs = {}
        if not self._connected:
            log.debug("Cannot clear - not connected")
            return
        try:
            self._rpc.clear()
            log.info("Discord presence cleared.")
        except Exception as e:
            log.warning("Failed to clear presence: %s", e)

    def close(self):
        log.info("Closing Discord RPC connection...")
        self.clear()
        if self._rpc:
            try:
                self._rpc.close()
                log.info("Discord RPC closed successfully.")
            except Exception as e:
                log.warning("Error closing RPC: %s", e)


# =============================================================================
#  Build presence kwargs from FL state
# =============================================================================


def build_presence(state: dict, play_start: float, status: str) -> dict:
    project = state["project"]
    playing = state["playing"]

    app_state["current_fl_project"] = project

    custom_name = app_state.get("custom_project_name", "")
    custom_enabled = app_state.get("custom_name_enabled", False)
    show_ext = app_state.get("show_flp_extension", True)

    if custom_enabled and custom_name:
        project = custom_name
        log.debug("Using custom project name: '%s'", custom_name)
    elif not custom_name and custom_enabled:
        log.debug("Custom name enabled but empty, using actual project: '%s'", project)
    elif custom_name:
        log.debug("Custom project name stored but not enabled: '%s'", custom_name)

    if not show_ext and project.lower().endswith(".flp"):
        project = project[:-4]

    details = project
    state_text = status if playing else "Idle in FL Studio"
    small_img = SMALL_IMAGE_PLAY if playing else SMALL_IMAGE_PAUSE
    small_txt = status if playing else "Idle"

    kwargs = dict(
        details=details,
        state=state_text,
        large_image=LARGE_IMAGE,
        large_text="FL Studio",
        small_image=small_img,
        small_text=small_txt,
    )
    if playing and play_start > 0:
        kwargs["start"] = int(play_start)
        log.debug(
            "Presence built with timer: project='%s', status='%s', start=%d",
            project,
            state_text,
            int(play_start),
        )
    else:
        log.debug(
            "Presence built without timer: project='%s', status='%s'",
            project,
            state_text,
        )

    return kwargs


# =============================================================================
#  System tray icon  (pystray)
# =============================================================================
import tkinter as tk

SOLARIZED_DARK = {
    "bg": "#002b36",
    "fg": "#839496",
    "highlight": "#fdf6e3",
    "accent": "#ff7e00",
    "hover": "#073642",
    "selected": "#b58900",
    "border": "#657b83",
    "green": "#2ecc71",
    "blue": "#3498db",
}

SOLARIZED_LIGHT = {
    "bg": "#fdf6e3",
    "fg": "#657b83",
    "highlight": "#002b36",
    "accent": "#ff7e00",
    "hover": "#eee8d5",
    "selected": "#b58900",
    "border": "#93a1a1",
    "green": "#27ae60",
    "blue": "#2980b9",
}

THEMES = {"dark": SOLARIZED_DARK, "light": SOLARIZED_LIGHT}


def _make_tray_icon() -> Image.Image:
    """Load fl_logo.png for the tray icon, fallback to generated icon on failure."""
    try:
        img = Image.open("fl_logo.png")
        img = img.resize((64, 64), Image.LANCZOS)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        return img
    except Exception as e:
        log.warning("Failed to load fl_logo.png for tray: %s", e)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, 62, 62], radius=14, fill=(255, 126, 0, 255))
    d.ellipse([14, 8, 46, 40], fill=(255, 255, 255, 255))
    d.ellipse([22, 16, 34, 28], fill=(255, 126, 0, 255))
    d.rounded_rectangle([28, 35, 36, 56], radius=4, fill=(255, 255, 255, 255))
    return img


app_state = {
    "playing": True,
    "session_start": 0.0,
    "status": "Mixing",
    "theme": "dark",
    "today_session_time": 0.0,
    "current_session_time": 0.0,
    "custom_project_name": "",
    "custom_name_enabled": False,
    "show_flp_extension": True,
    "activity_enabled": True,
    "current_fl_project": "",
}

_rpc = None


class SolarizedMenu:
    def __init__(self, on_quit_callback):
        self.on_quit = on_quit_callback
        self.main_frame = None
        self.root = None

    def _create_window(self):
        # Tell Windows this is a distinct app, not python.exe — must be before any window creation
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "absxl.fldiscordrpc"
            )
        except Exception as e:
            log.warning("Failed to set AppUserModelID: %s", e)

        config = load_config()
        theme_name = config.get("theme", "dark")
        colors = THEMES[theme_name]

        root = tk.Tk()
        root.withdraw()
        root.configure(bg=colors["bg"])

        screen_x = root.winfo_screenwidth() - 240
        screen_y = 50

        menu = tk.Toplevel(root)
        menu.title("FL Discord - @absxl")
        menu.geometry(f"240x700+{screen_x}+{screen_y}")
        menu.minsize(200, 400)
        menu.configure(bg=colors["bg"])
        menu.attributes("-topmost", True)
        menu.attributes("-alpha", 0.95)
        menu.overrideredirect(True)
        self.root = menu

        def set_icon():
            try:
                icon_img = Image.open("fl_logo.png")
                ico_path = os.path.join(_log_dir, "fl_icon.ico")
                icon_img.save(ico_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
                menu.wm_iconbitmap(ico_path)
                root.iconphoto(True, tk.PhotoImage(data=icon_img.resize((32, 32), Image.LANCZOS).tobytes(), format="PNG"))
            except Exception as e:
                log.warning("Failed to set window icon: %s", e)

        menu.after(100, set_icon)

        self.main_frame = tk.Frame(menu, bg=colors["bg"], padx=0, pady=0)
        self.main_frame.pack(fill="both", expand=True)

        header_frame = tk.Frame(
            self.main_frame, bg=colors["accent"], cursor="fleur", height=40
        )
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        def start_drag(event):
            menu._drag_start_x = event.x
            menu._drag_start_y = event.y

        def do_drag(event):
            x = menu.winfo_x() + (event.x - menu._drag_start_x)
            y = menu.winfo_y() + (event.y - menu._drag_start_y)
            menu.geometry(f"+{x}+{y}")

        header_frame.bind("<Button-1>", start_drag)
        header_frame.bind("<B1-Motion>", do_drag)

        try:
            logo_img = Image.open("fl_logo.png")
            logo_img = logo_img.resize((24, 24), Image.LANCZOS)
            self._header_logo = tk.PhotoImage(data=logo_img.tobytes(), format="PNG")
            logo_label = tk.Label(
                header_frame, image=self._header_logo, bg=colors["accent"]
            )
            logo_label.pack(side="left", padx=(10, 5), pady=5)
        except Exception as e:
            log.warning("Failed to load fl_logo.png: %s", e)
            logo_canvas = tk.Canvas(
                header_frame,
                width=24,
                height=24,
                bg=colors["accent"],
                highlightthickness=0,
            )
            logo_canvas.create_oval(2, 2, 22, 22, fill=colors["highlight"], outline="")
            logo_canvas.create_oval(6, 6, 18, 18, fill=colors["accent"], outline="")
            logo_canvas.create_rectangle(
                10, 16, 14, 22, fill=colors["highlight"], outline=""
            )
            logo_canvas.pack(side="left", padx=(10, 5), pady=5)

        playing = app_state["playing"]
        play_color = colors["green"] if playing else colors["blue"]
        self._header_status_label = tk.Label(
            header_frame,
            text="Playing" if playing else "Idle",
            font=("Segoe UI", 9, "bold"),
            bg=play_color,
            fg="white",
            padx=10,
            pady=3,
            cursor="hand2",
        )
        self._header_status_label.pack(side="left", padx=(5, 0), pady=5)
        self._header_status_label.bind("<Button-1>", lambda e: self._toggle_play_idle())

        header_right_frame = tk.Frame(header_frame, bg=colors["accent"])
        header_right_frame.pack(side="right", padx=5)

        self._header_session_label = tk.Label(
            header_right_frame,
            text=self._get_session_time_string(),
            font=("Segoe UI", 9),
            bg=colors["accent"],
            fg=colors["highlight"],
        )
        self._header_session_label.pack(side="left", padx=3)

        def update_header_session_time():
            try:
                if (
                    hasattr(self, "_header_session_label")
                    and self._header_session_label.winfo_exists()
                ):
                    time_str = self._get_session_time_string()
                    self._header_session_label.config(text=time_str)
                    self._header_session_label.after(1000, update_header_session_time)
            except Exception as e:
                log.error(f"Session time update error: {e}")

        update_header_session_time()

        reset_btn = tk.Button(
            header_right_frame,
            text="↺",
            font=("Segoe UI", 9, "bold"),
            bg=colors["blue"],
            fg="white",
            activebackground=colors["hover"],
            activeforeground=colors["fg"],
            relief="flat",
            bd=0,
            padx=4,
            cursor="hand2",
            command=self.reset_session_timer,
        )
        reset_btn.pack(side="left", padx=2)

        close_btn = tk.Button(
            header_right_frame,
            text="x",
            font=("Segoe UI", 9, "bold"),
            bg=colors["accent"],
            fg="#dc322f",
            activebackground="#dc322f",
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=6,
            cursor="hand2",
            command=self.hide_window,
        )
        close_btn.pack(side="left", padx=(8, 0))

        content_frame = tk.Frame(self.main_frame, bg=colors["bg"], padx=10, pady=10)
        content_frame.pack(fill="both", expand=True)

        self.content_frame = content_frame
        self._build_buttons(content_frame, colors)

        menu.bind("<FocusOut>", lambda e: self._on_focus_out())
        menu.bind("<Escape>", lambda e: self.hide_window())
        menu.protocol("WM_DELETE_WINDOW", self.hide_window)

        menu.lift()
        root.mainloop()

    def _on_focus_out(self):
        pass  # Don't close when clicking on entry field

    def _build_buttons(self, parent, colors):
        self.activity_enabled_var = tk.BooleanVar(value=app_state.get("activity_enabled", True))

        def on_activity_toggle():
            app_state["activity_enabled"] = self.activity_enabled_var.get()
            config = load_config()
            save_config({"activity_enabled": app_state["activity_enabled"]})
            self._update_discord_status_display()

        discord_frame = tk.Frame(parent, bg=colors["bg"])
        discord_frame.pack(pady=(0, 5))

        tk.Checkbutton(
            discord_frame,
            variable=self.activity_enabled_var,
            command=on_activity_toggle,
            bg=colors["bg"],
            fg=colors["fg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            selectcolor=colors["bg"],
            relief="flat",
            cursor="hand2",
        ).pack(side="left")

        self._discord_status_label = tk.Label(
            discord_frame,
            text="Discord: Connecting...",
            font=("Papyrus", 9, "bold"),
            bg=colors["bg"],
            fg=colors["fg"],
        )
        self._discord_status_label.pack(side="left", padx=(5, 0))

        def update_discord_status_main():
            try:
                if (
                    hasattr(self, "_discord_status_label")
                    and self._discord_status_label.winfo_exists()
                ):
                    self._update_discord_status_display()
                    self._discord_status_label.after(2000, update_discord_status_main)
            except Exception:
                pass

        update_discord_status_main()

        tk.Label(
            parent,
            text="Status",
            font=("Segoe UI", 9, "bold"),
            bg=colors["bg"],
            fg=colors["accent"],
        ).pack()

        for status in STATUS_PRESETS:
            is_selected = status == app_state["status"]
            bg = colors["accent"] if is_selected else colors["hover"]
            txt = f"{status} ✓" if is_selected else status
            self._add_status_button(
                parent,
                txt,
                bg,
                colors["highlight"] if is_selected else colors["fg"],
                lambda s=status: self.set_status(s),
            ).pack(fill="x", pady=1, padx=5)

        config = load_config()
        custom_statuses = config.get("custom_statuses", [])[:3]

        if custom_statuses:
            tk.Label(
                parent,
                text="Custom",
                font=("Segoe UI", 8, "bold"),
                bg=colors["bg"],
                fg=colors["fg"],
            ).pack()

            for status in custom_statuses:
                is_selected = status == app_state["status"]
                bg = colors["accent"] if is_selected else colors["hover"]
                txt = f"{status} ✓" if is_selected else status

                row_frame = tk.Frame(parent, bg=colors["bg"])
                row_frame.pack(fill="x", pady=1)

                self._add_status_button(
                    row_frame,
                    txt,
                    bg,
                    colors["highlight"] if is_selected else colors["fg"],
                    lambda s=status: self.set_status(s),
                ).pack(side="left", fill="x", expand=True, padx=(5, 0))

                delete_btn = tk.Button(
                    row_frame,
                    text="x",
                    font=("Segoe UI", 8, "bold"),
                    bg=colors["hover"],
                    fg=colors["fg"],
                    activebackground="#dc322f",
                    activeforeground="white",
                    relief="flat",
                    bd=0,
                    cursor="hand2",
                    width=2,
                    command=lambda s=status: self.delete_custom_status(s),
                )
                delete_btn.pack(side="right", padx=(2, 5))

            custom_frame = tk.Frame(parent, bg=colors["bg"])
            custom_frame.pack(fill="x", pady=(5, 0), padx=5)

            self.custom_entry = tk.Entry(
                custom_frame,
                font=("Segoe UI", 9),
                bg=colors["hover"],
                fg=colors["fg"],
                insertbackground=colors["fg"],
                relief="flat",
                bd=0,
            )
            self.custom_entry.pack(side="left", fill="x", expand=True, padx=(0, 3))
            self.custom_entry.bind("<Return>", lambda e: self.add_custom_status())

            add_btn = tk.Button(
                custom_frame,
                text="+",
                font=("Segoe UI", 10, "bold"),
                bg=colors["hover"],
                fg=colors["fg"],
                activebackground=colors["accent"],
                activeforeground=colors["highlight"],
                relief="flat",
                bd=0,
                cursor="hand2",
                width=2,
                command=self.add_custom_status,
            )
            add_btn.pack(side="right")

        tk.Label(
            parent,
            text="Custom FLP Name",
            font=("Segoe UI", 9, "bold"),
            bg=colors["bg"],
            fg=colors["accent"],
        ).pack()

        self.current_fl_label = tk.Label(
            parent,
            text=f"FLP: {app_state.get('current_fl_project', 'None')[:25]}",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["fg"],
        )
        self.current_fl_label.pack()

        custom_enabled = app_state.get("custom_name_enabled", False)
        custom_name = app_state.get("custom_project_name", "")
        if custom_enabled and custom_name:
            showing_text = f"→ {custom_name[:23]} (ON)"
            showing_color = colors["accent"]
        elif custom_name:
            showing_text = f"• {custom_name[:23]} (off)"
            showing_color = colors["fg"]
        else:
            showing_text = "No custom name"
            showing_color = colors["fg"]

        self.showing_label = tk.Label(
            parent,
            text=showing_text,
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=showing_color,
        )
        self.showing_label.pack()

        custom_name_frame = tk.Frame(parent, bg=colors["bg"])
        custom_name_frame.pack(fill="x", pady=5, padx=5)

        self.custom_name_var = tk.BooleanVar(
            value=app_state.get("custom_name_enabled", False)
        )

        def on_checkbox_change():
            app_state["custom_name_enabled"] = self.custom_name_var.get()
            config = load_config()
            save_config(
                {
                    "playing": app_state["playing"],
                    "status": app_state["status"],
                    "theme": app_state.get("theme", "dark"),
                    "today_session_time": app_state.get("today_session_time", 0.0),
                    "custom_statuses": config.get("custom_statuses", []),
                    "custom_project_name": app_state.get("custom_project_name", ""),
                    "custom_name_enabled": app_state.get("custom_name_enabled", False),
                    "show_flp_extension": app_state.get("show_flp_extension", True),
                }
            )

            if _rpc:
                rpc_start = (
                    app_state["session_start"]
                    if app_state["playing"] and app_state["session_start"] > 0
                    else 0
                )
                state = {
                    "project": app_state.get("current_fl_project", "Unknown"),
                    "playing": app_state["playing"],
                }
                kwargs = build_presence(state, rpc_start, app_state["status"])
                _rpc.update(force=True, **kwargs)

        self.custom_name_checkbox = tk.Checkbutton(
            custom_name_frame,
            variable=self.custom_name_var,
            command=on_checkbox_change,
            bg=colors["bg"],
            fg=colors["fg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            selectcolor=colors["bg"],
            relief="flat",
            cursor="hand2",
        )
        self.custom_name_checkbox.pack(side="left")

        self.custom_name_entry = tk.Entry(
            custom_name_frame,
            font=("Segoe UI", 9),
            bg=colors["hover"],
            fg=colors["fg"],
            insertbackground=colors["fg"],
            relief="flat",
            bd=0,
        )
        self.custom_name_entry.insert(0, app_state.get("custom_project_name", ""))
        self.custom_name_entry.pack(side="left", fill="x", expand=True, padx=(3, 3))
        self.custom_name_entry.bind(
            "<Return>", lambda e: self.set_custom_project_name()
        )

        clear_btn = tk.Button(
            custom_name_frame,
            text="x",
            font=("Segoe UI", 9, "bold"),
            bg=colors["hover"],
            fg=colors["fg"],
            activebackground="#dc322f",
            activeforeground="white",
            relief="flat",
            bd=0,
            cursor="hand2",
            width=2,
            command=lambda: self.clear_custom_project_name(),
        )
        clear_btn.pack(side="right")

        ext_frame = tk.Frame(parent, bg=colors["bg"])
        ext_frame.pack(fill="x", pady=(10, 0))

        self.show_ext_var = tk.BooleanVar(
            value=app_state.get("show_flp_extension", True)
        )

        def on_ext_change():
            app_state["show_flp_extension"] = self.show_ext_var.get()
            config = load_config()
            save_config(
                {
                    "playing": app_state["playing"],
                    "status": app_state["status"],
                    "theme": app_state.get("theme", "dark"),
                    "today_session_time": app_state.get("today_session_time", 0.0),
                    "custom_statuses": config.get("custom_statuses", []),
                    "custom_project_name": app_state.get("custom_project_name", ""),
                    "custom_name_enabled": app_state.get("custom_name_enabled", False),
                    "show_flp_extension": app_state.get("show_flp_extension", True),
                }
            )
            if _rpc:
                rpc_start = (
                    app_state["session_start"]
                    if app_state["playing"] and app_state["session_start"] > 0
                    else 0
                )
                state = {
                    "project": app_state.get("current_fl_project", "Unknown"),
                    "playing": app_state["playing"],
                }
                kwargs = build_presence(state, rpc_start, app_state["status"])
                _rpc.update(force=True, **kwargs)

        tk.Checkbutton(
            ext_frame,
            text="Show .flp extension",
            variable=self.show_ext_var,
            command=on_ext_change,
            bg=colors["bg"],
            fg=colors["fg"],
            activebackground=colors["bg"],
            activeforeground=colors["fg"],
            selectcolor=colors["bg"],
            relief="flat",
            cursor="hand2",
        ).pack(side="left")

        link_frame = tk.Frame(parent, bg=colors["bg"])
        link_frame.pack(fill="x", pady=1)

        self._add_button(
            link_frame, "Log", colors["hover"], colors["fg"], self.open_log
        ).pack(side="left", fill="both", expand=True, padx=(0, 1))

        self._add_button(
            link_frame, "Theme", colors["hover"], colors["fg"], self.toggle_theme
        ).pack(side="left", fill="both", expand=True, padx=(1, 0))

        link_frame2 = tk.Frame(parent, bg=colors["bg"])
        link_frame2.pack(fill="x", pady=1)

        self._add_button(
            link_frame2, "Discord", "#5865F2", "white", self.open_discord
        ).pack(side="left", fill="both", expand=True, padx=(0, 1))

        self._add_button(
            link_frame2, "Donate", "#0070BA", "white", self.open_donate
        ).pack(side="left", fill="both", expand=True, padx=(1, 0))

        self._add_button(parent, "Quit", "#dc322f", "white", self.quit_app).pack(
            fill="x", pady=(5, 0)
        )

        tk.Label(
            parent,
            text="@absol on github — All rights reserved • Open Source",
            font=("Segoe UI", 7),
            bg=colors["bg"],
            fg=colors["fg"],
        ).pack(pady=(10, 5))

    def _add_button(self, parent, text, bg, fg, command):
        colors = SOLARIZED_DARK
        btn = tk.Button(
            parent,
            text=text,
            font=("Segoe UI", 9, "bold"),
            bg=bg,
            fg=fg,
            activebackground=colors["accent"],
            activeforeground=colors["highlight"],
            relief="flat",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
            anchor="center",
            command=command,
        )
        return btn

    def _add_status_button(self, parent, text, bg, fg, command):
        colors = SOLARIZED_DARK
        btn = tk.Button(
            parent,
            text=text,
            font=("Segoe UI", 9),
            bg=bg,
            fg=fg,
            activebackground=colors["accent"],
            activeforeground=colors["highlight"],
            relief="flat",
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2",
            anchor="w",
            command=command,
        )
        return btn

    def _update_discord_status_display(self):
        try:
            activity_enabled = app_state.get("activity_enabled", True)
            connected = getattr(_rpc, "_connected", False) if _rpc else False

            if not activity_enabled:
                text = "Disabled"
                color = "#e74c3c"
            elif connected:
                text = "Connected"
                color = "#2ecc71"
            else:
                text = "Disconnected"
                color = "#e74c3c"

            if hasattr(self, "_discord_status_label") and self._discord_status_label.winfo_exists():
                self._discord_status_label.config(text=f"Discord: {text}", fg=color)
        except Exception:
            pass

    def open_donate(self):
        import webbrowser

        webbrowser.open("https://www.paypal.com/donate/?hosted_button_id=VQWNYHWLKV9DL")

    def open_discord(self):
        import webbrowser

        webbrowser.open("https://discord.gg/jeM65U49Rt")

    def _add_session_time_display(self, parent, colors):
        session_top_frame = tk.Frame(parent, bg=colors["bg"])
        session_top_frame.pack(fill="x")

        self.session_time_label = tk.Label(
            session_top_frame,
            text=f"Session: {self._get_session_time_string()}",
            font=("Segoe UI", 9, "bold"),
            bg=colors["bg"],
            fg=colors["accent"],
        )
        self.session_time_label.pack(side="left")

        reset_btn = tk.Button(
            session_top_frame,
            text="↺",
            font=("Segoe UI", 10, "bold"),
            bg=colors["hover"],
            fg=colors["fg"],
            activebackground=colors["accent"],
            activeforeground=colors["highlight"],
            relief="flat",
            bd=0,
            padx=6,
            cursor="hand2",
            command=self.reset_session_timer,
        )
        reset_btn.pack(side="right")

        def update_session_time():
            if self.session_time_label and self.session_time_label.winfo_exists():
                self.session_time_label.config(
                    text=f"Session: {self._get_session_time_string()}"
                )
                self.session_time_label.after(1000, update_session_time)

        update_session_time()

    def _get_session_time_string(self):
        log.debug(f"_get_session_time_string called - playing={app_state['playing']}, session_start={app_state['session_start']}")
        if app_state["playing"] and app_state["session_start"] > 0:
            total_seconds = time.time() - app_state["session_start"]
            log.debug(f"Calculated session time: {total_seconds} seconds")
        else:
            total_seconds = app_state.get("today_session_time", 0)
            log.debug(f"Using saved time: {total_seconds} seconds")
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def toggle_theme(self):
        config = load_config()
        current_theme = config.get("theme", "dark")
        new_theme = "light" if current_theme == "dark" else "dark"
        app_state["theme"] = new_theme
        config["theme"] = new_theme
        save_config(config)
        log.info("Theme changed to: %s", new_theme)

        if self.root:
            self.root.destroy()
            self.root = None
            self.main_frame = None
        self._create_window()

    def update_fl_label(self):
        try:
            if (
                hasattr(self, "current_fl_label")
                and self.current_fl_label
                and self.current_fl_label.winfo_exists()
            ):
                current_project = app_state.get("current_fl_project", "None")
                self.current_fl_label.config(text=f"FLP: {current_project[:25]}")
        except RuntimeError:
            pass

        try:
            if (
                hasattr(self, "showing_label")
                and self.showing_label
                and self.showing_label.winfo_exists()
            ):
                theme_name = app_state.get("theme", "dark")
                colors = THEMES[theme_name]
                custom_enabled = app_state.get("custom_name_enabled", False)
                custom_name = app_state.get("custom_project_name", "")
                if custom_enabled and custom_name:
                    showing_text = f"→ {custom_name[:23]} (ON)"
                    showing_color = colors["accent"]
                elif custom_name:
                    showing_text = f"• {custom_name[:23]} (off)"
                    showing_color = colors["fg"]
                else:
                    showing_text = "No custom name"
                    showing_color = colors["fg"]
                self.showing_label.config(text=showing_text, fg=showing_color)
        except RuntimeError:
            pass

    def show(self):
        try:
            if self.root is not None:
                try:
                    self.root.deiconify()
                    self.root.lift()
                    return
                except:
                    pass
            log.info("SolarizedMenu.show() called")
            t = threading.Thread(target=self._create_window, daemon=True)
            t.start()
        except Exception as e:
            log.error("SolarizedMenu.show() error: %s", e)
            import traceback

            log.error(traceback.format_exc())

    def hide(self):
        if self.root:
            self.root.withdraw()

    def hide_window(self):
        try:
            self.hide()
        except RuntimeError:
            pass

    def _update_header_status(self):
        try:
            theme_name = app_state.get("theme", "dark")
            colors = THEMES[theme_name]
            if (
                hasattr(self, "_header_status_label")
                and self._header_status_label.winfo_exists()
            ):
                play_color = colors["green"] if app_state["playing"] else colors["blue"]
                self._header_status_label.config(
                    text="Playing" if app_state["playing"] else "Idle", bg=play_color
                )
        except Exception as e:
            log.error("Failed to update header status: %s", e)

    def toggle_play(self):
        log.info("Menu: Set to Playing")
        app_state["playing"] = True
        if app_state["session_start"] == 0:
            app_state["session_start"] = time.time()
        config = load_config()
        save_config(
            {
                "playing": app_state["playing"],
                "status": app_state["status"],
                "custom_statuses": config.get("custom_statuses", []),
                "custom_project_name": app_state.get("custom_project_name", ""),
                "custom_name_enabled": app_state.get("custom_name_enabled", False),
            }
        )

        if _rpc:
            rpc_start = (
                app_state["session_start"]
                if app_state["playing"] and app_state["session_start"] > 0
                else 0
            )
            state = {
                "project": app_state.get("current_fl_project", "Unknown"),
                "playing": app_state["playing"],
            }
            kwargs = build_presence(state, rpc_start, app_state["status"])
            _rpc.update(force=True, **kwargs)
            _rpc._last_status = app_state["status"]
            _rpc._last_playing = app_state["playing"]

        self._rebuild_current_window()
        self._update_header_status()

    def toggle_idle(self):
        log.info("Menu: Set to Idle")
        app_state["playing"] = False
        config = load_config()
        save_config(
            {
                "playing": app_state["playing"],
                "status": app_state["status"],
                "custom_statuses": config.get("custom_statuses", []),
                "custom_project_name": app_state.get("custom_project_name", ""),
                "custom_name_enabled": app_state.get("custom_name_enabled", False),
            }
        )

        if _rpc:
            rpc_start = (
                app_state["session_start"]
                if app_state["playing"] and app_state["session_start"] > 0
                else 0
            )
            state = {
                "project": app_state.get("current_fl_project", "Unknown"),
                "playing": app_state["playing"],
            }
            kwargs = build_presence(state, rpc_start, app_state["status"])
            _rpc.update(force=True, **kwargs)
            _rpc._last_status = app_state["status"]
            _rpc._last_playing = app_state["playing"]

        self._rebuild_current_window()
        self._update_header_status()

    def reset_session_timer(self):
        log.info("Menu: Session timer reset")
        app_state["session_start"] = time.time()
        log.info("Session timer reset to current time")
        try:
            if hasattr(self, "_header_session_label") and self._header_session_label.winfo_exists():
                self._header_session_label.config(text=self._get_session_time_string())
        except Exception as e:
            log.warning("Failed to update session label: %s", e)

    def _toggle_play_idle(self):
        if app_state["playing"]:
            self.toggle_idle()
        else:
            self.toggle_play()

    def set_custom_project_name(self, name=None):
        if name is None:
            name = (
                self.custom_name_entry.get().strip()
                if hasattr(self, "custom_name_entry")
                else ""
            )
        app_state["custom_project_name"] = name
        config = load_config()
        save_config(
            {
                "playing": app_state["playing"],
                "status": app_state["status"],
                "custom_statuses": config.get("custom_statuses", []),
                "custom_project_name": name,
                "custom_name_enabled": app_state.get("custom_name_enabled", False),
            }
        )
        log.info("Custom project name set to: '%s'", name)

        if _rpc:
            rpc_start = (
                app_state["session_start"]
                if app_state["playing"] and app_state["session_start"] > 0
                else 0
            )
            state = {
                "project": app_state.get("current_fl_project", "Unknown"),
                "playing": app_state["playing"],
            }
            kwargs = build_presence(state, rpc_start, app_state["status"])
            _rpc.update(force=True, **kwargs)

        self._rebuild_current_window()

    def clear_custom_project_name(self):
        app_state["custom_project_name"] = ""
        app_state["custom_name_enabled"] = False
        config = load_config()
        save_config(
            {
                "playing": app_state["playing"],
                "status": app_state["status"],
                "custom_statuses": config.get("custom_statuses", []),
                "custom_project_name": "",
                "custom_name_enabled": False,
            }
        )
        log.info("Custom project name cleared")

        if _rpc:
            rpc_start = (
                app_state["session_start"]
                if app_state["playing"] and app_state["session_start"] > 0
                else 0
            )
            state = {
                "project": app_state.get("current_fl_project", "Unknown"),
                "playing": app_state["playing"],
            }
            kwargs = build_presence(state, rpc_start, app_state["status"])
            _rpc.update(force=True, **kwargs)

        self._rebuild_current_window()

    def set_status(self, status):
        log.info("Menu: Status changed to '%s'", status)
        app_state["status"] = status
        config = load_config()
        custom_statuses = config.get("custom_statuses", [])
        save_config(
            {
                "playing": app_state["playing"],
                "status": app_state["status"],
                "custom_statuses": custom_statuses,
                "custom_project_name": app_state.get("custom_project_name", ""),
                "custom_name_enabled": app_state.get("custom_name_enabled", False),
            }
        )

        if _rpc:
            rpc_start = (
                app_state["session_start"]
                if app_state["playing"] and app_state["session_start"] > 0
                else 0
            )
            state = {
                "project": app_state.get("current_fl_project", "Unknown"),
                "playing": app_state["playing"],
            }
            kwargs = build_presence(state, rpc_start, app_state["status"])
            _rpc.update(force=True, **kwargs)
            _rpc._last_status = app_state["status"]
            _rpc._last_playing = app_state["playing"]

        self._rebuild_current_window()

    def add_custom_status(self):
        status = self.custom_entry.get().strip()
        if not status:
            return
        log.info("Adding custom status: '%s'", status)
        config = load_config()
        custom_statuses = config.get("custom_statuses", [])[:3]
        if status not in custom_statuses and len(custom_statuses) < 3:
            custom_statuses.append(status)
            save_config(
                {
                    "playing": app_state["playing"],
                    "status": app_state["status"],
                    "custom_statuses": custom_statuses,
                    "custom_project_name": app_state.get("custom_project_name", ""),
                    "custom_name_enabled": app_state.get("custom_name_enabled", False),
                }
            )
            log.info("Custom status added. Total: %d/5", len(custom_statuses))
        elif status in custom_statuses:
            log.info("Custom status '%s' already exists", status)
        elif len(custom_statuses) >= 3:
            log.warning("Cannot add more custom statuses (max 5 reached)")
        self.custom_entry.delete(0, "end")
        self._rebuild_current_window()

    def delete_custom_status(self, status):
        log.info("Deleting custom status: '%s'", status)
        config = load_config()
        custom_statuses = config.get("custom_statuses", [])
        if status in custom_statuses:
            custom_statuses.remove(status)
            save_config(
                {
                    "playing": app_state["playing"],
                    "status": app_state["status"],
                    "custom_statuses": custom_statuses,
                    "custom_project_name": app_state.get("custom_project_name", ""),
                    "custom_name_enabled": app_state.get("custom_name_enabled", False),
                }
            )
            log.info("Custom status deleted. Remaining: %d", len(custom_statuses))
        if app_state["status"] == status:
            app_state["status"] = STATUS_PRESETS[0]
            save_config(
                {
                    "playing": app_state["playing"],
                    "status": app_state["status"],
                    "custom_statuses": custom_statuses,
                    "custom_project_name": app_state.get("custom_project_name", ""),
                    "custom_name_enabled": app_state.get("custom_name_enabled", False),
                }
            )
            log.info("Reset status to default: '%s'", STATUS_PRESETS[0])
        self._rebuild_current_window()

    def _rebuild_current_window(self):
        if self.content_frame:
            for widget in self.content_frame.winfo_children():
                widget.destroy()
            theme_name = app_state.get("theme", "dark")
            colors = THEMES[theme_name]
            self._build_buttons(self.content_frame, colors)

    def open_log(self):
        os.startfile(_log_dir)

    def quit_app(self):
        self.hide()
        self.on_quit()


solarized_menu = None
_stop_event = None


def _run_tray(stop_event: threading.Event, icon_ref):
    global solarized_menu, _stop_event
    _stop_event = stop_event

    log.info("Initializing system tray...")
    solarized_menu = SolarizedMenu(lambda: _quit())
    log.info("Menu initialized")

    if HAS_KEYBOARD:
        try:

            def toggle_menu():
                log.info("Keyboard shortcut pressed (Ctrl+Shift+F)")
                solarized_menu.show()

            keyboard.add_hotkey("ctrl+shift+f", toggle_menu)
            log.info("Keyboard shortcut registered: Ctrl+Shift+F opens menu")

            def reset_timer():
                log.info("Keyboard shortcut pressed (Ctrl+Shift+R) - Timer reset")
                if solarized_menu:
                    solarized_menu.reset_session_timer()
                else:
                    app_state["session_start"] = time.time()
                    log.info("Session timer reset to current time")

            keyboard.add_hotkey("ctrl+shift+r", reset_timer)
            log.info("Keyboard shortcut registered: Ctrl+Shift+R resets timer")
        except Exception as e:
            log.warning("Could not register keyboard shortcut: %s", e)
    else:
        log.info("Keyboard module not available, using tray menu only")

    def toggle_startup(icon, _):
        current = _get_startup_path()
        _set_startup(not current)

    def on_show_menu(icon, _):
        log.debug("Tray menu: Open Menu clicked")
        solarized_menu.show()

    def on_open_log(icon, _):
        os.startfile(_log_dir)

    def on_donate(icon, _):
        import webbrowser

        webbrowser.open("https://www.paypal.com/donate/?hosted_button_id=VQWNYHWLKV9DL")

    def on_discord(icon, _):
        import webbrowser

        webbrowser.open("https://discord.gg/jeM65U49Rt")

    def on_check_update(icon, _):
        import json
        import threading
        import urllib.request

        def check():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                req = urllib.request.Request(url, headers={"User-Agent": "FL-Discord"})
                with urllib.request.urlopen(req, timeout=10) as response:
                    data = json.loads(response.read())
                    latest = data.get("tag_name", "").lstrip("v")
                    if latest > VERSION:
                        import webbrowser

                        webbrowser.open(
                            data.get(
                                "html_url",
                                "https://github.com/absxl/FL-Discord/releases",
                            )
                        )
                        log.info(f"Update available: {latest}")
                    else:
                        log.info(f"Already on latest version: {VERSION}")
            except Exception as e:
                log.error(f"Failed to check for updates: {e}")

        threading.Thread(target=check, daemon=True).start()

    def on_quit(icon, _):
        _quit()

    def get_startup_label():
        return "Run at Startup ✓" if _get_startup_path() else "Run at Startup"

    def create_menu():
        menu = pystray.Menu(
            pystray.MenuItem("FL Discord RPC", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Menu", on_show_menu),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _: get_startup_label(), toggle_startup),
            pystray.MenuItem("Open Log Folder", on_open_log),
            pystray.MenuItem("Check for Updates", on_check_update),
            pystray.MenuItem("Join Discord", on_discord),
            pystray.MenuItem("Donate", on_donate),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )
        return menu

    icon = pystray.Icon(
        "fl_discord_rpc",
        _make_tray_icon(),
        menu=create_menu(),
    )

    icon_ref[0] = icon
    log.info("Starting tray icon...")
    icon.run()
    log.info("Tray icon stopped")


def _quit():
    if _stop_event:
        _stop_event.set()
    if solarized_menu and solarized_menu.root:
        solarized_menu.root.destroy()


# =============================================================================
#  Main loop
# =============================================================================


def main():
    log.info("=" * 60)
    log.info("FL Discord RPC v1.0")
    log.info("=" * 60)

    if DISCORD_CLIENT_ID == "YOUR_CLIENT_ID_HERE":
        log.error("Discord Client ID not configured!")
        ctypes.windll.user32.MessageBoxW(
            0,
            "You haven't set your Discord Client ID!\n\n"
            "Open fl_discord_rpc.py and replace\n"
            "YOUR_CLIENT_ID_HERE\n"
            "with your Discord Application ID.",
            "FL Discord RPC — Setup Required",
            0x30,
        )
        return

    config = load_config()
    app_state["playing"] = config.get("playing", True)
    app_state["status"] = config.get("status", "Mixing")
    app_state["theme"] = config.get("theme", "dark")
    app_state["today_session_time"] = 0.0
    app_state["custom_project_name"] = config.get("custom_project_name", "")
    app_state["custom_name_enabled"] = config.get("custom_name_enabled", False)
    app_state["show_flp_extension"] = config.get("show_flp_extension", True)
    app_state["activity_enabled"] = config.get("activity_enabled", True)

    log.info("Configuration loaded:")
    log.info("  - Playing: %s", app_state["playing"])
    log.info("  - Status: %s", app_state["status"])
    log.info("  - Theme: %s", app_state["theme"])
    log.info("  - Session time today: %s", app_state["today_session_time"])
    log.info("  - Custom project name: '%s'", app_state.get("custom_project_name", ""))
    log.info("  - Custom name enabled: %s", app_state.get("custom_name_enabled", False))
    log.info("  - Show .flp extension: %s", app_state.get("show_flp_extension", True))
    log.info("  - Custom statuses: %s", config.get("custom_statuses", []))
    log.info("  - Run at startup: %s", _get_startup_path())
    log.info("Starting FL Discord RPC...")
    log.info("Poll interval: %s seconds", POLL_INTERVAL)
    log.info("Clear after: %s seconds", CLEAR_AFTER)

    stop_event = threading.Event()
    icon_ref = [None]

    global _rpc
    _rpc = DiscordRPC(DISCORD_CLIENT_ID)
    last_seen_fl = 0.0
    fl_was_open = False
    last_project = ""

    log.info("Starting system tray...")
    tray_thread = threading.Thread(
        target=_run_tray, args=(stop_event, icon_ref), daemon=True
    )
    tray_thread.start()

    log.info("Main loop started. Waiting for FL Studio...")

    while not stop_event.is_set():
        hwnd, title = _find_fl_window()

        if hwnd is None:
            if fl_was_open:
                closed_duration = time.monotonic() - last_seen_fl
                if closed_duration > CLEAR_AFTER:
                    _rpc.clear()
                    fl_was_open = False
                    log.info(
                        "FL Studio closed — presence cleared after %.1f seconds",
                        closed_duration,
                    )
        else:
            last_seen_fl = time.monotonic()
            if not fl_was_open:
                log.info("FL Studio detected! Window: '%s'", title)
            fl_was_open = True

            state = _read_fl_state(hwnd, title)

            if state["project"] != last_project:
                log.info(
                    "Project changed: '%s' -> '%s'",
                    last_project or "(none)",
                    state["project"],
                )
                last_project = state["project"]

            if solarized_menu:
                solarized_menu.update_fl_label()

            state["playing"] = app_state["playing"]

            if app_state["playing"]:
                if app_state["session_start"] == 0:
                    app_state["session_start"] = time.time()
                    log.info("Session started. Status: '%s'", app_state["status"])

            rpc_start = (
                app_state["session_start"]
                if app_state["playing"] and app_state["session_start"] > 0
                else 0
            )
            kwargs = build_presence(state, rpc_start, app_state["status"])

            last_playing = getattr(_rpc, "_last_playing", None)
            last_status = getattr(_rpc, "_last_status", None)
            force_update = (
                app_state["playing"] != last_playing
                or app_state["status"] != last_status
            )
            if app_state.get("activity_enabled", True):
                _rpc.update(force=force_update, **kwargs)
            else:
                _rpc.clear()
            _rpc._last_playing = app_state["playing"]
            _rpc._last_status = app_state["status"]

        time.sleep(POLL_INTERVAL)

    log.info("Saving configuration...")
    config = load_config()
    if app_state["playing"] and app_state["session_start"] > 0:
        session_duration = time.time() - app_state["session_start"]
        app_state["today_session_time"] += session_duration
    save_config(
        {
            "playing": app_state["playing"],
            "status": app_state["status"],
            "theme": app_state.get("theme", "dark"),
            "today_session_time": app_state.get("today_session_time", 0.0),
            "custom_statuses": config.get("custom_statuses", []),
            "custom_project_name": app_state.get("custom_project_name", ""),
            "custom_name_enabled": app_state.get("custom_name_enabled", False),
            "show_flp_extension": app_state.get("show_flp_extension", True),
        }
    )
    log.info("Configuration saved.")
    _rpc.close()
    log.info("=" * 60)
    log.info("FL Discord RPC stopped.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
