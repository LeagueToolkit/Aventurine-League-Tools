import bpy
import bmesh
import time
from bpy.types import Operator, Panel, PropertyGroup
from bpy.props import PointerProperty, BoolProperty, CollectionProperty, StringProperty, IntProperty, FloatProperty, EnumProperty
from mathutils import Vector
from mathutils.geometry import intersect_point_line
from ..ui import icons

# Try to import voxel heat module
try:
    from . import voxel_heat
    HAS_VOXEL_HEAT = True
except ImportError:
    HAS_VOXEL_HEAT = False
    print("Voxel Heat module not available")

# Core bone names that should receive weights
# This list matches the standard logic used in retargeting
CORE_BONES = {
    'pelvis', 'hip', 'spine', 'spine1', 'spine2', 'spine3', 'chest', 'neck', 'head',
    'clavicle', 'shoulder', 'elbow', 'hand',
    'thumb1', 'thumb2', 'thumb3', 
    'index1', 'index2', 'index3', 
    'middle1', 'middle2', 'middle3', 
    'ring1', 'ring2', 'ring3', 
    'pinky1', 'pinky2', 'pinky3',
    'knee', 'kneelower', 'foot'
}


def normalize_bone_name(name):
    """Normalize bone name for comparison - remove common prefixes and lowercase"""
    name = name.lower()
    # Remove common prefixes
    prefixes = ['c_', 'l_', 'r_', 'buffbone_', 'glb_', 'cstm_']
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name


# =============================================================================
# VOXELIZED SKINNING - Inspired by Auto Rig Pro's approach
# Creates a voxelized copy, binds that, then transfers weights back
# =============================================================================

def create_voxelized_copy(context, mesh_obj, voxel_resolution=8):
    """
    Create a voxelized (remeshed) copy of the mesh.
    Voxelization creates a watertight mesh that Blender's heat algorithm
    can properly calculate distances through.
    
    Args:
        context: Blender context
        mesh_obj: Original mesh object
        voxel_resolution: Resolution for voxelization (higher = more detail, slower)
    
    Returns:
        The voxelized copy object
    """
    # Store current selection
    original_active = context.active_object
    
    # Duplicate the mesh
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    context.view_layer.objects.active = mesh_obj
    bpy.ops.object.duplicate()
    
    vox_obj = context.active_object
    vox_obj.name = mesh_obj.name + "_voxelized_temp"
    
    # Remove any shape keys (they mess with remeshing)
    if vox_obj.data.shape_keys:
        bpy.ops.object.shape_key_remove(all=True)
    
    # Apply any modifiers except Armature
    for mod in vox_obj.modifiers[:]:
        if mod.type != 'ARMATURE':
            try:
                bpy.ops.object.modifier_apply(modifier=mod.name)
            except:
                bpy.ops.object.modifier_remove(modifier=mod.name)
        else:
            bpy.ops.object.modifier_remove(modifier=mod.name)
    
    # Remove all vertex groups (we'll get fresh weights)
    vox_obj.vertex_groups.clear()
    
    # Get mesh dimensions for voxel size calculation
    dimensions = vox_obj.dimensions
    larger_dim = max(dimensions)
    larger_scale = max(abs(s) for s in vox_obj.scale)
    
    # Add Remesh modifier in VOXEL mode
    remesh = vox_obj.modifiers.new(name="Voxelize", type='REMESH')
    remesh.mode = 'VOXEL'
    
    # Calculate voxel size based on mesh dimensions and resolution
    # Higher resolution number = smaller voxels = more detail
    base_size = (larger_dim / larger_scale) * 0.003
    remesh.voxel_size = base_size / (voxel_resolution / 8.0)
    
    print(f"  Voxel size: {remesh.voxel_size:.6f}")
    
    # Apply the remesh modifier
    bpy.ops.object.modifier_apply(modifier=remesh.name)
    
    # Decimate if too high poly (for performance)
    max_faces = 70000
    iterations = 0
    
    while len(vox_obj.data.polygons) > max_faces and iterations < 20:
        print(f"  {len(vox_obj.data.polygons)} faces, decimating...")
        decimate = vox_obj.modifiers.new(name="Decimate", type='DECIMATE')
        decimate.ratio = 0.7
        bpy.ops.object.modifier_apply(modifier=decimate.name)
        iterations += 1
    
    # Clean up the mesh for better heat weighting
    print("  Cleaning up mesh geometry...")
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    
    # Recalculate normals (crucial for heat weighting)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    
    # Remove any loose geometry
    bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=True)
    
    # Remove doubles to ensure manifold mesh
    bpy.ops.mesh.remove_doubles(threshold=0.0001)
    
    bpy.ops.object.mode_set(mode='OBJECT')
    
    print(f"  Voxelized mesh: {len(vox_obj.data.vertices)} verts, {len(vox_obj.data.polygons)} faces")
    
    return vox_obj


