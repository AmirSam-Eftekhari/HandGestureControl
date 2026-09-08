# Configuration

The application does not read a config file from this folder at
runtime. Settings are loaded from and saved to a per-user config
directory (`app/config/settings.py`):

- Linux: `$XDG_CONFIG_HOME/hand_gesture_control/settings.json`
  (or `~/.config/hand_gesture_control/settings.json`)
- Windows: `%APPDATA%\hand_gesture_control\settings.json`
- macOS: `~/.config/hand_gesture_control/settings.json`

This keeps user-specific settings (camera index, gesture mappings you've
customized, etc.) out of the repository and out of version control. The
full schema and factory defaults are in `app/config/schema.py` and
`app/config/defaults.py` if you want to see every available field.
