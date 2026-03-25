# =============================================================================
#  fl_discord_rpc.py — FL Studio Discord Rich Presence
#  Standalone script. Convert to .exe with:
#      pip install pyinstaller
#      pyinstaller --onefile --noconsole --icon=icon.ico fl_discord_rpc.py
#
#  No FL Studio scripts, no loopMIDI, no manual installs.
#  Just run it and it lives in your system tray.
# =============================================================================

DISCORD_CLIENT_ID = "YOUR_CLIENT_ID_HERE"   # <-- paste your Discord App ID here

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
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
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
    "Creating",
    "Mixing",
    "Mastering",
    "Sound Design",
    "Arranging",
    "Composing",
    "Producing",
    "Editing",
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
    return STATUS_PRESETS + config.get("custom_statuses", [])[:5]

def save_config(config):
    try:
        with open(_config_file, "w") as f:
            json.dump(config, f, indent=2)
        log.debug("Configuration saved to %s: %s", _config_file, config)
    except Exception as e:
        log.error("Failed to save config: %s", e)


def _get_startup_path():
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
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
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_WRITE)
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
        log.error("Permission denied when setting startup. Run as administrator may be required: %s", e)
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
    """Parse everything we can out of the window title + process."""
    # Parse project name from "ProjectName - FL Studio 2024" format
    m = FL_TITLE_RE.match(title.strip())
    project = (m.group(1) or "").strip() if m else ""
    if not project:
        project = "Untitled"
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
            log.warning("Discord is not running. Please start Discord to enable Rich Presence.")
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
            log.info("Discord presence updated - Project: '%s' | Status: '%s' | Playing: %s", 
                    kwargs.get("details", "?"), 
                    kwargs.get("state", "?"),
                    "Yes" if kwargs.get("start") else "No")
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
        log.debug("Presence built: project='%s', status='%s', playing=%s, start=%d", 
                  project, state_text, playing, int(play_start))
    else:
        log.debug("Presence built: project='%s', status='%s', playing=%s", 
                  project, state_text, playing)

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
}


def _make_tray_icon() -> Image.Image:
    """Draw a tiny orange FL-style icon for the tray (64x64)."""
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
    "status": "Creating",
}


