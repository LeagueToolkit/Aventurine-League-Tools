import bpy
import os
import glob
from ..LtMAO import pyRitoFile, Ritoddstex

def find_bin_and_read(skn_path):
    # Try to find a bin file nearby
    start_folder = os.path.dirname(skn_path)
    norm_path = os.path.normpath(skn_path)
    path_sep = os.sep
    
    # Handle mixed separators
    if '/' in norm_path and '\\' in norm_path:
        norm_path = norm_path.replace('/', '\\')
    
    parts = norm_path.split(path_sep)
    
    # Find "assets" and "characters" in the path
    assets_idx = None
    chars_idx = None
    for i, part in enumerate(parts):
        if part.lower() == 'assets':
            assets_idx = i
        if part.lower() == 'characters':
            chars_idx = i
    
    if assets_idx is not None and chars_idx is not None and chars_idx > assets_idx:
        # Base path is everything before "assets"
        base_path = path_sep.join(parts[:assets_idx])
        
        # Extract character name and skin folder
        # Path pattern: .../characters/{charname}/skins/{skinX}/file.skn
        if chars_idx + 3 < len(parts):
            char_name = parts[chars_idx + 1]
            skins_folder = parts[chars_idx + 2]
            skin_folder = parts[chars_idx + 3]
            
            if skins_folder.lower() == 'skins':
                # Map "base" to "skin0"
                if skin_folder.lower() == 'base':
                    skin_folder = 'skin0'
                
                # Try exact match first
                bin_path = os.path.join(base_path, 'data', 'characters', char_name, 'skins', f'{skin_folder}.bin')
                if os.path.exists(bin_path):
                    return bin_path
                
                # Try skin0.bin as fallback (often contains shared data)
                bin_path_skin0 = os.path.join(base_path, 'data', 'characters', char_name, 'skins', 'skin0.bin')
                if os.path.exists(bin_path_skin0):
                    return bin_path_skin0
                
                # Try any skin*.bin in the skins folder
                skins_data_folder = os.path.join(base_path, 'data', 'characters', char_name, 'skins')
                if os.path.exists(skins_data_folder):
                    bins = glob.glob(os.path.join(skins_data_folder, 'skin*.bin'))
                    if bins:
                        bins.sort()  # Get lowest numbered skin
                        return bins[0]
    
    # Fallback: Search nearby folders
    search_folders = [start_folder]
    
    for folder_path in search_folders:
        folder = folder_path
        for _ in range(5): 
            if not os.path.exists(folder):
                parent = os.path.dirname(folder)
                if parent == folder: break
                folder = parent
                continue

            bins = glob.glob(os.path.join(folder, "skin*.bin")) \
                 + glob.glob(os.path.join(folder, "skins", "skin*.bin"))
            
            bins.sort(key=lambda x: 0 if 'skin0' in os.path.basename(x).lower() else 1)
            
            if bins:
                return bins[0]
            
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
            
    return None

def parse_bin_for_textures(bin_path):
    # return dict: { 'BASE': default_texture, 'SubmeshName': override_texture }
    results = {}
    
    try:
        bin_file = pyRitoFile.bin.BIN()
        bin_file.read(bin_path)
    except Exception as e:
        print(f"LtMAO: Failed to read BIN {bin_path}: {e}")
        return results
    
    # Map entries by hash for linking
    entries_map = { e.hash: e for e in bin_file.entries }
    
    # Traverse all entries to find field 0x45ff5904 (skinMeshProperties)
    for entry in bin_file.entries:
        for field in entry.data:
            if field.hash == '45ff5904': # skinMeshProperties
                # EMBED: field.data is list of fields
                data_fields = field.data if isinstance(field.data, list) else getattr(field.data, 'data', [])
                
                # Check fields
                for sub in data_fields:
                    if sub.hash == '3c6468f4': # texture (default)
                        results['BASE'] = sub.data # string path
                    
                    if sub.hash == '24725910': # materialOverride (list[embed])
                        if isinstance(sub.data, list):
                             for override in sub.data: 
                                 # Each override is an EMBED (list of fields)
                                 override_fields = override if isinstance(override, list) else getattr(override, 'data', [])
                                 
                                 mat_name = None
                                 tex_path = None
                                 linked_mat_hash = None
                                 
                                 for prop in override_fields:
                                     if prop.hash == 'aad7612c': # name
                                         mat_name = prop.data
                                     if prop.hash == '3c6468f4': # texture
                                         tex_path = prop.data
                                     if prop.hash == 'd2e4d060': # material (link)
                                         linked_mat_hash = prop.data
                                
                                 # If no direct texture, try to follow material link
                                 if not tex_path and linked_mat_hash and linked_mat_hash in entries_map:
                                     mat_entry = entries_map[linked_mat_hash]
                                     # Look for properties list 0x0a6f0eb5
                                     for mat_field in mat_entry.data:
                                         if mat_field.hash == '0a6f0eb5': # Properties list
                                             if isinstance(mat_field.data, list):
                                                 for prop_embed in mat_field.data:
                                                     # prop_embed is list of fields
                                                     p_fields = prop_embed if isinstance(prop_embed, list) else getattr(prop_embed, 'data', [])
                                                     
                                                     p_name = None
                                                     p_val = None
                                                     
                                                     for p_f in p_fields:
                                                         if p_f.hash == 'b311d4ef': # prop name
                                                             p_name = p_f.data
                                                         if p_f.hash == 'f0a363e3': # prop value
                                                             p_val = p_f.data
                                                     
                                                     if p_name == "Diffuse_Texture":
                                                         tex_path = p_val
                                                         break
                                         if tex_path: break

                                 if mat_name and tex_path:
                                     results[mat_name] = tex_path
    
    return results

