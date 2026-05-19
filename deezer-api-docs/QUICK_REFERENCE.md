# Deezer API Quick Reference

## Authentication

```python
import deezer
client = deezer.Deezer()
client.login_via_arl("your_arl_token")
```

**Get ARL Token**: Browser cookie `arl` from `.deezer.com`

## Key URLs

| Purpose | URL |
|---------|-----|
| Gateway API | `https://www.deezer.com/ajax/gw-light.php` |
| Public API | `https://api.deezer.com/2.0/` |
| Audio CDN | `https://e-cdns-proxy-{X}.dzcdn.net/mobile/1/` |
| Image CDN | `https://cdn-images.dzcdn.net/images/cover/{id}/{size}-000000-80-0-0.jpg` |

## Image Sizes

| Size | Dimensions |
|------|------------|
| small | 56x56 |
| medium | 250x250 |
| large | 500x500 |
| xl | 1000x1000 |

## Quality Levels

| Quality | Format ID | Description |
|---------|-----------|-------------|
| MP3_128 | 1 | 128 kbps MP3 |
| MP3_320 | 3 | 320 kbps MP3 |
| FLAC | 6 | Lossless FLAC |

## Common API Calls

```python
# Get track info
track = client.gw.get_track(track_id)

# Get album
album = client.api.get_album(album_id)

# Get album tracks
tracks = client.api.get_album_tracks(album_id)

# Get download URL
url = client.get_track_url(track_token, "FLAC")
```

## Download URL Encryption

```python
from Crypto.Cipher import AES

def encrypt_url(md5, track_id, version, quality_id):
    s = f"{md5}{quality_id}{version}{track_id}"
    pad = 16 - (len(s) % 16)
    s += chr(pad) * pad
    cipher = AES.new(b"jo6aey6haid2Teih", AES.MODE_ECB)
    return f"https://e-cdns-proxy-{md5[0]}.dzcdn.net/mobile/1/{cipher.encrypt(s.encode()).hex()}"
```

## Audio Decryption

```python
from Crypto.Cipher import Blowfish
import hashlib

def get_key(track_id):
    md5 = hashlib.md5(track_id.encode()).hexdigest()
    secret = "g4el58wc0zvf9na1"
    return "".join(chr(functools.reduce(lambda x, y: x ^ y, map(ord, t)))
        for t in zip(md5[:16], md5[16:], secret)).encode()

def decrypt(key, data):
    return Blowfish.new(key, Blowfish.MODE_CBC, b"\x00\x01\x02\x03\x04\x05\x06\x07").decrypt(data)

# Decrypt every 3rd full block (2048 bytes)
```

## Track Metadata Fields

| Field | Description |
|-------|-------------|
| `SNG_TITLE` | Song title |
| `ART_NAME` | Artist name |
| `ALB_TITLE` | Album title |
| `TRACK_NUMBER` | Track position |
| `DISK_NUMBER` | Disc number |
| `DURATION` | Duration (seconds) |
| `ISRC` | ISRC code |
| `LYRICS` | Lyrics |
| `MD5_ORIGIN` | MD5 hash (encryption) |
| `TRACK_TOKEN` | Download token |
| `MEDIA_VERSION` | Media version |

## Error Codes

| Code | Meaning | Action |
|------|---------|--------|
| 401 | Unauthorized | Re-authenticate |
| 403 | Forbidden | Check license |
| 404 | Not Found | Invalid ID |
| 429 | Rate Limited | Backoff |

## Session Setup

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

session = requests.Session()
retry = Retry(total=3, backoff_factor=0.5, 
              status_forcelist=[429, 500, 502, 503, 504])
session.mount("https://", HTTPAdapter(max_retries=retry))
session.headers.update({
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 14; Deezer/8.21.18.1)"
})
```

## Public API Endpoints

```
GET https://api.deezer.com/2.0/track/{id}
GET https://api.deezer.com/2.0/album/{id}
GET https://api.deezer.com/2.0/album/{id}/tracks
GET https://api.deezer.com/2.0/artist/{id}/albums
GET https://api.deezer.com/2.0/playlist/{id}/tracks
```

## CLI Usage

```bash
# Download track
python deezload.py --arl TOKEN --url "https://deezer.com/track/123"

# Save config
python deezload.py --arl TOKEN --save-config
```
