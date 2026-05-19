# Deezer API SDK Examples

## Python

### Basic Authentication

```python
import deezer

# Initialize and authenticate
client = deezer.Deezer()
success = client.login_via_arl("your_arl_token")

if success:
    user = client.current_user
    print(f"Logged in as: {user.get('name')}")
    print(f"User ID: {user.get('id')}")
```

### Download Track (Full Example)

```python
import deezer
import requests
from Crypto.Cipher import AES, Blowfish
import hashlib
import functools

class DeezerDownloader:
    BLOWFISH_SECRET = "g4el58wc0zvf9na1"
    
    def __init__(self, arl_token: str):
        self.client = deezer.Deezer()
        self.session = requests.Session()
        self.arl_token = arl_token
        self.license_token = None
        self.user_id = None
        
    def authenticate(self) -> bool:
        """Authenticate with ARL token."""
        success = self.client.login_via_arl(self.arl_token)
        if success:
            user = self.client.current_user
            self.user_id = str(user.get('id'))
            self.license_token = user.get('license_token')
        return success
    
    def get_track_info(self, track_id: str) -> dict:
        """Get track information via gateway API."""
        return self.client.gw.get_track(track_id)
    
    def get_download_url(self, track_id: str, track_info: dict, 
                         quality: str = "FLAC") -> str:
        """Get download URL for track."""
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
        """Construct encrypted download URL."""
        to_encrypt = f"{md5}{quality_id}{version}{track_id}"
        padding = 16 - (len(to_encrypt) % 16)
        to_encrypt += chr(padding) * padding
        
        cipher = AES.new(b"jo6aey6haid2Teih", AES.MODE_ECB)
        encrypted = cipher.encrypt(to_encrypt.encode())
        
        return f"https://e-cdns-proxy-{md5[0]}.dzcdn.net/mobile/1/{encrypted.hex()}"
    
    def generate_blowfish_key(self, track_id: str) -> bytes:
        """Generate Blowfish decryption key."""
        md5_hash = hashlib.md5(track_id.encode()).hexdigest()
        return "".join(
            chr(functools.reduce(lambda x, y: x ^ y, map(ord, t)))
            for t in zip(md5_hash[:16], md5_hash[16:], self.BLOWFISH_SECRET)
        ).encode()
    
    def decrypt_chunk(self, key: bytes, data: bytes) -> bytes:
        """Decrypt audio chunk."""
        return Blowfish.new(
            key, Blowfish.MODE_CBC,
            b"\x00\x01\x02\x03\x04\x05\x06\x07"
        ).decrypt(data)
    
    def download_track(self, track_id: str, quality: str = "FLAC") -> bytes:
        """Download and decrypt track."""
        track_info = self.get_track_info(track_id)
        url = self.get_download_url(track_id, track_info, quality)
        key = self.generate_blowfish_key(track_id)
        
        response = self.session.get(url, stream=True)
        response.raise_for_status()
        
        decrypted = bytearray()
        block_index = 0
        
        for chunk in response.iter_content(chunk_size=2048):
            if len(chunk) == 2048 and block_index % 3 == 0:
                chunk = self.decrypt_chunk(key, chunk)
            decrypted.extend(chunk)
            block_index += 1
        
        return bytes(decrypted)
```

### Get Album Tracks

```python
def get_album_tracks(client, album_id: str):
    """Get all tracks from an album."""
    album = client.api.get_album(album_id)
    tracks = []
    
    # Get initial tracks
    tracks.extend(album.get('tracks', []))
    
    # Handle pagination
    next_url = album.get('next')
    while next_url:
        response = requests.get(next_url)
        data = response.json()
        tracks.extend(data.get('data', []))
        next_url = data.get('next')
    
    return tracks
```

### Add ID3 Tags

```python
from mutagen.id3 import ID3, TIT2, TALB, TPE1, TRCK, TYER, APIC
from mutagen.mp3 import MP3

def add_id3_tags(filepath: str, track_info: dict, cover_art: bytes = None):
    """Add ID3 tags to MP3 file."""
    try:
        audio = MP3(filepath, ID3=ID3)
    except:
        audio = MP3(filepath)
        audio.add_tags()
    
    # Title
    audio.tags.add(TIT2(
        encoding=3,
        text=track_info.get('SNG_TITLE', '')
    ))
    
    # Artist
    audio.tags.add(TPE1(
        encoding=3,
        text=track_info.get('ART_NAME', '')
    ))
    
    # Album
    audio.tags.add(TALB(
        encoding=3,
        text=track_info.get('ALB_TITLE', '')
    ))
    
    # Track number
    audio.tags.add(TRCK(
        encoding=3,
        text=str(track_info.get('TRACK_NUMBER', ''))
    ))
    
    # Year
    audio.tags.add(TYER(
        encoding=3,
        text=str(track_info.get('YEAR', ''))
    ))
    
    # Cover art
    if cover_art:
        audio.tags.add(APIC(
            encoding=3,
            mime='image/jpeg',
            type=3,
            desc='Cover',
            data=cover_art
        ))
    
    audio.save()
```