def resolve_texture_path(skn_path, tex_asset_path):
    if not tex_asset_path: return None
    
    filename = os.path.basename(tex_asset_path)
    skn_dir = os.path.dirname(skn_path)
    
    # 1. Check same dir as SKN
    p = os.path.join(skn_dir, filename)
    if os.path.exists(p): return p
    
    # 2. Check recursive in skn_dir (useful if textures are in /Textures subfolder)
    # Limit depth to avoid infinite scan
    for root, dirs, files in os.walk(skn_dir):
        if filename in files:
            return os.path.join(root, filename)
        # Don't go too deep
        if root.count(os.sep) - skn_dir.count(os.sep) > 2:
            del dirs[:]
            
    # 3. Check up levels (parent folders)
    curr = skn_dir
    for _ in range(3):
        curr = os.path.dirname(curr)
        p = os.path.join(curr, filename)
        if os.path.exists(p): return p
        
    return None

def import_textures(skn_object, skn_path):
    print(f"LtMAO: Attempting to load textures for {skn_path}")
    bin_path = find_bin_and_read(skn_path)
    tex_map = {}
    if bin_path:
        print(f"LtMAO: Found skin bin: {bin_path}")
        tex_map = parse_bin_for_textures(bin_path)
        print(f"LtMAO: Parsed textures: {tex_map}")
    else:
        print("LtMAO: Could not find skin bin file. Trying naive texture search.")
    
    # Map Blender materials to textures
    if not skn_object.data.materials:
        print("LtMAO: Object has no materials.")
        return

    # Check for texconv.exe once
    # texture_manager.py is in utils/, so addon root is one level up
    utils_dir = os.path.dirname(os.path.realpath(__file__))
    addon_dir = os.path.dirname(utils_dir)  # Go up to addon root
    
    texconv_path = os.path.join(addon_dir, 'texconv.exe')
    if not os.path.exists(texconv_path):
        # Try in utils dir as fallback
        possible = os.path.join(utils_dir, 'texconv.exe')
        if os.path.exists(possible): 
            texconv_path = possible
        else:
            # Try LtMAO subfolder
            possible = os.path.join(addon_dir, 'LtMAO', 'res', 'tools', 'texconv.exe')
            if os.path.exists(possible): texconv_path = possible
    
    has_texconv = os.path.exists(texconv_path)

    # Cache for already loaded textures to avoid re-reading the same file
    loaded_textures = {}  # local_path -> bpy_image

    for mat in skn_object.data.materials:
        clean_name = mat.name.split('.')[0]
        tex_path_asset = tex_map.get(mat.name)
        if not tex_path_asset:
             tex_path_asset = tex_map.get(clean_name)
        
        if not tex_path_asset:
            tex_path_asset = tex_map.get('BASE')
        
        local_path = None
        if tex_path_asset:
            local_path = resolve_texture_path(skn_path, tex_path_asset)
        
        # Fallback
        if not local_path and not tex_map:
             base_name = os.path.splitext(os.path.basename(skn_path))[0]
             potential_names = [f"{base_name}.tex", f"{base_name}.dds", f"{base_name}_TX_CM.tex", f"{base_name}_TX_CM.dds"]
             for name in potential_names:
                 local_path = resolve_texture_path(skn_path, name)
                 if local_path: break

        if local_path:
            # Check cache first
            if local_path in loaded_textures:
                bpy_image = loaded_textures[local_path]
                # Assign cached texture to this material
                if bpy_image and hasattr(mat, "node_tree") and mat.node_tree:
                    nodes = mat.node_tree.nodes
                    links = mat.node_tree.links
                    
                    bsdf = None
                    for n in nodes:
                        if n.type == 'BSDF_PRINCIPLED':
                            bsdf = n
                            break
                    
                    if not bsdf:
                        nodes.clear()
                        output = nodes.new('ShaderNodeOutputMaterial')
                        output.location = (200, 0)
                        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
                        bsdf.location = (0, 0)
                        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

                    tex_node = nodes.new('ShaderNodeTexImage')
                    tex_node.location = (-300, 0)
                    tex_node.image = bpy_image
                    
                    if not bsdf.inputs['Base Color'].is_linked:
                        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
                        
                    print(f"LtMAO: Reused cached {bpy_image.name} for {mat.name}")
                continue
            
            bpy_image = None
            use_texconv_for_this = has_texconv
            
            # --- TexConv Logic ---
            if use_texconv_for_this:
                try:
                    import subprocess, tempfile
                    print(f"LtMAO: Using texconv for {local_path}...")
                    
                    # Prepare input
                    temp_dds_path = None
                    input_arg = local_path
                    
                    if local_path.lower().endswith('.tex'):
                        # Convert TEX to DDS in temp
                        fd, temp_dds_path = tempfile.mkstemp(suffix='.dds')
                        os.close(fd)
                        with open(temp_dds_path, 'wb') as f:
                            f.write(Ritoddstex.tex_to_dds_bytes(local_path))
                        input_arg = temp_dds_path
                        
                    # Output
                    output_dir = os.path.dirname(local_path)
                    
                    cmd = [
                        texconv_path, 
                        '-ft', 'png', 
                        '-f', 'R8G8B8A8_UNORM', 
                        '-m', '1', 
                        '-y', 
                        '-o', output_dir, 
                        input_arg
                    ]
                    
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    subprocess.run(cmd, check=True, startupinfo=si)
                    
                    # Determine output filename
                    base_in = os.path.basename(input_arg).rsplit('.', 1)[0]
                    generated_png = os.path.join(output_dir, base_in + '.png')
                    
                    target_png_name = os.path.basename(local_path).rsplit('.', 1)[0] + '.png'
                    target_png_path = os.path.join(output_dir, target_png_name)
                    
                    if os.path.exists(generated_png):
                        if generated_png != target_png_path:
                            if os.path.exists(target_png_path): os.remove(target_png_path)
                            os.rename(generated_png, target_png_path)
                        
                        if os.path.exists(target_png_path):
                            bpy.data.images.load(target_png_path, check_existing=True)
                            bpy_image = bpy.data.images[os.path.basename(target_png_path)]
                            bpy_image.pack()

                    if temp_dds_path and os.path.exists(temp_dds_path):
                        os.remove(temp_dds_path)
                        
                except Exception as e:
                    print(f"LtMAO: Texconv failed: {e}")
                    use_texconv_for_this = False
            
            # --- Python Logic (Fallback) ---
            if not bpy_image and not use_texconv_for_this:
                try:
                    width, height, pixels = 0, 0, []
                    if local_path.lower().endswith('.tex'):
                        print(f"LtMAO: Reading TEX {local_path} (Python)...")
                        dds_bytes = Ritoddstex.tex_to_dds_bytes(local_path)
                        width, height, pixels = Ritoddstex.decompress_dds_bytes(dds_bytes)
                    else:
                         print(f"LtMAO: Reading DDS {local_path} (Python)...")
                         width, height, pixels = Ritoddstex.decompress_dds_file(local_path)
                    
                    if width > 0:
                        fb = os.path.basename(local_path).rsplit('.', 1)[0]
                        bpy_image = bpy.data.images.new(name=fb, width=width, height=height, alpha=True)
                        bpy_image.pixels = pixels
                        
                        png_p = local_path.rsplit('.', 1)[0] + '.png'
                        bpy_image.filepath_raw = png_p
                        bpy_image.file_format = 'PNG'
                        try:
                            bpy_image.save()
                        except: pass
                        bpy_image.pack()
                except Exception as e:
                    print(f"LtMAO: Python fallback failed: {e}")

            # --- Native Blender Load (Last Resort) ---
            if not bpy_image:
                 try:
                     bpy_image = bpy.data.images.load(local_path, check_existing=True)
                 except: pass

            # --- Assignment ---
            if bpy_image:
                # Add to cache for reuse
                loaded_textures[local_path] = bpy_image
                
                if hasattr(mat, "node_tree") and mat.node_tree:
                    nodes = mat.node_tree.nodes
                    links = mat.node_tree.links
                    
                    bsdf = None
                    for n in nodes:
                        if n.type == 'BSDF_PRINCIPLED':
                            bsdf = n
                            break
                    
                    if not bsdf:
                        nodes.clear()
                        output = nodes.new('ShaderNodeOutputMaterial')
                        output.location = (200, 0)
                        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
                        bsdf.location = (0, 0)
                        links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

                    tex_node = nodes.new('ShaderNodeTexImage')
                    tex_node.location = (-300, 0)
                    tex_node.image = bpy_image
                    
                    if not bsdf.inputs['Base Color'].is_linked:
                        links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
                        
                    print(f"LtMAO: Assigned {bpy_image.name} to {mat.name}")
            else:
                 print(f"LtMAO: Failed to load texture for {local_path}")
        else:
             print(f"LtMAO: Could not resolve texture for material {mat.name}")
