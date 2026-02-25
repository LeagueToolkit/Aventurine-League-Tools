import bpy
import bpy.utils.previews
import urllib.request
import urllib.error
import json
import os
import shutil
import zipfile
import threading
import ssl

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

class LOL_OT_CheckForUpdates(bpy.types.Operator):
    bl_idname = "lol.check_updates"
    bl_label = "Check for Updates"
    bl_description = "Check GitHub for the latest version of Aventurine League Tools"
    
    def execute(self, context):
        # Fix for finding preferences when package name varies
        addon_name = __package__.split('.')[0]
        prefs = context.preferences.addons[addon_name].preferences
        
        repo_owner = "LeagueToolkit"
        repo_name = "Aventurine-League-Tools"
            
        print(f"[Aventurine] Checking for updates from {repo_owner}/{repo_name}...")
        
        thread = threading.Thread(target=self.check_update_thread, args=(context, repo_owner, repo_name))
        thread.start()
        
        return {'FINISHED'}
    
    def check_update_thread(self, context, owner, repo):
        try:
            import time
            url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest?t={int(time.time())}"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Blender-Aventurine-Updater',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            })
            
            with urllib.request.urlopen(req, context=ssl_context) as response:
                data = json.loads(response.read().decode())
                
                tag_name = data.get('tag_name', '').strip()
                if tag_name.lower().startswith('v'):
                    version_str = tag_name[1:]
                else:
                    version_str = tag_name
                    
                try:
                    new_version = tuple(map(int, version_str.split('.')))
                except:
                    print(f"FAILED to parse version: {version_str}")
                    return

                from .. import bl_info 
                current_version = bl_info['version']
                
                print(f"[Aventurine] Current: {current_version}, Latest: {new_version}")

                if new_version > current_version:
                    addon_name = __package__.split('.')[0]
                    prefs = bpy.context.preferences.addons[addon_name].preferences
                    prefs.update_available = True
                    prefs.latest_version_str = tag_name
                    prefs.download_url = data.get('zipball_url', '') 
                    
                    assets = data.get('assets', [])
                    best_asset = None
                    for asset in assets:
                        if asset['name'].endswith('.zip'):
                            # Prefer asset with "Aventurine" in name
                            if "aventurine" in asset['name'].lower():
                                best_asset = asset['browser_download_url']
                                break
                            # Fallback to first zip if none match preference
                            if best_asset is None:
                                best_asset = asset['browser_download_url']
                    
                    if best_asset:
                        prefs.download_url = best_asset
                    
                    print(f"[Aventurine] Update available! {prefs.download_url}")
                else:
                    addon_name = __package__.split('.')[0]
                    prefs = bpy.context.preferences.addons[addon_name].preferences
                    prefs.update_available = False
                    # Allow redownload anyway?
                    print(f"[Aventurine] Up to date (or user can force redownload).")
                    # We can store the URL anyway so the "Install Update" button could technically work if we exposed it,
                    # but for now let's just properly report status.
                    # Actually, user requested "user can just redownload anyways".
                    # Let's say we set update_available = True so the button appears even if same version?
                    # Or we change the logic in the UI. 
                    # Simpler: Just ALWAYS set update_available = True if we found a valid release, 
                    # but maybe change the text?
                    # Let's just set the URL and let the user decide.
                    prefs.latest_version_str = tag_name + " (Re-download)"
                    prefs.download_url = data.get('zipball_url', '')
                    assets = data.get('assets', [])
                    best_asset = None
                    for asset in assets:
                        if asset['name'].endswith('.zip'):
                            if "aventurine" in asset['name'].lower():
                                best_asset = asset['browser_download_url']
                                break
                            if best_asset is None:
                                best_asset = asset['browser_download_url']
                    
                    if best_asset:
                        prefs.download_url = best_asset
                    
                    # If we want to allow force update, we set update_available = True
                    prefs.update_available = True

        except Exception as e:
            print(f"[Aventurine] Update check failed: {e}")

