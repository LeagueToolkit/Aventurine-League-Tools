bl_info = {
    "name": "Aventurine: League Tools",
    "author": "Bud and Frog",
    "version": (2, 1, 2),
    "blender": (4, 0, 0),
    "location": "File > Import-Export",
    "description": "Plugin for working with League of Legends 3D assets natively",
    "category": "Import-Export",
}

import bpy
from bpy.props import StringProperty, BoolProperty, CollectionProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from .ui import panels
from .ui import icons
from .tools import updater
from .tools import limit_influences
from .tools import uv_corners
from .tools import normals
from .tools import bind_pose
from .io import export_scb
from .io import export_sco
from .utils import history
from .io import texture_ops
from .tools import smart_weights
# Note: retarget and physics are now under .extras and loaded conditionally

def update_physics(self, context):
    try:
        from .extras import physics
        if self.enable_physics:
            physics.register()
        else:
            physics.unregister()
    except Exception as e:
        print(f"Error toggling physics: {e}")

def update_retarget(self, context):
    try:
        from .extras import retarget
        if self.enable_retarget:
            retarget.register()
        else:
            retarget.unregister()
    except Exception as e:
        print(f"Error toggling retarget: {e}")

def update_anim_loader(self, context):
    try:
        from .extras import anim_loader
        if self.enable_anim_loader:
            anim_loader.register()
        else:
            anim_loader.unregister()
    except Exception as e:
        print(f"Error toggling anim loader: {e}")

def update_animation_tools(self, context):
    """Master toggle for Misc LoL Tools - enables/disables physics, retarget, anim loader, and skin tools"""
    try:
        if self.enable_animation_tools:
            # Enable all sub-panels
            self.enable_physics = True
            self.enable_retarget = True
            self.enable_anim_loader = True
            self.enable_skin_tools = True
        else:
            # Disable all sub-panels
            self.enable_physics = False
            self.enable_retarget = False
            self.enable_anim_loader = False
            self.enable_skin_tools = False
    except Exception as e:
        print(f"Error toggling animation tools: {e}")

def update_skin_tools(self, context):
    """Toggle the Skin Tools panel visibility"""
    try:
        if self.enable_skin_tools:
            smart_weights.register_panel()
        else:
            smart_weights.unregister_panel()
    except Exception as e:
        print(f"Error toggling skin tools: {e}")

def get_preferences(context):
    return context.preferences.addons[__package__].preferences

class LolAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__
    
    # Feature Toggles
    enable_animation_tools: BoolProperty(
        name="Enable Misc LoL Tools",
        description="Show the Misc LoL Tools tab (Physics, Retargeting, Anim Loader)",
        default=False,
        update=update_animation_tools
    )
    
    enable_physics: BoolProperty(
        name="League Physics",
        description="Enable the physics simulation panel (based on Wiggle 2)",
        default=False,
        update=update_physics
    )
    
    enable_retarget: BoolProperty(
        name="Animation Retargeting",
        description="Enable the animation retargeting panel",
        default=False,
        update=update_retarget
    )

    enable_anim_loader: BoolProperty(
        name="Load Animations",
        description="Enable the animation loader panel for quick-loading animations from the animations folder",
        default=False,
        update=update_anim_loader
    )

    enable_skin_tools: BoolProperty(
        name="Skin Tools",
        description="Enable the skin tools panel for automatic weight painting",
        default=False,
        update=update_skin_tools
    )
    
    # History Properties (Moved from history.py)
    skn_history: CollectionProperty(type=history.LOLHistoryItem)
    anm_history: CollectionProperty(type=history.LOLHistoryItem)
    show_skn_history: BoolProperty(default=False, options={'SKIP_SAVE'})
    show_anm_history: BoolProperty(default=False, options={'SKIP_SAVE'})
    
    # Updater Properties
    update_available: BoolProperty(default=False, options={'SKIP_SAVE'})
    latest_version_str: StringProperty(default="", options={'SKIP_SAVE'})
    download_url: StringProperty(default="", options={'SKIP_SAVE'})

    def draw(self, context):
        layout = self.layout
        
        # Updater Section
        box = layout.box()
        box.label(text="Updates", icon='WORLD')
        box.label(text="Restart Blender after updating to apply changes.", icon='ERROR')
        
        row = box.row()
        if self.update_available:
            row.label(text=f"New version available: {self.latest_version_str}", icon='INFO')
            row.operator("lol.update_addon", text="Install Update", icon='IMPORT')
        else:
            row.operator("lol.check_updates", text="Check for Updates")
            if self.latest_version_str:
                row.label(text=self.latest_version_str) # Status message

        box = layout.box()
        box.label(text="Optional Features:")

        # Misc LoL Tools
        box.prop(self, "enable_animation_tools", text="Misc LoL Tools")
        if self.enable_animation_tools:
            sub = box.box()
            sub.prop(self, "enable_skin_tools")
            sub.prop(self, "enable_physics")
            sub.prop(self, "enable_retarget")
            sub.prop(self, "enable_anim_loader")
        
        box = layout.box()
        box.label(text="History (Stored Automatically)")




