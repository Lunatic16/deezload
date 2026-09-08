#!/usr/bin/env python3
"""
Deezer Music Downloader CLI

A command-line tool to download music from Deezer using ARL token authentication.
This tool uses the deezer-py library for authentication and streamrip's approach
for URL generation and download.

Requirements:
 - Python 3.7+
 - deezer-py
 - requests
 - pycryptodome
 - mutagen

Usage:
 python deezload.py --arl <YOUR_ARL_TOKEN> --url <TRACK_OR_PLAYLIST_OR_ALBUM_URL>
 python deezload.py --arl <YOUR_ARL_TOKEN> --playlist <PLAYLIST_URL>
 python deezload.py --arl <YOUR_ARL_TOKEN> --album <ALBUM_URL>
 python deezload.py --arl <YOUR_ARL_TOKEN> --url <URL> --concurrency 4
 python deezload.py --url <URL> --dry-run
 python deezload.py --arl <TOKEN> --save-config
"""

import argparse
import base64
import concurrent.futures
import functools
import hashlib
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from enum import Enum
from configparser import ConfigParser

try:
    import deezer
except ImportError:
    print("Error: deezer-py library not installed. Run: pip install deezer-py")
    sys.exit(1)

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    print("Error: requests library not installed. Run: pip install requests")
    sys.exit(1)

try:
    from Crypto.Cipher import AES, Blowfish
except ImportError:
    print("Error: pycryptodome not installed. Run: pip install pycryptodome")
    sys.exit(1)

try:
    from mutagen.id3 import ID3, TIT2, TALB, TPE1, TPE2, TCOM, TRCK, TPOS, TYER, TCON, \
        TDRC, APIC, ID3NoHeaderError, USLT, COMM, TBPM, WOAS, TSRC, TLEN, SYLT
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC, Picture
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    print("Warning: mutagen not installed. Tags won't be added to downloaded files.")
    print("Install with: pip install mutagen")


class AudioQuality(Enum):
    """Audio quality options matching Deezer's quality tiers"""
    MP3_128 = "MP3_128"  # Quality tier 1
    MP3_320 = "MP3_320"  # Quality tier 3
    FLAC = "FLAC"        # Quality tier 6 (HiFi)

    @property
    def format_id(self) -> int:
        """Get the format ID used in API calls"""
        mapping = {
            "MP3_128": 1,
            "MP3_320": 3,
            "FLAC": 6
        }
        return mapping.get(self.value, 1)


# Fallback order: highest to lowest quality. Used when the requested
# quality isn't actually available for a given track.
QUALITY_FALLBACK_ORDER = [AudioQuality.FLAC, AudioQuality.MP3_320, AudioQuality.MP3_128]


# Global verbosity flag — set by main() from --verbose / --quiet args
_VERBOSE = False
_QUIET = False

# Optional log file handle — set by main() from --log-file. When set,
# every log() call (regardless of level) is also written here, so the
# file keeps a full record even when the console is running --quiet.
_LOG_FILE_HANDLE = None


def log(msg: str, level: str = "info") -> None:
    """
    Centralised print with verbosity control.

    Levels:
      debug  — only printed when --verbose is set
      info   — printed unless --quiet is set
      warn   — always printed
      error  — always printed
    """
    if _LOG_FILE_HANDLE is not None:
        try:
            _LOG_FILE_HANDLE.write(f"[{level}] {msg}\n")
            _LOG_FILE_HANDLE.flush()
        except Exception:
            pass  # Never let logging-to-file problems break the actual download

    if level == "debug" and not _VERBOSE:
        return
    if level == "info" and _QUIET:
        return
    print(msg)


