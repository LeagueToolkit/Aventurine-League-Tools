"""
LoL Animation Loader
Quick-load animations from the animations folder relative to imported SKN/SKL
"""

import bpy
import os
from bpy.types import Panel, Operator, PropertyGroup, UIList
from bpy.props import StringProperty, CollectionProperty, IntProperty, PointerProperty
from ..ui import icons
from ..io import import_anm
from ..io import export_anm


class AnimationListItem(PropertyGroup):
    """Single animation file entry"""
    name: StringProperty(name="Animation Name")
    filepath: StringProperty(name="File Path")


def update_search_filter(self, context):
    """Force UI redraw when search filter changes"""
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            area.tag_redraw()


class LOLAnimLoaderProperties(PropertyGroup):
    """Properties for the animation loader panel"""
    animations: CollectionProperty(type=AnimationListItem)
    active_index: IntProperty(default=0)
    animations_folder: StringProperty(name="Animations Folder", default="")
    custom_folder: StringProperty(
        name="Custom Folder",
        description="Manually selected animations folder (overrides auto-detection)",
        default="",
        subtype='DIR_PATH'
    )
    current_loaded: StringProperty(name="Currently Loaded", default="")
    search_filter: StringProperty(
        name="Search",
        description="Filter animations by name",
        default="",
        update=update_search_filter,
        options={'TEXTEDIT_UPDATE'}  # Update on every keystroke
    )
    # Status text shown at top of panel
    status_text: StringProperty(default="Ready")


def get_animations_folder(armature_obj):
    """Get the animations folder path based on the armature's SKL filepath"""
    if not armature_obj:
        return None

    # Try to get the SKL filepath from the armature
    skl_path = armature_obj.get("lol_skl_filepath")
    if not skl_path:
        # Try to get SKN path and derive SKL path
        skn_path = armature_obj.get("lol_skn_filepath")
        if skn_path:
            skl_path = skn_path

    if not skl_path:
        return None

    # The folder structure is: parent_folder/skn_skl_files and parent_folder/animations/
    parent_folder = os.path.dirname(skl_path)
    animations_folder = os.path.join(parent_folder, "animations")

    if os.path.isdir(animations_folder):
        return animations_folder

    return None


def find_armature_with_path(context):
    """Find an armature that has a stored SKL/SKN path - searches all objects, not just active"""
    # First try active object
    if context.active_object and context.active_object.type == 'ARMATURE':
        arm = context.active_object
        if arm.get("lol_skl_filepath") or arm.get("lol_skn_filepath"):
            return arm

    # Search all armatures in scene for one with path
    for obj in context.scene.objects:
        if obj.type == 'ARMATURE':
            if obj.get("lol_skl_filepath") or obj.get("lol_skn_filepath"):
                return obj

    # Last resort: return any armature
    for obj in context.scene.objects:
        if obj.type == 'ARMATURE':
            return obj

    return None


class LOL_OT_BrowseAnimationsFolder(Operator):
    """Browse for a custom animations folder"""
    bl_idname = "lol_anim_loader.browse_folder"
    bl_label = "Browse Animations Folder"
    bl_description = "Choose a folder containing .anm animation files"
    bl_options = {'REGISTER'}

    directory: StringProperty(
        name="Directory",
        description="Directory to search for animations",
        subtype='DIR_PATH'
    )

    def execute(self, context):
        props = context.scene.lol_anim_loader

        if self.directory:
            # Store the custom folder path (remove trailing slash if present)
            props.custom_folder = self.directory.rstrip('/\\')
            # Auto-refresh after selecting folder
            bpy.ops.lol_anim_loader.refresh()

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class LOL_OT_ClearCustomFolder(Operator):
    """Clear the custom folder and revert to auto-detection"""
    bl_idname = "lol_anim_loader.clear_custom_folder"
    bl_label = "Clear Custom Folder"
    bl_description = "Clear the custom folder and use auto-detection based on imported SKN/SKL"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.lol_anim_loader
        props.custom_folder = ""
        # Refresh to use auto-detection
        bpy.ops.lol_anim_loader.refresh()
        return {'FINISHED'}


