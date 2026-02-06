"""
Auto Skinning for Blender

Fixes non-manifold geometry on a duplicate mesh (merge doubles, fill holes,
recalculate normals), applies Blender's automatic weights to the fixed copy,
then transfers weights back to the original.
"""

import bpy
import bmesh
import time
from mathutils.kdtree import KDTree
from bpy.types import Operator, PropertyGroup
from bpy.props import (
    FloatProperty, IntProperty, BoolProperty,
    PointerProperty, StringProperty, EnumProperty,
)


# =============================================================================
# UTILITIES
# =============================================================================

def closest_point_on_segment(point, seg_start, seg_end):
    """Find the closest point on a line segment to a given point."""
    seg = seg_end - seg_start
    seg_len_sq = seg.dot(seg)
    if seg_len_sq < 0.00001:
        return seg_start.copy()
    t = max(0.0, min(1.0, (point - seg_start).dot(seg) / seg_len_sq))
    return seg_start + seg * t


def get_bone_segments(armature, bone_names, mesh_obj):
    """Get bone head/tail positions in mesh local space."""
    arm_mat = armature.matrix_world
    mesh_inv = mesh_obj.matrix_world.inverted()
    segments = {}
    for name in bone_names:
        bone = armature.data.bones.get(name)
        if bone:
            h = mesh_inv @ (arm_mat @ bone.head_local)
            t = mesh_inv @ (arm_mat @ bone.tail_local)
            segments[name] = (h, t)
    return segments


def count_weighted_verts(mesh_obj):
    """Count vertices that have at least one weight > 0.001."""
    return sum(
        1 for v in mesh_obj.data.vertices
        if any(g.weight > 0.001 for g in v.groups)
    )


# =============================================================================
# WEIGHT TRANSFER
# =============================================================================

def transfer_weights_kdtree(source_obj, target_obj, bone_names, max_influences=4):
    """Transfer weights from source to target using nearest-vertex KD-tree lookup."""
    src_mesh = source_obj.data
    src_verts = src_mesh.vertices
    num_src = len(src_verts)

    # Build KD-tree from source vertices (world space)
    kd = KDTree(num_src)
    src_world_mat = source_obj.matrix_world
    for i, v in enumerate(src_verts):
        kd.insert(src_world_mat @ v.co, i)
    kd.balance()

    # Pre-build weight cache: src_vert_idx -> {bone_name: weight}
    src_vg_index_to_name = {}
    for vg in source_obj.vertex_groups:
        if vg.name in bone_names:
            src_vg_index_to_name[vg.index] = vg.name

    print(f"[AutoSkin] Building weight cache for {num_src} source verts...")
    weight_cache = [None] * num_src
    for i, v in enumerate(src_verts):
        bone_weights = {}
        for g in v.groups:
            bone_name = src_vg_index_to_name.get(g.group)
            if bone_name and g.weight > 0.001:
                bone_weights[bone_name] = g.weight
        if bone_weights:
            weight_cache[i] = bone_weights

    # Ensure target has vertex groups
    for bone_name in bone_names:
        if bone_name not in target_obj.vertex_groups:
            target_obj.vertex_groups.new(name=bone_name)

    # Clear existing weights for these bones
    tgt_verts = target_obj.data.vertices
    num_tgt = len(tgt_verts)
    all_vert_indices = list(range(num_tgt))
    for bone_name in bone_names:
        vg = target_obj.vertex_groups.get(bone_name)
        if vg:
            vg.remove(all_vert_indices)

    # Transfer weights using nearest neighbor
    tgt_world_mat = target_obj.matrix_world
    print(f"[AutoSkin] Transferring to {num_tgt} target verts (KD-tree)...")

    for vi, vert in enumerate(tgt_verts):
        world_co = tgt_world_mat @ vert.co
        co, idx, dist = kd.find(world_co)

        if idx < 0:
            continue

        cached = weight_cache[idx]
        if not cached:
            continue

        # Limit influences
        if len(cached) > max_influences:
            sorted_bones = sorted(cached.items(), key=lambda x: x[1], reverse=True)
            bone_weight_sum = dict(sorted_bones[:max_influences])
        else:
            bone_weight_sum = cached

        # Normalize and apply
        total_w = sum(bone_weight_sum.values())
        if total_w < 0.00001:
            continue

        for bone_name, weight in bone_weight_sum.items():
            normalized_w = weight / total_w
            if normalized_w > 0.001:
                vg = target_obj.vertex_groups.get(bone_name)
                if vg:
                    vg.add([vi], normalized_w, 'REPLACE')

        if vi > 0 and vi % 5000 == 0:
            print(f"[AutoSkin] Transfer progress: {vi}/{num_tgt}")


