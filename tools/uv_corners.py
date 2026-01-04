"""
UV Corner Placement Operators
Moves selected UVs to the four corners of UV space, matching Maya's functionality.
"""

import bpy
import bmesh
from bpy.types import Operator
from mathutils import Vector


class UV_CORNER_OT_top_left(Operator):
    """Move selected UVs to top left corner and scale to half size"""
    bl_idname = "uv.corner_top_left"
    bl_label = "UV Top Left"
    bl_description = "Moves selected UVs to top left corner and makes them half the size"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return move_uvs_to_corner(context, corner='top_left')

    def invoke(self, context, event):
        return self.execute(context)


class UV_CORNER_OT_top_right(Operator):
    """Move selected UVs to top right corner and scale to half size"""
    bl_idname = "uv.corner_top_right"
    bl_label = "UV Top Right"
    bl_description = "Moves selected UVs to top right corner and makes them half the size"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return move_uvs_to_corner(context, corner='top_right')

    def invoke(self, context, event):
        return self.execute(context)


class UV_CORNER_OT_bottom_left(Operator):
    """Move selected UVs to bottom left corner and scale to half size"""
    bl_idname = "uv.corner_bottom_left"
    bl_label = "UV Bottom Left"
    bl_description = "Moves selected UVs to bottom left corner and makes them half the size"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return move_uvs_to_corner(context, corner='bottom_left')

    def invoke(self, context, event):
        return self.execute(context)


class UV_CORNER_OT_bottom_right(Operator):
    """Move selected UVs to bottom right corner and scale to half size"""
    bl_idname = "uv.corner_bottom_right"
    bl_label = "UV Bottom Right"
    bl_description = "Moves selected UVs to bottom right corner and makes them half the size"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        return move_uvs_to_corner(context, corner='bottom_right')

    def invoke(self, context, event):
        return self.execute(context)


def move_uvs_to_corner(context, corner='top_left'):
    """
    Move selected UVs to a corner and scale them to half size.
    
    This matches the Maya functionality:
    1. Pivot to center (0.5, 0.5) and scale to 0.5x
    2. Translate to the appropriate corner
    
    Corner positions:
    - top_left: (-0.25, 0.25) -> final position (0.25, 0.75)
    - top_right: (0.25, 0.25) -> final position (0.75, 0.75)
    - bottom_left: (-0.25, -0.25) -> final position (0.25, 0.25)
    - bottom_right: (0.25, -0.25) -> final position (0.75, 0.25)
    """
    
    # Get the active mesh object
    obj = context.active_object
    if not obj or obj.type != 'MESH':
        return {'CANCELLED'}
    
    # Check if object has UVs
    if not obj.data.uv_layers.active:
        return {'CANCELLED'}
    
    # Ensure we're in edit mode
    if obj.mode != 'EDIT':
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
    
    # Get bmesh from edit mesh
    bm = bmesh.from_edit_mesh(obj.data)
    
    # Ensure lookup tables
    bm.faces.ensure_lookup_table()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    
    # Get UV layer from bmesh
    uv_loops = bm.loops.layers.uv.active
    if not uv_loops:
        return {'CANCELLED'}
    
    # Collect selected UV loops
    # In Blender, UV selection is stored in the loop's UV data
    selected_loops = []
    
    # Iterate through all faces and collect selected UVs
    for face in bm.faces:
        if face.hide:
            continue
            
        for loop in face.loops:
            uv_data = loop[uv_loops]
            
            # Check UV selection - in Blender 4.x, this is stored in uv_data.select
            # The select attribute should exist on the UV data
            try:
                # Direct access to select attribute
                if uv_data.select:
                    selected_loops.append(loop)
            except AttributeError:
                # If select attribute doesn't exist, try alternative methods
                # This shouldn't happen in Blender 4.x, but handle it gracefully
                try:
                    # Try accessing via getattr
                    if getattr(uv_data, 'select', False):
                        selected_loops.append(loop)
                except:
                    # If all else fails, skip this loop
                    pass
    
    # Only operate on selected UVs - if nothing is selected, cancel
    if not selected_loops:
        return {'CANCELLED'}
    
    # Step 1: Scale around center (0.5, 0.5) to 0.5x
    # Formula: new_uv = (uv - pivot) * scale + pivot
    pivot = Vector((0.5, 0.5))
    scale = 0.5
    
    for loop in selected_loops:
        uv_data = loop[uv_loops]
        uv = uv_data.uv.copy()
        # Scale around pivot
        uv_scaled = (uv - pivot) * scale + pivot
        uv_data.uv = uv_scaled
    
    # Step 2: Translate to corner
    # Corner offsets (these are the offsets from center after scaling)
    corner_offsets = {
        'top_left': Vector((-0.25, 0.25)),
        'top_right': Vector((0.25, 0.25)),
        'bottom_left': Vector((-0.25, -0.25)),
        'bottom_right': Vector((0.25, -0.25))
    }
    
    offset = corner_offsets.get(corner, Vector((0, 0)))
    
    for loop in selected_loops:
        uv_data = loop[uv_loops]
        uv_data.uv = uv_data.uv + offset
    
    # Update mesh (bmesh.from_edit_mesh doesn't need free, just update)
    bmesh.update_edit_mesh(obj.data)
    
    # Print confirmation
    corner_names = {
        'top_left': 'Top Left',
        'top_right': 'Top Right',
        'bottom_left': 'Bottom Left',
        'bottom_right': 'Bottom Right'
    }
    print(f"Moved UV -> {corner_names.get(corner, corner)}")
    
    return {'FINISHED'}