class LOL_OT_RefreshAnimations(Operator):
    """Scan the animations folder and refresh the list"""
    bl_idname = "lol_anim_loader.refresh"
    bl_label = "Refresh Animations"
    bl_description = "Scan the animations folder for .anm files"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.lol_anim_loader
        props.animations.clear()
        props.animations_folder = ""
        props.search_filter = ""

        # Check if custom folder is set and valid
        if props.custom_folder and os.path.isdir(props.custom_folder):
            anim_folder = props.custom_folder
        else:
            # Fall back to auto-detection
            armature_obj = find_armature_with_path(context)
            if not armature_obj:
                self.report({'WARNING'}, "No armature found in scene. Use the folder button to select a folder manually.")
                return {'CANCELLED'}

            anim_folder = get_animations_folder(armature_obj)
            if not anim_folder:
                self.report({'WARNING'}, "No 'animations' folder found. Use the folder button to select a folder manually.")
                return {'CANCELLED'}

        props.animations_folder = anim_folder

        # Scan for .anm files
        anm_files = []
        for filename in os.listdir(anim_folder):
            if filename.lower().endswith('.anm'):
                anm_files.append(filename)

        # Sort alphabetically
        anm_files.sort()

        # Add to collection
        for filename in anm_files:
            item = props.animations.add()
            item.name = os.path.splitext(filename)[0]  # Name without extension
            item.filepath = os.path.join(anim_folder, filename)

        if len(anm_files) > 0:
            self.report({'INFO'}, f"Found {len(anm_files)} animations")
        else:
            self.report({'WARNING'}, f"No .anm files found in: {anim_folder}")

        return {'FINISHED'}