class DeezerDownloader:
    """Main downloader class that handles authentication and downloads"""

    # API Endpoints
    API_BASE = "https://www.deezer.com/ajax/gw-light.php"

    # CDN domains
    CDN_DOMAINS = {
        "images": "https://cdn-images.dzcdn.net",
        "assets": "https://cdn-assets.dzcdn.net",
    }

    # Blowfish key for encrypted downloads (from streamrip)
    BLOWFISH_SECRET = "g4el58wc0zvf9na1"

    def __init__(self, arl_token: str, quality: AudioQuality = AudioQuality.FLAC,
                 concurrency: int = 1, min_quality: Optional[AudioQuality] = None,
                 max_retries: int = 3, fetch_lyrics: bool = True):
        """
        Initialize the downloader with ARL authentication.

        Args:
            arl_token: ARL (Authentication Remember Login) token
            quality: Desired audio quality
            concurrency: Number of parallel download threads
            min_quality: Lowest quality tier the automatic fallback is allowed
                         to drop to (None = fall all the way to MP3_128)
            max_retries: Attempts per track (with resume between attempts)
                         before giving up
            fetch_lyrics: Whether to fetch plain + synced lyrics per track
        """
        self.arl_token = arl_token
        self.quality = quality
        self.concurrency = concurrency
        self.min_quality = min_quality
        self.max_retries = max(1, max_retries)
        self.fetch_lyrics_enabled = fetch_lyrics
        self.session = self._create_session()
        self.client = deezer.Deezer()
        self.user_id: Optional[str] = None
        self.license_token: Optional[str] = None
        self._genre_cache: Dict[str, Optional[str]] = {}
        self._stats_lock = threading.Lock()
        self.stats: Dict[str, int] = {
            'succeeded': 0, 'fallback': 0, 'failed': 0, 'skipped_existing': 0
        }

    def print_summary(self) -> None:
        """Print a one-line summary of everything downloaded in this run."""
        s = self.stats
        if not any(s.values()):
            return
        parts = [f"{s['succeeded']} downloaded"]
        if s['fallback']:
            parts.append(f"{s['fallback']} at reduced quality")
        if s['skipped_existing']:
            parts.append(f"{s['skipped_existing']} already existed")
        if s['failed']:
            parts.append(f"{s['failed']} failed")
        log("")
        log("Summary: " + ", ".join(parts) + ".")

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic and timeouts"""
        session = requests.Session()

        # Set up retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set headers to mimic official app
        session.headers.update({
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 14; Deezer/8.21.18.1)",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/json",
        })

        # Default timeouts: 10s connect, 60s read
        session.request = functools.partial(session.request, timeout=(10, 60))  # type: ignore

        return session

    def authenticate(self) -> bool:
        """
        Authenticate using ARL token.

        Returns:
            True if authentication successful
        """
        try:
            # Use deezer-py library for authentication
            success = self.client.login_via_arl(self.arl_token)
            if success:
                # Get user info from current_user (available after login)
                user_data = self.client.current_user
                self.user_id = str(user_data.get('id', ''))
                log(f"✓ Authenticated as user: {user_data.get('name', 'Unknown')} (ID: {self.user_id})")

                # Store license token for later use
                if 'license_token' in user_data:
                    self.license_token = user_data['license_token']

                return True
            else:
                log("✗ Authentication failed. Check your ARL token.", level="error")
                return False
        except Exception as e:
            log(f"✗ Authentication error: {e}", level="error")
            return False

    def get_track_info(self, track_id: str) -> Optional[Dict[str, Any]]:
        """
        Get track information from Deezer API.

        Args:
            track_id: Deezer track ID

        Returns:
            Track information dictionary or None
        """
        try:
            # Use deezer-py's gateway API (returns more detailed info)
            track = self.client.gw.get_track(track_id)
            if track:
                return track
        except Exception as e:
            log(f"Error getting track info via gateway: {e}", level="debug")

        # Fallback: try direct API
        try:
            response = self.session.get(
                f"https://api.deezer.com/2.0/track/{track_id}"
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            log(f"Error getting track info (fallback): {e}", level="debug")

        return None

    def get_cover_art_url(self, track_info: Dict[str, Any], size: str = 'large') -> Optional[str]:
        """
        Get the cover art URL from track info.

        Args:
            track_info: Track information dictionary
            size: Image size ('small', 'medium', 'large', 'xl')

        Returns:
            Cover art URL or None
        """
        # Try different possible keys for cover art
        cover_keys = ['ALB_PICTURE', 'picture', 'album.picture', 'cover', 'image']

        for key in cover_keys:
            if key in track_info:
                picture_id = track_info[key]
                if picture_id:
                    # Deezer picture sizes: 56x56, 250x250, 500x500, 1000x1000
                    size_map = {
                        'small': '56x56',
                        'medium': '250x250',
                        'large': '500x500',
                        'xl': '1000x1000'
                    }
                    size_str = size_map.get(size, '500x500')
                    return f"https://cdns-images.dzcdn.net/images/cover/{picture_id}/{size_str}-000000-80-0-0.jpg"

        # Fallback: try to get from album API
        album_id = track_info.get('ALB_ID') or track_info.get('album', {}).get('id', '')
        if album_id:
            try:
                response = self.session.get(f"https://api.deezer.com/2.0/album/{album_id}")
                if response.status_code == 200:
                    album_data = response.json()
                    cover = album_data.get('cover_xl') or album_data.get('cover_big') or album_data.get('cover_medium')
                    if cover:
                        return cover
            except Exception:
                pass

        return None

    def download_cover_art(self, url: str) -> Optional[bytes]:
        """
        Download cover art image.

        Args:
            url: Cover art URL

        Returns:
            Image data as bytes or None
        """
        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.content
        except Exception as e:
            log(f" Warning: Could not download cover art: {e}", level="warn")
            return None

    def _generate_blowfish_key(self, track_id: str) -> bytes:
        """Generate the blowfish key for Deezer downloads."""
        md5_hash = hashlib.md5(track_id.encode()).hexdigest()
        return "".join(
            chr(functools.reduce(lambda x, y: x ^ y, map(ord, t)))
            for t in zip(md5_hash[:16], md5_hash[16:], self.BLOWFISH_SECRET)
        ).encode()

    def _decrypt_chunk(self, key: bytes, data: bytes) -> bytes:
        """Decrypt a chunk of a Deezer stream."""
        return Blowfish.new(
            key,
            Blowfish.MODE_CBC,
            b"\x00\x01\x02\x03\x04\x05\x06\x07",
        ).decrypt(data)

    def get_download_url(self, track_id: str,
                         track_info: Optional[Dict[str, Any]] = None,
                         quality: Optional[AudioQuality] = None) -> Tuple[Optional[str], Optional[AudioQuality]]:
        """
        Get the download URL for a track using deezer-py library.

        Tries the requested quality first, then steps down through
        QUALITY_FALLBACK_ORDER (e.g. FLAC -> MP3_320 -> MP3_128) if the
        requested quality resolves to a URL that isn't actually playable
        (Deezer returns a "valid-looking" URL even for unavailable
        qualities — the CDN just serves an empty/short response for it).

        Args:
            track_id: Deezer track ID
            track_info: Pre-fetched track info dict (avoids a redundant API call)
            quality: Quality to request (defaults to self.quality)

        Returns:
            Tuple of (download URL or None, the AudioQuality actually resolved or None)
        """
        # Reuse caller's track_info if provided; otherwise fetch once
        if track_info is None:
            track_info = self.get_track_info(track_id)
        if not track_info:
            return None, None

        requested_quality = quality or self.quality

        # Build the fallback chain starting at the requested quality and
        # stepping down through anything lower in QUALITY_FALLBACK_ORDER.
        try:
            start_idx = QUALITY_FALLBACK_ORDER.index(requested_quality)
        except ValueError:
            start_idx = 0
        fallback_chain = QUALITY_FALLBACK_ORDER[start_idx:]

        # Respect --min-quality: never fall back below the configured floor.
        if self.min_quality is not None and self.min_quality in QUALITY_FALLBACK_ORDER:
            min_idx = QUALITY_FALLBACK_ORDER.index(self.min_quality)
            if min_idx < start_idx:
                # The floor is a *higher* tier than what was requested — that's
                # a contradictory combination (the ceiling is already below the
                # floor), so just ignore the floor rather than blocking the
                # download entirely.
                log(f" ⚠ --min-quality {self.min_quality.value} is higher than the requested "
                    f"quality {requested_quality.value} — ignoring the floor for this track",
                    level="debug")
            else:
                fallback_chain = [q for q in fallback_chain
                                   if QUALITY_FALLBACK_ORDER.index(q) <= min_idx]

        for candidate_quality in fallback_chain:
            url = self._resolve_url_for_quality(track_id, track_info, candidate_quality)
            if not url:
                continue

            if not self._url_is_available(url):
                log(f" {candidate_quality.value} resolved but isn't actually available, trying next quality",
                    level="debug")
                continue

            if candidate_quality != requested_quality:
                log(f" ⚠ {requested_quality.value} not available for this track — "
                    f"falling back to {candidate_quality.value}", level="warn")
            else:
                log(f" ✓ URL resolved via token exchange", level="debug")

            return url, candidate_quality

        log(f" ✗ No available quality could be resolved for track {track_id}", level="error")
        return None, None

    def _resolve_url_for_quality(self, track_id: str, track_info: Dict[str, Any],
                                  quality: AudioQuality) -> Optional[str]:
        """Resolve a download URL for a specific quality, without checking availability."""
        try:
            token = track_info.get('TRACK_TOKEN')
            if not token:
                return self._construct_encrypted_url(track_id, track_info, quality)

            url = self.client.get_track_url(token, quality.value)
            if url:
                return url

            # Primary failed — fall back to encrypted URL construction
            log(" Falling back to encrypted URL construction", level="debug")
            return self._construct_encrypted_url(track_id, track_info, quality)

        except Exception as e:
            log(f"Error getting download URL: {e}", level="debug")
            return self._construct_encrypted_url(track_id, track_info, quality)

    def _url_is_available(self, url: str) -> bool:
        """
        Check whether a resolved download URL actually serves audio.

        Deezer's token exchange (and the encrypted-URL construction) can
        return a well-formed URL for a quality tier the track simply
        doesn't have — the CDN then serves a zero-length or error
        response instead of a 404. A small ranged GET is a reliable way
        to detect that before committing to a full download.
        """
        try:
            response = self.session.get(url, headers={"Range": "bytes=0-1"}, stream=True)
            available = response.status_code in (200, 206)
            if available:
                content_length = response.headers.get('content-length')
                if content_length is not None and int(content_length) == 0:
                    available = False
            response.close()
            return available
        except Exception as e:
            log(f"Availability check failed: {e}", level="debug")
            return False

    def _construct_encrypted_url(self, track_id: str, track_info: Dict[str, Any],
                                  quality: Optional[AudioQuality] = None) -> Optional[str]:
        """Construct encrypted download URL (streamrip approach)."""
        try:
            track_md5 = track_info.get('MD5_ORIGIN', '')
            media_version = str(track_info.get('MEDIA_VERSION', '1') or '1')
            quality_id = (quality or self.quality).format_id

            if not track_md5:
                log(" ✗ MD5_ORIGIN missing — cannot construct fallback URL", level="warn")
                return None

            # Build the string to encrypt
            # Format: {md5}{quality}{media_version}{track_id}
            to_encrypt = f"{track_md5}{quality_id}{media_version}{track_id}"

            # Pad to multiple of 16 bytes
            padding = 16 - (len(to_encrypt) % 16)
            to_encrypt += chr(padding) * padding

            # Encrypt with AES ECB
            key = b"jo6aey6haid2Teih"
            cipher = AES.new(key, AES.MODE_ECB)
            encrypted = cipher.encrypt(to_encrypt.encode())
            encrypted_hex = encrypted.hex()

            # Use first character of MD5 to select CDN
            cdn_index = track_md5[0]
            url = f"https://e-cdns-proxy-{cdn_index}.dzcdn.net/mobile/1/{encrypted_hex}"

            log(f" ✓ Fallback URL constructed", level="debug")
            return url
        except Exception as e:
            log(f"Error constructing encrypted URL: {e}", level="debug")
            return None

    def _resolve_genre_name(self, genre_id: Any) -> Optional[str]:
        """
        Resolve a numeric Deezer genre ID to its display name via the public
        API, caching results so a batch of tracks in the same genre only
        triggers one network call.
        """
        genre_id = str(genre_id)
        if genre_id in self._genre_cache:
            return self._genre_cache[genre_id]

        name = None
        try:
            response = self.session.get(f"https://api.deezer.com/genre/{genre_id}")
            if response.status_code == 200:
                name = response.json().get('name') or None
        except Exception as e:
            log(f"Could not resolve genre name for id {genre_id}: {e}", level="debug")

        self._genre_cache[genre_id] = name
        return name

    def _fetch_lyrics(self, track_id: str) -> Dict[str, Optional[str]]:
        """
        Fetch plain and synced lyrics for a track via the authenticated
        gateway API. Not every track has lyrics, so a miss is normal and
        silently returns empty results rather than an error.

        Returns:
            {'plain': str or None, 'synced': str or None}
            'synced' is pre-formatted as standard LRC text (one
            "[mm:ss.xx]line" entry per line).
        """
        result: Dict[str, Optional[str]] = {'plain': None, 'synced': None}

        try:
            data = self.client.gw.get_track_lyrics(track_id)
        except Exception as e:
            log(f"No lyrics available for track {track_id}: {e}", level="debug")
            return result

        if not data:
            return result

        result['plain'] = data.get('LYRICS_TEXT') or None

        sync_entries = data.get('LYRICS_SYNC_JSON')
        if sync_entries:
            lines = []
            for entry in sync_entries:
                timestamp = entry.get('lrc_timestamp')
                text = entry.get('line', '')
                if timestamp:
                    lines.append(f"{timestamp}{text}")
            if lines:
                result['synced'] = "\n".join(lines)

        return result

    @staticmethod
    def _parse_lrc_to_sylt(lrc_text: str) -> list:
        """
        Parse standard LRC text ("[mm:ss.xx]line", possibly with multiple
        timestamps per line) into a sorted list of (text, milliseconds)
        tuples suitable for an ID3 SYLT frame.
        """
        entries = []
        ts_pattern = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\]')
        for line in lrc_text.splitlines():
            timestamps = ts_pattern.findall(line)
            if not timestamps:
                continue
            text = ts_pattern.sub('', line).strip()
            for minutes, seconds in timestamps:
                ms = int(round((int(minutes) * 60 + float(seconds)) * 1000))
                entries.append((text, ms))
        entries.sort(key=lambda e: e[1])
        return entries

    def download_track(self, track_id: str, output_dir: str = "downloads",
                       track_num: Optional[int] = None,
                       disc_num: Optional[int] = None,
                       disc_total: Optional[int] = None,
                       progress_cb=None) -> Optional[str]:
        """
        Download a single track.

        Args:
            track_id: Deezer track ID
            output_dir: Directory to save downloaded file
            track_num: Optional track number (for album downloads)
            disc_num: Optional disc number (for album downloads)
            disc_total: Optional total disc count for the album this track
                        belongs to — when > 1, the disc number is folded into
                        the filename so multi-disc albums don't interleave
            progress_cb: Optional callable(pct: float) for progress updates.
                         When provided the inline \r progress bar is suppressed.

        Returns:
            Path to downloaded file or None
        """
        # In concurrent mode, suppress the noisy "Downloading track …" line;
        # the caller's slot display already shows track name + progress.
        if progress_cb is None:
            log(f"Downloading track {track_id}...")

        # Get track info once and reuse for URL resolution + tagging
        track_info = self.get_track_info(track_id)
        if not track_info:
            log(f" ✗ Could not get track info for {track_id}", level="error")
            with self._stats_lock:
                self.stats['failed'] += 1
            return None

        # Get download URL, passing track_info to avoid a second API call.
        # This automatically falls back to a lower quality if the requested
        # one isn't actually available for this track.
        download_url, resolved_quality = self.get_download_url(track_id, track_info=track_info)
        if not download_url:
            log(f" ✗ Could not get download URL for {track_id}", level="error")
            with self._stats_lock:
                self.stats['failed'] += 1
            return None

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Build filename with safe sanitisation (Enhancement 18)
        artist = track_info.get("ART_NAME") or track_info.get("artist", {}).get("name", "Unknown Artist")
        title = track_info.get("SNG_TITLE") or track_info.get("title", "Unknown Title")
        # Extension reflects the quality actually resolved (post-fallback), not the requested one
        extension = ".flac" if resolved_quality == AudioQuality.FLAC else ".mp3"
        multi_disc = bool(disc_total and disc_total > 1 and disc_num is not None)
        if track_num is not None:
            if multi_disc:
                raw_name = f"{disc_num}-{track_num:02d} - {artist} - {title}{extension}"
            else:
                raw_name = f"{track_num:02d} - {artist} - {title}{extension}"
        else:
            raw_name = f"{artist} - {title}{extension}"
        filename = sanitise_filename(raw_name)
        filepath = output_path / filename

        # Enhancement 8: skip already-downloaded files
        if filepath.exists():
            log(f" ⏭ Skipping (already exists): {filepath}")
            with self._stats_lock:
                self.stats['skipped_existing'] += 1
            return str(filepath)

        # Enhancement 6: write to a .part temp file; rename on success.
        # A .part file left behind from a prior interrupted attempt is
        # reused as a resume point rather than restarted from scratch.
        part_path = filepath.with_suffix(filepath.suffix + ".part")

        success = False
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                success = self._download_stream(download_url, part_path, track_id, progress_cb)
                if success:
                    break
                last_error = None  # Size mismatch, not an exception — still worth retrying
            except requests.exceptions.RequestException as e:
                last_error = e
            except Exception as e:
                # Non-network error (disk full, permissions, a genuine bug) —
                # not something a retry is likely to fix.
                last_error = e
                break

            if attempt < self.max_retries:
                backoff = min(2 ** attempt, 30)
                resumed_bytes = part_path.stat().st_size if part_path.exists() else 0
                resume_note = f", will resume from {resumed_bytes:,} bytes" if resumed_bytes else ""
                reason = f": {last_error}" if last_error else " (incomplete)"
                log(f" ⚠ Attempt {attempt}/{self.max_retries} failed{reason} — "
                    f"retrying in {backoff}s{resume_note}", level="warn")
                time.sleep(backoff)

        if not success:
            log(f" ✗ Download failed after {self.max_retries} attempt(s)"
                f"{': ' + str(last_error) if last_error else ''}", level="error")
            with self._stats_lock:
                self.stats['failed'] += 1
            # An empty .part file is useless to keep; anything with actual
            # bytes is left in place so a future run can resume it.
            if part_path.exists() and part_path.stat().st_size == 0:
                part_path.unlink()
            return None

        # Rename .part → final filename only after full successful write
        part_path.rename(filepath)
        if progress_cb is None and not _QUIET:
            log(f" ✓ Downloaded: {filepath.name}")

        with self._stats_lock:
            self.stats['succeeded'] += 1
            if resolved_quality != self.quality:
                self.stats['fallback'] += 1

        # Add metadata tags if mutagen is available
        if MUTAGEN_AVAILABLE:
            self._add_tags(str(filepath), track_info, track_id, silent=(progress_cb is not None))

        return str(filepath)

    def _download_stream(self, url: str, part_path: Path, track_id: str,
                          progress_cb=None) -> bool:
        """
        Perform a single download attempt, resuming from an existing .part
        file if one is present. Raises requests exceptions on network
        failures so the caller's retry loop can back off and try again;
        returns False (without raising) if the stream completed but the
        resulting file size doesn't match what the server advertised.

        Returns:
            True if the file was fully and correctly written.
        """
        chunk_size = 2048
        resume_offset = 0

        if part_path.exists():
            existing_size = part_path.stat().st_size
            # Decryption depends on knowing exactly which 2048-byte block
            # index we're resuming at, so any trailing partial chunk left
            # over from an interrupted attempt is dropped first.
            resume_offset = (existing_size // chunk_size) * chunk_size
            if resume_offset != existing_size:
                with open(part_path, 'r+b') as f:
                    f.truncate(resume_offset)

        headers = {}
        mode = 'wb'
        if resume_offset > 0:
            headers['Range'] = f'bytes={resume_offset}-'
            mode = 'ab'

        response = self.session.get(url, headers=headers, stream=True)

        if resume_offset > 0 and response.status_code == 416:
            # The server rejected our resume point (e.g. a stale/mismatched
            # .part file) — discard it and restart this attempt from scratch.
            response.close()
            log(" Existing partial file rejected by server — restarting from scratch", level="debug")
            part_path.unlink()
            return self._download_stream(url, part_path, track_id, progress_cb)

        response.raise_for_status()

        resumed = resume_offset > 0 and response.status_code == 206
        if resume_offset > 0 and not resumed:
            # Server ignored the Range header — fall back to a clean restart.
            resume_offset = 0
            mode = 'wb'

        # Work out the total expected size, for both progress % and the
        # post-download size-verification check.
        total_size = 0
        content_range = response.headers.get('content-range')  # "bytes 100-999/1000"
        if content_range and '/' in content_range:
            try:
                total_size = int(content_range.rsplit('/', 1)[-1])
            except ValueError:
                total_size = 0
        if not total_size:
            content_length = int(response.headers.get('content-length', 0))
            total_size = (resume_offset + content_length) if resumed else content_length

        downloaded = resume_offset
        block_index = resume_offset // chunk_size
        bf_key = self._generate_blowfish_key(track_id)

        if resumed:
            log(f" ↻ Resuming from {resume_offset:,} bytes", level="debug")

        try:
            with open(part_path, mode) as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    # Decrypt every 3rd full-sized block
                    if block_index % 3 == 0 and len(chunk) == chunk_size:
                        chunk = self._decrypt_chunk(bf_key, chunk)
                    f.write(chunk)
                    downloaded += len(chunk)
                    block_index += 1
                    if total_size > 0:
                        pct = (downloaded / total_size) * 100
                        if progress_cb is not None:
                            progress_cb(pct)
                        elif not _QUIET:
                            # Sequential mode: simple inline progress bar
                            bar_width = 30
                            filled = int(bar_width * pct / 100)
                            bar = "█" * filled + "░" * (bar_width - filled)
                            print(f"\r [{bar}] {pct:5.1f}%", end="", flush=True)
        finally:
            if progress_cb is None and not _QUIET:
                print()  # newline after the progress bar, success or not

        if total_size > 0 and downloaded != total_size:
            log(f" ⚠ Downloaded size ({downloaded:,} bytes) doesn't match "
                f"expected ({total_size:,} bytes)", level="warn")
            return False

        return True

    def _add_tags(self, filepath: str, track_info: Dict[str, Any], track_id: str,
                  silent: bool = False):
        """Add comprehensive metadata tags to downloaded file (MP3 or FLAC)"""
        if not MUTAGEN_AVAILABLE:
            return

        try:
            # Extract metadata using field names from deezer-py utils.py mapping
            # Basic info - supports both gw-light API (SNG_TITLE, etc) and standard API
            title = track_info.get('SNG_TITLE') or track_info.get('title', '')
            title_short = track_info.get('title_short', '')
            title_version = track_info.get('title_version', '')
            if title_short and not title:
                title = title_short
                if title_version:
                    title = f"{title_short} {title_version}".strip()

            # Artist - from nested artist object or gw-light format
            artist = track_info.get('ART_NAME')
            if not artist:
                artist_obj = track_info.get('artist', {})
                artist = artist_obj.get('name', '') if isinstance(artist_obj, dict) else ''

            # Album - from nested album object or gw-light format
            album = track_info.get('ALB_TITLE')
            if not album:
                album_obj = track_info.get('album', {})
                album = album_obj.get('title', '') if isinstance(album_obj, dict) else ''

            # Track number - from track_position or TRACK_NUMBER
            track_number = track_info.get('TRACK_NUMBER') or track_info.get('track_position', '')
            # Get total tracks from album if available
            track_total = track_info.get('nb_tracks', '')

            # Disc number — fix: was looking up 'disk_number' twice
            disc_number = track_info.get('DISK_NUMBER') or track_info.get('disk_number', 1)
            disc_total = track_info.get('DISK_TOTAL') or track_info.get('nb_disk', '')

            # Format track/disc numbers as "current/total"
            if track_number and track_total:
                track_num_str = f"{track_number}/{track_total}"
            elif track_number:
                track_num_str = str(track_number)
            else:
                track_num_str = ''

            if disc_number and disc_total:
                disc_num_str = f"{disc_number}/{disc_total}"
            elif disc_number:
                disc_num_str = str(disc_number)
            else:
                disc_num_str = ''

            # Date/Year - from release_date or physical_release_date
            release_date = track_info.get('RELEASE_DATE') or track_info.get('release_date', '')
            if not release_date:
                release_date = track_info.get('physical_release_date', '') or track_info.get('PHYSICAL_RELEASE_DATE', '')
            year = track_info.get('YEAR') or track_info.get('year', '')

            if release_date and len(str(release_date)) >= 4:
                year_str = str(release_date)[:4]
            elif year:
                year_str = str(year)
            else:
                year_str = ''

            # Genre - from genre_id, resolved to a display name via the API
            genre = track_info.get('GENRE') or track_info.get('genre', '')
            if not genre:
                genre_id = track_info.get('genre_id', '')
                if genre_id:
                    genre = self._resolve_genre_name(genre_id) or ''

            # Album artist - from ALB_ARTIST or album.artist
            album_artist = track_info.get('ALB_ARTIST')
            if not album_artist:
                album_obj = track_info.get('album', {})
                album_artist = album_obj.get('artist', '') if isinstance(album_obj, dict) else ''
            # Check for compilation
            if not album_artist:
                if track_info.get('COMPILATION') or track_info.get('compilation'):
                    album_artist = 'Various Artists'

            # Composer - not directly available in deezer API, leave blank or use contributors
            composer = track_info.get('COMPOSER') or track_info.get('composer', '')
            if not composer:
                # Try to get from contributors if it's a single contributor
                contributors = track_info.get('contributors', [])
                if isinstance(contributors, list) and len(contributors) == 1:
                    composer = contributors[0].get('name', '') if isinstance(contributors[0], dict) else ''

            # Duration (in seconds)
            duration = track_info.get('DURATION') or track_info.get('duration', '')

            # ISRC (International Standard Recording Code)
            isrc = track_info.get('ISRC') or track_info.get('isrc', '')

            # Explicit content flag
            explicit = track_info.get('EXPLICIT') or track_info.get('explicit', False)
            if not explicit:
                explicit = track_info.get('explicit_lyrics', False) or track_info.get('EXPLICIT_LYRICS', False)
            explicit_str = '1' if explicit else ''

            # BPM - not directly available in deezer API
            bpm = track_info.get('BPM') or track_info.get('bpm', '')

            # Get cover art
            cover_art_data = None
            cover_url = self.get_cover_art_url(track_info, 'xl')
            if cover_url:
                cover_art_data = self.download_cover_art(cover_url)

            # Lyrics: plain text (embedded as a tag) and synced/LRC (embedded
            # where the format supports it, plus written as a .lrc sidecar
            # file since that's what most players actually look for)
            if self.fetch_lyrics_enabled:
                lyrics_data = self._fetch_lyrics(track_id)
            else:
                lyrics_data = {'plain': None, 'synced': None}
            plain_lyrics = lyrics_data.get('plain') or track_info.get('LYRICS') or track_info.get('lyrics', '')
            synced_lrc = lyrics_data.get('synced')

            if synced_lrc:
                try:
                    Path(filepath).with_suffix('.lrc').write_text(synced_lrc, encoding='utf-8')
                except Exception as lrc_err:
                    log(f" Warning: Could not write .lrc sidecar: {lrc_err}", level="debug")

            # Use appropriate format for FLAC vs MP3
            if filepath.endswith('.flac'):
                # FLAC format (Vorbis comments)
                audio = FLAC(filepath)
                if audio.tags is None:
                    audio.add_tags()

                # Basic tags
                if title:
                    audio['TITLE'] = title
                if artist:
                    audio['ARTIST'] = artist
                if album:
                    audio['ALBUM'] = album
                if track_num_str:
                    audio['TRACKNUMBER'] = track_num_str
                if disc_num_str:
                    audio['DISCNUMBER'] = disc_num_str
                if year_str:
                    audio['DATE'] = year_str
                if genre:
                    audio['GENRE'] = genre
                if album_artist:
                    audio['ALBUMARTIST'] = album_artist
                if composer:
                    audio['COMPOSER'] = composer
                if isrc:
                    audio['ISRC'] = isrc
                if explicit_str:
                    audio['ITUNESADVISORY'] = explicit_str
                if bpm:
                    audio['BPM'] = str(bpm)
                if duration:
                    audio['LENGTH'] = str(duration)
                if plain_lyrics:
                    audio['LYRICS'] = plain_lyrics

                # Embed cover art using mutagen's Picture block (Enhancement 1)
                if cover_art_data:
                    try:
                        pic = Picture()
                        pic.data = cover_art_data
                        pic.type = 3       # Cover (front)
                        pic.mime = 'image/jpeg'
                        pic.width = 1000
                        pic.height = 1000
                        pic.depth = 24
                        audio.add_picture(pic)
                    except Exception as pic_err:
                        log(f" Warning: Could not embed FLAC cover art: {pic_err}", level="warn")

                audio.save()
            else:
                # MP3 format (ID3 tags)
                audio = MP3(filepath, ID3=ID3)

                # Add tags if they don't exist
                try:
                    audio.add_tags()
                except ID3NoHeaderError:
                    pass

                # Basic tags
                if title:
                    audio.tags.add(TIT2(encoding=3, text=title))
                if artist:
                    audio.tags.add(TPE1(encoding=3, text=artist))
                if album:
                    audio.tags.add(TALB(encoding=3, text=album))

                # Track number
                if track_num_str:
                    audio.tags.add(TRCK(encoding=3, text=track_num_str))

                # Disc number
                if disc_num_str:
                    audio.tags.add(TPOS(encoding=3, text=disc_num_str))

                # Year/Date
                if year_str:
                    audio.tags.add(TYER(encoding=3, text=year_str))
                    audio.tags.add(TDRC(encoding=3, text=year_str))

                # Genre
                if genre:
                    audio.tags.add(TCON(encoding=3, text=genre))

                # Album artist
                if album_artist:
                    audio.tags.add(TPE2(encoding=3, text=album_artist))

                # Composer
                if composer:
                    audio.tags.add(TCOM(encoding=3, text=composer))

                # ISRC
                if isrc:
                    audio.tags.add(TSRC(encoding=3, text=isrc))

                # Duration (in milliseconds for ID3)
                if duration:
                    audio.tags.add(TLEN(encoding=3, text=str(int(float(duration) * 1000))))

                # BPM
                if bpm:
                    audio.tags.add(TBPM(encoding=3, text=str(int(float(bpm)))))

                # Explicit content
                if explicit_str:
                    audio.tags.add(COMM(encoding=3, lang='eng', desc='iTunes Advisory', text=explicit_str))

                # URL to official audio source
                track_url = track_info.get('TRACK_URL') or track_info.get('link', '')
                if track_url:
                    audio.tags.add(WOAS(url=track_url))

                # Lyrics: synced (SYLT) when available, otherwise plain (USLT)
                if synced_lrc:
                    try:
                        sylt_entries = self._parse_lrc_to_sylt(synced_lrc)
                        if sylt_entries:
                            audio.tags.add(SYLT(encoding=3, lang='eng', format=2, type=1,
                                                 desc='', text=sylt_entries))
                    except Exception as sylt_err:
                        log(f" Warning: Could not add synced lyrics: {sylt_err}", level="debug")
                elif plain_lyrics:
                    audio.tags.add(USLT(encoding=3, lang='eng', desc='', text=plain_lyrics))

                # Embed cover art
                if cover_art_data:
                    audio.tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=cover_art_data
                    ))

                audio.save()

            if not silent:
                log(f" ✓ Added metadata tags")

        except Exception as e:
            log(f" Warning: Could not add tags: {e}", level="warn")

    def download_playlist(self, playlist_id: str, output_dir: str = "downloads"):
        """
        Download all tracks from a playlist (handles pagination).

        Args:
            playlist_id: Deezer playlist ID
            output_dir: Directory to save downloaded files
        """
        log(f"Downloading playlist {playlist_id}...")

        try:
            # Enhancement 4: follow 'next' pagination links to get all tracks
            tracks: list = []
            url: Optional[str] = f"https://api.deezer.com/2.0/playlist/{playlist_id}/tracks?limit=100"

            while url:
                response = self.session.get(url)
                if response.status_code != 200:
                    log(f" ✗ Could not get playlist page: {response.status_code}", level="error")
                    break
                data = response.json()
                page_tracks = data.get('data', [])
                tracks.extend(page_tracks)
                url = data.get('next')  # None when on last page

            if not tracks:
                log(" ✗ No tracks found in playlist", level="error")
                return

            log(f" Found {len(tracks)} tracks")
            self._download_track_list(tracks, output_dir)

        except Exception as e:
            log(f" ✗ Error downloading playlist: {e}", level="error")
    def download_artist(self, artist_id: str, output_dir: str = "downloads"):
        """
        Enhancement 7: Download all albums for an artist.

        Args:
            artist_id: Deezer artist ID
            output_dir: Root directory; each album gets its own subdirectory
        """
        log(f"Fetching discography for artist {artist_id}...")
        try:
            response = self.session.get(
                f"https://api.deezer.com/2.0/artist/{artist_id}/albums?limit=100"
            )
            response.raise_for_status()
            data = response.json()
            albums = data.get('data', [])
            if not albums:
                log(" ✗ No albums found for this artist", level="error")
                return
            log(f" Found {len(albums)} albums")
            for album in albums:
                album_id = str(album['id'])
                log(f"\n→ Album: {album.get('title', album_id)}")
                self.download_album(album_id, output_dir)
        except Exception as e:
            log(f" ✗ Error downloading artist discography: {e}", level="error")

    def _download_track_list(self, tracks: list, output_dir: str,
                              track_nums: Optional[list] = None,
                              disc_nums: Optional[list] = None,
                              disc_total: Optional[int] = None):
        """
        Download a list of tracks sequentially or concurrently.

        Sequential mode: one track at a time with an inline progress bar.
        Concurrent mode: each completed track prints a single ✓/✗ line.
                         A single shared status line (\r) shows which tracks
                         are currently active — no ANSI cursor tricks needed.
        """
        total = len(tracks)

        if self.concurrency > 1:
            log(f" Downloading {total} tracks with {self.concurrency} threads")
            term_width = shutil.get_terminal_size((80, 24)).columns
            _lock = threading.Lock()
            # Track which labels are currently downloading
            _active: Dict[int, str] = {}   # thread_id -> label

            def _render_status() -> None:
                """Overwrite the current line with all active track names."""
                if _active:
                    names = ", ".join(_active.values())
                    line = f" ⬇ {names}"
                else:
                    line = ""
                line = line[:term_width - 1].ljust(term_width - 1)
                sys.stdout.write("\r" + line)
                sys.stdout.flush()

            def _do_download_concurrent(args: Tuple) -> Optional[str]:
                i, track = args
                tid = threading.get_ident()
                track_id = str(track["id"])
                t_num = track_nums[i - 1] if track_nums else None
                d_num = disc_nums[i - 1] if disc_nums else None
                title = track.get("title", track_id)
                label = f"[{i}/{total}] {title}"

                with _lock:
                    _active[tid] = label
                    _render_status()

                result = self.download_track(
                    track_id, output_dir,
                    track_num=t_num, disc_num=d_num, disc_total=disc_total,
                    progress_cb=lambda pct: None,  # suppress inline bar
                )

                with _lock:
                    del _active[tid]
                    # Clear the status line, then print the final result
                    sys.stdout.write("\r" + " " * (term_width - 1) + "\r")
                    if result:
                        print(f" ✓ {label}")
                    else:
                        print(f" ✗ {label}  (failed)")
                    _render_status()

                return result

            indexed = list(enumerate(tracks, 1))
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency) as executor:
                list(executor.map(_do_download_concurrent, indexed))
            # Clear any leftover status line
            sys.stdout.write("\r" + " " * (term_width - 1) + "\r")
            sys.stdout.flush()

        else:
            for i, track in enumerate(tracks, 1):
                track_id = str(track["id"])
                t_num = track_nums[i - 1] if track_nums else None
                d_num = disc_nums[i - 1] if disc_nums else None
                title = track.get("title", track_id)
                log(f"\n[{i}/{total}] {title}")
                self.download_track(track_id, output_dir, track_num=t_num, disc_num=d_num,
                                     disc_total=disc_total)
                time.sleep(0.5)

    def download_album(self, album_id: str, output_dir: str = "downloads"):
        """
        Download all tracks from an album.
        Creates a directory for the album with track numbers in filenames.

        Args:
            album_id: Deezer album ID
            output_dir: Directory to save downloaded files
        """
        log(f"Downloading album {album_id}...")

        try:
            album_metadata = self.client.api.get_album(album_id)
            album_tracks_response = self.client.api.get_album_tracks(album_id)

            if not album_metadata or not album_tracks_response:
                log(" ✗ Could not get album data from API", level="error")
                return

            tracks_data = album_tracks_response.get('data', [])
            if not tracks_data:
                log(" ✗ No tracks found in album", level="error")
                return

            album_name = album_metadata.get('title', 'Unknown Album')
            artist_name = album_metadata.get('artist', {}).get('name', 'Unknown Artist')

            # Enhancement 13: removed inner `from pathlib import Path`
            # Enhancement 18: use safe sanitisation instead of stripping all non-alnum
            safe_album_name = sanitise_filename(album_name)
            safe_artist_name = sanitise_filename(artist_name)
            album_dir = Path(output_dir) / f"{safe_artist_name} - {safe_album_name}"
            album_dir.mkdir(parents=True, exist_ok=True)

            log(f" Album: {safe_artist_name} - {safe_album_name}")
            log(f" Directory: {album_dir}")
            log(f" Found {len(tracks_data)} tracks")

            # Save Cover.jpg to the album folder
            cover_path = album_dir / "Cover.jpg"
            if not cover_path.exists():
                cover_url = (
                    album_metadata.get('cover_xl')
                    or album_metadata.get('cover_big')
                    or album_metadata.get('cover_medium')
                )
                if not cover_url:
                    # Build URL from picture hash the same way get_cover_art_url does
                    picture_id = album_metadata.get('picture') or album_metadata.get('cover')
                    if picture_id:
                        cover_url = f"https://cdns-images.dzcdn.net/images/cover/{picture_id}/1000x1000-000000-80-0-0.jpg"
                if cover_url:
                    cover_data = self.download_cover_art(cover_url)
                    if cover_data:
                        cover_path.write_bytes(cover_data)
                        log(f" ✓ Saved Cover.jpg")
                    else:
                        log(" Warning: Could not download album cover art", level="warn")
                else:
                    log(" Warning: No cover art URL found for album", level="warn")

            track_nums = [t.get('track_position', i + 1) for i, t in enumerate(tracks_data)]
            disc_nums = [t.get('disk_number', 1) for t in tracks_data]
            disc_total = max(disc_nums) if disc_nums else 1

            self._download_track_list(tracks_data, str(album_dir),
                                       track_nums=track_nums, disc_nums=disc_nums,
                                       disc_total=disc_total)

        except Exception as e:
            log(f" ✗ Error downloading album: {e}", level="error")


def sanitise_filename(name: str) -> str:
    """
    Enhancement 18: Replace only filesystem-illegal characters, preserving
    accented letters, punctuation, and Unicode that are safe on modern OSes.

    Replaces  / \\ : * ? " < > |  with an en-dash and strips leading/trailing
    whitespace and dots (Windows compat).
    """
    illegal = r'[/\\:*?"<>|]'
    return re.sub(illegal, '-', name).strip('. ')


def resolve_deezer_url(url: str) -> str:
    """
    Resolve a Deezer share link or redirect to its canonical URL.

    Deezer share links (e.g. https://deezer.page.link/…, https://share.deezer.com/…,
    or any URL that redirects) are followed silently. Tracking parameters are
    stripped so only scheme + host + path remain.

    If the URL already looks like a canonical Deezer link (contains deezer.com
    and one of /track/, /album/, /playlist/, /artist/) it is returned as-is
    without making any HTTP request.

    Args:
        url: Raw URL from the user (share link or canonical)

    Returns:
        Clean canonical Deezer URL (no query string or fragment)
    """
    from urllib.parse import urlparse, urlunparse

    # Fast path: already a canonical URL — no request needed
    canonical_patterns = ['/track/', '/album/', '/playlist/', '/artist/', '/song/']
    if 'deezer.com' in url and any(p in url for p in canonical_patterns):
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))

    log(f" Resolving share link: {url}", level="debug")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; deezload)'}
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=(10, 15))
        parsed = urlparse(response.url)
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        log(f" Resolved to: {clean}", level="debug")
        return clean
    except Exception as e:
        log(f" Warning: Could not resolve share link ({e}), using original URL", level="warn")
        return url


def extract_id_and_type(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Enhancement 7: Extract numeric ID *and* content type from a Deezer URL.

    Returns:
        (id, type) where type is one of 'track', 'playlist', 'album', 'artist'
        or (None, None) if no match.
    """
    patterns = [
        (r'/track/(\d+)',    'track'),
        (r'/song/(\d+)',     'track'),
        (r'/playlist/(\d+)', 'playlist'),
        (r'/album/(\d+)',    'album'),
        (r'/artist/(\d+)',   'artist'),
    ]
    for pattern, url_type in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), url_type
    return None, None