class SolarizedMenu:
    def __init__(self, on_quit_callback):
        self.on_quit = on_quit_callback
        self.main_frame = None
        self.root = None
        
    def _create_window(self):
        colors = SOLARIZED_DARK
        
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-alpha", 0)
        
        screen_x = root.winfo_screenwidth() - 230
        screen_y = 50
        
        menu = tk.Toplevel(root)
        menu.geometry(f"230x700+{screen_x}+{screen_y}")
        menu.configure(bg=colors["bg"])
        menu.attributes("-topmost", True)
        menu.attributes("-alpha", 0.95)
        menu.overrideredirect(True)
        self.root = menu
        
        self.main_frame = tk.Frame(menu, bg=colors["bg"], padx=0, pady=0)
        self.main_frame.pack(fill="both", expand=True)
        
        header_frame = tk.Frame(self.main_frame, bg=colors["accent"], cursor="fleur")
        header_frame.pack(fill="x", ipady=8)
        
        def start_drag(event):
            menu._drag_start_x = event.x
            menu._drag_start_y = event.y
        
        def do_drag(event):
            x = menu.winfo_x() + (event.x - menu._drag_start_x)
            y = menu.winfo_y() + (event.y - menu._drag_start_y)
            menu.geometry(f"+{x}+{y}")
        
        header_frame.bind("<Button-1>", start_drag)
        header_frame.bind("<B1-Motion>", do_drag)
        
        logo_canvas = tk.Canvas(header_frame, width=24, height=24, bg=colors["accent"], highlightthickness=0)
        logo_canvas.create_oval(2, 2, 22, 22, fill=colors["highlight"], outline="")
        logo_canvas.create_oval(6, 6, 18, 18, fill=colors["accent"], outline="")
        logo_canvas.create_rectangle(10, 16, 14, 22, fill=colors["highlight"], outline="")
        logo_canvas.pack(side="left", padx=(10, 5), pady=5)
        
        tk.Label(
            header_frame,
            text="FL DISCORD",
            font=("Segoe UI", 12, "bold"),
            bg=colors["accent"],
            fg=colors["highlight"]
        ).pack(side="left", pady=5)
        
        close_btn = tk.Button(
            header_frame,
            text="X",
            font=("Segoe UI", 10, "bold"),
            bg=colors["accent"],
            fg=colors["highlight"],
            activebackground="#dc322f",
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=8,
            cursor="hand2",
            command=self._on_close
        )
        close_btn.pack(side="right", padx=5, pady=3)
        
        content_frame = tk.Frame(self.main_frame, bg=colors["bg"], padx=10, pady=10)
        content_frame.pack(fill="both", expand=True)
        
        self.content_frame = content_frame
        self._build_buttons(content_frame, colors)
        
        menu.bind("<FocusOut>", lambda e: self._on_focus_out())
        menu.bind("<Escape>", lambda e: self._on_close())
        menu.protocol("WM_DELETE_WINDOW", self._on_close)
        
        menu.lift()
        root.mainloop()
        
    def _on_close(self):
        import sys
        sys.exit(0)
        
    def _on_focus_out(self):
        pass  # Don't close when clicking on entry field
        
    def _build_buttons(self, parent, colors):
        playing = app_state["playing"]
        play_bg = colors["accent"] if playing else colors["hover"]
        idle_bg = colors["hover"] if playing else colors["accent"]
        
        btn_frame = tk.Frame(parent, bg=colors["bg"])
        btn_frame.pack(fill="x", pady=5)
        
        self._add_button(
            btn_frame,
            "Playing",
            play_bg,
            colors["highlight"],
            self.toggle_play
        ).pack(side="left", fill="x", expand=True)
        
        self._add_button(
            btn_frame,
            "Idle",
            idle_bg,
            colors["highlight"],
            self.toggle_idle
        ).pack(side="left", fill="x", expand=True, padx=(3, 0))
        
        tk.Frame(parent, height=1, bg=colors["border"]).pack(fill="x", pady=8)
        
        tk.Label(
            parent,
            text="Status",
            font=("Segoe UI", 9, "bold"),
            bg=colors["bg"],
            fg=colors["accent"]
        ).pack(pady=(0, 5))
        
        for status in STATUS_PRESETS:
            is_selected = (status == app_state["status"])
            bg = colors["accent"] if is_selected else colors["hover"]
            txt = f"{status} ✓" if is_selected else status
            self._add_status_button(parent, txt, bg, colors["highlight"] if is_selected else colors["fg"], lambda s=status: self.set_status(s)).pack(fill="x", pady=1, padx=5)
        
        config = load_config()
        custom_statuses = config.get("custom_statuses", [])[:5]
        
        header_frame = tk.Frame(parent, bg=colors["bg"])
        header_frame.pack(fill="x", pady=(5, 0))
        
        tk.Label(
            header_frame,
            text="Custom",
            font=("Segoe UI", 8, "bold"),
            bg=colors["bg"],
            fg=colors["fg"]
        ).pack(side="left")
        
        tk.Label(
            header_frame,
            text=f"({len(custom_statuses)}/5)",
            font=("Segoe UI", 8),
            bg=colors["bg"],
            fg=colors["accent"]
        ).pack(side="right")
        
        for status in custom_statuses:
            is_selected = (status == app_state["status"])
            bg = colors["accent"] if is_selected else colors["hover"]
            txt = f"{status} ✓" if is_selected else status
            
            row_frame = tk.Frame(parent, bg=colors["bg"])
            row_frame.pack(fill="x", pady=1)
            
            self._add_status_button(row_frame, txt, bg, colors["highlight"] if is_selected else colors["fg"], lambda s=status: self.set_status(s)).pack(side="left", fill="x", expand=True, padx=(5, 0))
            
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
                command=lambda s=status: self.delete_custom_status(s)
            )
            delete_btn.pack(side="right", padx=(2, 5))
        
        custom_frame = tk.Frame(parent, bg=colors["bg"])
        custom_frame.pack(fill="x", pady=(8, 0), padx=5)
        
        self.custom_entry = tk.Entry(
            custom_frame,
            font=("Segoe UI", 9),
            bg=colors["hover"],
            fg=colors["fg"],
            insertbackground=colors["fg"],
            relief="flat",
            bd=0
        )
        self.custom_entry.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.custom_entry.bind("<Return>", lambda e: self.add_custom_status())
        
        add_btn = tk.Button(
            custom_frame,
            text="+",
            font=("Segoe UI", 10, "bold"),
            bg=colors["accent"],
            fg=colors["highlight"],
            activebackground=colors["accent"],
            activeforeground=colors["highlight"],
            relief="flat",
            bd=0,
            cursor="hand2",
            width=2,
            command=self.add_custom_status
        )
        add_btn.pack(side="right")
        
        tk.Frame(parent, height=1, bg=colors["border"]).pack(fill="x", pady=8)
        
        self._add_button(
            parent,
            "Open Log",
            colors["hover"],
            colors["fg"],
            self.open_log
        ).pack(fill="x", pady=1)
        
        self._add_button(
            parent,
            "Donate",
            "#0070BA",
            "white",
            self.open_donate
        ).pack(fill="x", pady=1)
        
        self._add_button(
            parent,
            "Quit",
            "#dc322f",
            "white",
            self.quit_app
        ).pack(fill="x", pady=(5, 0))
        
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
            command=command
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
            command=command
        )
        return btn
        
    def open_donate(self):
        import webbrowser
        webbrowser.open("https://www.paypal.com/donate/?hosted_button_id=VQWNYHWLKV9DL")
        
    def show(self):
        try:
            log.info("SolarizedMenu.show() called")
            t = threading.Thread(target=self._create_window, daemon=True)
            t.start()
        except Exception as e:
            log.error("SolarizedMenu.show() error: %s", e)
            import traceback
            log.error(traceback.format_exc())
        
    def hide(self):
        pass
            
    def toggle_play(self):
        log.info("Menu: Set to Playing")
        app_state["playing"] = True
        if app_state["session_start"] == 0:
            app_state["session_start"] = time.time()
        config = load_config()
        save_config({"playing": app_state["playing"], "status": app_state["status"], "custom_statuses": config.get("custom_statuses", [])})
        self._rebuild_current_window()
        
    def toggle_idle(self):
        log.info("Menu: Set to Idle")
        app_state["playing"] = False
        config = load_config()
        save_config({"playing": app_state["playing"], "status": app_state["status"], "custom_statuses": config.get("custom_statuses", [])})
        self._rebuild_current_window()
        
    def set_status(self, status):
        log.info("Menu: Status changed to '%s'", status)
        app_state["status"] = status
        config = load_config()
        custom_statuses = config.get("custom_statuses", [])
        save_config({"playing": app_state["playing"], "status": app_state["status"], "custom_statuses": custom_statuses})
        self._rebuild_current_window()
        
    def add_custom_status(self):
        status = self.custom_entry.get().strip()
        if not status:
            return
        log.info("Adding custom status: '%s'", status)
        config = load_config()
        custom_statuses = config.get("custom_statuses", [])[:5]
        if status not in custom_statuses and len(custom_statuses) < 5:
            custom_statuses.append(status)
            save_config({"playing": app_state["playing"], "status": app_state["status"], "custom_statuses": custom_statuses})
            log.info("Custom status added. Total: %d/5", len(custom_statuses))
        elif status in custom_statuses:
            log.info("Custom status '%s' already exists", status)
        elif len(custom_statuses) >= 5:
            log.warning("Cannot add more custom statuses (max 5 reached)")
        self.custom_entry.delete(0, "end")
        self._rebuild_current_window()
        
    def delete_custom_status(self, status):
        log.info("Deleting custom status: '%s'", status)
        config = load_config()
        custom_statuses = config.get("custom_statuses", [])
        if status in custom_statuses:
            custom_statuses.remove(status)
            save_config({"playing": app_state["playing"], "status": app_state["status"], "custom_statuses": custom_statuses})
            log.info("Custom status deleted. Remaining: %d", len(custom_statuses))
        if app_state["status"] == status:
            app_state["status"] = STATUS_PRESETS[0]
            save_config({"playing": app_state["playing"], "status": app_state["status"], "custom_statuses": custom_statuses})
            log.info("Reset status to default: '%s'", STATUS_PRESETS[0])
        self._rebuild_current_window()
        
    def _rebuild_current_window(self):
        if self.content_frame:
            for widget in self.content_frame.winfo_children():
                widget.destroy()
            colors = SOLARIZED_DARK
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
    
    def on_left_click(icon):
        log.info("Left click detected, calling show()")
        try:
            solarized_menu.show()
        except Exception as e:
            log.error("Left click error: %s", e)
    
    def on_open_log(icon, _):
        os.startfile(_log_dir)
        
    def on_donate(icon, _):
        import webbrowser
        webbrowser.open("https://www.paypal.com/donate/?hosted_button_id=VQWNYHWLKV9DL")
        
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
            pystray.MenuItem("Donate", on_donate),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        )
        icon.menu = menu
    
    icon = pystray.Icon(
        "fl_discord_rpc",
        _make_tray_icon(),
        "FL Discord RPC",
        on_left_click=on_left_click,
    )
    
    icon_ref[0] = icon
    create_menu()
    icon.run()
    
    if HAS_KEYBOARD:
        try:
            keyboard.remove_hotkey("ctrl+shift+f")
        except:
            pass


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
    app_state["status"] = config.get("status", "Creating")
    
    log.info("Configuration loaded:")
    log.info("  - Playing: %s", app_state["playing"])
    log.info("  - Status: %s", app_state["status"])
    log.info("  - Custom statuses: %s", config.get("custom_statuses", []))
    log.info("  - Run at startup: %s", _get_startup_path())
    log.info("Starting FL Discord RPC...")
    log.info("Poll interval: %s seconds", POLL_INTERVAL)
    log.info("Clear after: %s seconds", CLEAR_AFTER)

    stop_event = threading.Event()

    icon_ref = [None]
    log.info("Starting system tray icon...")
    tray_thread = threading.Thread(target=_run_tray, args=(stop_event, icon_ref), daemon=True)
    tray_thread.start()

    rpc = DiscordRPC(DISCORD_CLIENT_ID)

    last_seen_fl = 0.0
    fl_was_open = False
    last_project = ""
    
    log.info("Main loop started. Waiting for FL Studio...")

    while not stop_event.is_set():
        hwnd, title = _find_fl_window()

        if hwnd is None:
            if fl_was_open:
                closed_duration = time.monotonic() - last_seen_fl
                if closed_duration > CLEAR_AFTER:
                    rpc.clear()
                    fl_was_open = False
                    log.info("FL Studio closed — presence cleared after %.1f seconds", closed_duration)
        else:
            last_seen_fl = time.monotonic()
            if not fl_was_open:
                log.info("FL Studio detected! Window: '%s'", title)
            fl_was_open = True

            state = _read_fl_state(hwnd, title)
            
            if state["project"] != last_project:
                log.info("Project changed: '%s' -> '%s'", last_project or "(none)", state["project"])
                last_project = state["project"]
            
            state["playing"] = app_state["playing"]
            
            if app_state["playing"] and app_state["session_start"] == 0:
                app_state["session_start"] = time.time()
                log.info("Session started. Status: '%s'", app_state["status"])
            
            rpc_start = app_state["session_start"] if app_state["playing"] and app_state["session_start"] > 0 else 0
            kwargs = build_presence(state, rpc_start, app_state["status"])
            
            last_playing = getattr(rpc, '_last_playing', None)
            last_status = getattr(rpc, '_last_status', None)
            force_update = (
                app_state["playing"] != last_playing or 
                app_state["status"] != last_status
            )
            rpc.update(force=force_update, **kwargs)
            rpc._last_playing = app_state["playing"]
            rpc._last_status = app_state["status"]

        time.sleep(POLL_INTERVAL)

    log.info("Saving configuration...")
    config = load_config()
    save_config({
        "playing": app_state["playing"], 
        "status": app_state["status"],
        "custom_statuses": config.get("custom_statuses", [])
    })
    log.info("Configuration saved.")
    rpc.close()
    log.info("=" * 60)
    log.info("FL Discord RPC stopped.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
