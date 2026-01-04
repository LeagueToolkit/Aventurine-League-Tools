"""
SCB Export Operator for V4
Native SCB (Static Object Binary) exporter for League of Legends
"""

import bpy
import os
import struct
import math
from bpy.types import Operator
from bpy.props import StringProperty, FloatProperty, BoolProperty
from bpy_extras.io_utils import ExportHelper
from mathutils import Vector


class ExportSCB(Operator, ExportHelper):
    """Export League of Legends SCB (Static Object Binary)"""
    bl_idname = "export_scene.scb"
    bl_label = "Export SCB"
    bl_description = "Export selected mesh as SCB static object"
    bl_options = {'REGISTER', 'UNDO'}
    
    filename_ext = ".scb"
    filter_glob: StringProperty(default="*.scb", options={'HIDDEN'})
    
    scale_factor: FloatProperty(
        name="Scale Factor",
        description="Scale factor for export (0.01 = 1% of original size)",
        default=0.01,
        min=0.0001,
        max=100.0
    )
    
    use_riot_reference: BoolProperty(
        name="Use Riot Reference",
        description="Preserve central point and flags from riot.scb if available",
        default=True
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
            path = obj.get('lol_scb_filepath')
            if path:
                self.filepath = path
            elif 'lol_scb_original_name' in obj:
                # Fallback to old property
                original_name = obj['lol_scb_original_name']
                if bpy.data.filepath:
                    default_dir = os.path.dirname(bpy.data.filepath)
                else:
                    default_dir = os.path.expanduser("~")
                self.filepath = os.path.join(default_dir, f"{original_name}.scb")
        
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
            # Check for riot.scb reference
            riot_data = None
            if self.use_riot_reference:
                riot_data = self.load_riot_reference(self.filepath)
            
            # Export SCB
            self.export_scb(context, obj, self.filepath, self.scale_factor, riot_data)
            
            self.report({'INFO'}, f"Successfully exported {os.path.basename(self.filepath)}")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export SCB: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'CANCELLED'}
    
    def load_riot_reference(self, filepath):
        """Load riot.scb reference file if it exists"""
        dirname = os.path.dirname(filepath)
        basename = os.path.basename(filepath)
        
        # Try riot_{filename}.scb first
        path1 = os.path.join(dirname, f"riot_{basename}")
        if os.path.exists(path1):
            return self.read_riot_scb(path1)
        
        # Try riot.scb
        path2 = os.path.join(dirname, "riot.scb")
        if os.path.exists(path2):
            return self.read_riot_scb(path2)
        
        return None
    
    def read_riot_scb(self, path):
        """Read only central point and flag from riot.scb"""
        try:
            with open(path, 'rb') as f:
                # Skip to central point
                f.seek(8)  # Magic
                major, minor = struct.unpack('<HH', f.read(4))
                f.seek(128)  # Name padding
                vertex_count, face_count, scb_flag = struct.unpack('<III', f.read(12))
                f.seek(24)  # Bounding box
                
                if major == 3 and minor == 2:
                    vertex_type = struct.unpack('<I', f.read(4))[0]
                    f.seek(vertex_count * 12, 1)  # Vertices
                    if vertex_type == 1:
                        f.seek(vertex_count * 4, 1)  # Vertex colors
                else:
                    f.seek(vertex_count * 12, 1)  # Vertices
                
                # Read central point (don't swap here, will swap during export)
                cx, cy, cz = struct.unpack('<fff', f.read(12))
                central = Vector((cx, cy, cz))
                
                return {
                    'central': central,  # Will be swapped during export
                    'scb_flag': scb_flag
                }
        except Exception as e:
            print(f"[export_scb] WARNING: Could not read riot.scb: {e}")
            return None
    
    def export_scb(self, context, obj, filepath, scale_factor, riot_data):
        """Export mesh to SCB format"""
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
        if riot_data:
            # If we have riot data, we could use it, but let's use object origin for consistency
            origin_world = eval_obj.matrix_world.translation
            central_world = origin_world
        else:
            # Object origin in world space = pivot point location
            origin_world = eval_obj.matrix_world.translation
            central_world = origin_world
        
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
        
        # Central point in SCB format (absolute position)
        central = central_scb
        
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
            if len(material_name) > 64:
                material_name = material_name[:64]
        
        # Get SCB flag
        scb_flag = 2  # Default: local origin locator
        if riot_data:
            scb_flag = riot_data['scb_flag']
        elif 'lol_scb_flag' in obj:
            scb_flag = obj['lol_scb_flag']
        
        # Write SCB file
        with open(filepath, 'wb') as f:
            # Write magic
            f.write(b'r3d2Mesh')
            
            # Write version (3.2)
            f.write(struct.pack('<HH', 3, 2))
            
            # Write name padding (128 bytes)
            f.write(b'\x00' * 128)
            
            # Write counts and flag
            face_count = len(faces)
            f.write(struct.pack('<III', len(vertices), face_count, scb_flag))
            
            # Calculate bounding box
            if vertices:
                min_bb = Vector((min(v.x for v in vertices), 
                                min(v.y for v in vertices), 
                                min(v.z for v in vertices)))
                max_bb = Vector((max(v.x for v in vertices), 
                                max(v.y for v in vertices), 
                                max(v.z for v in vertices)))
            else:
                min_bb = Vector((0, 0, 0))
                max_bb = Vector((0, 0, 0))
            
            # Write bounding box
            f.write(struct.pack('<6f', min_bb.x, min_bb.y, min_bb.z, 
                               max_bb.x, max_bb.y, max_bb.z))
            
            # Write vertex type (0 = no vertex colors)
            f.write(struct.pack('<I', 0))
            
            # Write vertices (Y and Z are already swapped)
            for v in vertices:
                f.write(struct.pack('<fff', v.x, v.y, v.z))
            
            # Write central point (Y and Z are already swapped)
            f.write(struct.pack('<fff', central.x, central.y, central.z))
            
            # Write faces
            for i, face in enumerate(faces):
                # Write face indices
                f.write(struct.pack('<III', face[0], face[1], face[2]))
                
                # Write material name (64 bytes, padded)
                mat_bytes = material_name.encode('ascii', errors='ignore')
                mat_padded = mat_bytes[:64].ljust(64, b'\x00')
                f.write(mat_padded)
                
                # Write UVs (per-face format: u1, u2, u3, v1, v2, v3)
                face_uv = face_uvs[i]
                f.write(struct.pack('<6f', 
                    face_uv[0].x, face_uv[1].x, face_uv[2].x,  # u1, u2, u3
                    face_uv[0].y, face_uv[1].y, face_uv[2].y   # v1, v2, v3
                ))