class LOL_OT_UpdateAddon(bpy.types.Operator):
    bl_idname = "lol.update_addon"
    bl_label = "Update Addon"
    bl_description = "Download and install the latest version"
    
    def execute(self, context):
        addon_name = __package__.split('.')[0]
        prefs = context.preferences.addons[addon_name].preferences
        url = prefs.download_url
        if not url:
            self.report({'ERROR'}, "No download URL found")
            return {'CANCELLED'}
        version = prefs.latest_version_str
        
        thread = threading.Thread(target=self.install_update_thread, args=(context, url, version))
        thread.start()
        
        return {'FINISHED'}

    def install_update_thread(self, context, url, version):
        import tempfile
        import zipfile
        import shutil
        import time
        
        try:
            print(f"[Aventurine] Downloading update from {url}...")
            
            req = urllib.request.Request(url, headers={'User-Agent': 'Blender-Aventurine-Updater'})
            with urllib.request.urlopen(req, context=ssl_context) as response:
                data = response.read()
                
            tmp_dir = tempfile.gettempdir()
            zip_path = os.path.join(tmp_dir, "aventurine_update.zip")
            extract_dir = os.path.join(tmp_dir, "aventurine_extract")
            
            with open(zip_path, 'wb') as f:
                f.write(data)
                
            print(f"[Aventurine] Downloaded to {zip_path}")
            
            # Installation needs to happen carefully
            # We can't use bpy.ops.preferences.addon_install because it misnames the folder
            
            def perform_install():
                try:
                    # 1. Extract
                    if os.path.exists(extract_dir):
                        shutil.rmtree(extract_dir, ignore_errors=True)
                    os.makedirs(extract_dir, exist_ok=True)
                    
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                        
                    # 2. Find the inner folder (Github release zips usually have one root folder)
                    inner_items = os.listdir(extract_dir)
                    source_path = None
                    for item in inner_items:
                        item_path = os.path.join(extract_dir, item)
                        if os.path.isdir(item_path):
                            # Verify it looks like an addon (has __init__.py)
                            if "__init__.py" in os.listdir(item_path):
                                source_path = item_path
                                break
                    
                    if not source_path:
                        print("[Aventurine] Update failed: Could not find valid addon in zip")
                        return

                    # 3. Identify Target Directory
                    # We want to maintain the current folder name so it stays enabled
                    addon_name = __package__.split('.')[0]
                    addons_dir = bpy.utils.user_resource('SCRIPTS', path="addons")
                    target_path = os.path.join(addons_dir, addon_name)
                    
                    print(f"Target: {target_path}")
                    
                    # 4. Swap Folders
                    # Rename current to _old (Windows allows renaming used folders usually)
                    backup_path = os.path.join(addons_dir, f"{addon_name}_old_{int(time.time())}")
                    
                    if os.path.exists(target_path):
                        try:
                            os.rename(target_path, backup_path)
                        except Exception as e:
                            print(f"Could not rename current addon folder: {e}. Trying overwrite...")
                            # If rename fails, we resort to copytree over it
                            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
                            backup_path = None # No backup created
                    
                    if backup_path and os.path.exists(backup_path):
                        # Move new to target
                        shutil.move(source_path, target_path)
                        
                        # Try to remove backup (might fail if files are locked)
                        try:
                            shutil.rmtree(backup_path) 
                        except:
                            print(f"[Aventurine] Could not fully remove backup {backup_path} (files in use). You can delete it manually later.")
                            
                    # 5. Success UI Update
                    def update_ui():
                        addon_name_ui = __package__.split('.')[0]
                        if addon_name_ui in bpy.context.preferences.addons:
                            prefs = bpy.context.preferences.addons[addon_name_ui].preferences
                            prefs.update_available = False
                            prefs.latest_version_str = f"Updated to {version}"
                        
                    bpy.app.timers.register(update_ui, first_interval=0.1)
                    print(f"[Aventurine] Update installed successfully.")
                    
                except Exception as e:
                    print(f"[Aventurine] Install failed: {e}")
                    import traceback
                    traceback.print_exc()

            # Run install logic immediately (file ops don't need main thread usually, 
            # but modifying addon folder might be safer? No, standard python file ops are fine)
            perform_install()

        except Exception as e:
            print(f"[Aventurine] Update download failed: {e}")