def transfer_weights_to_original(context, source_obj, target_obj):
    """
    Transfer vertex weights from source (voxelized) to target (original) mesh.
    Uses Blender's Data Transfer with nearest face interpolation.
    
    Args:
        context: Blender context
        source_obj: Object with weights (voxelized mesh)
        target_obj: Object to receive weights (original mesh)
    """
    bpy.ops.object.select_all(action='DESELECT')
    target_obj.select_set(True)
    source_obj.select_set(True)
    context.view_layer.objects.active = target_obj
    
    # Use data transfer operator
    bpy.ops.object.data_transfer(
        data_type='VGROUP_WEIGHTS',
        vert_mapping='POLYINTERP_NEAREST',  # Nearest face interpolated - best for different topologies
        layers_select_src='ALL',
        layers_select_dst='NAME'
    )
    
    # Clean up tiny weights
    bpy.ops.object.vertex_group_clean(group_select_mode='ALL', limit=0.01)


def apply_voxelized_skinning(context, mesh_obj, armature, enabled_bones, props, use_scale_fix=True):
    """
    Main function for improved skinning approach.
    
    1. Creates a working copy of the mesh
    2. Scales up to help Blender's heat algorithm
    3. Applies Blender's auto-weights
    4. Transfers weights back to original
    5. Cleans up
    
    If heat weighting fails, returns False so caller can use fallback.
    """
    print("Starting Improved Skinning...")
    start_time = time.time()
    
    # Ensure we're in object mode
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    
    # CRITICAL: Set armature to REST pose - heat weighting requires this!
    original_pose_position = armature.data.pose_position
    armature.data.pose_position = 'REST'
    print(f"  Set armature to REST pose (was: {original_pose_position})")
    
    # Store original deform states and set only enabled bones to deform
    original_states = {}
    for bone in armature.data.bones:
        original_states[bone.name] = bone.use_deform
        bone.use_deform = bone.name in enabled_bones
    
    print(f"  Enabled {len(enabled_bones)} bones for deform")
    
    # Step 1: Create a working copy of the mesh
    print("Step 1: Preparing mesh copy...")
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    context.view_layer.objects.active = mesh_obj
    
    # Duplicate WITHOUT linked data to avoid shape key issues
    bpy.ops.object.duplicate(linked=False)
    
    work_obj = context.active_object
    work_obj.name = mesh_obj.name + "_temp_bind"
    
    # Remove shape keys to avoid warnings during binding
    if work_obj.data.shape_keys:
        work_obj.shape_key_clear()
    
    # Remove existing vertex groups
    work_obj.vertex_groups.clear()
    
    # Remove armature modifiers
    for mod in work_obj.modifiers[:]:
        if mod.type == 'ARMATURE':
            work_obj.modifiers.remove(mod)
    
    # Clear parent
    if work_obj.parent:
        work_obj.parent = None
    
    # Step 2: Scale fix - Blender's heat algorithm often fails on small meshes
    scale_factor = 20.0
    original_arm_scale = armature.scale.copy()
    original_arm_location = armature.location.copy()
    
    print(f"  Applying scale fix: {scale_factor}x")
    
    # Scale both mesh and armature equally
    armature.scale *= scale_factor
    armature.location *= scale_factor
    work_obj.scale *= scale_factor
    work_obj.location *= scale_factor
    
    # Update scene
    context.view_layer.update()
    
    # Step 3: Bind mesh to armature
    print("Step 2: Binding mesh...")
    bpy.ops.object.select_all(action='DESELECT')
    work_obj.select_set(True)
    armature.select_set(True)
    context.view_layer.objects.active = armature
    
    # Try auto-weights
    heat_failed = False
    try:
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        print("  Auto-weights applied")
    except Exception as e:
        print(f"  Error during auto-weights: {e}")
        heat_failed = True
    
    # Restore armature scale
    armature.scale = original_arm_scale
    armature.location = original_arm_location
    
    # Restore work mesh scale
    work_obj.scale /= scale_factor
    work_obj.location /= scale_factor
    context.view_layer.update()
    
    # Check if we got any weights
    has_weights = False
    for vg in work_obj.vertex_groups:
        if vg.name in enabled_bones:
            has_weights = True
            break
    
    print(f"  Has weights: {has_weights}")
    
    # Step 3: Transfer weights to original mesh
    if has_weights:
        print("Step 3: Transferring weights to original...")
        transfer_weights_to_original(context, work_obj, mesh_obj)
    else:
        print("Step 3: No weights to transfer!")
        heat_failed = True
    
    # Step 4: Setup armature modifier on original mesh
    print("Step 4: Setting up armature modifier...")
    
    # Remove any existing armature modifiers
    for mod in mesh_obj.modifiers[:]:
        if mod.type == 'ARMATURE':
            mesh_obj.modifiers.remove(mod)
    
    # Add new armature modifier
    arm_mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
    arm_mod.object = armature
    arm_mod.use_vertex_groups = True
    
    # Parent mesh to armature
    mesh_obj.parent = armature
    mesh_obj.matrix_parent_inverse = armature.matrix_world.inverted()
    
    # Step 5: Clean up
    print("Step 5: Cleaning up...")
    bpy.data.objects.remove(work_obj, do_unlink=True)
    
    # Restore deform flags
    for name, state in original_states.items():
        if name in armature.data.bones:
            armature.data.bones[name].use_deform = state
    
    # Restore pose position
    armature.data.pose_position = original_pose_position
    
    elapsed = time.time() - start_time
    
    if heat_failed or not has_weights:
        print(f"Skinning FAILED in {elapsed:.2f} seconds - will use fallback")
        return False
    else:
        print(f"Skinning complete in {elapsed:.2f} seconds")
        return True


