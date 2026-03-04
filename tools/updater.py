import bpy
import urllib.request
import urllib.error
import json
import os
import shutil
import zipfile
import threading
import tempfile
import time


class LOL_OT_CheckForUpdates(bpy.types.Operator):
    bl_idname = "lol.check_updates"
    bl_label = "Check for Updates"
    bl_description = "Check GitHub for the latest version of Aventurine League Tools"

    def execute(self, context):
        addon_name = __package__.split('.')[0]
        prefs = context.preferences.addons[addon_name].preferences

        # Reset status
        prefs.update_status = "Checking for updates..."
        prefs.update_available = False
        prefs.update_in_progress = False

        repo_owner = "LeagueToolkit"
        repo_name = "Aventurine-League-Tools"

        thread = threading.Thread(
            target=self._check_thread,
            args=(repo_owner, repo_name),
            daemon=True
        )
        thread.start()

        return {'FINISHED'}

    def _check_thread(self, owner, repo):
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest?t={int(time.time())}"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Blender-Aventurine-Updater',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            })

            with urllib.request.urlopen(req) as response:
                data = json.loads(response.read().decode())

            tag_name = data.get('tag_name', '').strip()
            version_str = tag_name[1:] if tag_name.lower().startswith('v') else tag_name

            try:
                new_version = tuple(map(int, version_str.split('.')))
            except Exception:
                _set_prefs(update_status=f"Failed to parse version: {version_str}")
                return

            from .. import bl_info
            current_version = bl_info['version']

            # Find best download URL
            download_url = data.get('zipball_url', '')
            for asset in data.get('assets', []):
                if asset['name'].endswith('.zip'):
                    if "aventurine" in asset['name'].lower():
                        download_url = asset['browser_download_url']
                        break
                    if download_url == data.get('zipball_url', ''):
                        download_url = asset['browser_download_url']

            if new_version > current_version:
                _set_prefs(
                    update_available=True,
                    latest_version_str=tag_name,
                    download_url=download_url,
                    update_status=f"Update available: {tag_name}"
                )
            else:
                _set_prefs(
                    update_available=True,
                    latest_version_str=tag_name,
                    download_url=download_url,
                    update_status=f"Up to date ({tag_name}) - re-download available"
                )

        except Exception as e:
            _set_prefs(update_status=f"Check failed: {e}")


class LOL_OT_UpdateAddon(bpy.types.Operator):
    bl_idname = "lol.update_addon"
    bl_label = "Install Update"
    bl_description = "Download and install the latest version"

    def execute(self, context):
        addon_name = __package__.split('.')[0]
        prefs = context.preferences.addons[addon_name].preferences

        url = prefs.download_url
        if not url:
            self.report({'ERROR'}, "No download URL found")
            return {'CANCELLED'}

        if prefs.update_in_progress:
            self.report({'WARNING'}, "Update already in progress")
            return {'CANCELLED'}

        version = prefs.latest_version_str

        _set_prefs(update_in_progress=True, update_status="Starting download...")

        thread = threading.Thread(
            target=self._install_thread,
            args=(url, version),
            daemon=True
        )
        thread.start()

        return {'FINISHED'}

    def _install_thread(self, url, version):
        try:
            _set_prefs(update_status="Downloading...")

            req = urllib.request.Request(url, headers={'User-Agent': 'Blender-Aventurine-Updater'})
            with urllib.request.urlopen(req) as response:
                total = response.headers.get('Content-Length')
                total = int(total) if total else None

                chunks = []
                downloaded = 0
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded / total * 100)
                        _set_prefs(update_status=f"Downloading... {pct}% ({downloaded // 1024}KB / {total // 1024}KB)")
                    else:
                        _set_prefs(update_status=f"Downloading... {downloaded // 1024}KB")

                data = b''.join(chunks)

            _set_prefs(update_status="Installing...")

            tmp_dir = tempfile.gettempdir()
            zip_path = os.path.join(tmp_dir, "aventurine_update.zip")
            extract_dir = os.path.join(tmp_dir, "aventurine_extract")

            with open(zip_path, 'wb') as f:
                f.write(data)

            # Extract
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir, ignore_errors=True)
            os.makedirs(extract_dir, exist_ok=True)

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)

            # Find the addon root inside the zip
            source_path = None
            for item in os.listdir(extract_dir):
                item_path = os.path.join(extract_dir, item)
                if os.path.isdir(item_path) and "__init__.py" in os.listdir(item_path):
                    source_path = item_path
                    break

            if not source_path:
                _set_prefs(
                    update_status="Install failed: no valid addon found in zip",
                    update_in_progress=False
                )
                return

            # Target directory - keep current folder name so it stays enabled
            addon_name = __package__.split('.')[0]
            addons_dir = bpy.utils.user_resource('SCRIPTS', path="addons")
            target_path = os.path.join(addons_dir, addon_name)

            _set_prefs(update_status="Swapping addon files...")

            # Rename current -> backup, move new -> target
            backup_path = os.path.join(addons_dir, f"{addon_name}_old_{int(time.time())}")

            if os.path.exists(target_path):
                try:
                    os.rename(target_path, backup_path)
                except Exception:
                    # Rename failed (locked files), overwrite in-place
                    _set_prefs(update_status="Files locked, overwriting in-place...")
                    shutil.copytree(source_path, target_path, dirs_exist_ok=True)
                    backup_path = None

            if backup_path and os.path.exists(backup_path):
                shutil.move(source_path, target_path)
                # Try to clean backup immediately
                try:
                    shutil.rmtree(backup_path)
                except Exception:
                    # Will be cleaned on next startup
                    pass

            # Cleanup temp files
            try:
                os.remove(zip_path)
                shutil.rmtree(extract_dir, ignore_errors=True)
            except Exception:
                pass

            _set_prefs(
                update_available=False,
                update_in_progress=False,
                update_status=f"Updated to {version} - restart Blender to apply"
            )

        except Exception as e:
            _set_prefs(
                update_status=f"Update failed: {e}",
                update_in_progress=False
            )


def _set_prefs(**kwargs):
    """Thread-safe way to set addon preferences via bpy.app.timers."""
    def _apply():
        try:
            addon_name = __package__.split('.')[0]
            prefs = bpy.context.preferences.addons[addon_name].preferences
            for key, value in kwargs.items():
                setattr(prefs, key, value)
            # Force UI redraw so status updates are visible
            for area in bpy.context.screen.areas if bpy.context.screen else []:
                if area.type == 'PREFERENCES':
                    area.tag_redraw()
        except Exception:
            pass
        return None  # Don't repeat

    bpy.app.timers.register(_apply, first_interval=0.0)


def cleanup_old_backups():
    """Remove leftover _old_ backup folders from previous updates.
    Called once on addon startup."""
    try:
        addon_name = __package__.split('.')[0]
        addons_dir = bpy.utils.user_resource('SCRIPTS', path="addons")
        prefix = f"{addon_name}_old_"

        for item in os.listdir(addons_dir):
            if item.startswith(prefix):
                backup_path = os.path.join(addons_dir, item)
                if os.path.isdir(backup_path):
                    try:
                        shutil.rmtree(backup_path)
                        print(f"[Aventurine] Cleaned up old backup: {item}")
                    except Exception as e:
                        print(f"[Aventurine] Could not remove backup {item}: {e}")
    except Exception:
        pass
