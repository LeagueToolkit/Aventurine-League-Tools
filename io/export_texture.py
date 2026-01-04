import bpy
import os
from ..LtMAO import Ritoddstex

class LOL_OT_SaveTextures(bpy.types.Operator):
    bl_idname = "lol.save_textures"
    bl_label = "Save Textures"
    bl_description = "Save all edited textures back to disk as .tex or .dds (This may take a while as it compresses manually)"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        # Filter: Only selected objects
        selected_objs = context.selected_objects
        if not selected_objs:
             self.report({'WARNING'}, "No objects selected. Select a mesh to save its textures.")
             return {'CANCELLED'}
             
        images_to_process = set()
        
        for obj in selected_objs:
            if obj.type != 'MESH': continue
            for slot in obj.material_slots:
                if slot.material and slot.material.use_nodes:
                     # Find image nodes
                     for node in slot.material.node_tree.nodes:
                         if node.type == 'TEX_IMAGE' and node.image:
                             images_to_process.add(node.image)
                             
        if not images_to_process:
             self.report({'WARNING'}, "No textures found on selected objects.")
             return {'CANCELLED'}

        # Check for texconv.exe in addon folder
        addon_dir = os.path.dirname(os.path.realpath(__file__))
        texconv_path = os.path.join(addon_dir, 'texconv.exe')
        use_texconv = os.path.exists(texconv_path)
        
        if not use_texconv:
            # Check LtMAO tools
            possible_path = os.path.join(addon_dir, 'LtMAO', 'res', 'tools', 'texconv.exe') # Hypothetical
            if os.path.exists(possible_path):
                texconv_path = possible_path
                use_texconv = True
        
        if not use_texconv:
             self.report({'INFO'}, "texconv.exe not found. Using slow Python compression. (Download texconv.exe to addon folder for speed)")

        count = 0
        error_count = 0
        
        # Iterate filtered images
        for img in images_to_process:
            if not img.filepath: continue
            
            # Check for corresponding game file
            abs_path = bpy.path.abspath(img.filepath)
            folder = os.path.dirname(abs_path)
            basename = os.path.basename(abs_path)
            if '.' in basename: basename = basename.split('.')[0]
            
            # Auto-detect target (tex or dds)
            target_path = None
            is_tex = False
            
            tex_p = os.path.join(folder, basename + '.tex')
            dds_p = os.path.join(folder, basename + '.dds')
            
            if os.path.exists(tex_p):
                target_path = tex_p
                is_tex = True
            elif os.path.exists(dds_p):
                target_path = dds_p
                is_tex = False
            
            if target_path:
                try:
                    self.report({'INFO'}, f"Saving {img.name} -> {os.path.basename(target_path)}...")
                    
                    dds_bytes = None
                    
                    if use_texconv:
                        import subprocess
                        import tempfile
                        import shutil
                        
                        # Save temp PNG
                        with tempfile.TemporaryDirectory() as temp_dir:
                            temp_png = os.path.join(temp_dir, 'temp.png')
                            img.save_render(filepath=temp_png)
                            
                            # Run texconv
                            # -f DXT5 (BC3_UNORM)
                            # -m 1 (No Mipmaps for now, keeping it simple. Or let it generate?)
                            # User might want mipmaps but my manual python code didn't supports them.
                            # texconv generates mips by default. Let's force 1 for consistency unless requested.
                            # -y (overwrite)
                            cmd = [texconv_path, '-f', 'BC3_UNORM', '-m', '1', '-y', '-o', temp_dir, temp_png]
                            # Hide window
                            si = subprocess.STARTUPINFO()
                            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            
                            subprocess.run(cmd, check=True, startupinfo=si)
                            
                            # Result is temp.dds
                            temp_dds = os.path.join(temp_dir, 'temp.dds')
                            if os.path.exists(temp_dds):
                                with open(temp_dds, 'rb') as f:
                                    dds_bytes = f.read()
                            else:
                                raise Exception("texconv failed to create DDS")
                                
                    else:
                        # Slow Python
                        width, height = img.size
                        pixels = list(img.pixels)
                        dds_bytes = Ritoddstex.compress_dds_bytes(pixels, width, height)
                    
                    if dds_bytes:
                        output_bytes = dds_bytes
                        if is_tex:
                            output_bytes = Ritoddstex.dds_bytes_to_tex_bytes(dds_bytes)
                            
                        with open(target_path, 'wb') as f:
                            f.write(output_bytes)
                        count += 1
                        
                except Exception as e:
                    self.report({'ERROR'}, f"Failed {img.name}: {e}")
                    error_count += 1
                    print(f"Error saving {img.name}: {e}")
        
        msg = f"Saved {count} textures."
        if not use_texconv: msg += " (Slow mode)"
        if error_count > 0: msg += f" ({error_count} failed)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}