# Import operator for SKN files
class ImportSKN(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.skn"
    bl_label = "Import SKN"
    bl_options = {'PRESET', 'UNDO'}
    
    filename_ext = ".skn"
    filter_glob: StringProperty(default="*.skn", options={'HIDDEN'})
    
    load_skl: BoolProperty(
        name="Load SKL",
        description="Automatically load matching SKL file",
        default=True
    )

    split_by_material: BoolProperty(
        name="Split by Material",
        description="Split mesh into separate objects for each material (matches Maya behavior)",
        default=True
    )
    
    auto_load_textures: BoolProperty(
        name="Auto-Load Textures",
        description="Try to find and apply .dds/.png textures from the same folder (Requires converted textures, not .tex)",
        default=True
    )
    
    def execute(self, context):
        from .io import import_skn
        result = import_skn.load(self, context, self.filepath, self.load_skl, self.split_by_material, self.auto_load_textures)
        if result == {'FINISHED'}:
            history.add_to_history(context, self.filepath, 'SKN')
        return result


# Import operator for SKL files
class ImportSKL(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.skl"
    bl_label = "Import SKL"
    bl_options = {'PRESET', 'UNDO'}
    
    filename_ext = ".skl"
    filter_glob: StringProperty(default="*.skl", options={'HIDDEN'})
    
    def execute(self, context):
        from .io import import_skl
        return import_skl.load(self, context, self.filepath)


# Import operator for ANM files
class ImportANM(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.anm"
    bl_label = "Import ANM"
    bl_options = {'PRESET', 'UNDO'}
    
    filename_ext = ".anm"
    filter_glob: StringProperty(default="*.anm", options={'HIDDEN'})
    
    # Multi-file support
    files: bpy.props.CollectionProperty(
        type=bpy.types.OperatorFileListElement,
        options={'HIDDEN', 'SKIP_SAVE'}
    )
    directory: StringProperty(subtype='DIR_PATH', options={'HIDDEN'})
    
    import_mode: bpy.props.EnumProperty(
        name="Import Mode",
        description="How to import the animation",
        items=[
            ('NEW_ACTION', "New Action", "Create a new action for each file"),
            ('INSERT_AT_FRAME', "Insert at Current Frame", "Insert keyframes into current action at playhead position"),
        ],
        default='NEW_ACTION'
    )
    
    def execute(self, context):
        import os
        from .io import import_anm
        
        # Build list of files to import
        if self.files and len(self.files) > 0:
            # Multiple files selected
            filepaths = [os.path.join(self.directory, f.name) for f in self.files if f.name.lower().endswith('.anm')]
        else:
            # Single file
            filepaths = [self.filepath]
        
        if not filepaths:
            self.report({'ERROR'}, "No ANM files selected")
            return {'CANCELLED'}
        
        imported_count = 0
        max_frame_end = context.scene.frame_end  # Track the longest animation
        
        for filepath in filepaths:
            insert_frame = context.scene.frame_current if self.import_mode == 'INSERT_AT_FRAME' else 0
            create_new_action = self.import_mode == 'NEW_ACTION'
            result = import_anm.load(self, context, filepath, create_new_action, insert_frame)
            if result == {'FINISHED'}:
                history.add_to_history(context, filepath, 'ANM')
                imported_count += 1
                # Track the longest animation's end frame
                if context.scene.frame_end > max_frame_end:
                    max_frame_end = context.scene.frame_end
        
        # Set scene to longest animation so all frames are visible
        if imported_count > 0:
            context.scene.frame_end = max_frame_end
        
        if imported_count > 1:
            self.report({'INFO'}, f"Imported {imported_count} animation files (timeline set to longest: {max_frame_end} frames)")
        
        return {'FINISHED'} if imported_count > 0 else {'CANCELLED'}


# Import operator for SCB files
class ImportSCB(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.scb"
    bl_label = "Import SCB"
    bl_options = {'PRESET', 'UNDO'}
    
    filename_ext = ".scb"
    filter_glob: StringProperty(default="*.scb", options={'HIDDEN'})
    
    def execute(self, context):
        from .io import import_scb
        return import_scb.load(self, context, self.filepath)


# Import operator for SCO files
class ImportSCO(bpy.types.Operator, ImportHelper):
    bl_idname = "import_scene.sco"
    bl_label = "Import SCO"
    bl_options = {'PRESET', 'UNDO'}
    
    filename_ext = ".sco"
    filter_glob: StringProperty(default="*.sco", options={'HIDDEN'})
    
    def execute(self, context):
        from .io import import_sco
        return import_sco.load(self, context, self.filepath)


# Export operator for SKN
class ExportSKN(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.skn"
    bl_label = "Export SKN"
    bl_options = {'PRESET', 'UNDO'}
    
    filename_ext = ".skn"
    filter_glob: StringProperty(default="*.skn", options={'HIDDEN'})
    
    check_existing: BoolProperty(
        name="Confirm Overwrite",
        description="Prompt before overwriting existing files",
        default=True
    )
    
    export_skl: BoolProperty(
        name="Export SKL",
        description="Also export skeleton (.skl) file",
        default=True
    )
    
    clean_names: BoolProperty(
        name="Clean Names",
        description="Remove Blender's .001, .002 suffixes from bone and material names",
        default=True
    )

    disable_scaling: BoolProperty(
        name="Disable Scaling",
        description="Disable the 100x scale factor applied during export (exports raw Blender units)",
        default=False
    )

    disable_transforms: BoolProperty(
        name="Disable Transforms",
        description="Disable coordinate system conversion (Y-up to Z-up transformation)",
        default=False
    )

    target_armature_name: StringProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        # Try to get stored path from mesh or armature
        obj = context.active_object

        # Capture target armature
        if obj:
            if obj.type == 'ARMATURE':
                self.target_armature_name = obj.name
            elif obj.type == 'MESH':
                arm = obj.find_armature() or (obj.parent if obj.parent and obj.parent.type == 'ARMATURE' else None)
                if arm:
                    self.target_armature_name = arm.name

        if obj:
            path = obj.get("lol_skn_filepath")
            if path:
                self.filepath = path
            elif obj.type == 'ARMATURE':
                path = obj.get("lol_skn_filepath")
                if path:
                    self.filepath = path
        return super().invoke(context, event)

    def execute(self, context):
        from .io import export_skn
        target_armature = context.scene.objects.get(self.target_armature_name) if self.target_armature_name else None
        return export_skn.save(self, context, self.filepath, self.export_skl, self.clean_names, target_armature=target_armature, disable_scaling=self.disable_scaling, disable_transforms=self.disable_transforms)

# Export operator for SKL
class ExportSKL(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.skl"
    bl_label = "Export SKL"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".skl"
    filter_glob: StringProperty(default="*.skl", options={'HIDDEN'})

    check_existing: BoolProperty(
        name="Confirm Overwrite",
        description="Prompt before overwriting existing files",
        default=True
    )

    disable_scaling: BoolProperty(
        name="Disable Scaling",
        description="Disable the 100x scale factor applied during export (exports raw Blender units)",
        default=False
    )

    disable_transforms: BoolProperty(
        name="Disable Transforms",
        description="Disable coordinate system conversion (Y-up to Z-up transformation)",
        default=False
    )

    target_armature_name: StringProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        # Try to get stored path from armature
        obj = context.active_object

        # Capture target armature
        if obj:
            if obj.type == 'ARMATURE':
                self.target_armature_name = obj.name
            elif obj.type == 'MESH':
                arm = obj.find_armature() or (obj.parent if obj.parent and obj.parent.type == 'ARMATURE' else None)
                if arm:
                    self.target_armature_name = arm.name

        if obj:
            if obj.type == 'ARMATURE':
                path = obj.get("lol_skl_filepath")
                if path:
                    self.filepath = path
            elif obj.type == 'MESH':
                arm = obj.find_armature() or obj.parent
                if arm and arm.type == 'ARMATURE':
                    path = arm.get("lol_skl_filepath")
                    if path:
                        self.filepath = path
        return super().invoke(context, event)

    def execute(self, context):
        from .io import export_skl
        target_armature = context.scene.objects.get(self.target_armature_name) if self.target_armature_name else None
        return export_skl.save(self, context, self.filepath, target_armature=target_armature, disable_scaling=self.disable_scaling, disable_transforms=self.disable_transforms)

# Export operator for ANM
class ExportANM(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.anm"
    bl_label = "Export ANM"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".anm"
    filter_glob: StringProperty(default="*.anm", options={'HIDDEN'})

    check_existing: BoolProperty(
        name="Confirm Overwrite",
        description="Prompt before overwriting existing files",
        default=True
    )

    disable_scaling: BoolProperty(
        name="Disable Scaling",
        description="Disable the 100x scale factor applied during export (exports raw Blender units)",
        default=False
    )

    disable_transforms: BoolProperty(
        name="Disable Transforms",
        description="Disable coordinate system conversion (Y-up to Z-up transformation)",
        default=False
    )

    flip: BoolProperty(
        name="Flip",
        description="Flip coordinates for export. Leave unchecked for normal export, might fix issues with imported animations",
        default=False
    )

    target_armature_name: StringProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        # Try to get the filename from the action
        armature_obj = context.active_object

        if not armature_obj or armature_obj.type != 'ARMATURE':
             # Try to find from selection if active is invalid
             # This duplicates the check below which is fine, but ensures we capture specific intention
             pass

        if not armature_obj or armature_obj.type != 'ARMATURE':
            armature_obj = next((o for o in context.scene.objects if o.type == 'ARMATURE'), None)

        if armature_obj:
            self.target_armature_name = armature_obj.name

        if armature_obj and armature_obj.animation_data and armature_obj.animation_data.action:
            action = armature_obj.animation_data.action
            # Try stored filepath first, then use action name
            original_path = action.get("lol_anm_filepath")
            if original_path:
                self.filepath = original_path
            else:
                # Use action name as filename
                self.filepath = action.name + ".anm"

        return super().invoke(context, event)

    def execute(self, context):
        from .io import export_anm
        target_armature = context.scene.objects.get(self.target_armature_name) if self.target_armature_name else None
        return export_anm.save(self, context, self.filepath, target_armature=target_armature, disable_scaling=self.disable_scaling, disable_transforms=self.disable_transforms, flip=self.flip)


# Menu function
def menu_func_import_skn(self, context):
    self.layout.operator(ImportSKN.bl_idname, text="League of Legends SKN (.skn)")

def menu_func_import_skl(self, context):
    self.layout.operator(ImportSKL.bl_idname, text="League of Legends SKL (.skl)")

def menu_func_import_anm(self, context):
    self.layout.operator(ImportANM.bl_idname, text="League of Legends ANM (.anm)")

def menu_func_import_scb(self, context):
    self.layout.operator(ImportSCB.bl_idname, text="League of Legends SCB (.scb)")

def menu_func_import_sco(self, context):
    self.layout.operator(ImportSCO.bl_idname, text="League of Legends SCO (.sco)")

def menu_func_export_skn(self, context):
    self.layout.operator(ExportSKN.bl_idname, text="League of Legends SKN (.skn)")

def menu_func_export_skl(self, context):
    self.layout.operator(ExportSKL.bl_idname, text="League of Legends SKL (.skl)")

def menu_func_export_anm(self, context):
    self.layout.operator(ExportANM.bl_idname, text="League of Legends ANM (.anm)")

def menu_func_export_scb(self, context):
    self.layout.operator(export_scb.ExportSCB.bl_idname, text="League of Legends SCB (.scb)")

def menu_func_export_sco(self, context):
    self.layout.operator(export_sco.ExportSCO.bl_idname, text="League of Legends SCO (.sco)")

# Registration
def register():
    icons.register()
    
    bpy.utils.register_class(updater.LOL_OT_CheckForUpdates)
    bpy.utils.register_class(updater.LOL_OT_UpdateAddon)
    
    bpy.utils.register_class(ImportSKN)
    bpy.utils.register_class(ImportSKL)
    bpy.utils.register_class(ImportANM)
    bpy.utils.register_class(ImportSCB)
    bpy.utils.register_class(ImportSCO)
    bpy.utils.register_class(ExportSKN)
    bpy.utils.register_class(ExportSKL)
    bpy.utils.register_class(ExportANM)
    
    # Register ported SCB/SCO exporters
    bpy.utils.register_class(export_scb.ExportSCB)
    bpy.utils.register_class(export_sco.ExportSCO)
    
    # Register ported operators
    bpy.utils.register_class(limit_influences.LOLLeagueLimitInfluences_V4)
    bpy.utils.register_class(uv_corners.UV_CORNER_OT_top_left)
    bpy.utils.register_class(uv_corners.UV_CORNER_OT_top_right)
    bpy.utils.register_class(uv_corners.UV_CORNER_OT_bottom_left)
    bpy.utils.register_class(uv_corners.UV_CORNER_OT_bottom_right)
    
    # Register normals operators
    bpy.utils.register_class(normals.MESH_OT_show_normals)
    bpy.utils.register_class(normals.MESH_OT_recalculate_normals_outside)
    bpy.utils.register_class(normals.MESH_OT_recalculate_normals_inside)
    bpy.utils.register_class(normals.MESH_OT_flip_normals)
    
    # Register bind pose operators
    bind_pose.register()

    # Register UI Panels (main panel first so it appears at top of N panel)
    bpy.utils.register_class(panels.LOL_PT_MainPanel)
    bpy.utils.register_class(panels.UV_CORNER_PT_panel)

    # Register Skin Tools classes (but not the panel - that's controlled by preferences)
    smart_weights.register()
    
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_skn)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_skl)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_anm)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_scb)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import_sco)
    
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export_skn)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export_skl)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export_anm)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export_scb)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export_sco)
    
    # Register history
    bpy.utils.register_class(history.LOLHistoryItem)
    # bpy.utils.register_class(history.LOLAddonPreferences) # Replaced by local class
    bpy.utils.register_class(LolAddonPreferences)
    
    bpy.utils.register_class(history.LOL_OT_OpenFromHistory)
    bpy.utils.register_class(history.LOL_OT_ClearHistory)
    bpy.utils.register_class(texture_ops.LOL_OT_ReloadTextures)
    
    # Check preferences to load Extras
    # We defer this slightly or wrap in try-except because on fresh install prefs might not exist
    try:
        prefs = bpy.context.preferences.addons[__package__].preferences

        # Skin Tools panel is disabled by default (part of Misc LoL Tools)
        # Unregister the panel that was registered by smart_weights.register()
        # It will be re-registered if enable_skin_tools is True
        try:
            smart_weights.unregister_panel()
        except Exception as e:
            pass  # Panel may not be registered yet

        if prefs.enable_skin_tools:
            try:
                smart_weights.register_panel()
            except Exception as e:
                print(f"Failed to auto-load skin tools: {e}")

        if prefs.enable_physics:
            try:
                from .extras import physics
                physics.register()
            except Exception as e:
                print(f"Failed to auto-load physics: {e}")
        
        if prefs.enable_retarget:
            try:
                from .extras import retarget
                retarget.register()
            except Exception as e:
                print(f"Failed to auto-load retarget: {e}")

        if prefs.enable_anim_loader:
            try:
                from .extras import anim_loader
                anim_loader.register()
            except Exception as e:
                print(f"Failed to auto-load anim loader: {e}")
    except:
        pass