class LOL_OT_LoadAnimation(Operator):
    """Load the selected animation"""
    bl_idname = "lol_anim_loader.load"
    bl_label = "Load Animation"
    bl_description = "Load the selected animation onto the armature"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty()
    anim_name: StringProperty()
    index: IntProperty(default=-1)

    def execute(self, context):
        props = context.scene.lol_anim_loader

        if not self.filepath:
            self.report({'ERROR'}, "No animation file specified")
            return {'CANCELLED'}

        if not os.path.exists(self.filepath):
            self.report({'ERROR'}, f"Animation file not found: {self.filepath}")
            return {'CANCELLED'}

        # Auto-detect armature - no need for user to select it
        armature_obj = find_armature_with_path(context)

        if not armature_obj:
            self.report({'ERROR'}, "No armature found in scene. Import an SKN+SKL first.")
            return {'CANCELLED'}

        # Make sure we're in object mode first (safely)
        try:
            if context.active_object and context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass  # Already in object mode or no active object

        # Select and activate the armature
        bpy.ops.object.select_all(action='DESELECT')
        armature_obj.select_set(True)
        context.view_layer.objects.active = armature_obj

        # Load the animation
        try:
            action_name = self.anim_name if self.anim_name else os.path.splitext(os.path.basename(self.filepath))[0]

            # Set status and force redraw before import
            props.status_text = f"Importing animation 1/1..."
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)

            anm = import_anm.read_anm(self.filepath)

            # Create animation data if needed
            if not armature_obj.animation_data:
                armature_obj.animation_data_create()

            # Create new action with the animation name
            new_action = bpy.data.actions.new(name=action_name)
            armature_obj.animation_data.action = new_action

            # Apply the animation
            import_anm.apply_anm(anm, armature_obj, frame_offset=0)

            # Store info on the action
            new_action["lol_anm_filepath"] = self.filepath
            new_action["lol_anm_filename"] = os.path.basename(self.filepath)

            # Update current loaded indicator
            props.current_loaded = action_name

            # Update active_index to match the clicked item
            if self.index >= 0:
                props.active_index = self.index

            # Update status
            props.status_text = "Ready"

            self.report({'INFO'}, f"Loaded animation: {action_name}")
            return {'FINISHED'}

        except Exception as e:
            # Update status on error
            props.status_text = "Import failed"

            self.report({'ERROR'}, f"Failed to load animation: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}


class LOL_OT_ClearAnimation(Operator):
    """Clear the current animation from the skeleton"""
    bl_idname = "lol_anim_loader.clear"
    bl_label = "Clear Animation"
    bl_description = "Remove the current animation and reset to bind pose"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.lol_anim_loader

        # Auto-detect armature
        armature_obj = find_armature_with_path(context)

        if not armature_obj:
            self.report({'ERROR'}, "No armature found in scene. Import an SKN+SKL first.")
            return {'CANCELLED'}

        # Clear the animation
        if armature_obj.animation_data:
            armature_obj.animation_data.action = None

        # Make sure we're in object mode first (safely)
        try:
            if context.active_object and context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass  # Already in object mode or no active object

        # Select and activate the armature
        bpy.ops.object.select_all(action='DESELECT')
        armature_obj.select_set(True)
        context.view_layer.objects.active = armature_obj

        # Reset all pose bones to rest pose
        bpy.ops.object.mode_set(mode='POSE')

        for pbone in armature_obj.pose.bones:
            pbone.location = (0, 0, 0)
            pbone.rotation_quaternion = (1, 0, 0, 0)
            pbone.rotation_euler = (0, 0, 0)
            pbone.scale = (1, 1, 1)

        bpy.ops.object.mode_set(mode='OBJECT')

        props.current_loaded = ""

        self.report({'INFO'}, "Animation cleared")
        return {'FINISHED'}


class LOL_OT_ImportAllToNLA(Operator):
    """Import all animations from folder to NLA tracks"""
    bl_idname = "lol_anim_loader.import_all_nla"
    bl_label = "Import All to NLA"
    bl_description = "Import all animations from the folder as NLA tracks (may freeze Blender briefly)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.lol_anim_loader

        # Check if we have animations loaded
        if len(props.animations) == 0:
            self.report({'ERROR'}, "No animations found. Click Refresh first.")
            return {'CANCELLED'}

        # Auto-detect armature
        armature_obj = find_armature_with_path(context)

        if not armature_obj:
            self.report({'ERROR'}, "No armature found in scene. Import an SKN+SKL first.")
            return {'CANCELLED'}

        # Make sure we're in object mode first (safely)
        try:
            if context.active_object and context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass

        # Select and activate the armature
        bpy.ops.object.select_all(action='DESELECT')
        armature_obj.select_set(True)
        context.view_layer.objects.active = armature_obj

        # Create animation data if needed
        if not armature_obj.animation_data:
            armature_obj.animation_data_create()

        total_anims = len(props.animations)
        imported_count = 0
        failed_count = 0

        for idx, anim_item in enumerate(props.animations):
            # Update status and force redraw
            props.status_text = f"Importing animation {idx + 1}/{total_anims}..."
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)

            try:
                # Read the animation
                anm = import_anm.read_anm(anim_item.filepath)

                # Create new action
                action_name = anim_item.name
                new_action = bpy.data.actions.new(name=action_name)
                armature_obj.animation_data.action = new_action

                # Apply the animation keyframes
                import_anm.apply_anm(anm, armature_obj, frame_offset=0)

                # Store info on the action
                new_action["lol_anm_filepath"] = anim_item.filepath
                new_action["lol_anm_filename"] = os.path.basename(anim_item.filepath)

                # Keep action from being deleted
                new_action.use_fake_user = True

                # Create NLA track and push action to it
                track = armature_obj.animation_data.nla_tracks.new()
                track.name = action_name

                # Create strip from action
                strip = track.strips.new(action_name, start=0, action=new_action)
                strip.name = action_name

                # Mute the track (user unmutes the one they want to preview)
                track.mute = True

                imported_count += 1

            except Exception as e:
                print(f"Failed to import {anim_item.name}: {str(e)}")
                import traceback
                traceback.print_exc()
                failed_count += 1

        # Clear the active action (animations are now in NLA)
        armature_obj.animation_data.action = None

        # Reset pose
        bpy.ops.object.mode_set(mode='POSE')
        for pbone in armature_obj.pose.bones:
            pbone.location = (0, 0, 0)
            pbone.rotation_quaternion = (1, 0, 0, 0)
            pbone.rotation_euler = (0, 0, 0)
            pbone.scale = (1, 1, 1)
        bpy.ops.object.mode_set(mode='OBJECT')

        # Update status
        props.status_text = "Ready"
        props.current_loaded = ""

        if failed_count > 0:
            self.report({'WARNING'}, f"Imported {imported_count}/{total_anims} animations to NLA ({failed_count} failed)")
        else:
            self.report({'INFO'}, f"Imported {imported_count} animations to NLA tracks")

        return {'FINISHED'}