def transfer_weights_data_transfer(context, source_obj, target_obj, bone_names):
    """Transfer weights using Blender's data transfer with face interpolation."""
    # Clear existing bone weights on target
    for bone_name in bone_names:
        vg = target_obj.vertex_groups.get(bone_name)
        if vg:
            target_obj.vertex_groups.remove(vg)

    # Use Blender's data transfer: source (selected) -> target (active)
    bpy.ops.object.select_all(action='DESELECT')
    source_obj.select_set(True)
    target_obj.select_set(True)
    context.view_layer.objects.active = target_obj
    bpy.ops.object.data_transfer(
        data_type='VGROUP_WEIGHTS',
        vert_mapping='POLYINTERP_NEAREST',
        layers_select_src='ALL',
        layers_select_dst='NAME',
        mix_mode='REPLACE',
        mix_factor=1.0,
    )
    print(f"[AutoSkin] Transfer complete (face-interpolated): {len(target_obj.vertex_groups)} groups")


# =============================================================================
# POST-PROCESSING
# =============================================================================

def smooth_weights(mesh_obj, iterations=2, factor=0.5):
    """Laplacian smoothing on all vertex group weights."""
    if iterations <= 0:
        return

    mesh = mesh_obj.data
    num_verts = len(mesh.vertices)

    # Build adjacency from edges
    adjacency = [[] for _ in range(num_verts)]
    for edge in mesh.edges:
        adjacency[edge.vertices[0]].append(edge.vertices[1])
        adjacency[edge.vertices[1]].append(edge.vertices[0])

    for _iteration in range(iterations):
        for vg in mesh_obj.vertex_groups:
            vg_idx = vg.index

            weights = {}
            for vi, vert in enumerate(mesh.vertices):
                for g in vert.groups:
                    if g.group == vg_idx:
                        weights[vi] = g.weight
                        break

            if not weights:
                continue

            new_weights = {}
            for vi, w in weights.items():
                neighbors = adjacency[vi]
                if not neighbors:
                    new_weights[vi] = w
                    continue

                neighbor_avg = 0.0
                neighbor_count = 0
                for ni in neighbors:
                    if ni in weights:
                        neighbor_avg += weights[ni]
                        neighbor_count += 1

                if neighbor_count > 0:
                    neighbor_avg /= neighbor_count
                    new_weights[vi] = w * (1.0 - factor) + neighbor_avg * factor
                else:
                    new_weights[vi] = w

            for vi, w in new_weights.items():
                if w > 0.001:
                    vg.add([vi], w, 'REPLACE')
                else:
                    vg.remove([vi])


def apply_sharpness(mesh_obj, bone_names, power):
    """Adjust weight contrast. power>1 = sharper, power<1 = softer, 1.0 = no change."""
    if abs(power - 1.0) < 0.01:
        return

    bone_name_set = set(bone_names)
    mesh = mesh_obj.data
    vg_idx_to_name = {}
    for vg in mesh_obj.vertex_groups:
        if vg.name in bone_name_set:
            vg_idx_to_name[vg.index] = vg.name

    for vert in mesh.vertices:
        weights = {}
        for g in vert.groups:
            name = vg_idx_to_name.get(g.group)
            if name and g.weight > 0.0:
                weights[name] = g.weight ** power

        if not weights:
            continue

        total = sum(weights.values())
        if total < 1e-10:
            continue

        for name, w in weights.items():
            vg = mesh_obj.vertex_groups.get(name)
            if vg:
                vg.add([vert.index], w / total, 'REPLACE')


# =============================================================================
# PROPERTY GROUP
# =============================================================================

