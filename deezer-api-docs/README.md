# Deezer gw-light.php API Documentation

## Overview

This documentation covers the internal Deezer API as implemented in the `deezload.py` reference implementation. The API consists of two main components:

1. **Gateway API (gw-light.php)**: Internal GraphQL-like API used by Deezer's web and mobile apps
2. **Public REST API**: Standard REST API at `api.deezer.com`

## API Endpoints

### Base URLs

| API Type | Base URL |
|----------|----------|
| Gateway API | `https://www.deezer.com/ajax/gw-light.php` |
| Public API | `https://api.deezer.com/2.0/` |
| Image CDN | `https://cdn-images.dzcdn.net` |
| Assets CDN | `https://cdn-assets.dzcdn.net` |
| Audio CDN | `https://e-cdns-proxy-{X}.dzcdn.net/mobile/1/` |

## Authentication

### ARL Token Authentication

The Deezer API uses ARL (Authentication Remember Login) tokens for authentication. This is a session-based authentication method.

```python
import deezer

# Initialize client
client = deezer.Deezer()

# Authenticate with ARL token
success = client.login_via_arl("your_arl_token_here")

# Get user data after authentication
user_data = client.current_user
user_id = user_data.get('id')
license_token = user_data.get('license_token')
```

### Obtaining ARL Token

1. Log in to Deezer in your browser
2. Open browser developer tools (F12)
3. Go to Network tab
4. Look for requests to `deezer.com`
5. Find the `arl` cookie value
6. Alternatively, look for `getAccount` API calls containing the ARL token

### License Token

After authentication, a `license_token` is provided. This token is required for certain operations and stream authorization.

## Gateway API Methods

The gateway API is accessed through the `deezer-py` library:

```python
# Get track information
track = client.gw.get_track(track_id)

# Get album information
album = client.api.get_album(album_id)

# Get album tracks
album_tracks = client.api.get_album_tracks(album_id)
```

### Track Information Response Fields

| Field | Description |
|-------|-------------|
| `TRACK_TOKEN` | Unique token for the track (required for download URL) |
| `MD5_ORIGIN` | MD5 hash of the original track (used for encryption) |
| `MEDIA_VERSION` | Version number of the media file |
| `SNG_TITLE` | Song title |
| `title_short` | Short version of title |
| `title_version` | Version descriptor |
| `ART_NAME` | Artist name |
| `ALB_TITLE` | Album title |
| `ALB_ARTIST` | Album artist |
| `ALB_PICTURE` | Album picture ID |
| `TRACK_NUMBER` | Track position in album |
| `DISK_NUMBER` | Disc number |
| `GENRE` | Genre name |
| `ISRC` | International Standard Recording Code |
| `DURATION` | Duration in seconds |
| `LYRICS` | Track lyrics |
| `RELEASE_DATE` | Release date |
| `YEAR` | Release year |
| `BPM` | Beats per minute |
| `EXPLICIT` | Explicit content flag |
| `EXPLICIT_LYRICS` | Explicit lyrics flag |
| `COMPILATION` | Compilation album flag |
| `TRACK_URL` | Direct URL to track |
| `CONTRIBUTORS` | List of contributors |

## Audio Quality Tiers

| Quality | Format ID | Description |
|---------|-----------|-------------|
| MP3_128 | 1 | Standard MP3 128kbps |
| MP3_320 | 3 | High quality MP3 320kbps |
| FLAC | 6 | Lossless FLAC audio |

## Download URL Construction

### Primary Method: Token Exchange

```python
# Get download URL using track token
quality_str = "FLAC"  # or "MP3_320", "MP3_128"
url = client.get_track_url(track_token, quality_str)
```

### Fallback: Encrypted URL Construction

When token exchange fails, construct encrypted URLs manually:

