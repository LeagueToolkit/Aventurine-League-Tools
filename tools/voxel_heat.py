"""
Smart Distance Skinning - Maya-Style Algorithm
===============================================

Pure distance-based automatic weighting inspired by Maya's 
"Closest Distance + Classic Linear" bind method.

Features:
- All bones compete equally on pure distance
- Closest bone to each vertex naturally wins
- Smooth falloff with adjustable sharpness
- Configurable max bone influences per vertex
- Optional weight smoothing

Author: Aventurine Team
License: Same as Aventurine addon
"""

import bpy
import numpy as np
from mathutils import Vector
from mathutils.geometry import intersect_point_line
import time


def get_bone_distance(point, bone_head, bone_tail):
    """Get shortest Euclidean distance from point to bone segment."""
    closest_point, t = intersect_point_line(point, bone_head, bone_tail)
    
    # Clamp to bone segment
    if t < 0.0:
        closest_point = bone_head
        t = 0.0
    elif t > 1.0:
        closest_point = bone_tail
        t = 1.0
    
    distance = (point - closest_point).length
    return distance, closest_point, t


def compute_smart_weights(mesh_obj, armature, enabled_bones, 
                          max_influences=4, 
                          falloff_power=2.0,
                          relative_threshold=2.5):
    """
    Maya-style pure distance weighting.
    
    NO bone length factor - all bones compete equally on pure distance.
    The closest bone to a vertex naturally wins.
    
    Args:
        mesh_obj: Mesh object
        armature: Armature object
        enabled_bones: Set of bone names
        max_influences: Maximum bones per vertex
        falloff_power: How sharply weights drop off (higher = sharper)
        relative_threshold: Only consider bones within this multiple of closest distance
    
    Returns:
        dict: vertex_index -> [(bone_name, weight), ...]
    """
    mesh = mesh_obj.data
    matrix = mesh_obj.matrix_world
    arm_matrix = armature.matrix_world
    
    # Collect bone data
    bones_data = []
    
    for bone in armature.data.bones:
        if bone.name not in enabled_bones:
            continue
        
        head_world = arm_matrix @ bone.head_local
        tail_world = arm_matrix @ bone.tail_local
        
        bones_data.append({
            'name': bone.name,
            'head': head_world,
            'tail': tail_world,
        })
    
    if not bones_data:
        print("  No bones to weight!")
        return {}
    
    print(f"  Maya-style pure distance for {len(bones_data)} bones...")
    
    vertex_weights = {}
    
    # For each vertex
    for vert in mesh.vertices:
        vert_world = matrix @ vert.co
        
        # Calculate distance to ALL bones
        bone_distances = []
        for bone_data in bones_data:
            dist, _, _ = get_bone_distance(
                vert_world, 
                bone_data['head'], 
                bone_data['tail']
            )
            bone_distances.append((bone_data['name'], dist))
        
        # Sort by distance (closest first)
        bone_distances.sort(key=lambda x: x[1])
        closest_distance = bone_distances[0][1]
        
        # Avoid division by zero
        if closest_distance < 0.0001:
            closest_distance = 0.0001
        
        # Calculate weight for each bone
        # Maya style: pure inverse distance, no length factors
        bone_weights = []
        
        for bone_name, dist in bone_distances:
            relative_dist = dist / closest_distance
            
            # Only consider bones within threshold of closest
            if relative_dist > relative_threshold:
                continue
            
            # Pure distance-based weight
            # relative_dist = 1.0 → full weight
            # relative_dist = 2.0 → reduced weight
            weight = 1.0 / (relative_dist ** falloff_power)
            
            if weight > 0.001:
                bone_weights.append((bone_name, weight))
        
        if not bone_weights:
            continue
        
        # Take top N influences
        bone_weights.sort(key=lambda x: x[1], reverse=True)
        bone_weights = bone_weights[:max_influences]
        
        # Normalize to sum to 1.0
        total_weight = sum(w for _, w in bone_weights)
        if total_weight > 0:
            normalized = [(name, w / total_weight) for name, w in bone_weights]
            vertex_weights[vert.index] = normalized
    
    return vertex_weights


