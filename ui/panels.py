
import bpy
from bpy.types import Panel
from ..utils import history
from . import icons

class LOL_PT_MainPanel(Panel):
    """Main panel for LoL Blender"""
    bl_label = "Aventurine LoL"
    bl_idname = "VIEW3D_PT_lol_blender_new"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Aventurine LoL'
    
    def draw_header(self, context):
        layout = self.layout
        layout.label(text="", icon_value=icons.get_icon("plugin_icon"))
    
    def draw(self, context):
        layout = self.layout
        
        # SKN+SKL section
        box = layout.box()
        box.label(text="SKN+SKL", icon='MESH_DATA')
        row = box.row()
        row.operator("import_scene.skn", text="Import", icon='IMPORT')
        row.operator("export_scene.skn", text="Export", icon='EXPORT')
        
        # History for SKN
        history.draw_history_panel(box, context, 'SKN')
        
        # ANM section
        box = layout.box()
        box.label(text="ANM", icon='ANIM')
        row = box.row()
        row.operator("import_scene.anm", text="Import", icon='IMPORT')
        row.operator("export_scene.anm", text="Export", icon='EXPORT')
        
        # History for ANM
        history.draw_history_panel(box, context, 'ANM')
        
        # SCB section
        box = layout.box()
        box.label(text="SCB (Static Objects)", icon='MESH_CUBE')
        row = box.row()
        row.operator("import_scene.scb", text="Import", icon='IMPORT')
        row.operator("export_scene.scb", text="Export", icon='EXPORT')
        
        # SCO section
        box = layout.box()
        box.label(text="SCO (Static Objects with Pivot)", icon='BONE_DATA')
        row = box.row()
        row.operator("import_scene.sco", text="Import", icon='IMPORT')
        row.operator("export_scene.sco", text="Export", icon='EXPORT')
        

        
        # Show metadata if armature is selected
        if context.active_object and context.active_object.type == 'ARMATURE':
            arm_obj = context.active_object
            # We display this only if we have relevant info, 
            # currently just basic name since custom props aren't set by new importer yet
            box = layout.box()
            box.label(text="Armature Info", icon='ARMATURE_DATA')
            box.label(text=f"Name: {arm_obj.name}")
            
        # Texture section
        box = layout.box()
        box.label(text="Textures", icon='TEXTURE')
        row = box.row()
        row.operator("lol.save_textures", text="Save All", icon='DISK_DRIVE')
        row.operator("lol.reload_textures", text="Reload All", icon='FILE_REFRESH')


class UV_CORNER_PT_panel(Panel):
    """UV Corner Placement Panel for UV Editor"""
    bl_label = "UV Corners"
    bl_idname = "IMAGE_EDITOR_PT_uv_corners"
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'UV Corners'
    
    @classmethod
    def poll(cls, context):
        # Only show in UV editing mode (Image Editor)
        return (context.space_data and 
                context.space_data.type == 'IMAGE_EDITOR' and
                context.active_object and 
                context.active_object.type == 'MESH' and
                context.active_object.data.uv_layers.active)
    
    def draw(self, context):
        layout = self.layout
        
        # Corner buttons in a 2x2 grid with corner symbols
        col = layout.column(align=True)
        
        # Top row
        row = col.row(align=True)
        # Top Left - corner symbol ◸
        row.operator("uv.corner_top_left", text="◸", icon='NONE')
        # Top Right - corner symbol ◹
        row.operator("uv.corner_top_right", text="◹", icon='NONE')
        
        # Bottom row
        row = col.row(align=True)
        # Bottom Left - corner symbol ◺
        row.operator("uv.corner_bottom_left", text="◺", icon='NONE')
        # Bottom Right - corner symbol ◿
        row.operator("uv.corner_bottom_right", text="◿", icon='NONE')
