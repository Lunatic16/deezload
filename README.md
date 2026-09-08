<p align="center">
  <a href="https://github.com/topics/deezer">
    <img src="https://cdn-files.dzcdn.net/cache/slash/images/common/logos/logo-horizontal-white-text.c409af08ede4db772948.svg" width="200" alt="Deezer Logo">
  </a>
</p>

# Deezload - Deezer Music Downloader CLI

A fast, feature-complete command-line tool for downloading music from Deezer. Supports tracks, albums, playlists, and full artist discographies in lossless FLAC or MP3, with parallel downloads, rich metadata tagging, embedded cover art, and share link resolution.

---

## Features

- **Any Deezer URL** — tracks, albums, playlists, artists, and share/redirect links all work with a single `--url` flag
- **Search Deezer directly** — no URL needed: `--search "query"` finds tracks/albums/artists/playlists and lets you pick one (or auto-pick with `--search-index` for scripts)
- **Three quality tiers** — MP3 128kbps, MP3 320kbps, FLAC lossless (default)
- **Automatic quality fallback** — if the requested quality isn't actually available for a track, Deezload steps down (FLAC → MP3 320 → MP3 128) instead of failing the download; set a floor with `--min-quality` if you'd rather skip a track than accept a low bitrate
- **Resumable, retried downloads** — interrupted downloads resume from where they left off instead of restarting, with configurable retry attempts (`--retries`) and automatic backoff
- **Parallel downloads** — configurable thread count with a per-slot live progress bar per thread
- **Full metadata tagging** — 16+ fields written to ID3v2 (MP3) and Vorbis comments (FLAC)
- **Lyrics** — plain lyrics embedded as a tag (both formats); synced lyrics embedded as ID3 `SYLT` for MP3 and written as a `.lrc` sidecar file for both formats
- **Cover art** — embedded at 1000×1000px; also saved as `Cover.jpg` in album folders
- **Multi-disc album support** — filenames include the disc number (`1-01 - ...`) whenever an album has more than one disc, so discs don't interleave
- **Skip existing files** — re-running on the same folder skips already-downloaded tracks
- **Safe filenames** — only replaces the 9 actually-illegal filesystem characters, preserving accents, apostrophes, and Unicode
- **Persistent config** — save your ARL token once, never type it again (or use the `DEEZLOAD_ARL` environment variable)
- **Share link resolution** — `deezer.page.link`, `link.deezer.com`, and other redirect URLs resolved automatically
- **Dry run mode** — preview what would be downloaded without writing any files
- **Run summary** — a one-line recap after every run: how many downloaded, how many fell back to a lower quality, how many already existed, how many failed
- **Optional log file** — `--log-file` keeps a full record of a run even when the console is running `--quiet`
- **Graceful failure** — a failed download's `.part` file is kept (not deleted) so the next run can resume it instead of starting over; completed files are never re-downloaded

---

## Requirements