class LOL_OT_ExportAllFromNLA(Operator):
    """Export all NLA tracks as separate ANM files"""
    bl_idname = "lol_anim_loader.export_all_nla"
    bl_label = "Export All from NLA"
    bl_description = "Export all NLA tracks as separate ANM files (may freeze Blender briefly)"
    bl_options = {'REGISTER'}

    directory: StringProperty(
        name="Output Directory",
        description="Directory to save exported ANM files",
        subtype='DIR_PATH'
    )

    def execute(self, context):
        props = context.scene.lol_anim_loader

        if not self.directory:
            self.report({'ERROR'}, "No output directory specified")
            return {'CANCELLED'}

        # Auto-detect armature
        armature_obj = find_armature_with_path(context)

        if not armature_obj:
            self.report({'ERROR'}, "No armature found in scene. Import an SKN+SKL first.")
            return {'CANCELLED'}

        if not armature_obj.animation_data:
            self.report({'ERROR'}, "No animation data on armature")
            return {'CANCELLED'}

        nla_tracks = armature_obj.animation_data.nla_tracks
        if len(nla_tracks) == 0:
            self.report({'ERROR'}, "No NLA tracks found. Import animations to NLA first.")
            return {'CANCELLED'}

        # Make sure we're in object mode
        try:
            if context.active_object and context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass

        # Select and activate the armature
        bpy.ops.object.select_all(action='DESELECT')
        armature_obj.select_set(True)
        context.view_layer.objects.active = armature_obj

        total_tracks = len(nla_tracks)
        exported_count = 0
        failed_count = 0

        # Store original action
        original_action = armature_obj.animation_data.action

        fps = context.scene.render.fps

        for idx, track in enumerate(nla_tracks):
            # Update status and force redraw
            props.status_text = f"Exporting animation {idx + 1}/{total_tracks}..."
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)

            # Get the action from the first strip in the track
            if len(track.strips) == 0:
                continue

            strip = track.strips[0]
            action = strip.action

            if not action:
                continue

            try:
                # Temporarily assign the action to the armature
                armature_obj.animation_data.action = action

                # Build output filepath
                anim_name = track.name
                filepath = os.path.join(self.directory, f"{anim_name}.anm")

                # Export
                export_anm.write_anm(filepath, armature_obj, fps)

                exported_count += 1

            except Exception as e:
                print(f"Failed to export {track.name}: {str(e)}")
                import traceback
                traceback.print_exc()
                failed_count += 1

        # Restore original action
        armature_obj.animation_data.action = original_action

        # Update status
        props.status_text = "Ready"

        if failed_count > 0:
            self.report({'WARNING'}, f"Exported {exported_count}/{total_tracks} animations ({failed_count} failed)")
        else:
            self.report({'INFO'}, f"Exported {exported_count} animations to {self.directory}")

        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class LOL_UL_AnimationList(UIList):
    """UI List for displaying animations with filtering"""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        props = context.scene.lol_anim_loader

        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)

            # Icon: play icon if currently loaded, otherwise action icon
            if item.name == props.current_loaded:
                row.label(text="", icon='PLAY')
            else:
                row.label(text="", icon='ACTION')

            # Animation name as clickable button - loads on click
            op = row.operator("lol_anim_loader.load", text=item.name, emboss=False)
            op.filepath = item.filepath
            op.anim_name = item.name
            op.index = index

        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.name, icon='ACTION')

    def filter_items(self, context, data, propname):
        """Filter animations based on search string"""
        props = context.scene.lol_anim_loader
        items = getattr(data, propname)
        filter_name = props.search_filter.lower()

        # Default: show all
        flt_flags = [self.bitflag_filter_item] * len(items)
        flt_neworder = []

        # Apply name filter
        if filter_name:
            for i, item in enumerate(items):
                if filter_name not in item.name.lower():
                    flt_flags[i] = 0  # Hide this item

        return flt_flags, flt_neworder


