bl_info = {
    "name": "Aventurine: League Tools",
    "author": "Bud and Frog",
    "version": (2, 6, 1),
    "blender": (4, 0, 0),
    "location": "File > Import-Export",
    "description": "Plugin for working with League of Legends 3D assets natively",
    "category": "Import-Export",
}

import bpy
import os
from bpy.props import StringProperty, BoolProperty, IntProperty, CollectionProperty
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
from .io import file_handlers
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
        default=True,
        update=update_animation_tools
    )
    
    enable_physics: BoolProperty(
        name="League Physics",
        description="Enable the physics simulation panel (based on Wiggle 2)",
        default=True,
        update=update_physics
    )
    
    enable_retarget: BoolProperty(
        name="Animation Retargeting",
        description="Enable the animation retargeting panel",
        default=True,
        update=update_retarget
    )

    enable_anim_loader: BoolProperty(
        name="Load Animations",
        description="Enable the animation loader panel for quick-loading animations from the animations folder",
        default=True,
        update=update_anim_loader
    )

    enable_skin_tools: BoolProperty(
        name="Skin Tools",
        description="Enable the skin tools panel for automatic weight painting",
        default=True,
        update=update_skin_tools
    )

    direct_drag_drop: BoolProperty(
        name="Direct Import (Drag & Drop)",
        description="Import files immediately with default settings when dragging into Blender (skips file browser). Only affects drag-and-drop, not File > Import menu",
        default=False
    )

    # History Properties (Moved from history.py)
    skn_history: CollectionProperty(type=history.LOLHistoryItem)
    anm_history: CollectionProperty(type=history.LOLHistoryItem)
    show_skn_history: BoolProperty(default=False, options={'SKIP_SAVE'})
    show_anm_history: BoolProperty(default=False, options={'SKIP_SAVE'})
    
    # Updater Properties (all SKIP_SAVE so they reset on restart)
    update_checked: BoolProperty(default=False, options={'SKIP_SAVE'})
    update_available: BoolProperty(default=False, options={'SKIP_SAVE'})
    update_is_newer: BoolProperty(default=False, options={'SKIP_SAVE'})
    latest_version_str: StringProperty(default="", options={'SKIP_SAVE'})
    download_url: StringProperty(default="", options={'SKIP_SAVE'})
    update_in_progress: BoolProperty(default=False, options={'SKIP_SAVE'})
    update_status: StringProperty(default="", options={'SKIP_SAVE'})

    # Patch notes properties
    show_patch_notes: BoolProperty(default=False, options={'SKIP_SAVE'})
    patch_notes_lines: CollectionProperty(type=updater.LOL_PatchNoteLine)
    patch_notes_active_line: IntProperty(default=0, options={'SKIP_SAVE'})
    patch_releases_json: StringProperty(default="", options={'SKIP_SAVE'})
    patch_notes_version: StringProperty(default="", options={'SKIP_SAVE'})
    patch_notes_index: IntProperty(default=0, options={'SKIP_SAVE'})

    def draw(self, context):
        layout = self.layout
        
        # Updater Section
        box = layout.box()
        box.label(text="Updates", icon='WORLD')

        if self.update_in_progress:
            # Show progress, disable buttons
            row = box.row()
            row.enabled = False
            row.label(text=self.update_status, icon='SORTTIME')
        elif not self.update_checked:
            # Haven't checked yet this session
            row = box.row()
            row.operator("lol.check_updates", text="Check for Updates")
        elif self.update_is_newer:
            # Genuine new version
            row = box.row()
            row.label(text=f"New version: {self.latest_version_str}", icon='INFO')
            sub = row.row(align=True)
            sub.operator("lol.update_addon", text="Install Update", icon='IMPORT')
            sub.operator("lol.check_updates", text="", icon='FILE_REFRESH')
            box.label(text="Restart Blender after updating to apply changes.", icon='ERROR')
        elif self.update_available:
            # Same or older - re-download option
            row = box.row()
            row.label(text=f"Up to date ({self.latest_version_str})")
            sub = row.row(align=True)
            sub.operator("lol.update_addon", text="Re-download", icon='IMPORT')
            sub.operator("lol.check_updates", text="", icon='FILE_REFRESH')
        else:
            row = box.row()
            row.operator("lol.check_updates", text="Check for Updates")

        # Always show status if there is one
        if self.update_status and not self.update_in_progress:
            box.label(text=self.update_status)

        # Patch notes toggle - always visible
        row = box.row(align=True)
        icon = 'TRIA_DOWN' if self.show_patch_notes else 'DOWNARROW_HLT'
        row.operator("lol.toggle_patch_notes", text="Patch Notes", icon=icon)
        row.operator("lol.refresh_patch_notes", text="", icon='FILE_REFRESH')

        if self.show_patch_notes:
            if self.patch_releases_json:
                notes_box = box.box()

                # Header: version label + navigation arrows
                header = notes_box.row()
                header.label(text=self.patch_notes_version if self.patch_notes_version else "---")

                nav = header.row(align=True)
                nav.alignment = 'RIGHT'
                older = nav.operator("lol.cycle_patch_notes", text="", icon='TRIA_LEFT')
                older.direction = 1
                newer = nav.operator("lol.cycle_patch_notes", text="", icon='TRIA_RIGHT')
                newer.direction = -1

                # Scrollable patch notes list (4 visible rows)
                notes_box.template_list(
                    "LOL_UL_PatchNotes", "",
                    self, "patch_notes_lines",
                    self, "patch_notes_active_line",
                    rows=4,
                    maxrows=4,
                )
            else:
                box.label(text="Click the refresh button to load patch notes.")

        box = layout.box()
        box.label(text="Optional Features:")

        # Misc LoL Tools
        box.prop(self, "enable_animation_tools", text="Misc LoL Tools")

        # Sub-options (always visible, grayed out when parent disabled)
        sub = box.box()
        sub.enabled = self.enable_animation_tools
        sub.prop(self, "enable_skin_tools")
        sub.prop(self, "enable_physics")
        sub.prop(self, "enable_retarget")
        sub.prop(self, "enable_anim_loader")

        # Drag & Drop Setting
        box.prop(self, "direct_drag_drop")

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

    def draw(self, context):
        """Draw the import settings UI"""
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        layout.prop(self, "load_skl")
        layout.prop(self, "split_by_material")
        layout.prop(self, "auto_load_textures")

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

    flip: BoolProperty(
        name="Flip",
        description="Flip coordinates for import. Enable when importing animations onto a non-League skeleton",
        default=False
    )

    def draw(self, context):
        """Draw the import settings UI"""
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False

        layout.prop(self, "import_mode")
        layout.prop(self, "flip")

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
            result = import_anm.load(self, context, filepath, create_new_action, insert_frame, flip=self.flip)
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