def extract_id_from_url(url: str) -> Optional[str]:
    """Extract numeric ID from a Deezer URL (backwards-compatible wrapper)."""
    id_, _ = extract_id_and_type(url)
    return id_


def _describe_search_result(item: Dict[str, Any], search_type: str) -> str:
    """One-line human-readable description of a search result, by type."""
    if search_type in ("track", "album"):
        artist = item.get("artist", {}).get("name", "Unknown Artist")
        return f"{item.get('title', 'Unknown')} — {artist}"
    if search_type == "artist":
        return item.get("name", "Unknown Artist")
    if search_type == "playlist":
        creator = item.get("user", {}).get("name", "Unknown")
        return f"{item.get('title', 'Unknown')} (by {creator})"
    return str(item.get("id"))


def search_and_select(query: str, search_type: str = "track", limit: int = 10,
                       index: Optional[int] = None) -> Tuple[Optional[str], Optional[str]]:
    """
    Search Deezer's public API and either auto-select a result (for
    scripting, via `index`) or prompt the user to pick one interactively.

    Args:
        query: Free-text search query
        search_type: One of 'track', 'album', 'artist', 'playlist'
        limit: Max results to fetch/show
        index: 1-based result to auto-select without prompting

    Returns:
        (content_id, url_type) matching what extract_id_and_type would
        produce for a URL of that type, or (None, None) if nothing was
        found or selected.
    """
    endpoint = {
        "track": "search/track",
        "album": "search/album",
        "artist": "search/artist",
        "playlist": "search/playlist",
    }.get(search_type, "search/track")

    try:
        response = requests.get(
            f"https://api.deezer.com/{endpoint}",
            params={"q": query, "limit": limit},
            timeout=(10, 15),
        )
        response.raise_for_status()
        results = response.json().get("data", [])
    except Exception as e:
        log(f"✗ Search failed: {e}", level="error")
        return None, None

    if not results:
        log(f"✗ No {search_type} results found for '{query}'", level="error")
        return None, None

    if index is not None:
        if not (1 <= index <= len(results)):
            log(f"✗ --search-index {index} is out of range (1-{len(results)})", level="error")
            return None, None
        chosen = results[index - 1]
    else:
        # Interactive prompt — printed directly (not via log()) so it always
        # shows up even when running with --quiet.
        print(f"\nSearch results for '{query}' ({search_type}):")
        for i, item in enumerate(results, 1):
            print(f"  {i}. {_describe_search_result(item, search_type)}")
        try:
            choice = input(f"\nSelect 1-{len(results)} (or Enter to cancel): ").strip()
        except EOFError:
            choice = ""
        if not choice:
            log("Cancelled — nothing selected", level="error")
            return None, None
        if not choice.isdigit() or not (1 <= int(choice) <= len(results)):
            log(f"✗ Invalid selection: {choice}", level="error")
            return None, None
        chosen = results[int(choice) - 1]

    return str(chosen.get("id")), search_type


