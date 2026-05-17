<p align="center">
  <a href="YOUR_DEEZER_LINK_HERE">
    <img src="https://cdn-files.dzcdn.net/cache/slash/images/common/logos/logo-horizontal-white-text.c409af08ede4db772948.svg" width="200" alt="Deezer Logo">
  </a>
</p>
# Deezload - Deezer Music Downloader CLI

A command-line tool for downloading music from Deezer with full metadata tagging. Supports individual tracks, full playlists, and complete albums in MP3 or lossless FLAC quality.

---

## Features

- Download tracks, playlists, and albums from Deezer URLs or IDs
- Three quality tiers: MP3 128kbps, MP3 320kbps, FLAC (lossless)
- On-the-fly Blowfish stream decryption
- Full metadata tagging — title, artist, album, track/disc numbers, year, genre, ISRC, BPM, lyrics, and embedded cover art (1000×1000)
- Supports both MP3 (ID3v2) and FLAC (Vorbis comments) tag formats
- Persistent config file — save your ARL token once, omit it from every subsequent command
- Automatic retry on HTTP failures with exponential backoff
- Album downloads organised into `Artist - Album/` subdirectories with zero-padded track numbers

---

## Requirements

- Python 3.7+
- A Deezer account with a valid ARL token (see [Getting your ARL token](#getting-your-arl-token))

---

## Installation

Clone or download the script, then install dependencies:

```bash
pip install -r requirements.txt
```

Or install manually:

```bash
pip install deezer-py requests pycryptodome mutagen
```

`mutagen` is optional — without it, files will still download but without metadata tags.

---

## Getting Your ARL Token

The ARL (Authentication Remember Login) token is a long-lived session cookie used to authenticate with Deezer's API.

1. Log in to [deezer.com](https://www.deezer.com) in your browser
2. Open DevTools → Application (Chrome) or Storage (Firefox) → Cookies → `https://www.deezer.com`
3. Find the cookie named `arl` and copy its value

> **Note:** Keep your ARL token private. It grants full access to your Deezer account.

---

## Quick Start

```bash
# Download a track (FLAC by default)
python deezload.py --arl YOUR_ARL_TOKEN --url "https://www.deezer.com/track/3135556"

# Save your token so you don't have to pass it every time
python deezload.py --arl YOUR_ARL_TOKEN --save-config

# Now download without --arl
python deezload.py --url "https://www.deezer.com/track/3135556"
```

---

## Usage

```
python deezload.py [OPTIONS]
```

### Options

| Option | Description |
|---|---|
| `--arl TOKEN` | ARL authentication token (can be stored in config) |
| `--url URL` | Deezer URL — auto-detects track, playlist, or album |
| `--track-id ID` | Download a single track by its numeric Deezer ID |
| `--playlist URL` | Download all tracks from a playlist URL |
| `--album URL` | Download all tracks from an album URL |
| `--output DIR` | Output directory (default: `downloads/`) |
| `--save-config` | Save current `--arl`, `--quality`, and `--output` as defaults |
| `--show-config` | Print current configuration and exit |

### Advanced Options

| Option | Description | Default |
| :--- | :--- | :--- |
| `--quality QUALITY` | Audio quality: `MP3_128`, `MP3_320`, or `FLAC` | `FLAC` |
| `--concurrency` | Number of parallel download threads | `1` |
| `--output` | Custom output directory path | Current Directory |
| `--dry-run` | Preview downloads without saving files | Disabled |
| `--verbose` | Enable debug logging | Disabled |

### Examples

```bash
# Single track by URL
python deezload.py --url "https://www.deezer.com/track/3135556"

# Single track by ID, MP3 320
python deezload.py --track-id 3135556 --quality MP3_320

# Full album, saved to a custom directory
python deezload.py --album "https://www.deezer.com/album/302127" --output ~/Music

# Full playlist
python deezload.py --playlist "https://www.deezer.com/playlist/1963962142"

# Download at 128kbps MP3
python deezload.py --url "https://www.deezer.com/track/3135556" --quality MP3_128
```

---

## Output Structure

**Single track:**
```
downloads/
└── Artist Name - Track Title.flac
```

**Album:**
```
downloads/
└── Artist Name - Album Title/
    ├── Cover.jpg
    ├── 01 - Artist Name - Track One.flac
    ├── 02 - Artist Name - Track Two.flac
    └── 03 - Artist Name - Track Three.flac
```

**Playlist:**
```
downloads/
├── Artist A - Track One.flac
├── Artist B - Track Two.flac
└── Artist C - Track Three.flac
```

File extension is `.flac` for FLAC quality, `.mp3` for both MP3 tiers.

---

## Configuration

Settings are stored in an INI file, created automatically on first `--save-config` run.

**Default location:** `~/.config/deezload/deezload-config.ini`

**Override with environment variable:**
```bash
export DEEZLOAD_CONFIG=/path/to/my-config.ini
```

**Config file format:**
```ini
[deezer]
arl_token = your_arl_token_here
quality = FLAC
output = downloads
```

**Config management:**
```bash
# Save current settings as defaults
python deezload.py --arl YOUR_TOKEN --quality FLAC --output ~/Music --save-config

# View current config
python deezload.py --show-config
```

CLI arguments always take precedence over config file values.

---

## Metadata Tags

When `mutagen` is installed, downloaded files are tagged with all available metadata.

| Field | MP3 (ID3v2) | FLAC (Vorbis) |
|---|---|---|
| Title | TIT2 | TITLE |
| Artist | TPE1 | ARTIST |
| Album | TALB | ALBUM |
| Album Artist | TPE2 | ALBUMARTIST |
| Composer | TCOM | COMPOSER |
| Track Number | TRCK | TRACKNUMBER |
| Disc Number | TPOS | DISCNUMBER |
| Year | TYER + TDRC | DATE |
| Genre | TCON | GENRE |
| ISRC | TSRC | ISRC |
| Duration | TLEN | LENGTH |
| BPM | TBPM | BPM |
| Explicit Flag | COMM | ITUNESADVISORY |
| Lyrics | USLT | — |
| Source URL | WOAS | — |
| Cover Art | APIC | METADATA_BLOCK_PICTURE |

Cover art is downloaded at 1000×1000px and embedded as JPEG.

---

## Architecture

### Directory Structure

```
├── deezload.py                 # Main CLI entry point and core logic
├── requirements.txt            # Python dependencies
├── deezload-config.example.ini # Example configuration file
└── README.md                   # This documentation
```

### Core Logic

- **`DeezerDownloader` Class**: The central orchestrator for session authentication, URL resolution, stream decryption, and file system operations.
- **`AudioQuality` Enum**: Maps requested quality settings to Deezer's internal format IDs.
- **Metadata Tagging**: Employs `mutagen` to apply appropriate ID3 tags (MP3) or FLAC tags to downloaded files.
- **Error Handling**: Implements retry mechanisms for network requests and utilizes a centralized `log` function for progress tracking and debugging.

---

## Troubleshooting

**Authentication failed**
Your ARL token may have expired. Log out and back in to Deezer and extract a fresh token from your browser cookies.

**"No track token available"**
The track may be region-locked or unavailable on your account tier. Try a different track to confirm your token is otherwise working.

**Files download but have no tags**
`mutagen` is not installed. Run `pip install mutagen` and retry.

**Download URL errors / fallback mode**
If `deezer-py`'s `get_track_url()` fails, the script automatically falls back to constructing an encrypted CDN URL. If both fail, the track is skipped with an error message.

**A track in a playlist/album was skipped**
The script logs the error and continues to the next track. Check the console output for the specific error on the skipped track.

---

## How It Works

1. **Authentication** — logs in via your ARL cookie using `deezer-py`, which retrieves a session and license token.
2. **Track resolution** — fetches track metadata from Deezer's private gateway API (falls back to the public REST API).
3. **URL resolution** — retrieves a signed download URL via `deezer-py`. If unavailable, constructs one using AES-128-ECB encryption of the track's MD5 hash, quality tier, media version, and ID.
4. **Download + decryption** — streams the audio in 2048-byte chunks. Every third chunk is Blowfish-CBC decrypted using a key derived from the track ID and a known secret.
5. **Tagging** — writes all available metadata fields and embeds cover art using `mutagen`.

---

## Legal Notice

This tool is intended for personal use only. Downloading copyrighted music may violate Deezer's Terms of Service and applicable copyright law in your jurisdiction. You are responsible for ensuring your use complies with local laws and the terms of your Deezer subscription.