# =============================================================================
# DISTANCE-BASED WEIGHTS (Fallback method)
# =============================================================================

def get_bone_segment_distance(point, head, tail):
    """Calculate shortest distance from point to bone segment."""
    pt_on_segment, t = intersect_point_line(point, head, tail)
    
    if t < 0.0:
        closest = head
        t = 0.0
    elif t > 1.0:
        closest = tail
        t = 1.0
    else:
        closest = pt_on_segment
    
    distance = (point - closest).length
    return distance, closest, t


def calculate_bone_weight(distance, falloff_radius, falloff_power=2.0):
    """Calculate weight based on distance with smooth falloff."""
    if distance <= 0.0001:
        return 1.0
    
    if distance >= falloff_radius:
        return 0.0
    
    t = distance / falloff_radius
    weight = (1.0 - t) ** falloff_power
    
    return max(0.0, min(1.0, weight))


def build_vertex_adjacency(mesh_obj):
    """Build adjacency list for weight smoothing."""
    mesh = mesh_obj.data
    adjacency = {i: set() for i in range(len(mesh.vertices))}
    
    for edge in mesh.edges:
        v1, v2 = edge.vertices
        adjacency[v1].add(v2)
        adjacency[v2].add(v1)
    
    return adjacency


def smooth_weights_pass(mesh_obj, vertex_weights, adjacency, strength=0.5):
    """Single pass of weight smoothing using neighbor averaging."""
    smoothed = {}
    
    for bone_name, weights in vertex_weights.items():
        smoothed[bone_name] = {}
        
        for vert_idx, weight in weights.items():
            if vert_idx not in adjacency or not adjacency[vert_idx]:
                smoothed[bone_name][vert_idx] = weight
                continue
            
            neighbor_sum = 0.0
            neighbor_count = 0
            
            for neighbor_idx in adjacency[vert_idx]:
                if neighbor_idx in weights:
                    neighbor_sum += weights[neighbor_idx]
                    neighbor_count += 1
            
            if neighbor_count > 0:
                neighbor_avg = neighbor_sum / neighbor_count
                new_weight = weight * (1.0 - strength) + neighbor_avg * strength
                smoothed[bone_name][vert_idx] = new_weight
            else:
                smoothed[bone_name][vert_idx] = weight
    
    return smoothed


def normalize_vertex_weights(vertex_weights, num_verts, max_influences=4):
    """Normalize weights per vertex and limit influences."""
    per_vertex = {i: [] for i in range(num_verts)}
    
    for bone_name, weights in vertex_weights.items():
        for vert_idx, weight in weights.items():
            if weight > 0.0001:
                per_vertex[vert_idx].append((bone_name, weight))
    
    normalized = {}
    for vert_idx, bone_weights in per_vertex.items():
        if not bone_weights:
            continue
        
        bone_weights.sort(key=lambda x: x[1], reverse=True)
        bone_weights = bone_weights[:max_influences]
        
        total = sum(w for _, w in bone_weights)
        if total > 0.0001:
            normalized[vert_idx] = [(name, w / total) for name, w in bone_weights]
        else:
            normalized[vert_idx] = bone_weights
    
    return normalized


def calculate_adaptive_radius(armature, bone, scale_factor=2.0):
    """Calculate adaptive falloff radius for a bone."""
    bone_length = (bone.tail_local - bone.head_local).length
    base_radius = bone_length * scale_factor
    min_radius = 0.05
    
    return max(base_radius, min_radius)


def compute_distance_weights(mesh_obj, armature, enabled_bones, falloff_multiplier=2.0, falloff_power=2.0):
    """Compute weights using distance-based algorithm."""
    mesh = mesh_obj.data
    mw_mesh = mesh_obj.matrix_world
    mw_arm = armature.matrix_world
    
    bone_data = []
    for bone in armature.data.bones:
        if bone.name not in enabled_bones:
            continue
        
        head_world = mw_arm @ bone.head_local
        tail_world = mw_arm @ bone.tail_local
        radius = calculate_adaptive_radius(armature, bone, falloff_multiplier)
        
        bone_data.append({
            'name': bone.name,
            'head': head_world,
            'tail': tail_world,
            'radius': radius,
        })
    
    if not bone_data:
        return {}
    
    vertex_weights = {bd['name']: {} for bd in bone_data}
    
    for vert in mesh.vertices:
        vert_world = mw_mesh @ vert.co
        
        for bd in bone_data:
            dist, _, _ = get_bone_segment_distance(vert_world, bd['head'], bd['tail'])
            weight = calculate_bone_weight(dist, bd['radius'], falloff_power)
            
            if weight > 0.0001:
                vertex_weights[bd['name']][vert.index] = weight
    
    return vertex_weights