class LOL_GeodesicVoxelProperties(PropertyGroup):
    """Properties for auto skinning"""

    skinning_method: EnumProperty(
        name="Skinning",
        description="Deformation method used by the armature modifier",
        items=[
            ('LINEAR', "Linear",
             "Classic linear blend skinning (may collapse at twists)"),
            ('DUAL_QUATERNION', "Dual Quaternion",
             "Volume-preserving skinning (reduces candy wrapper effect)"),
        ],
        default='LINEAR'
    )

    face_interpolation: BoolProperty(
        name="Face Interpolation",
        description="Use Blender's face-interpolated transfer (smoother but experimental). "
                    "Off = nearest-vertex KD-tree (proven reliable)",
        default=False
    )

    sharpness: FloatProperty(
        name="Sharpness",
        description="Weight contrast. 1.0 = Blender default, higher = weights "
                    "concentrated on dominant bone, lower = more spread",
        default=1.0,
        min=0.25,
        max=4.0,
        step=10,
    )

    falloff: FloatProperty(
        name="Fallback Falloff",
        description="For vertices the heat map missed: controls how fast "
                    "distance-based influence drops off. Higher = tighter to nearest bone",
        default=2.0,
        min=0.5,
        max=6.0,
        step=10,
    )

    merge_distance: FloatProperty(
        name="Merge Distance",
        description="Distance threshold for merging duplicate vertices on proxy mesh",
        default=0.0001,
        min=0.00001,
        max=0.01,
        precision=5
    )

    max_influences: IntProperty(
        name="Max Influences",
        description="Maximum bones per vertex",
        default=4,
        min=1,
        max=8
    )

    smooth_iterations: IntProperty(
        name="Smooth Passes",
        description="Laplacian smoothing iterations after weight transfer",
        default=2,
        min=0,
        max=10
    )

    smooth_factor: FloatProperty(
        name="Smooth Factor",
        description="Smoothing strength per iteration",
        default=0.5,
        min=0.0,
        max=1.0
    )



# =============================================================================
# MAIN OPERATOR
# =============================================================================