def unregister():
    # Unregister Extras if loaded
    try:
        from .extras import physics
        physics.unregister()
    except: pass

    try:
        from .extras import retarget
        retarget.unregister()
    except: pass

    try:
        from .extras import anim_loader
        anim_loader.unregister()
    except: pass

    bpy.utils.unregister_class(ImportSKN)
    bpy.utils.unregister_class(ImportSKL)
    bpy.utils.unregister_class(ImportANM)
    bpy.utils.unregister_class(ImportSCB)
    bpy.utils.unregister_class(ImportSCO)
    bpy.utils.unregister_class(ExportSKN)
    bpy.utils.unregister_class(ExportSKL)
    bpy.utils.unregister_class(ExportANM)
    
    # Unregister ported SCB/SCO exporters
    bpy.utils.unregister_class(export_scb.ExportSCB)
    bpy.utils.unregister_class(export_sco.ExportSCO)
    
    # Unregister ported operators
    bpy.utils.unregister_class(limit_influences.LOLLeagueLimitInfluences_V4)
    bpy.utils.unregister_class(uv_corners.UV_CORNER_OT_top_left)
    bpy.utils.unregister_class(uv_corners.UV_CORNER_OT_top_right)
    bpy.utils.unregister_class(uv_corners.UV_CORNER_OT_bottom_left)
    bpy.utils.unregister_class(uv_corners.UV_CORNER_OT_bottom_right)
    
    # Unregister normals operators
    bpy.utils.unregister_class(normals.MESH_OT_show_normals)
    bpy.utils.unregister_class(normals.MESH_OT_recalculate_normals_outside)
    bpy.utils.unregister_class(normals.MESH_OT_recalculate_normals_inside)
    bpy.utils.unregister_class(normals.MESH_OT_flip_normals)
    
    # Unregister bind pose operators
    bind_pose.unregister()
    
    smart_weights.unregister()
    
    # Unregister UI Panels
    bpy.utils.unregister_class(panels.LOL_PT_MainPanel)
    bpy.utils.unregister_class(panels.UV_CORNER_PT_panel)
    
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_skn)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_skl)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_anm)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_scb)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import_sco)
    
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_skn)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_skl)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_anm)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_scb)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export_sco)
    
    # Unregister history
    bpy.utils.unregister_class(history.LOLHistoryItem)
    # bpy.utils.unregister_class(history.LOLAddonPreferences) # Removed
    bpy.utils.unregister_class(LolAddonPreferences)
    
    bpy.utils.unregister_class(history.LOL_OT_OpenFromHistory)
    bpy.utils.unregister_class(history.LOL_OT_ClearHistory)
    
    bpy.utils.unregister_class(texture_ops.LOL_OT_ReloadTextures)

    bpy.utils.unregister_class(updater.LOL_OT_CheckForUpdates)
    bpy.utils.unregister_class(updater.LOL_OT_UpdateAddon)

    icons.unregister()





if __name__ == "__main__":
    register()