def get_config_path() -> Path:
    """Get the path to the Deezload configuration file."""
    # Check environment variable first
    env_path = os.environ.get('DEEZLOAD_CONFIG')
    if env_path:
        return Path(env_path)

    # Default to ~/.config/deezload/deezload-config.ini
    config_dir = Path.home() / '.config' / 'deezload'
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / 'deezload-config.ini'

    return config_file


def load_config() -> Dict[str, str]:
    """Load configuration from file."""
    config = {}
    config_path = get_config_path()

    if config_path.exists():
        parser = ConfigParser()
        parser.read(config_path)

        # Load from 'deezer' section
        if parser.has_section('deezer'):
            for key in ['arl_token', 'quality', 'output']:
                value = parser.get('deezer', key, fallback=None)
                if value:
                    config[key] = value

        # Load from 'defaults' section
        if parser.has_section('defaults'):
            for key in ['output']:
                value = parser.get('defaults', key, fallback=None)
                if value:
                    config.setdefault(key, value)

    return config


def save_config(arl_token: str, quality: str = 'FLAC', output: str = 'downloads'):
    """Save configuration to Deezload config file."""
    config_path = get_config_path()

    parser = ConfigParser()
    parser.read(config_path)

    if not parser.has_section('deezer'):
        parser.add_section('deezer')

    parser.set('deezer', 'arl_token', arl_token)
    parser.set('deezer', 'quality', quality)
    parser.set('deezer', 'output', output)

    with open(config_path, 'w') as f:
        parser.write(f)

    # Enhancement 19: security reminder — ARL grants full account access
    os.chmod(config_path, 0o600)
    log(f"✓ Deezload configuration saved to {config_path}")
    log("⚠ Config file permissions set to 600 (owner read/write only).")
    log("  Your ARL token grants full Deezer account access — keep this file private.")