class LOL_OT_ReloadTextures(bpy.types.Operator):
    """Reloads all textures from disk (Auto-updates from .tex/.dds if newer)"""
    bl_idname = "lol.reload_textures"
    bl_label = "Reload Textures"
    
    def execute(self, context):
        count = 0
        converted_count = 0
        
        # Check for texconv (for potential re-conversion)
        addon_dir = os.path.dirname(os.path.realpath(__file__))
        texconv_path = os.path.join(addon_dir, 'texconv.exe')
        if not os.path.exists(texconv_path):
             possible = os.path.join(addon_dir, 'LtMAO', 'res', 'tools', 'texconv.exe')
             if os.path.exists(possible): texconv_path = possible
        
        use_texconv = os.path.exists(texconv_path)
        
        for img in bpy.data.images:
            if not img.filepath: continue
            
            # Allow skipping internal/generated images?
            if img.source != 'FILE': continue

            path = bpy.path.abspath(img.filepath)
            if not os.path.exists(path): continue
            
            # Smart Check: Is there a newer .tex/.dds?
            # Assume image is [name].png
            folder = os.path.dirname(path)
            basename = os.path.basename(path).rsplit('.', 1)[0]
            
            tex_p = os.path.join(folder, basename + '.tex')
            dds_p = os.path.join(folder, basename + '.dds')
            source_p = None
            
            if os.path.exists(tex_p): source_p = tex_p
            elif os.path.exists(dds_p): source_p = dds_p
            
            if source_p:
                # Compare timestamps
                try:
                    png_mtime = os.path.getmtime(path)
                    src_mtime = os.path.getmtime(source_p)
                    
                    if src_mtime > png_mtime:
                        # Source is newer! Re-convert.
                        # We reuse the logic from texture_manager somewhat, but simpler
                        import subprocess, tempfile
                        from ..LtMAO import Ritoddstex
                        
                        input_arg = source_p
                        temp_dds_path = None
                        
                        if source_p.lower().endswith('.tex'):
                             fd, temp_dds_path = tempfile.mkstemp(suffix='.dds')
                             os.close(fd)
                             with open(temp_dds_path, 'wb') as f:
                                 f.write(Ritoddstex.tex_to_dds_bytes(source_p))
                             input_arg = temp_dds_path
                        
                        # Run texconv
                        if use_texconv:
                            cmd = [
                                texconv_path, '-ft', 'png', '-f', 'R8G8B8A8_UNORM', 
                                '-m', '1', '-y', '-o', folder, input_arg
                            ]
                            si = subprocess.STARTUPINFO()
                            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                            subprocess.run(cmd, check=True, startupinfo=si)
                            
                            # Rename if needed (unlikely if names match)
                            # texconv outputs [basename].png.
                            # if input was temp file, we renamed it.
                            if temp_dds_path:
                                base_temp = os.path.basename(temp_dds_path).rsplit('.', 1)[0]
                                gen_png = os.path.join(folder, base_temp + '.png')
                                if os.path.exists(gen_png):
                                    # Copy to real path
                                    if os.path.exists(path): os.remove(path)
                                    os.rename(gen_png, path)
                            
                            converted_count += 1
                        
                        if temp_dds_path and os.path.exists(temp_dds_path): os.remove(temp_dds_path)
                except Exception as e:
                    print(f"Smart reload failed for {img.name}: {e}")

            try:
                img.reload()
                count += 1
            except:
                pass
                
        self.report({'INFO'}, f"Reloaded {count} textures ({converted_count} updated from game files)")
        return {'FINISHED'}