def smooth_weights(mesh_obj, vertex_weights, iterations=2, strength=0.3, max_influences=4):
    """
    Smooth weights using vertex connectivity.
    Helps blend transitions between bone influences.
    """
    if iterations == 0:
        return vertex_weights
    
    mesh = mesh_obj.data
    
    # Build adjacency
    adjacency = {i: set() for i in range(len(mesh.vertices))}
    for edge in mesh.edges:
        v1, v2 = edge.vertices
        adjacency[v1].add(v2)
        adjacency[v2].add(v1)
    
    for iteration in range(iterations):
        new_weights = {}
        
        # Get all bone names
        all_bones = set()
        for weights in vertex_weights.values():
            for bone_name, _ in weights:
                all_bones.add(bone_name)
        
        if not all_bones:
            return vertex_weights
        
        # Build bone->vertex weight map
        bone_vertex_weights = {bone: {} for bone in all_bones}
        for vert_idx, weights in vertex_weights.items():
            for bone_name, weight in weights:
                bone_vertex_weights[bone_name][vert_idx] = weight
        
        # Smooth each bone's weights
        smoothed_bone_weights = {bone: {} for bone in all_bones}
        
        for bone_name in all_bones:
            weights = bone_vertex_weights[bone_name]
            
            for vert_idx in range(len(mesh.vertices)):
                current_weight = weights.get(vert_idx, 0.0)
                
                neighbors = adjacency.get(vert_idx, set())
                if not neighbors:
                    smoothed_bone_weights[bone_name][vert_idx] = current_weight
                    continue
                
                neighbor_sum = sum(weights.get(n, 0.0) for n in neighbors)
                neighbor_avg = neighbor_sum / len(neighbors) if neighbors else 0.0
                
                smoothed = current_weight * (1.0 - strength) + neighbor_avg * strength
                smoothed_bone_weights[bone_name][vert_idx] = smoothed
        
        # Rebuild vertex_weights and re-normalize
        for vert_idx in range(len(mesh.vertices)):
            bone_weights = []
            
            for bone_name in all_bones:
                weight = smoothed_bone_weights[bone_name].get(vert_idx, 0.0)
                if weight > 0.001:
                    bone_weights.append((bone_name, weight))
            
            if bone_weights:
                bone_weights.sort(key=lambda x: x[1], reverse=True)
                bone_weights = bone_weights[:max_influences]
                
                total = sum(w for _, w in bone_weights)
                if total > 0:
                    bone_weights = [(name, w / total) for name, w in bone_weights]
                    new_weights[vert_idx] = bone_weights
        
        vertex_weights = new_weights
    
    return vertex_weights


def apply_weights_to_mesh(mesh_obj, armature, vertex_weights, enabled_bones):
    """Apply computed weights to mesh vertex groups."""
    # Clear existing vertex groups for enabled bones
    for bone_name in enabled_bones:
        if bone_name in mesh_obj.vertex_groups:
            mesh_obj.vertex_groups.remove(mesh_obj.vertex_groups[bone_name])
        mesh_obj.vertex_groups.new(name=bone_name)
    
    # Apply weights
    for vert_idx, weights in vertex_weights.items():
        for bone_name, weight in weights:
            if bone_name in mesh_obj.vertex_groups:
                mesh_obj.vertex_groups[bone_name].add([vert_idx], weight, 'REPLACE')
    
    # Setup armature modifier
    arm_mod = None
    for mod in mesh_obj.modifiers:
        if mod.type == 'ARMATURE':
            arm_mod = mod
            break
    
    if arm_mod is None:
        arm_mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
    
    arm_mod.object = armature
    arm_mod.use_vertex_groups = True
    
    # Parent mesh to armature
    mesh_obj.parent = armature
    mesh_obj.matrix_parent_inverse = armature.matrix_world.inverted()


def voxel_heat_diffuse_skinning(context, mesh_obj, armature, enabled_bones,
                                 resolution=64, iterations=10, falloff=0.7,
                                 max_influences=4):
    """
    Main entry point for smart distance skinning.
    
    Parameters (mapped from UI):
    - resolution: Not used (kept for UI compatibility)
    - iterations: Smoothing passes (0-10)
    - falloff: Controls falloff power (0.5 -> power 1.0, 0.9 -> power 3.0)
    - max_influences: Max bones per vertex
    """
    print("Starting Smart Distance Skinning...")
    start_time = time.time()
    
    # Set armature to REST pose
    original_pose = armature.data.pose_position
    armature.data.pose_position = 'REST'
    
    try:
        # Ensure mesh data is up to date
        mesh_obj.data.update()
        
        # Map falloff UI parameter to algorithm parameters
        # Lower falloff = softer transitions, higher = sharper
        falloff_power = 1.0 + (falloff * 3.0)  # Range: 1.0 to 3.7
        
        print(f"  Falloff power: {falloff_power:.2f}")
        print(f"  Max influences: {max_influences}")
        
        # Compute weights
        vertex_weights = compute_smart_weights(
            mesh_obj, armature, enabled_bones,
            max_influences=max_influences,
            falloff_power=falloff_power,
            relative_threshold=3.0
        )
        
        if not vertex_weights:
            print("  No weights computed!")
            return False
        
        print(f"  Computed weights for {len(vertex_weights)} vertices")
        
        # Smoothing
        smooth_iterations = max(0, iterations // 3)  # 0-3 passes based on UI iterations
        if smooth_iterations > 0:
            print(f"  Smoothing weights ({smooth_iterations} passes)...")
            vertex_weights = smooth_weights(
                mesh_obj, vertex_weights,
                iterations=smooth_iterations,
                strength=0.4,
                max_influences=max_influences
            )
        
        # Apply weights
        apply_weights_to_mesh(mesh_obj, armature, vertex_weights, enabled_bones)
        
        elapsed = time.time() - start_time
        print(f"Smart Distance Skinning completed in {elapsed:.2f} seconds")
        
        return True
        
    except Exception as e:
        print(f"Smart Distance Skinning failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Restore pose position
        armature.data.pose_position = original_pose