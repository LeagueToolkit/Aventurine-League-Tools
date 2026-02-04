import bpy
import os
import tempfile
import numpy as np
from ..utils.texture_manager import tex_to_dds_bytes


class LOL_OT_ReloadTextures(bpy.types.Operator):
    """Reloads all textures from their source TEX/DDS files"""
    bl_idname = "lol.reload_textures"
    bl_label = "Reload Textures"

    def execute(self, context):
        count = 0

        for img in bpy.data.images:
            source_path = img.get("lol_source_path")
            if not source_path or not os.path.exists(source_path):
                continue

            temp_dds_path = None
            try:
                load_path = source_path

                # Convert TEX to temp DDS if needed
                if source_path.lower().endswith('.tex'):
                    dds_bytes = tex_to_dds_bytes(source_path)
                    fd, temp_dds_path = tempfile.mkstemp(suffix='.dds')
                    os.close(fd)
                    with open(temp_dds_path, 'wb') as f:
                        f.write(dds_bytes)
                    load_path = temp_dds_path

                # Load with Blender native
                temp_img = bpy.data.images.load(load_path, check_existing=False)

                # Get pixels and update existing image using fast numpy transfer
                width, height = temp_img.size

                if img.size[0] != width or img.size[1] != height:
                    img.scale(width, height)

                # Fast pixel transfer using foreach_get/foreach_set
                pixel_count = width * height * 4
                pixels = np.empty(pixel_count, dtype=np.float32)
                temp_img.pixels.foreach_get(pixels)
                img.pixels.foreach_set(pixels)

                # Remove temp image
                bpy.data.images.remove(temp_img)

                # Clean up temp file
                if temp_dds_path and os.path.exists(temp_dds_path):
                    os.remove(temp_dds_path)

                count += 1

            except Exception as e:
                print(f"Aventurine: Failed to reload {img.name}: {e}")
                if temp_dds_path and os.path.exists(temp_dds_path):
                    os.remove(temp_dds_path)

        self.report({'INFO'}, f"Reloaded {count} textures")
        return {'FINISHED'}