```python
from Crypto.Cipher import AES

def construct_encrypted_url(track_md5: str, track_id: str, 
                            media_version: int, quality_id: int) -> str:
    """Construct encrypted download URL."""
    # String to encrypt: {md5}{quality}{media_version}{track_id}
    to_encrypt = f"{track_md5}{quality_id}{media_version}{track_id}"
    
    # Pad to multiple of 16 bytes
    padding = 16 - (len(to_encrypt) % 16)
    to_encrypt += chr(padding) * padding
    
    # AES ECB encryption
    key = b"jo6aey6haid2Teih"
    cipher = AES.new(key, AES.MODE_ECB)
    encrypted = cipher.encrypt(to_encrypt.encode())
    encrypted_hex = encrypted.hex()
    
    # CDN index from first character of MD5
    cdn_index = track_md5[0]
    return f"https://e-cdns-proxy-{cdn_index}.dzcdn.net/mobile/1/{encrypted_hex}"
```

## Audio Stream Decryption

Downloaded audio streams are encrypted with Blowfish CBC and must be decrypted:

```python
from Crypto.Cipher import Blowfish
import hashlib
import functools

def generate_blowfish_key(track_id: str) -> bytes:
    """Generate Blowfish decryption key."""
    md5_hash = hashlib.md5(track_id.encode()).hexdigest()
    secret = "g4el58wc0zvf9na1"
    
    return "".join(
        chr(functools.reduce(lambda x, y: x ^ y, map(ord, t)))
        for t in zip(md5_hash[:16], md5_hash[16:], secret)
    ).encode()

def decrypt_chunk(key: bytes, data: bytes) -> bytes:
    """Decrypt a chunk of audio data."""
    return Blowfish.new(
        key,
        Blowfish.MODE_CBC,
        b"\x00\x01\x02\x03\x04\x05\x06\x07"
    ).decrypt(data)

# Usage: decrypt every 3rd full-sized block (2048 bytes)
def download_and_decrypt(url: str, track_id: str):
    key = generate_blowfish_key(track_id)
    response = requests.get(url, stream=True)
    
    block_index = 0
    for chunk in response.iter_content(chunk_size=2048):
        if len(chunk) == 2048 and block_index % 3 == 0:
            chunk = decrypt_chunk(key, chunk)
        # Process chunk
        block_index += 1
```

## Cover Art URLs

```python
def get_cover_art_url(picture_id: str, size: str = 'large') -> str:
    """Generate cover art URL."""
    sizes = {
        'small': '56x56',
        'medium': '250x250', 
        'large': '500x500',
        'xl': '1000x1000'
    }
    size_str = sizes.get(size, '500x500')
    return f"https://cdn-images.dzcdn.net/images/cover/{picture_id}/{size_str}-000000-80-0-0.jpg"
```

## Public REST API Endpoints

### Get Track

```
GET https://api.deezer.com/2.0/track/{track_id}
```

### Get Album

```
GET https://api.deezer.com/2.0/album/{album_id}
```

### Get Album Tracks

```
GET https://api.deezer.com/2.0/album/{album_id}/tracks?limit=100
```

Pagination: Response includes `next` field with URL for next page.

### Get Artist Albums

```
GET https://api.deezer.com/2.0/artist/{artist_id}/albums?limit=100
```

### Get Playlist Tracks

```
GET https://api.deezer.com/2.0/playlist/{playlist_id}/tracks?limit=100
```

## Session Configuration

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_session():
    """Create requests session with proper configuration."""
    session = requests.Session()
    
    # Retry strategy
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Headers
    session.headers.update({
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 14; Deezer/8.21.18.1)",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/json",
    })
    
    # Timeouts: 10s connect, 60s read
    session.request = functools.partial(session.request, timeout=(10, 60))
    
    return session
```

## Error Handling

| Error | Description | Handling |
|-------|-------------|----------|
| 401 | Unauthorized | Re-authenticate with valid ARL token |
| 403 | Forbidden | Check license token validity |
| 404 | Not Found | Invalid track/album/playlist ID |
| 429 | Rate Limited | Implement exponential backoff |
| 500-504 | Server Error | Retry with backoff |

## Complete Example

```python
import deezer
import requests
from Crypto.Cipher import AES, Blowfish
import hashlib
import functools

