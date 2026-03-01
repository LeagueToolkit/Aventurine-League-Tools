"""File handlers for drag-and-drop import functionality"""
import bpy


class FH_SKN_Import(bpy.types.FileHandler):
    """File handler for dragging .skn files into Blender"""
    bl_idname = "FH_skn_import"
    bl_label = "SKN File Handler"
    bl_import_operator = "import_scene.skn_dragdrop"
    bl_file_extensions = ".skn"

    @classmethod
    def poll_drop(cls, context):
        """Check if drag-drop should be accepted in this context"""
        return context.area and context.area.type in {'VIEW_3D', 'OUTLINER'}


class FH_SKL_Import(bpy.types.FileHandler):
    """File handler for dragging .skl files into Blender"""
    bl_idname = "FH_skl_import"
    bl_label = "SKL File Handler"
    bl_import_operator = "import_scene.skl_dragdrop"
    bl_file_extensions = ".skl"

    @classmethod
    def poll_drop(cls, context):
        """Check if drag-drop should be accepted in this context"""
        return context.area and context.area.type in {'VIEW_3D', 'OUTLINER'}


class FH_ANM_Import(bpy.types.FileHandler):
    """File handler for dragging .anm files into Blender"""
    bl_idname = "FH_anm_import"
    bl_label = "ANM File Handler"
    bl_import_operator = "import_scene.anm_dragdrop"
    bl_file_extensions = ".anm"

    @classmethod
    def poll_drop(cls, context):
        """Check if drag-drop should be accepted in this context"""
        return context.area and context.area.type in {'VIEW_3D', 'OUTLINER'}


class FH_SCB_Import(bpy.types.FileHandler):
    """File handler for dragging .scb files into Blender"""
    bl_idname = "FH_scb_import"
    bl_label = "SCB File Handler"
    bl_import_operator = "import_scene.scb_dragdrop"
    bl_file_extensions = ".scb"

    @classmethod
    def poll_drop(cls, context):
        """Check if drag-drop should be accepted in this context"""
        return context.area and context.area.type in {'VIEW_3D', 'OUTLINER'}


class FH_SCO_Import(bpy.types.FileHandler):
    """File handler for dragging .sco files into Blender"""
    bl_idname = "FH_sco_import"
    bl_label = "SCO File Handler"
    bl_import_operator = "import_scene.sco_dragdrop"
    bl_file_extensions = ".sco"

    @classmethod
    def poll_drop(cls, context):
        """Check if drag-drop should be accepted in this context"""
        return context.area and context.area.type in {'VIEW_3D', 'OUTLINER'}


# List of classes to register
classes = (
    FH_SKN_Import,
    FH_SKL_Import,
    FH_ANM_Import,
    FH_SCB_Import,
    FH_SCO_Import,
)


def register():
    """Register all file handlers"""
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    """Unregister all file handlers"""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