class LOL_PT_AnimLoaderPanel(Panel):
    """Animation Loader Panel"""
    bl_label = "Load Animations"
    bl_idname = "VIEW3D_PT_lol_anim_loader"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Animation Tools'
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        layout = self.layout
        layout.label(text="", icon_value=icons.get_icon("plugin_icon"))

    def draw(self, context):
        layout = self.layout
        props = context.scene.lol_anim_loader

        # Status box (always visible)
        box = layout.box()
        box.label(text=props.status_text, icon='INFO')

        # Top row: Refresh and Browse buttons
        row = layout.row(align=True)
        row.operator("lol_anim_loader.refresh", text="Refresh", icon='FILE_REFRESH')
        row.operator("lol_anim_loader.browse_folder", text="", icon='FILEBROWSER')

        # Folder path display (compact)
        row = layout.row(align=True)
        row.scale_y = 0.7
        if props.animations_folder:
            folder_name = os.path.basename(props.animations_folder)
            parent_name = os.path.basename(os.path.dirname(props.animations_folder))
            if props.custom_folder:
                row.label(text=f".../{parent_name}/{folder_name}", icon='FILE_FOLDER')
                row.operator("lol_anim_loader.clear_custom_folder", text="", icon='X')
            else:
                row.label(text=f".../{parent_name}/{folder_name}", icon='FILE_FOLDER')
        else:
            row.label(text="No folder selected", icon='FILE_FOLDER')

        # Clear animation button (always visible at top)
        row = layout.row(align=True)
        row.scale_y = 1.2
        row.operator("lol_anim_loader.clear", text="Clear Animation", icon='X')

        # Currently loaded indicator
        if props.current_loaded:
            box = layout.box()
            box.label(text=f"Playing: {props.current_loaded}", icon='PLAY')

        layout.separator()

        # Animation list
        if len(props.animations) > 0:
            # Count visible animations
            filter_text = props.search_filter.lower()
            if filter_text:
                visible_count = sum(1 for item in props.animations if filter_text in item.name.lower())
                label_text = f"Animations ({visible_count}/{len(props.animations)})"
            else:
                label_text = f"Animations ({len(props.animations)})"

            # List header
            row = layout.row()
            row.label(text=label_text, icon='ANIM')

            # Scrollable list
            row = layout.row()
            row.template_list(
                "LOL_UL_AnimationList", "",
                props, "animations",
                props, "active_index",
                rows=12
            )

            # Search filter below the list
            row = layout.row(align=True)
            row.prop(props, "search_filter", text="", icon='VIEWZOOM')

            # NLA import/export buttons
            layout.separator()
            row = layout.row(align=True)
            row.scale_y = 1.2
            row.operator("lol_anim_loader.import_all_nla", text="Import All to NLA", icon='NLA')
            row = layout.row(align=True)
            row.scale_y = 1.2
            row.operator("lol_anim_loader.export_all_nla", text="Export All from NLA", icon='EXPORT')
        else:
            # No animations message
            box = layout.box()
            col = box.column(align=True)
            col.label(text="No animations found", icon='INFO')
            col.label(text="Import an SKN+SKL first,")
            col.label(text="then click Refresh.")


# Registration
classes = [
    AnimationListItem,
    LOLAnimLoaderProperties,
    LOL_OT_BrowseAnimationsFolder,
    LOL_OT_ClearCustomFolder,
    LOL_OT_RefreshAnimations,
    LOL_OT_LoadAnimation,
    LOL_OT_ClearAnimation,
    LOL_OT_ImportAllToNLA,
    LOL_OT_ExportAllFromNLA,
    LOL_UL_AnimationList,
    LOL_PT_AnimLoaderPanel,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lol_anim_loader = PointerProperty(type=LOLAnimLoaderProperties)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.lol_anim_loader