def apply_weights_to_mesh(mesh_obj, normalized_weights):
    """Apply calculated weights to mesh vertex groups."""
    bone_names = set()
    for vert_weights in normalized_weights.values():
        for bone_name, _ in vert_weights:
            bone_names.add(bone_name)
    
    for bone_name in bone_names:
        if bone_name not in mesh_obj.vertex_groups:
            mesh_obj.vertex_groups.new(name=bone_name)
    
    for bone_name in bone_names:
        vg = mesh_obj.vertex_groups.get(bone_name)
        if vg:
            vg.remove(list(range(len(mesh_obj.data.vertices))))
    
    for vert_idx, bone_weights in normalized_weights.items():
        for bone_name, weight in bone_weights:
            vg = mesh_obj.vertex_groups.get(bone_name)
            if vg and weight > 0.0001:
                vg.add([vert_idx], weight, 'REPLACE')


# =============================================================================
# Property Groups
# =============================================================================

class WeightBoneItem(PropertyGroup):
    """List item for bone selection"""
    name: StringProperty()
    is_core: BoolProperty(default=False)
    enabled: BoolProperty(default=True)

class ShrinkBoneItem(PropertyGroup):
    """List item for bones to shrink"""
    name: StringProperty()

class LOL_SmartWeightProperties(PropertyGroup):
    """Properties for smart weighting"""
    bone_list: CollectionProperty(type=WeightBoneItem)
    active_bone_index: IntProperty()
    
    # Shrink List (for Blender method)
    shrink_bone_list: CollectionProperty(type=ShrinkBoneItem)
    active_shrink_index: IntProperty()
    shrink_search_str: StringProperty(name="Bone", description="Bone to add to shrink list")
    
    # Smart Distance Settings
    weight_falloff: FloatProperty(
        name="Falloff",
        description="Controls weight sharpness. Low = soft blending, High = sharp bone boundaries",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    max_influences: IntProperty(
        name="Max Influences",
        description="Maximum bones per vertex. 3-4 is standard for games",
        default=4,
        min=1,
        max=8
    )
    
    smooth_weights: BoolProperty(
        name="Smooth Weights",
        description="Apply smoothing pass after weight calculation",
        default=True
    )
    
    clear_unused_groups: BoolProperty(
        name="Clear Unchecked Groups",
        description="Remove vertex groups for unchecked bones before weighting",
        default=True
    )

    clean_shape_keys: BoolProperty(
        name="Remove Shape Keys",
        description="Remove all shape keys (morphs) before weighting. LoL doesn't use them.",
        default=True
    )

    clean_mismatched_groups: BoolProperty(
        name="Clean Mismatched Groups",
        description="Remove vertex groups that don't match any bone in the armature",
        default=True
    )


# =============================================================================
# Operators
# =============================================================================

class LOL_OT_PopulateWeightList(Operator):
    """Populate the list of bones to be used for weighting"""
    bl_idname = "lol.populate_weight_list"
    bl_label = "Scan Bones"
    bl_description = "Scan selected armature and identify core bones"
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'

    def execute(self, context):
        props = context.scene.lol_smart_weight
        armature = context.active_object
        
        if context.mode != 'OBJECT':
             bpy.ops.object.mode_set(mode='OBJECT')
        
        props.bone_list.clear()
        
        core_count = 0
        total_count = 0
        
        for bone in armature.data.bones:
            item = props.bone_list.add()
            item.name = bone.name
            
            norm_name = normalize_bone_name(bone.name)
            is_core = False
            
            if 'buffbone' not in bone.name.lower() and 'helper' not in bone.name.lower():
                if norm_name in CORE_BONES:
                    is_core = True
                elif any(norm_name == core for core in CORE_BONES):
                    is_core = True
            
            item.is_core = is_core
            item.enabled = is_core
            
            if is_core:
                core_count += 1
            total_count += 1
            
        self.report({'INFO'}, f"Found {core_count} core bones out of {total_count}")
        
        return {'FINISHED'}


class LOL_OT_ApplySmartWeights(Operator):
    """Apply weights using the selected method"""
    bl_idname = "lol.apply_smart_weights"
    bl_label = "Apply Smart Weights"
    bl_description = "Calculate and apply vertex weights using the selected algorithm"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        if not context.active_object or context.active_object.type != 'ARMATURE':
            return False
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        props = context.scene.lol_smart_weight
        armature = context.active_object
        
        meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if not meshes:
            self.report({'ERROR'}, "No mesh selected")
            return {'CANCELLED'}
            
        # 1. Cleanup Shape Keys
        if props.clean_shape_keys:
            count = 0
            for obj in meshes:
                if obj.data.shape_keys:
                    obj.shape_key_clear()
                    count += 1
            if count > 0:
                self.report({'INFO'}, f"Removed shape keys from {count} meshes")

        # 2. Cleanup Mismatched Groups
        if props.clean_mismatched_groups:
            bone_names = set(bone.name for bone in armature.data.bones)
            removed_count = 0
            for obj in meshes:
                to_remove = [vg.name for vg in obj.vertex_groups if vg.name not in bone_names]
                for name in to_remove:
                    obj.vertex_groups.remove(obj.vertex_groups[name])
                    removed_count += 1
            if removed_count > 0:
                self.report({'INFO'}, f"Removed {removed_count} mismatched vertex groups")
        
        # Build enabled bones set
        if len(props.bone_list) == 0:
            bpy.ops.lol.populate_weight_list()
        
        enabled_bones = {item.name for item in props.bone_list if item.enabled}
        
        if not enabled_bones:
            self.report({'ERROR'}, "No bones enabled for weighting")
            return {'CANCELLED'}
        
        # Clear old weights if requested
        if props.clear_unused_groups:
            unchecked_bones = {item.name for item in props.bone_list if not item.enabled}
            for mesh_obj in meshes:
                for bone_name in unchecked_bones:
                    vg = mesh_obj.vertex_groups.get(bone_name)
                    if vg:
                        mesh_obj.vertex_groups.remove(vg)
        
        # Apply Smart Distance weights to each mesh
        for mesh_obj in meshes:
            if HAS_VOXEL_HEAT:
                # Map 0-1 falloff slider to falloff_power (1.0 to 4.0)
                # Low slider = soft (power 1.0), High slider = sharp (power 4.0)
                falloff_power = 1.0 + (props.weight_falloff * 3.0)
                
                # Smoothing iterations based on checkbox
                smooth_iterations = 2 if props.smooth_weights else 0
                
                success = voxel_heat.voxel_heat_diffuse_skinning(
                    context, mesh_obj, armature, enabled_bones,
                    resolution=64,  # Not used but kept for compatibility
                    iterations=smooth_iterations * 3,  # 0 or 6
                    falloff=props.weight_falloff,
                    max_influences=props.max_influences
                )
                
                if not success:
                    self.report({'WARNING'}, "Weighting failed for " + mesh_obj.name)
            else:
                self.report({'ERROR'}, "Smart Weights module not available")
                return {'CANCELLED'}
        
        self.report({'INFO'}, f"Applied weights to {len(meshes)} mesh(es) ({len(enabled_bones)} bones)")
        return {'FINISHED'}
    
    def apply_distance_weights(self, context, mesh_obj, armature, enabled_bones, props):
        """Apply custom distance-based weights"""
        mesh_obj.data.update()
        
        vertex_weights = compute_distance_weights(
            mesh_obj, 
            armature, 
            enabled_bones,
            falloff_multiplier=props.falloff_multiplier,
            falloff_power=props.falloff_power
        )
        
        if props.smooth_iterations > 0:
            adjacency = build_vertex_adjacency(mesh_obj)
            for _ in range(props.smooth_iterations):
                vertex_weights = smooth_weights_pass(
                    mesh_obj, 
                    vertex_weights, 
                    adjacency, 
                    strength=props.smooth_strength
                )
        
        normalized = normalize_vertex_weights(
            vertex_weights, 
            len(mesh_obj.data.vertices),
            max_influences=props.max_influences
        )
        
        apply_weights_to_mesh(mesh_obj, normalized)
        
        if mesh_obj.parent != armature:
            mesh_obj.parent = armature
            mesh_obj.matrix_parent_inverse = armature.matrix_world.inverted()
        
        has_armature_mod = any(m.type == 'ARMATURE' for m in mesh_obj.modifiers)
        if not has_armature_mod:
            mod = mesh_obj.modifiers.new(name='Armature', type='ARMATURE')
            mod.object = armature
    
    def apply_blender_weights(self, context, mesh_obj, armature, enabled_bones, props):
        """Use Blender's built-in automatic weights"""
        original_states = {}
        for bone in armature.data.bones:
            original_states[bone.name] = bone.use_deform
            bone.use_deform = bone.name in enabled_bones
        
        original_geometry = {}
        if props.shrink_risky_bones:
            bpy.ops.object.mode_set(mode='EDIT')
            eb = armature.data.edit_bones
            
            shrink_names = {item.name for item in props.shrink_bone_list}
            
            for bone in eb:
                if bone.name in shrink_names:
                    original_geometry[bone.name] = {
                        'tail': bone.tail.copy(),
                        'use_connect': bone.use_connect,
                    }
                    bone.use_connect = False
                    direction = (bone.tail - bone.head).normalized()
                    if direction.length == 0:
                        direction = Vector((0, 0, 1))
                    bone.tail = bone.head + (direction * 0.05)
            
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # Select mesh and armature
        bpy.ops.object.select_all(action='DESELECT')
        mesh_obj.select_set(True)
        armature.select_set(True)
        context.view_layer.objects.active = armature
        
        try:
            bpy.ops.object.parent_set(type='ARMATURE_AUTO')
        except Exception as e:
            self.report({'WARNING'}, f"Blender auto-weights had issues: {str(e)}")
        
        # Restore bone geometry
        if props.shrink_risky_bones and original_geometry:
            bpy.ops.object.mode_set(mode='EDIT')
            eb = armature.data.edit_bones
            for name, data in original_geometry.items():
                if name in eb:
                    bone = eb[name]
                    bone.tail = data['tail']
                    bone.use_connect = data['use_connect']
            bpy.ops.object.mode_set(mode='OBJECT')
        
        # Restore deform flags
        for name, state in original_states.items():
            if name in armature.data.bones:
                armature.data.bones[name].use_deform = state


class LOL_OT_DebugWeights(Operator):
    """Print weights of selected vertices to System Console"""
    bl_idname = "lol.debug_weights"
    bl_label = "Debug Vertex Weights"
    bl_description = "Print influence list of selected vertices to the System Console"
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        
        selected_verts = [v for v in mesh.vertices if v.select]
        
        if not selected_verts:
            self.report({'WARNING'}, "No vertices selected")
            return {'CANCELLED'}
            
        print("-" * 50)
        print(f"Debug Weights for '{obj.name}' ({len(selected_verts)} verts):")
        
        group_names = {g.index: g.name for g in obj.vertex_groups}
        
        for v in selected_verts:
            print(f"Vertex {v.index}:")
            if not v.groups:
                print("  <No Weights>")
                continue
                
            sorted_groups = sorted(v.groups, key=lambda x: x.weight, reverse=True)
            for g in sorted_groups:
                g_name = group_names.get(g.group, f"Unknown({g.group})")
                print(f"  - {g_name}: {g.weight:.4f}")
        
        print("-" * 50)
        self.report({'INFO'}, "Weights printed to System Console")
        return {'FINISHED'}


class LOL_OT_DeleteShapeKeys(Operator):
    """Delete all shape keys from the selected mesh"""
    bl_idname = "lol.delete_shape_keys"
    bl_label = "Delete All Shape Keys"
    bl_description = "Remove all shape keys from selected meshes (LoL doesn't use shape keys)"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' and obj.data.shape_keys for obj in context.selected_objects)

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type == 'MESH' and obj.data.shape_keys:
                # Need to be in object mode and have this object active
                context.view_layer.objects.active = obj
                obj.shape_key_clear()
                count += 1
        
        self.report({'INFO'}, f"Deleted shape keys from {count} mesh(es)")
        return {'FINISHED'}


class LOL_OT_ClearMismatchedGroups(Operator):
    """Clear vertex groups that don't match armature bone names"""
    bl_idname = "lol.clear_mismatched_groups"
    bl_label = "Clear Mismatched Vertex Groups"
    bl_description = "Remove vertex groups that don't match any bone in the armature"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        if not context.active_object or context.active_object.type != 'ARMATURE':
            return False
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        armature = context.active_object
        bone_names = set(bone.name for bone in armature.data.bones)
        
        total_removed = 0
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            
            # Find groups that don't match any bone
            to_remove = []
            for vg in obj.vertex_groups:
                if vg.name not in bone_names:
                    to_remove.append(vg.name)
            
            # Remove the mismatched groups
            for name in to_remove:
                vg = obj.vertex_groups.get(name)
                if vg:
                    obj.vertex_groups.remove(vg)
                    total_removed += 1
        
        self.report({'INFO'}, f"Removed {total_removed} mismatched vertex groups")
        return {'FINISHED'}


class LOL_OT_ClearAllVertexGroups(Operator):
    """Clear all vertex groups from selected meshes"""
    bl_idname = "lol.clear_all_vertex_groups"
    bl_label = "Clear All Vertex Groups"
    bl_description = "Remove ALL vertex groups from selected meshes (fresh start before binding)"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return any(obj.type == 'MESH' and len(obj.vertex_groups) > 0 for obj in context.selected_objects)

    def execute(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type == 'MESH':
                num_groups = len(obj.vertex_groups)
                obj.vertex_groups.clear()
                count += num_groups
        
        self.report({'INFO'}, f"Removed {count} vertex groups")
        return {'FINISHED'}


class LOL_UL_WeightBoneList(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row()
            row.prop(item, "enabled", text="")
            row.label(text=item.name, icon='BONE_DATA')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text=item.name)


class LOL_OT_TransferWeights(Operator):
    """Transfer weights from another mesh"""
    bl_idname = "lol.transfer_weights"
    bl_label = "Transfer Weights"
    bl_description = "Transfer weights from source mesh to selected mesh"
    bl_options = {'REGISTER', 'UNDO'}
    
    source_object: StringProperty(name="Source Mesh")
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH'

    def execute(self, context):
        target_obj = context.active_object
        source_obj = context.scene.objects.get(self.source_object)
        
        if not source_obj:
            self.report({'ERROR'}, "Source object not found")
            return {'CANCELLED'}
        
        if source_obj.type != 'MESH':
            self.report({'ERROR'}, "Source must be a mesh")
            return {'CANCELLED'}
        
        bpy.ops.object.select_all(action='DESELECT')
        target_obj.select_set(True)
        source_obj.select_set(True)
        context.view_layer.objects.active = target_obj
        
        try:
            bpy.ops.object.data_transfer(
                data_type='VGROUP_WEIGHTS',
                vert_mapping='POLYINTERP_NEAREST',
                layers_select_src='ALL',
                layers_select_dst='NAME'
            )
            self.report({'INFO'}, f"Transferred weights from {source_obj.name}")
        except Exception as e:
            self.report({'ERROR'}, f"Transfer failed: {str(e)}")
            return {'CANCELLED'}
            
        return {'FINISHED'}


class LOL_OT_BindToNearestBone(Operator):
    """Rigidly bind selected vertices to nearest bone"""
    bl_idname = "lol.bind_nearest_bone"
    bl_label = "Bind Selected to Nearest"
    bl_description = "Find nearest bone for each selected vertex and assign 100% weight"
    bl_options = {'REGISTER', 'UNDO'}
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'MESH' and context.mode == 'EDIT_MESH'

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        armature = None
        
        for mod in obj.modifiers:
            if mod.type == 'ARMATURE' and mod.object:
                armature = mod.object
                break
        
        if not armature:
            self.report({'ERROR'}, "Object has no Armature modifier")
            return {'CANCELLED'}
            
        bm = bmesh.from_edit_mesh(mesh)
        selected_verts = [v for v in bm.verts if v.select]
        
        if not selected_verts:
            self.report({'WARNING'}, "No vertices selected")
            return {'CANCELLED'}
            
        mw_mesh = obj.matrix_world
        mw_arm = armature.matrix_world
        
        props = context.scene.lol_smart_weight
        if len(props.bone_list) > 0:
             enabled_names = {item.name for item in props.bone_list if item.enabled}
             source_bones = [b for b in armature.data.bones if b.name in enabled_names]
        else:
             source_bones = armature.data.bones
             
        if not source_bones:
             self.report({'ERROR'}, "No eligible bones found")
             return {'CANCELLED'}

        bones = []
        for bone in source_bones:
            head_world = mw_arm @ bone.head_local
            tail_world = mw_arm @ bone.tail_local
            bones.append((bone.name, head_world, tail_world))
            
        dvert_lay = bm.verts.layers.deform.verify()
        
        def get_group_index(name):
            vg = obj.vertex_groups.get(name)
            if not vg:
                vg = obj.vertex_groups.new(name=name)
            return vg.index

        count = 0
        
        for v in selected_verts:
            v_world = mw_mesh @ v.co
            
            best_bone_name = None
            min_dist = 999999.0
            
            for name, head, tail in bones:
                dist, _, _ = get_bone_segment_distance(v_world, head, tail)
                    
                if dist < min_dist:
                    min_dist = dist
                    best_bone_name = name
            
            if best_bone_name:
                dvert = v[dvert_lay]
                dvert.clear()
                gi = get_group_index(best_bone_name)
                dvert[gi] = 1.0
                count += 1
                
        bmesh.update_edit_mesh(mesh)
        self.report({'INFO'}, f"Bound {count} vertices to nearest bones")
        return {'FINISHED'}


class LOL_OT_AddShrinkBone(Operator):
    """Add bone to shrink list"""
    bl_idname = "lol.add_shrink_bone"
    bl_label = "Add"
    
    def execute(self, context):
        props = context.scene.lol_smart_weight
        bone_name = props.shrink_search_str
        if bone_name:
            exists = any(item.name == bone_name for item in props.shrink_bone_list)
            if not exists:
                item = props.shrink_bone_list.add()
                item.name = bone_name
                props.shrink_search_str = ""
        return {'FINISHED'}


class LOL_OT_RemoveShrinkBone(Operator):
    """Remove selected bone from shrink list"""
    bl_idname = "lol.remove_shrink_bone"
    bl_label = "Remove"
    
    def execute(self, context):
        props = context.scene.lol_smart_weight
        if props.active_shrink_index >= 0 and len(props.shrink_bone_list) > 0:
            props.shrink_bone_list.remove(props.active_shrink_index)
            props.active_shrink_index = max(0, props.active_shrink_index - 1)
        return {'FINISHED'}


class LOL_OT_PopulateShrinkList(Operator):
    """Auto-detect risky bones"""
    bl_idname = "lol.populate_shrink_list"
    bl_label = "Auto-Detect"
    
    @classmethod
    def poll(cls, context):
        return context.active_object and context.active_object.type == 'ARMATURE'
    
    def execute(self, context):
        props = context.scene.lol_smart_weight
        props.shrink_bone_list.clear()
        
        armature = context.active_object
        
        count = 0
        for bone in armature.data.bones:
            name_lower = bone.name.lower()
            if 'hand' in name_lower or 'buffbone' in name_lower:
                item = props.shrink_bone_list.add()
                item.name = bone.name
                count += 1
        self.report({'INFO'}, f"Added {count} risky bones")
        return {'FINISHED'}


class LOL_OT_WeightListAction(Operator):
    """Select/deselect items in the bone list"""
    bl_idname = "lol.weight_list_action"
    bl_label = "List Action"
    
    action: EnumProperty(
        items=[
            ('SELECT_ALL', "Select All", ""),
            ('DESELECT_ALL', "Deselect All", ""),
            ('SELECT_CORE', "Select Core", ""),
        ]
    )
    
    def execute(self, context):
        props = context.scene.lol_smart_weight
        for item in props.bone_list:
            if self.action == 'SELECT_ALL':
                item.enabled = True
            elif self.action == 'DESELECT_ALL':
                item.enabled = False
            elif self.action == 'SELECT_CORE':
                item.enabled = item.is_core
        return {'FINISHED'}


# =============================================================================
# UI Panel
# =============================================================================

class LOL_PT_SmartWeightPanel(Panel):
    bl_label = "Smart Weights"
    bl_idname = "VIEW3D_PT_lol_smart_weights"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Skin Tools'
    bl_options = {'DEFAULT_CLOSED'}  # Collapsed by default
    
    def draw_header(self, context):
        layout = self.layout
        from ..ui import icons
        layout.label(text="", icon_value=icons.get_icon("icon_54"))
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.lol_smart_weight
        
        # --- Weight Settings ---
        box = layout.box()
        box.label(text="Settings", icon='PREFERENCES')
        col = box.column(align=True)
        col.prop(props, "weight_falloff", text="Falloff")
        col.prop(props, "max_influences")
        col.prop(props, "smooth_weights")
        
        
        # --- Bone Selection ---
        box = layout.box()
        box.label(text="Bones to Weight", icon='GROUP_BONE')
        
        row = box.row()
        row.operator("lol.populate_weight_list", icon='FILE_REFRESH', text="Detect Bones")
        
        if len(props.bone_list) > 0:
            row = box.row()
            row.template_list("LOL_UL_WeightBoneList", "", props, "bone_list", props, "active_bone_index", rows=6)
            
            row = box.row(align=True)
            op = row.operator("lol.weight_list_action", text="All")
            op.action = 'SELECT_ALL'
            op = row.operator("lol.weight_list_action", text="None")
            op.action = 'DESELECT_ALL'
            op = row.operator("lol.weight_list_action", text="Core")
            op.action = 'SELECT_CORE'
        
        box.prop(props, "clear_unused_groups")
        box.prop(props, "clean_shape_keys")
        box.prop(props, "clean_mismatched_groups")
        
        layout.separator()
        
        # --- Apply Button ---
        row = layout.row()
        row.scale_y = 2.0
        row.operator("lol.apply_smart_weights", icon='MOD_ARMATURE')


# =============================================================================
# Registration
# =============================================================================

classes = [
    WeightBoneItem,
    ShrinkBoneItem,
    LOL_SmartWeightProperties,
    LOL_OT_PopulateWeightList,
    LOL_OT_ApplySmartWeights,
    LOL_OT_TransferWeights,
    LOL_OT_AddShrinkBone,
    LOL_OT_RemoveShrinkBone,
    LOL_OT_PopulateShrinkList,
    LOL_OT_BindToNearestBone,
    LOL_OT_DebugWeights,
    LOL_OT_WeightListAction,
    LOL_OT_DeleteShapeKeys,
    LOL_OT_ClearMismatchedGroups,
    LOL_OT_ClearAllVertexGroups,
    LOL_UL_WeightBoneList,
]

panel_classes = [
    LOL_PT_SmartWeightPanel
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    # Register panel by default (will be controlled by preferences)
    for cls in panel_classes:
        bpy.utils.register_class(cls)
    
    LOL_SmartWeightProperties.transfer_source = StringProperty(
        name="Source Mesh", 
        description="Mesh to transfer weights from"
    )
    
    bpy.types.Scene.lol_smart_weight = PointerProperty(type=LOL_SmartWeightProperties)

def unregister():
    # Unregister panel
    for cls in reversed(panel_classes):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.lol_smart_weight

def register_panel():
    """Register just the panel (for preference toggle)"""
    for cls in panel_classes:
        try:
            bpy.utils.register_class(cls)
        except:
            pass  # Already registered

def unregister_panel():
    """Unregister just the panel (for preference toggle)"""
    for cls in reversed(panel_classes):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass  # Already unregistered