class DeezerClient:
    API_BASE = "https://www.deezer.com/ajax/gw-light.php"
    BLOWFISH_SECRET = "g4el58wc0zvf9na1"
    
    def __init__(self, arl_token: str):
        self.arl_token = arl_token
        self.client = deezer.Deezer()
        self.session = self._create_session()
        self.user_id = None
        self.license_token = None
    
    def _create_session(self):
        # ... session setup as above ...
        pass
    
    def authenticate(self) -> bool:
        success = self.client.login_via_arl(self.arl_token)
        if success:
            user_data = self.client.current_user
            self.user_id = str(user_data.get('id'))
            self.license_token = user_data.get('license_token')
        return success
    
    def get_track_info(self, track_id: str):
        return self.client.gw.get_track(track_id)
    
    def get_download_url(self, track_id: str, track_info: dict, 
                         quality: str = "FLAC") -> str:
        # Try token exchange first
        token = track_info.get('TRACK_TOKEN')
        if token:
            url = self.client.get_track_url(token, quality)
            if url:
                return url
        
        # Fallback to encrypted URL
        md5 = track_info.get('MD5_ORIGIN', '')
        version = track_info.get('MEDIA_VERSION', 1)
        quality_id = {"MP3_128": 1, "MP3_320": 3, "FLAC": 6}[quality]
        return self._construct_encrypted_url(md5, track_id, version, quality_id)
    
    def _construct_encrypted_url(self, md5: str, track_id: str, 
                                  version: int, quality_id: int) -> str:
        to_encrypt = f"{md5}{quality_id}{version}{track_id}"
        padding = 16 - (len(to_encrypt) % 16)
        to_encrypt += chr(padding) * padding
        
        cipher = AES.new(b"jo6aey6haid2Teih", AES.MODE_ECB)
        encrypted = cipher.encrypt(to_encrypt.encode())
        
        return f"https://e-cdns-proxy-{md5[0]}.dzcdn.net/mobile/1/{encrypted.hex()}"
    
    def generate_blowfish_key(self, track_id: str) -> bytes:
        md5_hash = hashlib.md5(track_id.encode()).hexdigest()
        return "".join(
            chr(functools.reduce(lambda x, y: x ^ y, map(ord, t)))
            for t in zip(md5_hash[:16], md5_hash[16:], self.BLOWFISH_SECRET)
        ).encode()
    
    def decrypt_chunk(self, key: bytes, data: bytes) -> bytes:
        return Blowfish.new(
            key, Blowfish.MODE_CBC,
            b"\x00\x01\x02\x03\x04\x05\x06\x07"
        ).decrypt(data)
```

## Metadata Tagging

Use the `mutagen` library to add ID3 (MP3) or Vorbis (FLAC) tags:

```python
from mutagen.id3 import ID3, TIT2, TALB, TPE1, TRCK, TYER, APIC
from mutagen.mp3 import MP3

def add_tags(filepath: str, track_info: dict):
    audio = MP3(filepath, ID3=ID3)
    audio.add_tags()
    
    # Title
    audio.tags.add(TIT2(encoding=3, text=track_info.get('SNG_TITLE')))
    # Artist
    audio.tags.add(TPE1(encoding=3, text=track_info.get('ART_NAME')))
    # Album
    audio.tags.add(TALB(encoding=3, text=track_info.get('ALB_TITLE')))
    # Track number
    audio.tags.add(TRCK(encoding=3, text=track_info.get('TRACK_NUMBER')))
    # Year
    audio.tags.add(TYER(encoding=3, text=track_info.get('YEAR')))
    
    audio.save()
```

## Rate Limiting

- Implement exponential backoff for 429 errors
- Default backoff: 0.5s, 1s, 2s, 4s
- Consider request queuing for high-volume applications

## Security Considerations

- ARL tokens grant full account access - store securely
- Set config file permissions to 600 (owner read/write only)
- Do not commit tokens to version control
- Tokens may expire - handle re-authentication
