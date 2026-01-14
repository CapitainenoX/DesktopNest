# 🖥️ DesktopNest

**DesktopNest** is a modern, minimalist file manager built in **Python** using **PySide6**.  
It allows you to navigate, organize, and manage your **real system files** with a sleek, responsive interface.

---

## Key Features

- **Full file system access**: Browse and manage files from any root (e.g., `C:/` or `/home`).
- **Drag & Drop**: Move files and folders in real-time.
- **CRUD Operations**: Create, rename, and delete files/folders directly on disk.
- **Quick Search**: Threaded search with interactive results.
- **Dark/Light Theme**: Modern themes with readable text.
- **Customizable View**:
  - Tree view + Grid view (icon mode)
  - Hide hidden/system files or patterns (`*.secret`, `.env`, etc.)
  - Optionally hide file extensions
- **Favorites**: Quick access to frequently used files/folders.
- **Context Menu**: Right-click for all actions.
- **Performance-focused**: Threaded search, responsive interface, drag & drop optimized.
- **Persistent Settings**: Saves preferences and favorites in `~/.desktopnest_settings.json` and `~/.desktopnest_favorites.json`.

---

## 🛠 Installation

1. Clone the repository or download `Main.py`.
2. Install dependencies:

```bash
pip install PySide6