## Node.js

### Basic Setup

```javascript
const axios = require('axios');
const crypto = require('crypto');

class DeezerClient {
    constructor(arlToken) {
        this.arlToken = arlToken;
        this.baseURL = 'https://www.deezer.com/ajax/gw-light.php';
        this.session = axios.create({
            baseURL: this.baseURL,
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Accept': 'application/json',
            }
        });
    }

    async authenticate() {
        // Note: Node.js implementation requires cookie-based auth
        // or using a proxy service
        const response = await this.session.get('/getAccount');
        return response.data;
    }
}
```

### AES Encryption for Download URLs

```javascript
function constructEncryptedUrl(md5, trackId, version, qualityId) {
    const toEncrypt = `${md5}${qualityId}${version}${trackId}`;
    const padding = 16 - (toEncrypt.length % 16);
    const padded = toEncrypt + String(padding).repeat(padding);
    
    const key = Buffer.from('jo6aey6haid2Teih');
    const cipher = crypto.createCipheriv('aes-128-ecb', key, null);
    let encrypted = cipher.update(padded, 'utf8', 'hex');
    encrypted += cipher.final('hex');
    
    const cdnIndex = md5[0];
    return `https://e-cdns-proxy-${cdnIndex}.dzcdn.net/mobile/1/${encrypted}`;
}
```

## Go

### Basic Client

```go
package main

import (
    "crypto/aes"
    "crypto/cipher"
    "encoding/hex"
    "fmt"
)

func constructEncryptedURL(md5, trackID string, version, qualityID int) (string, error) {
    toEncrypt := fmt.Sprintf("%s%d%d%s", md5, qualityID, version, trackID)
    
    // Pad to multiple of 16
    padding := 16 - (len(toEncrypt) % 16)
    toEncrypt += string(bytes.Repeat([]byte{byte(padding)}, padding))
    
    // AES ECB
    key := []byte("jo6aey6haid2Teih")
    block, err := aes.NewCipher(key)
    if err != nil {
        return "", err
    }
    
    encrypted := make([]byte, len(toEncrypt))
    for i := 0; i < len(toEncrypt); i += aes.BlockSize {
        block.Encrypt(encrypted[i:i+aes.BlockSize], []byte(toEncrypt[i:i+aes.BlockSize]))
    }
    
    cdnIndex := md5[0]
    return fmt.Sprintf("https://e-cdns-proxy-%c.dzcdn.net/mobile/1/%s", 
        cdnIndex, hex.EncodeToString(encrypted)), nil
}
```

## Rust

### Basic Setup

```rust
use aes::cipher::{KeyPadding, generic_array::GenericArray};
use aes::Aes128;
use md5;

fn construct_encrypted_url(md5: &str, track_id: &str, 
                           version: u32, quality_id: u32) -> String {
    let to_encrypt = format!("{}{}{}{}", md5, quality_id, version, track_id);
    
    // PKCS7 padding
    let padding = 16 - (to_encrypt.len() % 16);
    let padded = format!("{}{}", to_encrypt, 
        " ".repeat(padding).replace(" ", 
            &((16 - (to_encrypt.len() % 16)) as u8).to_string()));
    
    // AES ECB encryption would go here
    // (Use aes crate with ECB mode)
    
    let cdn_index = md5.chars().next().unwrap();
    format!("https://e-cdns-proxy-{}.dzcdn.net/mobile/1/{}", 
        cdn_index, encrypted_hex)
}
```

## Command Line Examples

### Using curl (Public API)

```bash
# Get track info (public API, no auth required)
curl "https://api.deezer.com/2.0/track/3135556"

# Get album tracks
curl "https://api.deezer.com/2.0/album/302127/tracks?limit=100"

# Get artist albums
curl "https://api.deezer.com/2.0/artist/27/albums?limit=100"
```

### Using httpie (Gateway API with cookies)

```bash
# First, get your ARL cookie from browser
# Then use it in requests

# Get account info
http --session=deezer https://www.deezer.com/ajax/gw-light.php \
    api_method="deezer.user.get_account" \
    Cookie="arl=YOUR_ARL_TOKEN"
```

## Quality Selection

```python
QUALITY_MAP = {
    "MP3_128": {"format_id": 1, "name": "Standard"},
    "MP3_320": {"format_id": 3, "name": "High"},
    "FLAC":    {"format_id": 6, "name": "Lossless"},
}

def select_quality(quality_str: str = "FLAC") -> int:
    """Get format ID for quality string."""
    return QUALITY_MAP.get(quality_str, QUALITY_MAP["FLAC"])["format_id"]
```

## Error Handling Pattern

```python
from requests.exceptions import RequestException, Timeout

class DeezerAPIError(Exception):
    pass

def safe_request(func):
    """Decorator for handling API errors."""
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Timeout:
            raise DeezerAPIError("Request timed out")
        except RequestException as e:
            raise DeezerAPIError(f"Request failed: {e}")
    return wrapper
```