class LOL_OT_GeodesicVoxelSkinning(Operator):
    """Apply automatic weights via manifold-fixed proxy"""
    bl_idname = "lol.geodesic_voxel_skinning"
    bl_label = "Auto Skin"
    bl_description = "Fix non-manifold geometry on copy, apply auto weights, transfer to original"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if not context.active_object or context.active_object.type != 'ARMATURE':
            return False
        return any(obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        props = context.scene.lol_geodesic_voxel
        smart_props = context.scene.lol_smart_weight

        armature = context.active_object
        meshes = [obj for obj in context.selected_objects if obj.type == 'MESH']

        if not meshes:
            self.report({'ERROR'}, "No mesh selected")
            return {'CANCELLED'}

        mesh_obj = meshes[0]

        # Get enabled bones from bone list
        if len(smart_props.bone_list) == 0:
            bpy.ops.lol.populate_weight_list()

        enabled_bones = {item.name for item in smart_props.bone_list if item.enabled}

        if not enabled_bones:
            self.report({'ERROR'}, "No bones enabled for weighting. Use 'Detect Bones' first.")
            return {'CANCELLED'}

        total_bones = len(armature.data.bones)
        print(f"[AutoSkin] Falloff: {props.falloff} | Skinning: {props.skinning_method}")
        print(f"[AutoSkin] Processing {len(enabled_bones)} of {total_bones} bones")

        t_start = time.time()

        try:
            result = self._run_skinning(
                context, mesh_obj, armature, enabled_bones, props
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.report({'ERROR'}, f"Auto skinning failed: {e}")
            return {'CANCELLED'}

        t_elapsed = time.time() - t_start
        self.report({'INFO'}, f"Auto skinning complete: {result} vertices weighted in {t_elapsed:.1f}s")
        return {'FINISHED'}

    def _setup_armature(self, mesh_obj, armature, props):
        """Ensure armature modifier with correct skinning method, and parenting."""
        arm_mod = None
        for m in mesh_obj.modifiers:
            if m.type == 'ARMATURE' and m.object == armature:
                arm_mod = m
                break

        if not arm_mod:
            arm_mod = mesh_obj.modifiers.new(name='Armature', type='ARMATURE')
            arm_mod.object = armature

        arm_mod.use_deform_preserve_volume = (
            props.skinning_method == 'DUAL_QUATERNION'
        )

        if mesh_obj.parent != armature:
            mesh_obj.parent = armature
            mesh_obj.matrix_parent_inverse = armature.matrix_world.inverted()

    def _run_skinning(self, context, mesh_obj, armature, enabled_bones, props):
        """Run heat map skinning with post-processing."""
        num = self._run_heat_map(
            context, mesh_obj, armature, enabled_bones, props
        )

        # Post-processing
        bpy.ops.object.select_all(action='DESELECT')
        mesh_obj.select_set(True)
        context.view_layer.objects.active = mesh_obj

        # Apply sharpness (before smooth/normalize so pipeline flows correctly)
        if abs(props.sharpness - 1.0) > 0.01:
            print(f"[AutoSkin] Applying sharpness: {props.sharpness}")
            apply_sharpness(mesh_obj, list(enabled_bones), props.sharpness)

        # Limit bone influences per vertex
        print(f"[AutoSkin] Limiting to {props.max_influences} influences per vertex...")
        bpy.ops.object.vertex_group_limit_total(
            group_select_mode='ALL', limit=props.max_influences
        )

        # Smooth weights
        if props.smooth_iterations > 0:
            print(f"[AutoSkin] Smoothing weights ({props.smooth_iterations} passes)...")
            smooth_weights(
                mesh_obj,
                iterations=props.smooth_iterations,
                factor=props.smooth_factor,
            )

        # Normalize all weights to sum to 1.0 per vertex
        print("[AutoSkin] Normalizing weights...")
        bpy.ops.object.vertex_group_normalize_all(lock_active=False)

        # Clean tiny weights but keep at least one group per vertex
        bpy.ops.object.vertex_group_clean(
            group_select_mode='ALL', limit=0.01, keep_single=True
        )

        self._setup_armature(mesh_obj, armature, props)

        # Restore selection
        bpy.ops.object.select_all(action='DESELECT')
        mesh_obj.select_set(True)
        armature.select_set(True)
        context.view_layer.objects.active = armature

        num = count_weighted_verts(mesh_obj)
        print(f"[AutoSkin] Done: {num} vertices weighted")
        return num

    def _run_heat_map(self, context, mesh_obj, armature, enabled_bones, props):
        """Heat Map mode: duplicate, bmesh fix, Blender auto weights, transfer."""
        proxy_obj = None
        bone_names = list(enabled_bones)

        # Save bone deform states and disable non-selected bones
        print("[AutoSkin] Disabling non-selected bones for auto weights...")
        original_deform = {}
        for bone in armature.data.bones:
            original_deform[bone.name] = bone.use_deform
            if bone.name not in enabled_bones:
                bone.use_deform = False

        try:
            # Duplicate the mesh
            print("[AutoSkin] Duplicating mesh...")
            bpy.ops.object.select_all(action='DESELECT')
            mesh_obj.select_set(True)
            context.view_layer.objects.active = mesh_obj
            bpy.ops.object.duplicate()
            proxy_obj = context.active_object
            proxy_obj.name = mesh_obj.name + "_autoskin_proxy"

            proxy_vert_count = len(proxy_obj.data.vertices)
            print(f"[AutoSkin] Proxy mesh: {proxy_vert_count} verts")

            # Comprehensive manifold fix with bmesh
            print("[AutoSkin] Making proxy manifold...")
            bm = bmesh.new()
            bm.from_mesh(proxy_obj.data)

            # --- Phase 1: Merge duplicate vertices ---
            merge_dist = props.merge_distance
            verts_before = len(bm.verts)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_dist)
            merged = verts_before - len(bm.verts)
            if merged:
                print(f"[AutoSkin]   Merged {merged} duplicate verts")

            # --- Phase 2: Remove degenerate faces (zero/near-zero area) ---
            bm.faces.ensure_lookup_table()
            degen_faces = [f for f in bm.faces if f.calc_area() < 0.000001]
            if degen_faces:
                bmesh.ops.delete(bm, geom=degen_faces, context='FACES')
                print(f"[AutoSkin]   Removed {len(degen_faces)} degenerate faces")

            # --- Phase 3: Remove loose geometry ---
            bm.verts.ensure_lookup_table()
            loose_verts = [v for v in bm.verts if not v.link_faces]
            if loose_verts:
                bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')
                print(f"[AutoSkin]   Removed {len(loose_verts)} loose verts")

            bm.edges.ensure_lookup_table()
            loose_edges = [e for e in bm.edges if not e.link_faces]
            if loose_edges:
                bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')
                print(f"[AutoSkin]   Removed {len(loose_edges)} loose edges")

            # --- Phase 4: Fix non-manifold edges (3+ faces sharing one edge) ---
            bm.edges.ensure_lookup_table()
            faces_to_remove = set()
            for e in bm.edges:
                if len(e.link_faces) > 2:
                    linked = sorted(e.link_faces, key=lambda f: f.calc_area(), reverse=True)
                    for f in linked[2:]:
                        faces_to_remove.add(f)
            if faces_to_remove:
                bmesh.ops.delete(bm, geom=list(faces_to_remove), context='FACES')
                print(f"[AutoSkin]   Removed {len(faces_to_remove)} overlapping faces")

            # --- Phase 5: Fill boundary holes (multiple strategies) ---
            bm.edges.ensure_lookup_table()
            boundary_edges = [e for e in bm.edges if e.is_boundary]
            if boundary_edges:
                print(f"[AutoSkin]   Found {len(boundary_edges)} boundary edges, filling holes...")
                faces_before = len(bm.faces)

                try:
                    bmesh.ops.holes_fill(bm, edges=boundary_edges, sides=0)
                except:
                    pass

                bm.edges.ensure_lookup_table()
                remaining = {e for e in bm.edges if e.is_boundary}
                while remaining:
                    start_edge = next(iter(remaining))
                    remaining.discard(start_edge)
                    loop_verts = [start_edge.verts[0]]
                    current_vert = start_edge.verts[1]

                    while current_vert != loop_verts[0]:
                        loop_verts.append(current_vert)
                        next_edge = None
                        for linked_e in current_vert.link_edges:
                            if linked_e in remaining and linked_e.is_boundary:
                                next_edge = linked_e
                                break
                        if next_edge is None:
                            break
                        remaining.discard(next_edge)
                        current_vert = next_edge.other_vert(current_vert)

                    if len(loop_verts) >= 3:
                        try:
                            bmesh.ops.contextual_create(bm, geom=loop_verts)
                        except:
                            pass

                filled = len(bm.faces) - faces_before
                if filled:
                    print(f"[AutoSkin]   Filled {filled} holes")

            # --- Phase 6: Triangulate non-tri faces ---
            bm.faces.ensure_lookup_table()
            ngons = [f for f in bm.faces if len(f.verts) > 3]
            if ngons:
                bmesh.ops.triangulate(bm, faces=ngons)
                print(f"[AutoSkin]   Triangulated {len(ngons)} ngons")

            # --- Phase 7: Recalculate normals ---
            bm.faces.ensure_lookup_table()
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

            # --- Phase 8: Final doubles pass ---
            bm.verts.ensure_lookup_table()
            v_before = len(bm.verts)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_dist)
            extra = v_before - len(bm.verts)
            if extra:
                print(f"[AutoSkin]   Cleaned {extra} doubles from hole fill")

            bm.to_mesh(proxy_obj.data)
            bm.free()
            proxy_obj.data.update()

            final_vert_count = len(proxy_obj.data.vertices)
            print(f"[AutoSkin] Fixed proxy: {final_vert_count} verts (was {proxy_vert_count})")

            # Apply Blender automatic weights to proxy
            print("[AutoSkin] Applying automatic weights to proxy (Blender heat map)...")
            bpy.ops.object.select_all(action='DESELECT')
            proxy_obj.select_set(True)
            armature.select_set(True)
            context.view_layer.objects.active = armature
            bpy.ops.object.parent_set(type='ARMATURE_AUTO')

            proxy_bone_groups = {vg.name for vg in proxy_obj.vertex_groups}
            active_bones = proxy_bone_groups & enabled_bones
            if not active_bones:
                raise RuntimeError(
                    "Automatic weights failed - no bone vertex groups created on proxy"
                )

            print(f"[AutoSkin] Auto weights created for {len(active_bones)} bones")

            # Transfer weights from proxy to original
            if props.face_interpolation:
                print("[AutoSkin] Transferring weights (face-interpolated)...")
                transfer_weights_data_transfer(
                    context, proxy_obj, mesh_obj, list(active_bones)
                )
            else:
                print("[AutoSkin] Transferring weights (nearest vertex)...")
                transfer_weights_kdtree(
                    proxy_obj, mesh_obj, list(active_bones),
                    max_influences=props.max_influences
                )

            # Fallback: fill unweighted verts with closest-bone distance weights
            # Check BEFORE falloff so small heat weights aren't mistaken as unweighted
            unweighted = [
                vi for vi, v in enumerate(mesh_obj.data.vertices)
                if not any(g.weight > 0.001 for g in v.groups)
            ]
            if unweighted:
                print(f"[AutoSkin] {len(unweighted)} verts unweighted, applying distance fallback...")
                bone_segs = get_bone_segments(armature, list(active_bones), mesh_obj)
                verts = mesh_obj.data.vertices
                for vi in unweighted:
                    bone_dists = {}
                    for name, (h, t) in bone_segs.items():
                        closest = closest_point_on_segment(verts[vi].co, h, t)
                        bone_dists[name] = (verts[vi].co - closest).length

                    inv_w = {
                        n: 1.0 / (d ** props.falloff + 0.0001)
                        for n, d in bone_dists.items()
                    }
                    sorted_w = sorted(
                        inv_w.items(), key=lambda x: x[1], reverse=True
                    )[:props.max_influences]
                    total = sum(w for _, w in sorted_w)
                    if total < 0.00001:
                        continue
                    for name, w in sorted_w:
                        nw = w / total
                        if nw > 0.001:
                            vg = mesh_obj.vertex_groups.get(name)
                            if vg:
                                vg.add([vi], nw, 'REPLACE')

            # Falloff only controls distance fallback above; heat map weights are left as-is

            return count_weighted_verts(mesh_obj)

        finally:
            # Restore bone deform states
            print("[AutoSkin] Restoring bone deform states...")
            for bone in armature.data.bones:
                if bone.name in original_deform:
                    bone.use_deform = original_deform[bone.name]

            # Clean up proxy mesh
            if proxy_obj is not None and proxy_obj.name in bpy.data.objects:
                print("[AutoSkin] Cleaning up proxy mesh...")
                proxy_data = proxy_obj.data
                bpy.data.objects.remove(proxy_obj, do_unlink=True)
                if proxy_data and proxy_data.users == 0:
                    bpy.data.meshes.remove(proxy_data)


