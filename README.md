# FL Discord RPC

<p align="center">
  <img src="https://raw.githubusercontent.com/absxl/FL-Discord/main/fl_logo.png" width="140" alt="FL Discord RPC Logo">
</p>

<p align="center">
  <a href="https://github.com/absxl/FL-Discord/releases/latest">
    <img src="https://img.shields.io/badge/Download-Latest%20Release-blue?style=for-the-badge&logo=github" alt="Download Latest Release">
  </a>
</p>

<p align="center">
  <b>Show your FL Studio projects on Discord in real time</b>
</p>

---
> **⚠️ Beta Version**

A lightweight Windows app that shows your FL Studio project as Discord Rich Presence. Track your creative sessions and share what you're working on with friends!

## Screenshots

<p align="center">
  <img src="https://raw.githubusercontent.com/absxl/FL-Discord/main/tray.png" width="200" alt="Tray Menu Screenshot">
  <img src="https://raw.githubusercontent.com/absxl/FL-Discord/main/status.png" width="200" alt="Status Screenshot">
  <img src="https://raw.githubusercontent.com/absxl/FL-Discord/main/menu.png" width="200" alt="Menu Screenshot">:
</p>

## Features

- **Real-time Discord Presence** - Shows your current FL Studio project name on Discord
- **Playing/Idle Status** - Toggle between active work sessions and idle
- **Custom Statuses** - Choose from presets or create your own custom statuses (up to 3)
- **Session Timer** - Tracks how long you've been working on a project (live updates!)
- **Run at Startup** - Option to automatically start when Windows boots
- **Dark/Light Mode** - Toggle between dark and light theme
- **Keyboard Shortcut** - Press `Ctrl+Shift+F` to quickly open the menu

## Usage

### Opening the Menu

- Press **Ctrl+Shift+F** on your keyboard
- Or **right-click** the tray icon and select "Open Menu"

### Menu Options

- **Playing/Idle** - Toggle your work status
- **Status** - Select from presets or create custom statuses (up to 3)
- **Session** - Shows your current session time (live updates!)
- **Open Log** - View the application log file
- **Switch Theme** - Toggle between dark and light mode
- **Join Discord** - Join our Discord server for support
- **Donate** - Support the project!
- **Quit** - Exit the application

## Installation

### Option 1: Use Pre-built EXE

1. Download `FL Discord RPC.exe` from the releases
2. Double-click to run
3. The app will run in your system tray


### Option 2: Run from Source

1. Make sure you have **Python 3.8+** installed
2. Install dependencies:
   ```
   pip install pypresence pystray Pillow pywin32 psutil keyboard
   ```
3. Run the script:
   ```
   python fl_discord_rpc.py
   ```


## Custom Setup

The .exe version of the program will come out of the box with it's own images, if you want to change these icons and images follow this guide

### Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name (e.g., "FL Studio")
3. Copy the **Application ID**
4. Open `fl_discord_rpc.py` and replace `YOUR_CLIENT_ID_HERE` with your Application ID:
   ```python
   DISCORD_CLIENT_ID = "YOUR_CLIENT_ID_HERE"  # Your ID here
   ```
5. Upload artwork assets in the Discord Developer Portal:
   - **Large image**: `fl_logo` (your FL Studio themed image)
   - **Small images**: `icon_play`, `icon_pause`

### Building the EXE (Optional)

If you want to build your own EXE:

1. Run `build.bat`
2. Find your EXE in the `dist` folder
3. Share `dist\FL Discord RPC.exe` with friends!

## Status Presets

- Creating
- Mixing
- Mastering
- Sound Design
- Arranging
- Composing
- Producing
- Editing

Plus up to **3 custom statuses** you can create!

## Files & Locations

- **Config**: `%APPDATA%\FLDiscordRPC\config.json`
- **Logs**: `%APPDATA%\FLDiscordRPC\fl_discord_rpc.log`
- **Logs are limited to 1MB** to save disk space

## Troubleshooting

### Discord shows "FL Discord RPC" instead of my project name?

1. Make sure your Discord Client ID is set correctly in the script
2. Check the log file for any errors: `%APPDATA%\FLDiscordRPC\fl_discord_rpc.log`

### App doesn't detect FL Studio?

1. Make sure FL Studio window title includes the project name
2. The format should be: `ProjectName - FL Studio`

### Menu doesn't open on left-click?

Try:
- Press `Ctrl+Shift+F` to open the menu
- Right-click the tray icon and select "Open Menu"

## Support

Having issues? Check the log file at:
```
%APPDATA%\FLDiscordRPC\fl_discord_rpc.log
```

## Contributing

Want to contribute? Feel free to reach out!

- **Discord**: @amidnightgospel
- **GitHub**: @absxl

## Donate

If you find this tool useful, consider supporting its development:

[![Donate with PayPal](https://www.paypalobjects.com/webstatic/mktg/Logo/pp-logo-100px.png)](https://www.paypal.com/donate/?hosted_button_id=VQWNYHWLKV9DL)
