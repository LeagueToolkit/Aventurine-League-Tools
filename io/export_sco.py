"""
SCO Export Operator for V4
Native SCO (Static Object) exporter for League of Legends
"""

import bpy
import os
import struct
import math
from bpy.types import Operator
from bpy.props import StringProperty, FloatProperty, BoolProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Vector


class ExportSCO(Operator, ExportHelper):
    """Export League of Legends SCO (Static Object)"""
    bl_idname = "export_scene.sco"
    bl_label = "Export SCO"
    bl_description = "Export selected mesh as SCO static object with pivot point"
    bl_options = {'REGISTER', 'UNDO'}
    
    filename_ext = ".sco"
    filter_glob: StringProperty(default="*.sco", options={'HIDDEN'})
    
    scale_factor: FloatProperty(
        name="Scale Factor",
        description="Scale factor for export (0.01 = 1% of original size)",
        default=0.01,
        min=0.0001,
        max=100.0
    )
    
    check_existing: BoolProperty(
        name="Confirm Overwrite",
        description="Prompt before overwriting existing files",
        default=True
    )
    
    def invoke(self, context, event):
        # Set default filename from imported file if available
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            # Try to find mesh from selection
            for sel_obj in context.selected_objects:
                if sel_obj.type == 'MESH':
                    obj = sel_obj
                    break
        
        if obj:
            # Try stored filepath from import
            path = obj.get('lol_sco_filepath')
            if path:
                self.filepath = path
            elif 'lol_sco_original_name' in obj:
                # Fallback to old property
                original_name = obj['lol_sco_original_name']
                if bpy.data.filepath:
                    default_dir = os.path.dirname(bpy.data.filepath)
                else:
                    default_dir = os.path.expanduser("~")
                self.filepath = os.path.join(default_dir, f"{original_name}.sco")
        
        return super().invoke(context, event)
    
    def execute(self, context):
        # Get selected mesh
        obj = context.active_object
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object to export")
            return {'CANCELLED'}
        
        # Check for multiple meshes
        selected_meshes = [o for o in context.selected_objects if o.type == 'MESH']
        if len(selected_meshes) > 1:
            self.report({'ERROR'}, "Select only one mesh object")
            return {'CANCELLED'}
        
        try:
            # Export SCO
            self.export_sco(context, obj, self.filepath, self.scale_factor)
            
            self.report({'INFO'}, f"Successfully exported {os.path.basename(self.filepath)}")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export SCO: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def find_pivot_bone(self, context, obj, depsgraph, eval_mesh):
        """
        Find the pivot bone for SCO export.
        Returns the bone's world position if exactly one bone is bound, None otherwise.
        Based on Maya exporter: finds bone through skin cluster with exactly one influence.
        
        Args:
            context: Blender context
            obj: Mesh object
            depsgraph: Evaluated depsgraph (to avoid creating multiple times)
            eval_mesh: Evaluated mesh data
        """
        # Check for armature modifier
        armature_obj = None
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object:
                armature_obj = mod.object
                break
        
        if not armature_obj or armature_obj.type != 'ARMATURE':
            return None
        
        # Get vertex groups (bone influences)
        vertex_groups = obj.vertex_groups
        if not vertex_groups:
            return None
        
        # Count how many vertex groups have weights in the evaluated mesh
        active_groups = []
        for vg in vertex_groups:
            # Check if this vertex group has any weights
            has_weights = False
            for v in eval_mesh.vertices:
                for g in v.groups:
                    if g.group == vg.index and g.weight > 0.0:
                        has_weights = True
                        break
                if has_weights:
                    break
            
            if has_weights:
                active_groups.append(vg)
        
        # Must have exactly one bone influence (like Maya exporter)
        if len(active_groups) != 1:
            return None
        
        # Get the bone from armature
        bone_name = active_groups[0].name
        if bone_name not in armature_obj.data.bones:
            return None
        
        bone = armature_obj.data.bones[bone_name]
        
        # Get evaluated armature to get current bone position
        eval_armature_obj = armature_obj.evaluated_get(depsgraph)
        
        # Get bone's world position (head position in world space)
        # Maya uses: joint_translation = ik_joint.getTranslation(MSpace.kTransform)
        # This gets the bone's transform translation (head position) in world space
        if eval_armature_obj.pose and bone_name in eval_armature_obj.pose.bones:
            pose_bone = eval_armature_obj.pose.bones[bone_name]
            # Get bone head in world space using pose bone matrix
            bone_world_mat = eval_armature_obj.matrix_world @ pose_bone.matrix
            bone_world_pos = bone_world_mat.translation
        else:
            # Use rest pose - bone head in world space
            bone_world_mat = eval_armature_obj.matrix_world @ bone.matrix_local
            bone_world_pos = bone_world_mat.translation
        
        return bone_world_pos
    
    def export_sco(self, context, obj, filepath, scale_factor):
        """Export mesh to SCO format"""
        mesh = obj.data
        
        # Ensure mesh is evaluated (applies modifiers)
        depsgraph = context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.data
        
        # Get mesh data - vertices in Blender world space
        # Maya exporter gets vertices in world space and central as transform translation
        vertices_world = []
        for v in eval_mesh.vertices:
            world_pos = eval_obj.matrix_world @ v.co
            vertices_world.append(world_pos)
        
        # Calculate central point: object origin in world space (pivot point)
        # This matches Maya: transform.getTranslation(MSpace.kTransform)
        origin_world = eval_obj.matrix_world.translation
        central_world = origin_world
        
        # Find pivot bone (if exists) - pass depsgraph and eval_mesh to avoid recreating
        pivot_bone_world = self.find_pivot_bone(context, obj, depsgraph, eval_mesh)
        
        # Scale to SCB units (before coordinate transform)
        scale_inv = 1.0 / scale_factor
        vertices_scaled = [v * scale_inv for v in vertices_world]
        central_scaled = central_world * scale_inv
        
        # Transform central point to SCB coordinate system
        # Import expects: c_blender = (-cx, -cz, cy) where (cx, cy, cz) is in file
        # So if central_scaled = (x, y, z) in Blender space:
        #   We want: (-cx, -cz, cy) = (x, y, z) after import transform
        #   So: -cx = x => cx = -x
        #       -cz = y => cz = -y  
        #       cy = z => cy = z
        #   Therefore file has: (cx, cy, cz) = (-x, z, -y)
        central_scb = Vector((-central_scaled.x, central_scaled.z, -central_scaled.y))
        
        # Transform vertices to SCB coordinate system as ABSOLUTE positions
        # Do NOT subtract central - store absolute positions like Maya does
        vertices = []
        for v in vertices_scaled:
            # Transform vertex to SCB coordinate system (absolute position)
            v_scb = Vector((-v.x, v.z, -v.y))
            vertices.append(v_scb)
        
        # Calculate pivot point if bone exists
        # Maya stores: so.pivot = so.central - joint_translation
        # So pivot is relative to central (offset vector)
        pivot_scb = None
        if pivot_bone_world is not None:
            pivot_scaled = pivot_bone_world * scale_inv
            pivot_scb_transformed = Vector((-pivot_scaled.x, pivot_scaled.z, -pivot_scaled.y))
            # Pivot is stored as: central - bone_position (offset from central)
            pivot_scb = central_scb - pivot_scb_transformed
        
        # Get UV layer
        if not eval_mesh.uv_layers.active:
            raise ValueError("Mesh has no UV coordinates")
        
        uv_layer = eval_mesh.uv_layers.active
        
        # Triangulate if needed using bmesh (preserves UVs)
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(eval_mesh)
        
        # Ensure UV layer exists in bmesh
        uv_layer_bm = bm.loops.layers.uv.active
        if not uv_layer_bm:
            # Create UV layer if it doesn't exist
            uv_layer_bm = bm.loops.layers.uv.new("UVMap")
        
        # Triangulate
        bmesh.ops.triangulate(bm, faces=bm.faces)
        
        # Get faces and UVs from bmesh
        faces = []
        face_uvs = []
        
        # Update vertex indices to match our vertex list
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        
        # Collect face data
        for face in bm.faces:
            if len(face.verts) != 3:
                continue  # Skip non-triangles
            
            # Get vertex indices
            face_indices = [v.index for v in face.verts]
            faces.append(face_indices)
            
            # Get UVs for this face (per-face format)
            face_uv = []
            for loop in face.loops:
                uv = loop[uv_layer_bm].uv
                # Flip V coordinate
                face_uv.append(Vector((uv.x, 1.0 - uv.y)))
            
            face_uvs.append(face_uv)
        
        bm.free()
        
        # Get material name
        material_name = 'lambert69'
        if eval_mesh.materials and eval_mesh.materials[0]:
            material_name = eval_mesh.materials[0].name
        
        # Write SCO file (text format)
        with open(filepath, 'w') as f:
            # Write magic
            f.write('[ObjectBegin]\n')
            
            # Write name
            obj_name = obj.name
            if len(obj_name) > 64:
                obj_name = obj_name[:64]
            f.write(f'Name= {obj_name}\n')
            
            # Write central point
            f.write(f'CentralPoint= {central_scb.x:.4f} {central_scb.y:.4f} {central_scb.z:.4f}\n')
            
            # Write pivot point if exists
            if pivot_scb is not None:
                f.write(f'PivotPoint= {pivot_scb.x:.4f} {pivot_scb.y:.4f} {pivot_scb.z:.4f}\n')
            
            # Write vertices
            f.write(f'Verts= {len(vertices)}\n')
            for v in vertices:
                f.write(f'{v.x:.4f} {v.y:.4f} {v.z:.4f}\n')
            
            # Write faces
            face_count = len(faces)
            f.write(f'Faces= {face_count}\n')
            for i, face in enumerate(faces):
                # Write face: 3 <idx0> <idx1> <idx2> <material> <u1> <v1> <u2> <v2> <u3> <v3>
                face_uv = face_uvs[i]
                f.write('3\t')
                f.write(f' {face[0]:>5}')
                f.write(f' {face[1]:>5}')
                f.write(f' {face[2]:>5}')
                f.write(f'\t{material_name:>20}\t')
                f.write(f'{face_uv[0].x:.12f} {face_uv[0].y:.12f} ')
                f.write(f'{face_uv[1].x:.12f} {face_uv[1].y:.12f} ')
                f.write(f'{face_uv[2].x:.12f} {face_uv[2].y:.12f}\n')
            
            # Write end marker
            f.write('[ObjectEnd]')
