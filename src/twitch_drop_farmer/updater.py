"""Auto-update and version checking functionality."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple
from urllib.request import urlopen

logger = logging.getLogger(__name__)


class VersionInfo(NamedTuple):
    """Release version information."""

    current: str
    latest: str
    download_url: str
    is_update_available: bool
    release_notes: str


def parse_version(version_str: str) -> tuple[int, ...]:
    """Parse version string to tuple for comparison."""
    try:
        return tuple(map(int, version_str.split(".")))
    except (ValueError, AttributeError):
        return (0,)


def check_for_updates(current_version: str, timeout_sec: int = 10) -> VersionInfo | None:
    """
    Check GitHub releases for newer version.

    Returns VersionInfo if check succeeds, None on error.
    """
    try:
        url = "https://api.github.com/repos/NightmareFTW/TwitchDropFarmer/releases/latest"
        with urlopen(url, timeout=timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))

        latest_version = data.get("tag_name", "").lstrip("v")
        download_url = None
        for asset in data.get("assets", []):
            if asset["name"].endswith("-win64.zip"):
                download_url = asset["browser_download_url"]
                break

        if not download_url:
            download_url = data.get("html_url", "")

        release_notes = data.get("body", "")[:500]  # First 500 chars

        current_tuple = parse_version(current_version)
        latest_tuple = parse_version(latest_version)
        is_update_available = latest_tuple > current_tuple

        logger.info(
            f"Version check: current={current_version}, latest={latest_version}, "
            f"update_available={is_update_available}"
        )

        return VersionInfo(
            current=current_version,
            latest=latest_version,
            download_url=download_url,
            is_update_available=is_update_available,
            release_notes=release_notes,
        )

    except Exception as exc:
        logger.error(f"Version check failed: {exc}")
        return None


def download_release_zip(url: str, dest_path: Path, timeout_sec: int = 30) -> bool:
    """Download release ZIP to destination path."""
    try:
        logger.info(f"Downloading release from {url}")
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with urlopen(url, timeout=timeout_sec) as response:
            with open(dest_path, "wb") as f:
                f.write(response.read())

        logger.info(f"Downloaded to {dest_path}")
        return True
    except Exception as exc:
        logger.error(f"Download failed: {exc}")
        return False


def open_release_page(url: str) -> bool:
    """Open release page in browser."""
    try:
        import webbrowser

        webbrowser.open(url)
        return True
    except Exception as exc:
        logger.error(f"Failed to open browser: {exc}")
        return False


def apply_update_and_restart(
    download_url: str, 
    restart_delay_sec: int = 30, 
    notification_callback=None
) -> bool:
    """
    Download and apply update, then restart application.
    
    Args:
        download_url: URL to download release
        restart_delay_sec: Seconds to wait before restarting
        notification_callback: Optional callback to notify UI of progress
    
    Returns:
        True if update applied successfully
    """
    try:
        import shutil
        import time
        import zipfile
        from threading import Thread
        
        def _do_update():
            try:
                # Determine download path
                app_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent.parent
                temp_zip = app_dir / "update_temp.zip"
                
                # Download
                if notification_callback:
                    notification_callback("Transferindo ficheiro...")
                if not download_release_zip(download_url, temp_zip):
                    logger.error("Update download failed")
                    return
                
                # Extract to temp directory
                if notification_callback:
                    notification_callback("Extraindo ficheiros...")
                temp_extract = app_dir / "update_temp"
                if temp_extract.exists():
                    shutil.rmtree(temp_extract)
                
                with zipfile.ZipFile(temp_zip, 'r') as zf:
                    zf.extractall(temp_extract)
                
                # Replace current executable (for frozen app)
                if getattr(sys, 'frozen', False):
                    exe_path = Path(sys.executable)
                    exe_backup = exe_path.with_suffix('.exe.bak')
                    
                    # Find new exe in extracted files
                    new_exe = None
                    for item in temp_extract.rglob('*.exe'):
                        if 'TwitchDropFarmer' in item.name:
                            new_exe = item
                            break
                    
                    if new_exe:
                        if notification_callback:
                            notification_callback(f"Aguardando {restart_delay_sec}s para reiniciar...")
                        time.sleep(restart_delay_sec)
                        
                        # Backup old exe
                        if exe_backup.exists():
                            exe_backup.unlink()
                        exe_path.rename(exe_backup)
                        shutil.copy2(new_exe, exe_path)
                        
                        logger.info("Update applied, restarting...")
                        # Restart application
                        subprocess.Popen([str(exe_path)])
                        sys.exit(0)
                
                # Cleanup
                shutil.rmtree(temp_extract, ignore_errors=True)
                temp_zip.unlink(missing_ok=True)
                
            except Exception as exc:
                logger.exception(f"Update failed: {exc}")
                if notification_callback:
                    notification_callback(f"Erro na atualização: {exc}")
        
        # Run update in background thread
        update_thread = Thread(target=_do_update, daemon=False)
        update_thread.start()
        return True
        
    except Exception as exc:
        logger.error(f"Failed to start update: {exc}")
        return False


class UpdateManager:
    """Manages automatic update checking and installation."""
    
    def __init__(self, config=None):
        """Initialize update manager with optional config."""
        self.config = config
        self.last_check_time = 0
        self.check_interval_sec = 3600  # Check every hour
        
    def should_check_updates(self) -> bool:
        """Check if enough time has passed for next update check."""
        import time
        elapsed = time.time() - self.last_check_time
        return elapsed >= self.check_interval_sec
    
    def check_and_apply(self, current_version: str, auto_apply: bool = False, notification_callback=None) -> dict:
        """
        Check for updates and optionally apply automatically.
        
        Returns dict with status and details.
        """
        import time
        self.last_check_time = time.time()
        
        version_info = check_for_updates(current_version)
        if not version_info:
            return {"success": False, "error": "Version check failed"}
        
        result = {
            "success": True,
            "current_version": version_info.current,
            "latest_version": version_info.latest,
            "update_available": version_info.is_update_available,
            "download_url": version_info.download_url,
            "release_notes": version_info.release_notes,
        }
        
        if version_info.is_update_available and auto_apply:
            logger.info(f"Applying auto-update: {version_info.current} -> {version_info.latest}")
            delay = self.config.auto_update_restart_delay_sec if self.config else 30
            apply_update_and_restart(version_info.download_url, delay, notification_callback)
        
        return result

