"""
History management for LoL Import/Export
Stores recent files for SKN and ANM
"""

import bpy
import os
from bpy.props import StringProperty, CollectionProperty, IntProperty, BoolProperty
from bpy.types import PropertyGroup, AddonPreferences, Operator


import json

class LOLHistoryItem(PropertyGroup):
    filepath: StringProperty(name="File Path", subtype='FILE_PATH')
    filename: StringProperty(name="File Name")


# Removed LOLAddonPreferences - moved to __init__.py

HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".lol_blender_history.json")

def load_history_json():
    """Load history from JSON file"""
    if not os.path.exists(HISTORY_FILE):
        return {'skn': [], 'anm': []}
    
    try:
        with open(HISTORY_FILE, 'r') as f:
            data = json.load(f)
            return data
    except Exception as e:
        print(f"Error loading history JSON: {e}")
        return {'skn': [], 'anm': []}

def save_history_json(skn_list, anm_list):
    """Save history to JSON file"""
    data = {
        'skn': [{'filepath': item.filepath, 'filename': item.filename} for item in skn_list],
        'anm': [{'filepath': item.filepath, 'filename': item.filename} for item in anm_list]
    }
    
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving history JSON: {e}")

def get_addon_preferences(context):
    """Safely get addon preferences"""
    # Get the actual package name dynamically from this module's parent
    # __name__ is something like "Aventurine-League-Tools-main.utils.history"
    # We want just "Aventurine-League-Tools-main"
    package_name = __name__.split('.')[0]
    
    if package_name in context.preferences.addons:
        return context.preferences.addons[package_name].preferences
    
    # Fallback: search for Aventurine in addon names
    for name in context.preferences.addons.keys():
        if "aventurine" in name.lower():
            return context.preferences.addons[name].preferences
    
    return None

def sync_history_from_json(context):
    """Sync the UI list from the JSON file"""
    prefs = get_addon_preferences(context)
    if not prefs:
        return

    data = load_history_json()
    
    prefs.skn_history.clear()
    for item in data.get('skn', []):
        new = prefs.skn_history.add()
        new.filepath = item['filepath']
        new.filename = item['filename']
        
    prefs.anm_history.clear()
    for item in data.get('anm', []):
        new = prefs.anm_history.add()
        new.filepath = item['filepath']
        new.filename = item['filename']

def add_to_history(context, filepath, history_type='SKN'):
    """Add a file to the history, keeping only last 10"""
    prefs = get_addon_preferences(context)
    if not prefs:
        return
    
    if history_type == 'SKN':
        history_list = prefs.skn_history
    else:
        history_list = prefs.anm_history
        
    # Check if exists and remove (to move to top)
    for i, item in enumerate(history_list):
        if item.filepath == filepath:
            history_list.remove(i)
            break
            
    # Add to beginning (append then read reversed is easier for JSON structure too)
    item = history_list.add()
    item.filepath = filepath
    item.filename = os.path.basename(filepath)
    
    # Trim to 5
    while len(history_list) > 5:
        history_list.remove(0) # Remove oldest (at start)
        
    # Save to JSON immediately
    save_history_json(prefs.skn_history, prefs.anm_history)


class LOL_OT_OpenFromHistory(Operator):
    """Open a file from history"""
    bl_idname = "lol.open_history"
    bl_label = "Open Recent"
    bl_description = "Open this file"
    
    filepath: StringProperty()
    file_type: StringProperty() # SKN or ANM
    
    def execute(self, context):
        if not os.path.exists(self.filepath):
            self.report({'ERROR'}, f"File not found: {self.filepath}")
            return {'CANCELLED'}
            
        if self.file_type == 'SKN':
            bpy.ops.import_scene.skn(filepath=self.filepath)
        elif self.file_type == 'ANM':
            bpy.ops.import_scene.anm(filepath=self.filepath)
            
        return {'FINISHED'}


class LOL_OT_ClearHistory(Operator):
    """Clear history"""
    bl_idname = "lol.clear_history"
    bl_label = "Clear History"
    
    history_type: StringProperty()
    
    def execute(self, context):
        prefs = get_addon_preferences(context)
        if not prefs:
            return {'CANCELLED'}
        
        if self.history_type == 'SKN':
            prefs.skn_history.clear()
        else:
            prefs.anm_history.clear()
        
        # Save empty state
        save_history_json(prefs.skn_history, prefs.anm_history)
            
        return {'FINISHED'}


# Global flag to ensure we load once per session
HISTORY_LOADED = False

def draw_history_panel(layout, context, history_type):
    global HISTORY_LOADED
    try:
        prefs = get_addon_preferences(context)
        if not prefs:
            return
            
        # Lazy load on first draw
        if not HISTORY_LOADED:
            sync_history_from_json(context)
            HISTORY_LOADED = True
        
        if history_type == 'SKN':
            history_list = prefs.skn_history
            icon = 'MESH_DATA'
        else:
            history_list = prefs.anm_history
            icon = 'ANIM_DATA'
            
        # Draw collapsible box
        box = layout.box()
        row = box.row()
        
        # Toggle button
        is_visible = prefs.show_skn_history if history_type == 'SKN' else prefs.show_anm_history
        icon_arrow = 'TRIA_DOWN' if is_visible else 'TRIA_RIGHT'
        
        prop_name = "show_skn_history" if history_type == 'SKN' else "show_anm_history"
        row.prop(prefs, prop_name, icon=icon_arrow, text="Recent Files", emboss=False)
        
        row.operator("lol.clear_history", text="", icon='TRASH').history_type = history_type
        
        if is_visible:
            if len(history_list) == 0:
                box.label(text="No history yet", icon='INFO')
            else:
                # Show reversed (newest first)
                for i in range(len(history_list)-1, -1, -1):
                    item = history_list[i]
                    row = box.row()
                    op = row.operator("lol.open_history", text=item.filename, icon=icon)
                    op.filepath = item.filepath
                    op.file_type = history_type
    except Exception as e:
        layout.label(text="Error loading history", icon='ERROR')
        print(f"History draw error: {e}")
