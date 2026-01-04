import os
import bpy
import bpy.utils.previews

# Global dictionary to hold preview collections
preview_collections = {}

def register():
    pcoll = bpy.utils.previews.new()
    
    # Path to the folder where the icon is
    my_icons_dir = os.path.join(os.path.dirname(__file__))
    
    # Load the icon
    # We use "plugin_icon" as the identifier key
    pcoll.load("plugin_icon", os.path.join(my_icons_dir, "50.png"), 'IMAGE')
    
    preview_collections["main"] = pcoll

def unregister():
    for pcoll in preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    preview_collections.clear()

def get_icon(name):
    pcoll = preview_collections.get("main")
    if not pcoll:
        return 0
    
    icon = pcoll.get(name)
    if not icon:
        return 0
        
    return icon.icon_id