# Drag-and-drop only operators (never used from File > Import menu)
class ImportSKN_DragDrop(bpy.types.Operator):
    """Import SKN file from drag-and-drop"""
    bl_idname = "import_scene.skn_dragdrop"
    bl_label = "Import SKN"
    bl_options = {'INTERNAL'}

    filepath: StringProperty(subtype='FILE_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        # If direct import enabled, import with default settings
        if prefs.direct_drag_drop:
            from .io import import_skn
            result = import_skn.load(self, context, self.filepath,
                                   load_skl_file=True,
                                   split_by_material=True,
                                   auto_load_textures=True)
            if result == {'FINISHED'}:
                history.add_to_history(context, self.filepath, 'SKN')
            return result

        # Otherwise, delegate to regular import operator (shows file browser)
        bpy.ops.import_scene.skn('INVOKE_DEFAULT', filepath=self.filepath)
        return {'FINISHED'}


class ImportANM_DragDrop(bpy.types.Operator):
    """Import ANM file from drag-and-drop"""
    bl_idname = "import_scene.anm_dragdrop"
    bl_label = "Import ANM"
    bl_options = {'INTERNAL'}

    filepath: StringProperty(subtype='FILE_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        # If direct import enabled, import with default settings
        if prefs.direct_drag_drop:
            from .io import import_anm
            return import_anm.load(self, context, self.filepath,
                                 create_new_action=True,
                                 insert_frame=0,
                                 flip=False)

        # Otherwise, delegate to regular import operator (shows file browser)
        bpy.ops.import_scene.anm('INVOKE_DEFAULT', filepath=self.filepath)
        return {'FINISHED'}


class ImportSKL_DragDrop(bpy.types.Operator):
    """Import SKL file from drag-and-drop"""
    bl_idname = "import_scene.skl_dragdrop"
    bl_label = "Import SKL"
    bl_options = {'INTERNAL'}

    filepath: StringProperty(subtype='FILE_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        if prefs.direct_drag_drop:
            from .io import import_skl
            return import_skl.load(self, context, self.filepath)

        bpy.ops.import_scene.skl('INVOKE_DEFAULT', filepath=self.filepath)
        return {'FINISHED'}


class ImportSCB_DragDrop(bpy.types.Operator):
    """Import SCB file from drag-and-drop"""
    bl_idname = "import_scene.scb_dragdrop"
    bl_label = "Import SCB"
    bl_options = {'INTERNAL'}

    filepath: StringProperty(subtype='FILE_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        if prefs.direct_drag_drop:
            from .io import import_scb
            return import_scb.load(self, context, self.filepath)

        bpy.ops.import_scene.scb('INVOKE_DEFAULT', filepath=self.filepath)
        return {'FINISHED'}


class ImportSCO_DragDrop(bpy.types.Operator):
    """Import SCO file from drag-and-drop"""
    bl_idname = "import_scene.sco_dragdrop"
    bl_label = "Import SCO"
    bl_options = {'INTERNAL'}

    filepath: StringProperty(subtype='FILE_PATH', options={'HIDDEN', 'SKIP_SAVE'})

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences

        if prefs.direct_drag_drop:
            from .io import import_sco
            return import_sco.load(self, context, self.filepath)

        bpy.ops.import_scene.sco('INVOKE_DEFAULT', filepath=self.filepath)
        return {'FINISHED'}


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

    use_visual_pose: BoolProperty(
        name="Use Visual Rest Pose (Experimental)",
        description="Export bones using their current visual rest pose instead of the original imported transforms. Enable this if you moved bones in Edit Mode and want the changes to be exported",
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
        return export_skn.save(self, context, self.filepath, self.export_skl, self.clean_names, target_armature=target_armature, disable_scaling=self.disable_scaling, disable_transforms=self.disable_transforms, use_visual_pose=self.use_visual_pose)

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

    use_visual_pose: BoolProperty(
        name="Use Visual Rest Pose (Experimental)",
        description="Export bones using their current visual rest pose instead of the original imported transforms. Enable this if you moved bones in Edit Mode and want the changes to be exported",
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
        return export_skl.save(self, context, self.filepath, target_armature=target_armature, disable_scaling=self.disable_scaling, disable_transforms=self.disable_transforms, use_visual_pose=self.use_visual_pose)

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

    batch_export_all_actions: BoolProperty(
        name="Batch Export All Actions",
        description="Export every animation action as a separate ANM file in the selected folder",
        default=False
    )

    target_armature_name: StringProperty(options={'HIDDEN'})

    @staticmethod
    def _sanitize_action_filename(name):
        invalid = '<>:"/\\|?*'
        cleaned = ''.join('_' if c in invalid else c for c in name)
        cleaned = cleaned.strip().rstrip(" .")
        return cleaned or "Action"

    @staticmethod
    def _iter_action_fcurves(action):
        # Blender <=4.x stores fcurves directly on Action.
        direct_fcurves = getattr(action, "fcurves", None)
        if direct_fcurves is not None:
            for fc in direct_fcurves:
                yield fc
            return

        # Blender 5.x may store curves in layered/slotted actions.
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                for channelbag in getattr(strip, "channelbags", []):
                    for fc in getattr(channelbag, "fcurves", []):
                        yield fc

    @classmethod
    def _action_has_pose_bone_curves(cls, action):
        for fc in cls._iter_action_fcurves(action):
            data_path = getattr(fc, "data_path", "")
            if data_path.startswith('pose.bones["'):
                return True
        return False

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = False
        layout.use_property_decorate = False
        layout.prop(self, "disable_scaling")
        layout.prop(self, "disable_transforms")
        layout.prop(self, "batch_export_all_actions")
        layout.prop(self, "flip")

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
        if not self.batch_export_all_actions:
            return export_anm.save(self, context, self.filepath, target_armature=target_armature, disable_scaling=self.disable_scaling, disable_transforms=self.disable_transforms, flip=self.flip)

        if not target_armature:
            target_armature = context.active_object if context.active_object and context.active_object.type == 'ARMATURE' else None
        if not target_armature:
            target_armature = next((o for o in context.scene.objects if o.type == 'ARMATURE'), None)
        if not target_armature:
            self.report({'ERROR'}, "No Armature found")
            return {'CANCELLED'}

        export_dir = os.path.dirname(bpy.path.abspath(self.filepath))
        if not export_dir:
            self.report({'ERROR'}, "Choose an output folder for batch export")
            return {'CANCELLED'}
        os.makedirs(export_dir, exist_ok=True)

        actions = [action for action in bpy.data.actions if self._action_has_pose_bone_curves(action)]
        actions.sort(key=lambda a: a.name.lower())

        if not actions:
            self.report({'ERROR'}, "No animation actions found to export")
            return {'CANCELLED'}

        if not target_armature.animation_data:
            target_armature.animation_data_create()
        original_action = target_armature.animation_data.action

        fps = context.scene.render.fps
        exported_count = 0
        failed = []

        try:
            for action in actions:
                filename = f"{self._sanitize_action_filename(action.name)}.anm"
                filepath = os.path.join(export_dir, filename)
                if self.check_existing and os.path.exists(filepath):
                    failed.append(f"{action.name} (file exists)")
                    continue

                try:
                    target_armature.animation_data.action = action
                    export_anm.write_anm(
                        filepath,
                        target_armature,
                        fps,
                        disable_scaling=self.disable_scaling,
                        disable_transforms=self.disable_transforms,
                        flip=self.flip,
                    )
                    exported_count += 1
                except Exception as e:
                    failed.append(f"{action.name} ({str(e)})")
        finally:
            target_armature.animation_data.action = original_action

        if failed:
            self.report({'WARNING'}, f"Batch export finished: {exported_count}/{len(actions)} exported. Failed: {len(failed)}")
        else:
            self.report({'INFO'}, f"Batch export finished: {exported_count} animations exported")

        return {'FINISHED'} if exported_count > 0 else {'CANCELLED'}


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
    
    bpy.utils.register_class(updater.LOL_PatchNoteLine)
    bpy.utils.register_class(updater.LOL_UL_PatchNotes)
    bpy.utils.register_class(updater.LOL_OT_CheckForUpdates)
    bpy.utils.register_class(updater.LOL_OT_UpdateAddon)
    bpy.utils.register_class(updater.LOL_OT_CyclePatchNotes)
    bpy.utils.register_class(updater.LOL_OT_TogglePatchNotes)
    bpy.utils.register_class(updater.LOL_OT_RefreshPatchNotes)

    # Clean up leftover backup folders from previous updates
    updater.cleanup_old_backups()

    bpy.utils.register_class(ImportSKN)
    bpy.utils.register_class(ImportSKL)
    bpy.utils.register_class(ImportANM)
    bpy.utils.register_class(ImportSCB)
    bpy.utils.register_class(ImportSCO)

    # Register drag-drop only operators
    bpy.utils.register_class(ImportSKN_DragDrop)
    bpy.utils.register_class(ImportANM_DragDrop)
    bpy.utils.register_class(ImportSKL_DragDrop)
    bpy.utils.register_class(ImportSCB_DragDrop)
    bpy.utils.register_class(ImportSCO_DragDrop)

    bpy.utils.register_class(ExportSKN)
    bpy.utils.register_class(ExportSKL)
    bpy.utils.register_class(ExportANM)

    # Register file handlers for drag-and-drop
    file_handlers.register()
    
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

    # Unregister file handlers for drag-and-drop
    file_handlers.unregister()

    bpy.utils.unregister_class(ImportSKN)
    bpy.utils.unregister_class(ImportSKL)
    bpy.utils.unregister_class(ImportANM)
    bpy.utils.unregister_class(ImportSCB)
    bpy.utils.unregister_class(ImportSCO)

    # Unregister drag-drop only operators
    bpy.utils.unregister_class(ImportSKN_DragDrop)
    bpy.utils.unregister_class(ImportANM_DragDrop)
    bpy.utils.unregister_class(ImportSKL_DragDrop)
    bpy.utils.unregister_class(ImportSCB_DragDrop)
    bpy.utils.unregister_class(ImportSCO_DragDrop)

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

    bpy.utils.unregister_class(updater.LOL_OT_RefreshPatchNotes)
    bpy.utils.unregister_class(updater.LOL_OT_TogglePatchNotes)
    bpy.utils.unregister_class(updater.LOL_OT_CyclePatchNotes)
    bpy.utils.unregister_class(updater.LOL_OT_CheckForUpdates)
    bpy.utils.unregister_class(updater.LOL_OT_UpdateAddon)
    bpy.utils.unregister_class(updater.LOL_UL_PatchNotes)
    bpy.utils.unregister_class(updater.LOL_PatchNoteLine)

    icons.unregister()





if __name__ == "__main__":
    register()
