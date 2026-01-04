import bpy
import os
import struct
import mathutils

def read_scb(filepath):
    """Read SCB file and return data structure"""
    with open(filepath, 'rb') as f:
        # Read magic
        magic = f.read(8).decode('ascii', errors='ignore')
        if magic != 'r3d2Mesh':
            raise ValueError(f"Invalid SCB file signature: {magic}")
        
        # Read version
        major, minor = struct.unpack('<HH', f.read(4))
        # Support 3.2, 2.1, 2.2
        # Simple check: Major 3 or Major 2
        if major not in (2, 3):
             raise ValueError(f"Unsupported SCB version: {major}.{minor}")
        
        # Skip name padding (128 bytes)
        f.seek(128, 1)
        
        # Read counts and flag
        vertex_count, face_count, scb_flag = struct.unpack('<III', f.read(12))
        
        # Read bounding box (6 floats = 24 bytes)
        bbox = struct.unpack('<6f', f.read(24))
        
        # Read vertex type (only for version 3.2)
        vertex_type = 0
        if major == 3 and minor == 2:
            vertex_type = struct.unpack('<I', f.read(4))[0]
        
        # Read vertices (swap Y and Z, rotate around Z by 180 degrees)
        vertices = []
        for i in range(vertex_count):
            x, y, z = struct.unpack('<fff', f.read(12))
            # Match current project SKN coords: (-x, -z, y)
            vertices.append(mathutils.Vector((-x, -z, y)))
        
        # Skip vertex colors if present
        if vertex_type == 1:
            f.seek(4 * vertex_count, 1)
        
        # Read central point
        cx, cy, cz = struct.unpack('<fff', f.read(12))
        central = mathutils.Vector((-cx, -cz, cy))
        
        # Read faces
        indices = []
        uvs = []
        material = None
        
        for i in range(face_count):
            # Read face indices
            idx0, idx1, idx2 = struct.unpack('<III', f.read(12))
            
            # Skip degenerate faces
            if idx0 == idx1 or idx1 == idx2 or idx2 == idx0:
                # Still need to read material and UVs
                f.seek(64, 1)  # Material name
                f.seek(24, 1)  # UVs (6 floats)
                continue
            
            indices.extend([idx0, idx1, idx2])
            
            # Read material name (64 bytes, padded)
            material_bytes = f.read(64)
            if i == 0: # Only grab first material for now, often SCB has 1 material
                material = material_bytes.split(b'\x00')[0].decode('ascii', errors='ignore')
            
            # Read UVs (6 floats: u1, u2, u3, v1, v2, v3)
            uv_data = struct.unpack('<6f', f.read(24))
            # Convert to per-vertex UVs (per-face format)
            uvs.append(mathutils.Vector((uv_data[0], uv_data[3])))  # u1, v1
            uvs.append(mathutils.Vector((uv_data[1], uv_data[4])))  # u2, v2
            uvs.append(mathutils.Vector((uv_data[2], uv_data[5])))  # u3, v3
    
    return {
        'name': os.path.splitext(os.path.basename(filepath))[0],
        'vertices': vertices,
        'indices': indices,
        'uvs': uvs,
        'material': material or 'lambert69',
        'central': central,
        'scb_flag': scb_flag
    }

def create_mesh(scb_data):
    """Create Blender mesh from SCB data"""
    mesh = bpy.data.meshes.new(scb_data['name'])
    
    # Vertices are already transformed to Blender space
    # Just need to build the list of tuples
    vertices = [(v.x, v.y, v.z) for v in scb_data['vertices']]
    
    # Faces
    face_count = len(scb_data['indices']) // 3
    faces = []
    face_uvs = []
    
    for i in range(face_count):
        idx = i * 3
        faces.append([
            scb_data['indices'][idx],
            scb_data['indices'][idx + 1],
            scb_data['indices'][idx + 2]
        ])
        
        face_uvs.append([
            scb_data['uvs'][idx],
            scb_data['uvs'][idx + 1],
            scb_data['uvs'][idx + 2]
        ])
    
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    
    # UVs
    uv_layer = mesh.uv_layers.new(name="UVMap")
    for face_idx, face in enumerate(mesh.polygons):
        face_uv = face_uvs[face_idx]
        for loop_idx, loop in enumerate(face.loop_indices):
            uv = face_uv[loop_idx]
            uv_layer.data[loop].uv = (uv.x, 1.0 - uv.y) # Flip V
            
    # Material
    mat = bpy.data.materials.new(name=scb_data['material'])
    mat.use_nodes = True
    mesh.materials.append(mat)
    
    return mesh

def load(operator, context, filepath):
    try:
        scb_data = read_scb(filepath)
        mesh = create_mesh(scb_data)
        
        obj = bpy.data.objects.new(scb_data['name'], mesh)
        context.collection.objects.link(obj)
        
        # Store import path for export convenience
        obj["lol_scb_filepath"] = filepath
        obj["lol_scb_filename"] = os.path.basename(filepath)
        
        # Set active
        context.view_layer.objects.active = obj
        obj.select_set(True)
        
        operator.report({'INFO'}, f"Imported SCB: {scb_data['name']}")
        return {'FINISHED'}
    except Exception as e:
        operator.report({'ERROR'}, f"Failed to load SCB: {str(e)}")
        return {'CANCELLED'}
