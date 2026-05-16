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
 python deezload.py --arl <YOUR_ARL_TOKEN> --url <TRACK_URL>
 python deezload.py --arl <YOUR_ARL_TOKEN> --playlist <PLAYLIST_URL>
 python deezload.py --arl <YOUR_ARL_TOKEN> --album <ALBUM_URL>
"""

import argparse
import base64
import functools
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, Dict, List, Any
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
    from Crypto.Util import Counter
except ImportError:
    print("Error: pycryptodome not installed. Run: pip install pycryptodome")
    sys.exit(1)

try:
    from mutagen.id3 import ID3, TIT2, TALB, TPE1, TPE2, TCOM, TRCK, TPOS, TYER, TDAT, TCON, \
        TDRC, APIC, ID3NoHeaderError, USLT, COMM, TBPM, TKEY, WOAS, TSRC, TLEN
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
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

    def __init__(self, arl_token: str, quality: AudioQuality = AudioQuality.FLAC):
        """
        Initialize the downloader with ARL authentication.

        Args:
            arl_token: ARL (Authentication Remember Login) token
            quality: Desired audio quality
        """
        self.arl_token = arl_token
        self.quality = quality
        self.session = self._create_session()
        self.client = deezer.Deezer()
        self.user_id: Optional[str] = None
        self.license_token: Optional[str] = None

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic"""
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
                print(f"✓ Authenticated as user: {user_data.get('name', 'Unknown')} (ID: {self.user_id})")

                # Store license token for later use
                if 'license_token' in user_data:
                    self.license_token = user_data['license_token']

                return True
            else:
                print("✗ Authentication failed. Check your ARL token.")
                return False
        except Exception as e:
            print(f"✗ Authentication error: {e}")
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
            print(f"Error getting track info: {e}")

        # Fallback: try direct API
        try:
            response = self.session.get(
                f"https://api.deezer.com/2.0/track/{track_id}"
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Error getting track info (fallback): {e}")

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
            print(f" Warning: Could not download cover art: {e}")
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

    def get_download_url(self, track_id: str, track_token: Optional[str] = None) -> Optional[str]:
        """
        Get the download URL for a track using deezer-py library.

        Args:
            track_id: Deezer track ID
            track_token: Optional track token for DRM

        Returns:
            Download URL or None
        """
        try:
            # Get track info which includes TRACK_TOKEN
            track_info = self.get_track_info(track_id)
            if not track_info:
                return None

            # Get the track token
            token = track_info.get('TRACK_TOKEN')
            if not token:
                print(" ✗ No track token available")
                return None

            # Map quality to streamrip format
            quality_map = {
                "MP3_128": "MP3_128",
                "MP3_320": "MP3_320",
                "FLAC": "FLAC"
            }
            quality_str = quality_map.get(self.quality.value, "MP3_320")

            # Use deezer-py's get_track_url method
            # This handles the complex token exchange internally
            url = self.client.get_track_url(token, quality_str)
            if url:
                return url

            # If that failed, try fallback quality
            return self._construct_encrypted_url(track_id, track_info.get('MD5_ORIGIN', ''), self.quality.format_id)

        except Exception as e:
            print(f"Error getting download URL: {e}")
            # Fallback to encrypted URL construction
            track_info = self.get_track_info(track_id)
            if track_info:
                return self._construct_encrypted_url(track_id, track_info.get('MD5_ORIGIN', ''), self.quality.format_id)
            return None

    def _construct_encrypted_url(self, track_id: str, track_md5: str, quality: int) -> Optional[str]:
        """Construct encrypted download URL (streamrip approach)."""
        try:
            # Get media version from track info
            track_info = self.get_track_info(track_id)
            media_version = ""
            if track_info and 'MEDIA_VERSION' in track_info:
                media_version = str(track_info['MEDIA_VERSION'])

            if not media_version:
                media_version = "1"  # Default fallback

            # Build the string to encrypt
            # Format: {md5}{quality}{media_version}{track_id}
            to_encrypt = f"{track_md5}{quality}{media_version}{track_id}"

            # Pad to multiple of 16 bytes
            padding = 16 - (len(to_encrypt) % 16)
            to_encrypt += chr(padding) * padding

            # Encrypt with AES ECB
            key = b"jo6aey6haid2Teih"
            cipher = AES.new(key, AES.MODE_ECB)
            encrypted = cipher.encrypt(to_encrypt.encode())
            encrypted_hex = encrypted.hex()

            # Construct URL
            # Use first character of MD5 to select CDN
            cdn_index = track_md5[0]
            url = f"https://e-cdns-proxy-{cdn_index}.dzcdn.net/mobile/1/{encrypted_hex}"

            return url
        except Exception as e:
            print(f"Error constructing encrypted URL: {e}")
            return None

    def download_track(self, track_id: str, output_dir: str = "downloads", track_num: int = None, disc_num: int = None) -> Optional[str]:
        """
        Download a single track.

        Args:
            track_id: Deezer track ID
            output_dir: Directory to save downloaded file

        Returns:
            Path to downloaded file or None
        """
        print(f"Downloading track {track_id}...")

        # Get track info
        track_info = self.get_track_info(track_id)
        if not track_info:
            print(f" ✗ Could not get track info for {track_id}")
            return None

        # Get download URL
        download_url = self.get_download_url(track_id)
        if not download_url:
            print(f" ✗ Could not get download URL for {track_id}")
            return None

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Download the file
        try:
            response = self.session.get(download_url, stream=True)
            response.raise_for_status()

            # Determine filename (handle both API formats)
            # From gw.get_track(): ART_NAME, SNG_TITLE
            # From api.deezer.com: artist.name, title
            artist = track_info.get("ART_NAME") or track_info.get("artist", {}).get("name", "Unknown Artist")
            title = track_info.get("SNG_TITLE") or track_info.get("title", "Unknown Title")
            # Use correct extension based on quality
            extension = ".flac" if self.quality == AudioQuality.FLAC else ".mp3"
            # Include track number in filename if provided (for album downloads)
            if track_num is not None:
                filename = f"{track_num:02d} - {artist} - {title}{extension}"
            else:
                filename = f"{artist} - {title}{extension}"
            filepath = output_path / filename

            # Download with progress + Blowfish decryption
            # Deezer encrypts every 3rd 2048-byte block with Blowfish CBC
            total_size = int(response.headers.get('content-length', 0))
            chunk_size = 2048
            downloaded = 0
            block_index = 0
            bf_key = self._generate_blowfish_key(track_id)

            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    # Decrypt every 3rd full-sized block
                    if block_index % 3 == 0 and len(chunk) == 2048:
                        chunk = self._decrypt_chunk(bf_key, chunk)
                    f.write(chunk)
                    downloaded += len(chunk)
                    block_index += 1
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        print(f'\r Progress: {progress:.1f}%', end='')

            print(f"\n ✓ Downloaded: {filepath}")

            # Add metadata tags if mutagen is available
            if MUTAGEN_AVAILABLE:
                self._add_tags(str(filepath), track_info)

            return str(filepath)

        except Exception as e:
            print(f"\n ✗ Download failed: {e}")
            return None

    def _add_tags(self, filepath: str, track_info: Dict[str, Any]):
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

            # Disc number
            disc_number = track_info.get('DISK_NUMBER') or track_info.get('disk_number', '') or track_info.get('disk_number', 1)
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

            # Genre - from genre_id
            genre = track_info.get('GENRE') or track_info.get('genre', '')
            if not genre:
                genre_id = track_info.get('genre_id', '')
                if genre_id:
                    genre = str(genre_id)  # Genre ID as fallback

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

                # Embed cover art
                if cover_art_data:
                    try:
                        picture_block = base64.b64encode(cover_art_data).decode('ascii')
                        audio['METADATA_BLOCK_PICTURE'] = picture_block
                    except Exception as pic_err:
                        print(f" Warning: Could not embed FLAC cover art: {pic_err}")

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
                    audio.tags.add(WOAS(encoding=3, text=track_url))

                # Lyrics (if available)
                lyrics = track_info.get('LYRICS') or track_info.get('lyrics', '')
                if lyrics:
                    audio.tags.add(USLT(encoding=3, lang='eng', desc='', text=lyrics))

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

            print(f" ✓ Added metadata tags")

        except Exception as e:
            print(f" Warning: Could not add tags: {e}")

    def download_playlist(self, playlist_id: str, output_dir: str = "downloads"):
        """
        Download all tracks from a playlist.

        Args:
            playlist_id: Deezer playlist ID
            output_dir: Directory to save downloaded files
        """
        print(f"Downloading playlist {playlist_id}...")

        try:
            response = self.session.get(
                f"https://api.deezer.com/2.0/playlist/{playlist_id}/tracks"
            )

            if response.status_code != 200:
                print(f" ✗ Could not get playlist: {response.status_code}")
                return

            data = response.json()
            tracks = data.get('data', [])

            print(f" Found {len(tracks)} tracks")

            # Download each track
            for i, track in enumerate(tracks, 1):
                track_id = str(track['id'])
                print(f"\n[{i}/{len(tracks)}] Track {track_id}")
                self.download_track(track_id, output_dir)
                time.sleep(0.5)  # Rate limiting

        except Exception as e:
            print(f" ✗ Error downloading playlist: {e}")
    def download_album(self, album_id: str, output_dir: str = "downloads"):
        """
        Download all tracks from an album using the deezer library.
        Creates a directory for the album with track numbers in filenames.

        Args:
            album_id: Deezer album ID
            output_dir: Directory to save downloaded files
        """
        print(f"Downloading album {album_id}...")

        try:
            # Use deezer library to get album metadata and tracks
            album_metadata = self.client.api.get_album(album_id)
            album_tracks_response = self.client.api.get_album_tracks(album_id)

            if not album_metadata or not album_tracks_response:
                print(f" ✗ Could not get album data from API")
                return

            tracks_data = album_tracks_response.get('data', [])
            if not tracks_data:
                print(f" ✗ No tracks found in album")
                return

            # Create album directory using album name
            album_name = album_metadata.get('title', 'Unknown Album')
            artist_name = album_metadata.get('artist', {}).get('name', 'Unknown Artist')
            # Sanitize names for filesystem
            safe_album_name = "".join(c for c in album_name if c.isalnum() or c in ' -_').strip()
            safe_artist_name = "".join(c for c in artist_name if c.isalnum() or c in ' -_').strip()
            from pathlib import Path
            album_dir = Path(output_dir) / f"{safe_artist_name} - {safe_album_name}"
            album_dir.mkdir(parents=True, exist_ok=True)

            print(f" Album: {safe_artist_name} - {safe_album_name}")
            print(f" Directory: {album_dir}")
            print(f" Found {len(tracks_data)} tracks")

            # Download each track with track number info
            for i, track in enumerate(tracks_data, 1):
                track_id = str(track['id'])
                track_num = track.get('track_position', i)
                disc_num = track.get('disk_number', 1)
                print(f"\n[{i}/{len(tracks_data)}] Track {track_num}: {track.get('title', 'Unknown')}")
                self.download_track(track_id, str(album_dir), track_num=track_num, disc_num=disc_num)
                time.sleep(0.5) # Rate limiting

        except Exception as e:
            print(f" ✗ Error downloading album: {e}")


def extract_id_from_url(url: str) -> Optional[str]:
    """Extract ID from Deezer URL"""
    # Match patterns like /track/12345, /playlist/12345, /album/12345
    patterns = [
    r'/track/(\d+)',
    r'/playlist/(\d+)',
    r'/album/(\d+)',
    r'/song/(\d+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    return None


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


def save_config(arl_token: str, quality: str = 'MP3_320', output: str = 'downloads'):
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

    print(f"✓ Deezload configuration saved to {config_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Deezload - Deezer Music Downloader CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
 %(prog)s --url "https://www.deezer.com/track/12345"
 %(prog)s --playlist "https://www.deezer.com/playlist/12345"
 %(prog)s --album "https://www.deezer.com/album/12345"
 %(prog)s --track-id 12345 --quality FLAC
 %(prog)s --save-config  # Save current settings as defaults

Configuration:
  Configuration is stored in ~/.config/deezload/deezload-config.ini
  Set arl_token in the config to avoid passing it each time.
 """
    )

    parser.add_argument(
        "--arl",
        help="ARL (Authentication Remember Login) token from Deezer (or set in config)"
    )

    parser.add_argument(
        "--url",
        help="Deezer URL (track, playlist, or album)"
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
        "--quality",
        choices=["MP3_128", "MP3_320", "FLAC"],
        help="Audio quality (default: FLAC or from config)"
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

    args = parser.parse_args()

    # Load config file
    config = load_config()

    # Show config if requested
    if args.show_config:
        config_path = get_config_path()
        print(f"Deezload configuration file: {config_path}")
        if config_path.exists():
            print("\nContents:")
            with open(config_path) as f:
                print(f.read())
        else:
            print("\nNo configuration file found.")
        print("\nAvailable settings:")
        print(f"  arl_token: {'[SET]' if config.get('arl_token') else '[NOT SET]'}")
        print(f"  quality: {config.get('quality', 'MP3_320')}")
        print(f"  output: {config.get('output', 'downloads')}")
        sys.exit(0)

    # Get values from args, config, or defaults
    arl_token = args.arl or config.get('arl_token')
    quality = args.quality or config.get('quality', AudioQuality.FLAC.value)
    output_dir = args.output or config.get('output', 'downloads')

    # Validate ARL token
    if not arl_token:
        parser.error("ARL token is required. Provide --arl or set it in config file.")

    # Save config if requested
    if args.save_config:
        save_config(arl_token, quality, output_dir)
        print("Configuration saved. You can now omit --arl from future commands.")
        sys.exit(0)

    # Validate input
    if not any([args.url, args.track_id, args.playlist, args.album]):
        parser.error("One of --url, --track-id, --playlist, or --album is required")

    # Create downloader
    quality_enum = AudioQuality(quality)
    downloader = DeezerDownloader(arl_token, quality_enum)

    # Authenticate
    print("Authenticating...")
    if not downloader.authenticate():
        sys.exit(1)

    # Process download request
    try:
        if args.track_id:
            downloader.download_track(args.track_id, output_dir)

        elif args.url:
            track_id = extract_id_from_url(args.url)
            if not track_id:
                print(f"Error: Could not extract ID from URL: {args.url}")
                sys.exit(1)
            downloader.download_track(track_id, output_dir)

        elif args.playlist:
            playlist_id = extract_id_from_url(args.playlist)
            if not playlist_id:
                print(f"Error: Could not extract ID from URL: {args.playlist}")
                sys.exit(1)
            downloader.download_playlist(playlist_id, output_dir)

        elif args.album:
            album_id = extract_id_from_url(args.album)
            if not album_id:
                print(f"Error: Could not extract ID from URL: {args.album}")
                sys.exit(1)
            downloader.download_album(album_id, output_dir)

    except KeyboardInterrupt:
        print("\n\nDownload cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
