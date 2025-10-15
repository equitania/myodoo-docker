# getScripts.py User Detection Logic

## Critical: Dynamic User Detection

The script MUST work in ALL execution scenarios without hardcoded usernames:

### Execution Scenarios

1. **sudo user** (e.g., `sudo ./getScripts.py`):
   - `SUDO_USER` environment variable is set (e.g., "picard", "equitania", "admin")
   - Uses `pwd.getpwnam(SUDO_USER).pw_dir` to get real user's home
   - Example: SUDO_USER=picard → /home/picard

2. **root login** (e.g., logged in as root):
   - No `SUDO_USER` variable
   - Uses `os.path.expanduser('~')` → /root
   - Repository installed in /root/myodoo-docker

3. **normal user** (no sudo):
   - No `SUDO_USER` variable
   - Uses `os.path.expanduser('~')` → /home/username
   - Repository installed in /home/username/myodoo-docker

### Implementation (v6.8.2)

```python
if os.environ.get('SUDO_USER'):
    # Running with sudo - use the real user's home directory
    sudo_user = os.environ['SUDO_USER']
    try:
        _myhome = pwd.getpwnam(sudo_user).pw_dir
        logger.info(f"Running with sudo as user '{sudo_user}', using home: {_myhome}")
    except KeyError:
        # Fallback if user lookup fails
        logger.warning(f"Could not find home for SUDO_USER '{sudo_user}', using current home")
        _myhome = os.path.expanduser('~')
else:
    # Running as root or normal user without sudo
    _myhome = os.path.expanduser('~')
    current_user = os.environ.get('USER', 'unknown')
    logger.info(f"Running as user '{current_user}', using home: {_myhome}")
```

### Key Points

- **NO hardcoded usernames** like "equitania" or "picard"
- **Dynamic detection** using environment variables
- **Proper fallback** if user lookup fails
- **Clear logging** of detected user and home directory
- **Works on any Debian/Ubuntu** installation regardless of username