def main():
    parser = argparse.ArgumentParser(
        description="Deezload - Deezer Music Downloader CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
 %(prog)s --url "https://www.deezer.com/track/12345"
 %(prog)s --url "https://www.deezer.com/playlist/12345"   # auto-detected
 %(prog)s --url "https://www.deezer.com/album/12345"      # auto-detected
 %(prog)s --url "https://www.deezer.com/artist/12345"     # downloads discography
 %(prog)s --playlist "https://www.deezer.com/playlist/12345"
 %(prog)s --album "https://www.deezer.com/album/12345"
 %(prog)s --track-id 12345 --quality FLAC
 %(prog)s --search "Daft Punk Harder Better"               # search & pick interactively
 %(prog)s --search "Daft Punk" --search-type artist --search-index 1
 %(prog)s --save-config                # Save current settings as defaults
 %(prog)s --url "..." --dry-run        # Preview without downloading
 %(prog)s --url "..." --concurrency 4  # Parallel downloads
 %(prog)s --url "..." --min-quality MP3_320  # Never fall back below MP3 320
 %(prog)s --url "..." --log-file deezload.log

Configuration:
  Configuration is stored in ~/.config/deezload/deezload-config.ini
  Set arl_token in the config to avoid passing it each time.
  DEEZLOAD_ARL can also be used to supply the token via environment variable.
 """
    )

    parser.add_argument(
        "--arl",
        help="ARL (Authentication Remember Login) token from Deezer (or set in config / DEEZLOAD_ARL)"
    )
    parser.add_argument(
        "--url",
        help="Deezer URL — track, playlist, album, or artist (type auto-detected)"
    )
    parser.add_argument(
        "--track-id",
        help="Direct track ID to download"
    )
    parser.add_argument(
        "--playlist",
        help="Download all tracks from a playlist URL"
    )
    parser.add_argument(
        "--album",
        help="Download all tracks from an album URL"
    )
    parser.add_argument(
        "--search",
        metavar="QUERY",
        help="Search Deezer and pick a result to download (interactive, or use --search-index)"
    )
    parser.add_argument(
        "--search-type",
        choices=["track", "album", "artist", "playlist"],
        default="track",
        help="Type of content to search for with --search (default: track)"
    )
    parser.add_argument(
        "--search-index",
        type=int,
        metavar="N",
        help="Auto-select result N (1-based) from --search without prompting — for scripting"
    )
    parser.add_argument(
        "--quality",
        choices=["MP3_128", "MP3_320", "FLAC"],
        help="Audio quality (default: FLAC or from config)"
    )
    parser.add_argument(
        "--min-quality",
        choices=["MP3_128", "MP3_320", "FLAC"],
        help="Don't automatically fall back below this quality tier even if --quality isn't "
             "available for a track (default: falls all the way to MP3_128)"
    )
    parser.add_argument(
        "--output",
        help="Output directory (default: downloads or from config)"
    )
    parser.add_argument(
        "--save-config",
        action="store_true",
        help="Save current settings (including ARL token) as defaults"
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Show current configuration and exit"
    )
    # Enhancement 9
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show debug output (API calls, URL resolution steps)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress all non-error output (useful for scripting)"
    )
    parser.add_argument(
        "--log-file",
        metavar="PATH",
        help="Also write a full log (all levels, regardless of --quiet) to this file"
    )
    # Enhancement 11
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        metavar="N",
        help="Number of parallel download threads (default: 1)"
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        metavar="N",
        help="Attempts per track before giving up, resuming from the partial file "
             "between attempts (default: 3)"
    )
    parser.add_argument(
        "--no-lyrics",
        action="store_true",
        help="Skip fetching lyrics (plain + synced) to speed up downloads"
    )
    # Enhancement 8 (dry-run flag)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve track info and print filenames without downloading"
    )

    args = parser.parse_args()

    # Enhancement 9: set global verbosity flags
    global _VERBOSE, _QUIET, _LOG_FILE_HANDLE
    _VERBOSE = args.verbose
    _QUIET = args.quiet

    if args.log_file:
        try:
            _LOG_FILE_HANDLE = open(args.log_file, 'a', encoding='utf-8')
            _LOG_FILE_HANDLE.write(f"\n=== Deezload run started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception as e:
            print(f"Warning: could not open log file {args.log_file}: {e}")

    # Load config file
    config = load_config()

    # Show config if requested
    if args.show_config:
        config_path = get_config_path()
        log(f"Deezload configuration file: {config_path}")
        if config_path.exists():
            log("\nContents (secrets redacted):")
            with open(config_path) as f:
                raw = f.read()
            redacted = re.sub(r'(?im)^(arl_token\s*=\s*).+$', r'\1[REDACTED]', raw)
            log(redacted)
        else:
            log("\nNo configuration file found.")
        log("\nAvailable settings:")
        log(f"  arl_token: {'[SET]' if config.get('arl_token') else '[NOT SET]'}")
        log(f"  quality: {config.get('quality', 'FLAC')}")
        log(f"  output: {config.get('output', 'downloads')}")
        sys.exit(0)

    # Get values from args, env, config, or defaults.
    # Precedence: explicit CLI flag > DEEZLOAD_ARL env var > saved config.
    arl_token = args.arl or os.environ.get('DEEZLOAD_ARL') or config.get('arl_token')
    quality = args.quality or config.get('quality', AudioQuality.FLAC.value)
    output_dir = args.output or config.get('output', 'downloads')

    # Validate ARL token
    if not arl_token:
        parser.error("ARL token is required. Provide --arl, set DEEZLOAD_ARL, or set it in config file.")

    # Save config if requested (Enhancement 19: security note printed inside save_config)
    if args.save_config:
        save_config(arl_token, quality, output_dir)
        log("Configuration saved. You can now omit --arl from future commands.")
        sys.exit(0)

    # Validate input
    if not any([args.url, args.track_id, args.playlist, args.album, args.search]):
        parser.error("One of --url, --track-id, --playlist, --album, or --search is required")

    # Create downloader
    quality_enum = AudioQuality(quality)
    min_quality_enum = AudioQuality(args.min_quality) if args.min_quality else None
    downloader = DeezerDownloader(
        arl_token, quality_enum, concurrency=args.concurrency,
        min_quality=min_quality_enum, max_retries=args.retries,
        fetch_lyrics=not args.no_lyrics,
    )

    if args.dry_run:
        log("Dry-run mode — no files will be downloaded")

    # Authenticate
    log("Authenticating...")
    if not downloader.authenticate():
        sys.exit(1)

    # Process download request
    try:
        if args.track_id:
            if args.dry_run:
                info = downloader.get_track_info(args.track_id)
                log(f" Would download: {info.get('SNG_TITLE', args.track_id) if info else args.track_id}")
            else:
                downloader.download_track(args.track_id, output_dir)

        elif args.url:
            # Resolve share/redirect links before extracting ID
            resolved = resolve_deezer_url(args.url)
            content_id, url_type = extract_id_and_type(resolved)
            if not content_id:
                log(f"Error: Could not extract ID from URL: {resolved}", level="error")
                sys.exit(1)
            log(f" Detected URL type: {url_type}", level="debug")
            if url_type == 'track':
                if args.dry_run:
                    info = downloader.get_track_info(content_id)
                    log(f" Would download: {info.get('SNG_TITLE', content_id) if info else content_id}")
                else:
                    downloader.download_track(content_id, output_dir)
            elif url_type == 'playlist':
                downloader.download_playlist(content_id, output_dir)
            elif url_type == 'album':
                downloader.download_album(content_id, output_dir)
            elif url_type == 'artist':
                log(f"Artist URL detected — downloading all albums for artist {content_id}")
                downloader.download_artist(content_id, output_dir)
            else:
                log(f"Error: Unsupported URL type '{url_type}'", level="error")
                sys.exit(1)

        elif args.playlist:
            resolved = resolve_deezer_url(args.playlist)
            playlist_id = extract_id_from_url(resolved)
            if not playlist_id:
                log(f"Error: Could not extract ID from URL: {resolved}", level="error")
                sys.exit(1)
            downloader.download_playlist(playlist_id, output_dir)

        elif args.album:
            resolved = resolve_deezer_url(args.album)
            album_id = extract_id_from_url(resolved)
            if not album_id:
                log(f"Error: Could not extract ID from URL: {resolved}", level="error")
                sys.exit(1)
            downloader.download_album(album_id, output_dir)

        elif args.search:
            content_id, url_type = search_and_select(
                args.search, args.search_type, index=args.search_index
            )
            if not content_id:
                sys.exit(1)
            if url_type == 'track':
                if args.dry_run:
                    info = downloader.get_track_info(content_id)
                    log(f" Would download: {info.get('SNG_TITLE', content_id) if info else content_id}")
                else:
                    downloader.download_track(content_id, output_dir)
            elif url_type == 'album':
                downloader.download_album(content_id, output_dir)
            elif url_type == 'playlist':
                downloader.download_playlist(content_id, output_dir)
            elif url_type == 'artist':
                downloader.download_artist(content_id, output_dir)

        if not args.dry_run:
            downloader.print_summary()

    except KeyboardInterrupt:
        log("\n\nDownload cancelled by user")
        sys.exit(1)
    except Exception as e:
        log(f"\nUnexpected error: {e}", level="error")
        sys.exit(1)


if __name__ == "__main__":
    main()
