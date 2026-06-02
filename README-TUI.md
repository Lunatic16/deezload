<p align="center">
  <a href="https://github.com/topics/deezer">
    <img src="https://cdn-files.dzcdn.net/cache/slash/images/common/logos/logo-horizontal-white-text.c409af08ede4db772948.svg" width="200" alt="Deezer Logo">
  </a>
</p>
# Deezload TUI

A terminal user interface for [deezload](./deezload.py) — browse and download music from Deezer without leaving your terminal.

![Python 3.7+](https://img.shields.io/badge/python-3.7%2B-blue)
![Textual](https://img.shields.io/badge/TUI-Textual-purple)

---

## Requirements

Both files must live in the same directory:

```
deezload.py       ← original downloader (unchanged)
deezload_tui.py   ← this TUI wrapper
```

Install dependencies:

```bash
pip install textual deezer-py requests pycryptodome mutagen
```

---

## Getting Your ARL Token

The ARL token is a session cookie that authenticates you with Deezer. To find it:

1. Log in to [deezer.com](https://www.deezer.com) in your browser
2. Open DevTools → Application → Cookies → `https://www.deezer.com`
3. Copy the value of the `arl` cookie

> **Keep it private.** The ARL grants full access to your Deezer account. The config file is saved with `chmod 600` (owner read/write only).

---

## Usage

```bash
# Launch and enter your ARL in the auth dialog
python deezload_tui.py

# Pass your ARL directly (saves it to config automatically)
python deezload_tui.py --arl YOUR_ARL_TOKEN
```

Once authenticated, your token is saved to `~/.config/deezload/deezload-config.ini` and loaded automatically on future launches.

---

## Interface Overview

```
┌───────────────────────────────────────────────────────────────┐
│  Header                                               status  │
├─────────────┬─────────────────────────────────────────────────┤
│ 🎵 Deezload │  [ Search input...                 ] [Search]   │
│─────────────│─────────────────────────────────────────────────│
│ 🔍 Search   │                                                 │
│ 💿 Albums   │   Results table                                 │
│ 🎵Playlists │   (Type | Title | Artist | Extra)               │
│ 👤 Artists  │                                                 │
│ ⬇ Downloads │                                                 │
│             ├─────────────────────────────────────────────────│
│ 👤 username │  ⬇ Downloads                                    │
│             │  [████████░░░░░░░░░░░░] 45.2%                    │
│             │  ✓ Artist - Track.flac                          │
│             │  ✓ Artist - Track.flac                          │
└─────────────┴─────────────────────────────────────────────────┘
```

### Sidebar

| Item | Description |
|------|-------------|
| 🔍 Search | Focus the search bar |
| 💿 Albums | Your saved/favourite albums |
| 🎵 Playlists | Your playlists |
| 👤 Artists | Your followed artists |
| ⬇ Downloads | Focus the download log |

### Search Bar

- Type any **artist, album, or track name** to search Deezer
- Paste a **Deezer URL** directly — the content type is auto-detected:
  - `deezer.com/track/…` → single track
  - `deezer.com/album/…` → album browser
  - `deezer.com/playlist/…` → playlist browser
  - `deezer.com/artist/…` → artist's discography
  - Share links (e.g. `deezer.page.link/…`) are resolved automatically

### Results Table

Columns: **Type · Title · Artist / Info · Extra** (duration or track count)

Press `Enter` on any row to act on it:

| Row type | Action |
|----------|--------|
| 🎵 Track | Starts downloading immediately |
| 💿 Album | Opens track list modal |
| 🎶 Playlist | Opens track list modal |
| 👤 Artist | Loads artist's albums into the table |

### Track List Modal

When you open an album or playlist, a modal shows all tracks with title, artist, and duration. Press **Download all** to queue the entire release, or **Close** to go back.

### Download Panel

A progress bar and scrolling log sit at the bottom of the screen at all times. Individual track progress is shown as a percentage. Completed and failed downloads are logged with ✓ / ✗ indicators.

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+A` | Open auth dialog (enter / change ARL token) |
| `Ctrl+S` | Open settings (quality + output directory) |
| `Ctrl+D` | Download the currently selected row |
| `Enter` | Open / act on selected row |
| `F5` | Reconnect to Deezer |
| `Escape` | Close modal / return to search |
| `Ctrl+Q` | Quit |

---

## Settings

Press `Ctrl+S` to open the settings modal.

| Setting | Options | Default |
|---------|---------|---------|
| Audio quality | MP3 128 / MP3 320 / FLAC | FLAC |
| Output directory | Any path | `downloads` |

Settings are persisted to `~/.config/deezload/deezload-config.ini` alongside your ARL token. You can also override the config path with the `DEEZLOAD_CONFIG` environment variable.

---

## File Structure

```
deezload/
├── deezload.py        # Core downloader (do not modify)
├── deezload_tui.py    # TUI — run this
├── README.md
└── downloads/         # Created automatically on first download
    └── Artist - Album/
        ├── 01 - Artist - Track.flac
        ├── 02 - Artist - Track.flac
        └── Cover.jpg
```

Album downloads are organised into `Artist - Album/` subdirectories with zero-padded track numbers. A `Cover.jpg` is saved alongside the tracks. Files are written to a `.part` temporary file and renamed on completion, so interrupted downloads don't leave corrupt files behind.

---

## Troubleshooting

**`MountError: Can't mount widget(s) before ListView is mounted`**
Make sure you're using the latest version of `deezload_tui.py` — this was a bug in an earlier release.

**Auth fails / "Check your ARL token"**
ARL tokens expire when you log out of Deezer or change your password. Fetch a fresh one from your browser cookies and press `Ctrl+A` to re-enter it.

**FLAC downloads fail but MP3 works**
FLAC requires a Deezer HiFi subscription. Switch quality to MP3 320 in settings (`Ctrl+S`) if you don't have one.

**`mutagen not installed` warning**
Tags (artist, album art, etc.) won't be embedded without mutagen. Install it with:
```bash
pip install mutagen
```
