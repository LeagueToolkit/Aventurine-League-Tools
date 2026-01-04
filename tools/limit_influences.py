"""
Limit to 4 Influences Operator
Limits vertex weights to maximum 4 bone influences per vertex (League of Legends requirement)
"""

import bpy
from bpy.types import Operator
from bpy.props import FloatProperty


class LOLLeagueLimitInfluences_V4(Operator):
    """Limit vertex weights to maximum 4 bone influences per vertex"""
    bl_idname = "lol_league_v4.limit_influences"
    bl_label = "Limit to 4 Influences"
    bl_description = "Limit all vertices to maximum 4 bone influences (required for LoL export)"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        obj = context.active_object
        
        if not obj or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}
        
        mesh = obj.data
        
        # Check if mesh has vertex groups
        if not obj.vertex_groups:
            self.report({'WARNING'}, "Mesh has no vertex groups")
            return {'CANCELLED'}
        
        # Collect all modifications first (safer than modifying while iterating)
        modifications = []  # List of (vertex_index, [(group_idx, normalized_weight), ...])
        
        # Process each vertex
        for vertex in mesh.vertices:
            # Get all weights for this vertex
            vertex_weights = []
            for group in vertex.groups:
                if group.weight > 0.001:  # Only consider significant weights
                    vertex_weights.append((group.group, group.weight))
            
            # If vertex has more than 4 influences, plan the fix
            if len(vertex_weights) > 4:
                # Sort by weight (descending)
                vertex_weights.sort(key=lambda x: x[1], reverse=True)
                
                # Keep only top 4
                top_4 = vertex_weights[:4]
                
                # Calculate sum of top 4 weights for normalization
                weight_sum = sum(w for _, w in top_4)
                
                if weight_sum > 0.001:
                    # Store the groups to remove and the normalized weights to add
                    all_groups = [g for g, _ in vertex_weights]
                    normalized = [(g, w / weight_sum) for g, w in top_4]
                    modifications.append((vertex.index, all_groups, normalized))
        
        # Now apply all modifications
        for vertex_idx, groups_to_remove, normalized_weights in modifications:
            # Remove from all groups
            for group_idx in groups_to_remove:
                obj.vertex_groups[group_idx].remove([vertex_idx])
            
            # Re-add with normalized weights
            for group_idx, weight in normalized_weights:
                obj.vertex_groups[group_idx].add([vertex_idx], weight, 'REPLACE')
        
        vertices_fixed = len(modifications)
        
        if vertices_fixed == 0:
            self.report({'INFO'}, "All vertices already have 4 or fewer influences")
        else:
            self.report({'INFO'}, f"Limited {vertices_fixed} vertices to 4 influences")
        
        return {'FINISHED'}
    
    @classmethod
    def poll(cls, context):
        return (context.active_object and 
                context.active_object.type == 'MESH' and
                context.active_object.vertex_groups)
