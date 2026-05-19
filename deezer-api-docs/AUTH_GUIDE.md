# Deezer Authentication Guide

## Overview

Deezer uses **ARL (Authentication Remember Login)** tokens for authentication. This is a session-based authentication mechanism that provides full account access.

## How to Obtain Your ARL Token

### Method 1: Browser Cookie Extraction

1. **Log in to Deezer**
   - Open your browser and go to https://www.deezer.com
   - Log in to your account

2. **Open Developer Tools**
   - Press `F12` or right-click and select "Inspect"
   - Go to the **Application** tab (Chrome) or **Storage** tab (Firefox)

3. **Find the ARL Cookie**
   - In the left sidebar, expand **Cookies**
   - Select `.deezer.com`
   - Look for a cookie named `arl`
   - Copy the cookie value

4. **Alternative: Network Tab**
   - Go to the **Network** tab in developer tools
   - Refresh the page
   - Look for API requests to `gw-light.php` or `getAccount`
   - Check the request cookies for `arl`

### Method 2: From Existing Session

If you have an active Deezer session, you can extract the ARL token from browser storage:

```javascript
// Run in browser console on deezer.com
document.cookie.split('; ').find(row => row.startsWith('arl=')).split('=')[1]
```

## Using the ARL Token

### Python (deezer-py Library)

```python
import deezer

# Initialize client
client = deezer.Deezer()

# Authenticate
success = client.login_via_arl("your_arl_token_here")

if success:
    # Get user information
    user_data = client.current_user
    user_id = user_data.get('id')
    license_token = user_data.get('license_token')
    print(f"Authenticated as: {user_data.get('name')}")
```

### With deezload.py CLI

```bash
# Download a track
python deezload.py --arl YOUR_ARL_TOKEN --url "https://www.deezer.com/track/12345"

# Save token to config (secure storage)
python deezload.py --arl YOUR_ARL_TOKEN --save-config

# After saving config, omit --arl
python deezload.py --url "https://www.deezer.com/track/12345"
```

## Configuration File

The deezload CLI stores configuration in:
- **Linux/macOS**: `~/.config/deezload/deezload-config.ini`
- **Windows**: `%APPDATA%\deezload\deezload-config.ini`

### Config File Format

```ini
[deezer]
arl_token = your_arl_token_here
quality = FLAC
output = downloads
```

### Security Note

The ARL token grants **full account access**. Protect it accordingly:

- Config file permissions are automatically set to `600` (owner read/write only)
- Never commit tokens to version control
- Use environment variables for sensitive deployments
- Rotate tokens if compromised

## License Token

After authentication, you receive a `license_token`. This token:

- Is tied to your session
- May be required for certain API operations
- Should be stored alongside your user data

```python
# After authentication
user_data = client.current_user
license_token = user_data.get('license_token')
```

## Session Management

### Session Lifetime

ARL tokens are persistent but can expire. Signs of expiration:

- 401 Unauthorized errors
- Failed authentication attempts
- Invalid license token errors

### Re-authentication

When a token expires, obtain a new one:

1. Log out from Deezer in your browser
2. Clear cookies
3. Log in again
4. Extract the new ARL token

## Environment Variables

For CI/CD or containerized deployments:

```bash
export DEEZER_ARL="your_arl_token_here"
export DEEZER_QUALITY="FLAC"
export DEEZER_OUTPUT="downloads"
```

```python
import os

arl_token = os.environ.get('DEEZER_ARL')
quality = os.environ.get('DEEZER_QUALITY', 'FLAC')
```

## Troubleshooting

### Authentication Fails

| Issue | Solution |
|-------|----------|
| Invalid token format | Ensure token is copied correctly (no extra whitespace) |
| Token expired | Re-authenticate and get a new token |
| Network error | Check internet connection and firewall |

### Common Error Messages

```
✗ Authentication failed. Check your ARL token.
```
**Cause**: Invalid or expired token
**Solution**: Get a fresh ARL token from browser

```
✗ Authentication error: ...
```
**Cause**: Network or library issue
**Solution**: Check internet, verify deezer-py is installed

## Best Practices

1. **Store tokens securely**: Use config files with restricted permissions
2. **Don't log tokens**: Keep tokens out of logs and console output
3. **Use environment variables**: For production deployments
4. **Rotate periodically**: Especially if used across multiple devices
5. **Limit scope**: Use separate tokens for development and production

## API Rate Limits

While not strictly documented, Deezer enforces rate limits:

- Implement exponential backoff for 429 errors
- Default retry: 0.5s, 1s, 2s, 4s
- Consider request queuing for high-volume applications

```python
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure retry with backoff
retry = Retry(
    total=3,
    backoff_factor=0.5,
    status_forcelist=[429, 500, 502, 503, 504]
)
session.mount("https://", HTTPAdapter(max_retries=retry))
```