- Python 3.7+
- A premium Deezer account with a valid ARL token (see [Getting your ARL token](#getting-your-arl-token))

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

> **Note:** Keep your ARL token private. It grants full access to your Deezer account. `--show-config` redacts the token when printing your config file, but treat any saved config file itself (and shell history containing `--arl`) with the same care as a password.

---

## Quick Start

```bash
# Download a track (FLAC by default)
python deezload.py --arl YOUR_ARL_TOKEN --url "https://www.deezer.com/track/3135556"

# Save your token so you don't have to pass it every time
python deezload.py --arl YOUR_ARL_TOKEN --save-config

# Now download without --arl
python deezload.py --url "https://www.deezer.com/track/3135556"

# Share links work too
python deezload.py --url "https://link.deezer.com/s/33i3Lx16xPyuahDtZguSl"

# Don't have a URL? Search instead
python deezload.py --search "Daft Punk Harder Better Faster Stronger"
```

---

## Usage

```
python deezload.py [OPTIONS]
```

### Options

| Option | Description |
|---|---|
| `--arl TOKEN` | ARL authentication token (can be stored in config or `DEEZLOAD_ARL`) |
| `--url URL` | Deezer URL — auto-detects track, playlist, album, or artist |
| `--track-id ID` | Download a single track by its numeric Deezer ID |
| `--playlist URL` | Download all tracks from a playlist URL |
| `--album URL` | Download all tracks from an album URL |
| `--search QUERY` | Search Deezer and pick a result to download (interactive, or use `--search-index`) |
| `--search-type TYPE` | Type of content to search for: `track`, `album`, `artist`, `playlist` (default: `track`) |
| `--search-index N` | Auto-select result `N` (1-based) from `--search` without prompting — for scripts |
| `--output DIR` | Output directory (default: `downloads/`) |
| `--save-config` | Save current `--arl`, `--quality`, and `--output` as defaults |
| `--show-config` | Print current configuration and exit |

### Advanced Options

| Option | Description | Default |
| :--- | :--- | :--- |
| `--quality QUALITY` | Audio quality: `MP3_128`, `MP3_320`, or `FLAC`. Falls back to the next lower tier automatically if a track isn't available at the requested quality | `FLAC` |
| `--min-quality QUALITY` | Floor for automatic fallback — never drop below this tier even if `--quality` isn't available | No floor (falls to `MP3_128`) |
| `--concurrency N` | Number of parallel download threads | `1` |
| `--retries N` | Attempts per track before giving up; resumes from the partial file between attempts | `3` |
| `--no-lyrics` | Skip fetching lyrics (plain + synced) to speed up downloads | Lyrics fetched |
| `--output` | Custom output directory path | Current Directory |
| `--dry-run` | Preview downloads without saving files | Disabled |
| `--verbose` | Enable debug logging | Disabled |
| `--quiet` | Suppress all non-error output | Disabled |
| `--log-file PATH` | Also write a full log (every level, ignoring `--quiet`) to this file | Not set |

### Examples

```bash
# Single track
python deezload.py --url "https://www.deezer.com/track/3135556"

# Album — creates an Artist - Album/ subdirectory with Cover.jpg
python deezload.py --url "https://www.deezer.com/album/302127"

# Playlist
python deezload.py --url "https://www.deezer.com/playlist/1963962142"

# Full artist discography
python deezload.py --url "https://www.deezer.com/artist/246791"

# Share link (resolved automatically, no extra flags needed)
python deezload.py --url "https://link.deezer.com/s/33i3Lx16xPyuahDtZguSl"

# Album at MP3 320 with 4 parallel threads
python deezload.py --album "https://www.deezer.com/album/302127" --quality MP3_320 --concurrency 4

# Preview an album without downloading anything
python deezload.py --url "https://www.deezer.com/album/302127" --dry-run

# Download to a specific folder, silently (good for scripts)
python deezload.py --url "https://www.deezer.com/album/302127" --output ~/Music --quiet

# Search and pick interactively
python deezload.py --search "Daft Punk" --search-type artist

# Search and auto-pick the top result — good for scripts/automation
python deezload.py --search "Get Lucky Daft Punk" --search-index 1

# Never accept below MP3 320, even if FLAC isn't available for a track
python deezload.py --url "https://www.deezer.com/album/302127" --min-quality MP3_320

# Flaky connection: retry up to 5 times per track, log everything to a file
python deezload.py --url "https://www.deezer.com/playlist/1963962142" --retries 5 --log-file deezload.log

# Skip the lyrics lookup for a faster batch run
python deezload.py --url "https://www.deezer.com/album/302127" --no-lyrics
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
    ├── 01 - Artist Name - Track One.lrc      # only if synced lyrics were found
    ├── 02 - Artist Name - Track Two.flac
    └── 03 - Artist Name - Track Three.flac
```

**Multi-disc album** (filenames include the disc number so discs don't interleave):
```
downloads/
└── Artist Name - Album Title/
    ├── Cover.jpg
    ├── 1-01 - Artist Name - Track One.flac
    ├── 1-02 - Artist Name - Track Two.flac
    ├── 2-01 - Artist Name - Track One.flac
    └── 2-02 - Artist Name - Track Two.flac
```

**Playlist:**
```
downloads/
├── Artist A - Track One.flac
├── Artist B - Track Two.flac
└── Artist C - Track Three.flac
```
**Artist discography:**
```
downloads/
├── Artist - Album 1/
│   ├── Cover.jpg
│   └── 01 - Artist - Track One.flac
├── Artist - Album 2/
│   ├── Cover.jpg
│   └── ...
└── ...
```

File extension is `.flac` for FLAC quality, `.mp3` for both MP3 tiers, based on the quality actually downloaded — if a track fell back to a lower tier, the extension reflects that, not the tier you requested. A `.lrc` file is written alongside a track only when Deezer has synced lyrics for it.

---

## Configuration

Settings are stored in an INI file, created automatically on first `--save-config` run.

**Default location:** `~/.config/deezload/deezload-config.ini`

**Override with environment variable:**
```bash
export DEEZLOAD_CONFIG=/path/to/my-config.ini
```

**ARL token via environment variable** (useful for CI/headless boxes without a config file on disk):
```bash
export DEEZLOAD_ARL=your_arl_token_here
python deezload.py --url "https://www.deezer.com/track/3135556"
```
Precedence when a token comes from more than one place: `--arl` > `DEEZLOAD_ARL` > saved config.

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
| Genre | TCON (resolved from genre ID via API) | GENRE (resolved from genre ID via API) |
| ISRC | TSRC | ISRC |
| Duration | TLEN | LENGTH |
| BPM | TBPM | BPM |
| Explicit Flag | COMM | ITUNESADVISORY |
| Lyrics (plain) | USLT | LYRICS |
| Lyrics (synced) | SYLT, plus a `.lrc` sidecar file | `.lrc` sidecar file |
| Source URL | WOAS | — |
| Cover Art | APIC | METADATA_BLOCK_PICTURE |

Cover art is downloaded at 1000×1000px and embedded as JPEG. When a track has synced lyrics, Deezload embeds them (MP3 only, via ID3 `SYLT`) and also writes a `.lrc` file next to the track — most players (foobar2000, VLC, MusicBee, Plex, etc.) pick up sidecar `.lrc` files automatically regardless of audio format. Use `--no-lyrics` to skip the lyrics lookup entirely.

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

**Track downloaded at a lower quality than requested**
Not every track is available in every tier — FLAC in particular isn't always present. When the requested quality can't be resolved to a working URL, Deezload automatically retries at the next tier down and logs a `⚠ ... not available for this track — falling back to ...` warning. This is expected behavior, not an error; check the console output (or the end-of-run summary) to see which tier a given track actually downloaded at. Use `--min-quality` if you'd rather skip a track than accept a lower tier. If every tier fails, the track is skipped with an error message.

**A download was interrupted (network drop, Ctrl+C, etc.)**
Deezload keeps the `.part` file instead of deleting it, and resumes from that point (aligned to the internal 2048-byte block boundary) the next time you run the same command. Increase `--retries` if your connection is especially flaky — each attempt backs off (2s, 4s, 8s, ...) before trying again. If a `.part` file is ever left over from a genuinely different track at the same path, Deezload detects the server rejecting the resume point (HTTP 416) and restarts cleanly from scratch.

**`--search` doesn't find what I'm looking for**
Try `--search-type album` or `--search-type artist` instead of the default `track` search, or narrow the query (add the artist name). `--search-index N` skips the interactive prompt entirely and picks result `N` — handy in scripts, but only use it once you've confirmed what result 1 actually is.

**A track in a playlist/album was skipped**
The script logs the error and continues to the next track. Check the console output (or `--log-file`) for the specific error on the skipped track.

---

## How It Works

1. **Share link resolution** — every URL is passed through `resolve_deezer_url()`, which follows redirects and strips tracking parameters to produce a clean canonical URL. Canonical `deezer.com` URLs are returned immediately with no HTTP request. (`--search` skips this entirely and resolves a query directly to a track/album/artist/playlist ID via Deezer's public search API.)
2. **Authentication** — logs in via ARL cookie using `deezer-py`, retrieving a session and license token.
3. **Track info** — metadata is fetched from Deezer's private gateway API (`gw.get_track`), with automatic fallback to the public REST API at `api.deezer.com`.
4. **Download URL** — a signed CDN URL is obtained via `deezer-py`'s token exchange for the requested quality. If that fails, a fallback URL is constructed using AES-128-ECB encryption of the track's MD5 hash, quality tier, media version, and ID. Either way, the resolved URL is verified with a small ranged request before committing to it — Deezer can return a well-formed URL for a quality tier the track doesn't actually have, which otherwise only shows up as an empty/broken file after the fact. If the requested quality isn't available, Deezload automatically retries the same resolution process at the next tier down (FLAC → MP3 320 → MP3 128, bounded below by `--min-quality` if set) and downloads whichever tier succeeds first.
5. **Stream + decrypt** — the audio stream arrives in 2048-byte chunks. Every third chunk is Blowfish-CBC decrypted using a key derived from the track ID and a fixed secret. Audio is written to a `.part` temporary file. If the connection drops partway through, the `.part` file is kept (truncated to the last complete block) so the next attempt — up to `--retries` times, with exponential backoff — resumes via an HTTP `Range` request instead of starting over. Once the full expected size is verified, the file is atomically renamed to its final path.
6. **Lyrics** — unless `--no-lyrics` is set, synced and plain lyrics are fetched from Deezer's authenticated lyrics endpoint. Synced lyrics are embedded as an ID3 `SYLT` frame (MP3) and written as a `.lrc` sidecar file (both formats); plain lyrics are embedded as USLT (MP3) or a `LYRICS` Vorbis comment (FLAC).
7. **Tagging** — all available metadata fields (including genre, resolved from its numeric ID via the API) and cover art are written using `mutagen`.
8. **Summary** — after any non-dry-run download, a one-line summary reports how many tracks succeeded, how many fell back to a lower quality, how many already existed, and how many failed.

---

## Legal Notice

This tool is intended for personal use only. Downloading copyrighted music may violate Deezer's Terms of Service and applicable copyright law in your jurisdiction. You are responsible for ensuring your use complies with local laws and the terms of your Deezer subscription.