# =============================================================================
# UI PANEL SECTION
# =============================================================================

def draw_geodesic_panel(layout, context):
    """Draw the auto skinning UI section."""
    props = context.scene.lol_geodesic_voxel

    box = layout.box()

    # Header
    header = box.row()
    header.label(text="Auto Skinning", icon='MOD_ARMATURE')

    # Show bone count from the smart weight bone list
    smart_props = context.scene.lol_smart_weight
    if len(smart_props.bone_list) > 0:
        enabled_count = sum(1 for item in smart_props.bone_list if item.enabled)
        total_count = len(smart_props.bone_list)
        box.label(text=f"Will process: {enabled_count} of {total_count} bones", icon='BONE_DATA')
    else:
        box.label(text="Click 'Detect Bones' above first!", icon='ERROR')

    # Settings
    col = box.column(align=True)
    col.prop(props, "skinning_method")
    col.prop(props, "sharpness")
    col.prop(props, "max_influences")
    col.prop(props, "falloff")
    col.prop(props, "merge_distance")
    col.prop(props, "face_interpolation")

    col.separator()
    col.prop(props, "smooth_iterations")
    if props.smooth_iterations > 0:
        col.prop(props, "smooth_factor")

    # Apply button
    col.separator()
    row = box.row()
    row.scale_y = 1.5
    row.operator("lol.geodesic_voxel_skinning", icon='BONE_DATA')


# =============================================================================
# REGISTRATION
# =============================================================================

classes = [
    LOL_GeodesicVoxelProperties,
    LOL_OT_GeodesicVoxelSkinning,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.lol_geodesic_voxel = PointerProperty(type=LOL_GeodesicVoxelProperties)


def unregister():
    del bpy.types.Scene.lol_geodesic_voxel

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
