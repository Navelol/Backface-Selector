bl_info = {
    "name":        "Select Orientation with Z-Depth",
    "author":      "Evan Pierce",
    "version":     (2, 1),
    "blender":     (2, 91, 0),
    "location":    "3D View > Select (N-Panel)",
    "description": "Select front/back facing geometry relative to viewport, with occlusion, X-Ray, and loose-part support",
    "warning":     "",
    "category":    "Mesh",
}

import bpy
import bmesh
from mathutils import Vector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_view_origin_and_direction(rv3d):
    """
    Return (view_origin, is_ortho).

    PERSP/CAMERA : origin is the real camera position in world space.
    ORTHO        : origin is pushed far back along the view axis so all
                   rays are effectively parallel (simulates infinity).
    """
    view_mat_inv = rv3d.view_matrix.inverted()
    is_ortho = (rv3d.view_perspective == 'ORTHO')

    if is_ortho:
        view_dir = view_mat_inv.to_3x3() @ Vector((0.0, 0.0, -1.0))
        view_dir.normalize()
        view_center = view_mat_inv.translation
        view_origin = view_center - view_dir * 1e7
    else:
        view_origin = view_mat_inv.translation

    return view_origin, is_ortho


def get_correct_normal_matrix(mat_world):
    """
    Inverse-transpose of the world matrix — the mathematically correct way
    to transform normals, handles non-uniform scale properly.
    """
    return mat_world.inverted().transposed().to_3x3()


def is_face_visible_via_raycast(scene, depsgraph, view_origin,
                                 face_center_world, obj_eval, poly_index):
    """
    Returns True if the face at poly_index is the first thing hit by a ray
    from view_origin, or if nothing is hit at all.
    """
    direction_vec = face_center_world - view_origin
    distance = direction_vec.length
    if distance < 1e-6:
        return True

    direction = direction_vec.normalized()
    hit_distance = distance * 0.9999  # stop just before the face center

    hit, _loc, _normal, face_idx, obj_hit, _ = scene.ray_cast(
        depsgraph,
        view_origin,
        direction,
        distance=hit_distance
    )

    if not hit:
        return True  # nothing in the way

    return obj_hit == obj_eval and face_idx == poly_index


def flood_fill_islands(bm, seed_face_indices):
    """
    Given a set of seed face indices, expand each seed outward via shared
    edges (connected-component / flood-fill) and return the full set of
    face indices that belong to any island containing at least one seed.

    This replicates what Blender's 'L' (select linked) does.
    """
    # Build face -> neighbouring faces adjacency list
    face_neighbours = [[] for _ in range(len(bm.faces))]
    for e in bm.edges:
        linked = e.link_faces
        if len(linked) == 2:
            a, b = linked[0].index, linked[1].index
            face_neighbours[a].append(b)
            face_neighbours[b].append(a)

    visited = set()
    result = set()

    for seed in seed_face_indices:
        if seed in visited:
            continue
        # BFS from this seed
        queue = [seed]
        island = set()
        while queue:
            fi = queue.pop()
            if fi in visited:
                continue
            visited.add(fi)
            island.add(fi)
            queue.extend(face_neighbours[fi])
        result |= island

    return result


# ---------------------------------------------------------------------------
# Shared core logic (used by both operators)
# ---------------------------------------------------------------------------

def run_orientation_selection(context, select_backfaces, xray, loose_parts):
    """
    Performs the full orientation + occlusion (+ optional island expand) pass
    and writes the selection back to the mesh.

    Returns (report_string, error_string). error_string is None on success.
    """
    obj = context.object
    if not obj or obj.type != 'MESH':
        return None, "No valid mesh object selected!"

    area = next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)
    if not area:
        return None, "No 3D View found!"

    space = next((s for s in area.spaces if s.type == 'VIEW_3D'), None)
    if not space or not space.region_3d:
        return None, "No RegionView3D found!"

    rv3d = space.region_3d

    # Current edit select mode
    sel = context.tool_settings.mesh_select_mode
    if sel[2]:
        mode = 'FACE'
    elif sel[1]:
        mode = 'EDGE'
    else:
        mode = 'VERT'

    was_edit = (obj.mode == 'EDIT')
    if was_edit:
        bpy.ops.object.mode_set(mode='OBJECT')

    mesh = obj.data
    mat_world = obj.matrix_world
    mat_normal = get_correct_normal_matrix(mat_world)
    view_origin, is_ortho = get_view_origin_and_direction(rv3d)

    # Compute ortho view direction once if needed
    ortho_view_dir = None
    if is_ortho:
        view_mat_inv = rv3d.view_matrix.inverted()
        ortho_view_dir = view_mat_inv.to_3x3() @ Vector((0.0, 0.0, -1.0))
        ortho_view_dir.normalize()

    # ------------------------------------------------------------------
    # Step 1: Orientation pass
    # ------------------------------------------------------------------
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()

    orientation_pass = set()

    for f in bm.faces:
        f_normal_world = mat_normal @ f.normal
        f_normal_world.normalize()
        f_center_world = mat_world @ f.calc_center_median()

        if is_ortho:
            dot_val = f_normal_world.dot(ortho_view_dir)
        else:
            view_to_face = (f_center_world - view_origin).normalized()
            dot_val = f_normal_world.dot(view_to_face)

        is_backfacing = (dot_val < 0)

        if select_backfaces and is_backfacing:
            orientation_pass.add(f.index)
        elif (not select_backfaces) and (not is_backfacing):
            orientation_pass.add(f.index)

    # ------------------------------------------------------------------
    # Step 2: Occlusion pass
    # ------------------------------------------------------------------
    context.view_layer.update()
    depsgraph = context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh_eval = obj_eval.data

    if xray:
        after_occlusion = orientation_pass
    else:
        after_occlusion = set()
        for poly in mesh_eval.polygons:
            if poly.index not in orientation_pass:
                continue
            face_center_world = obj_eval.matrix_world @ poly.center
            if is_face_visible_via_raycast(
                context.scene, depsgraph,
                view_origin, face_center_world,
                obj_eval, poly.index
            ):
                after_occlusion.add(poly.index)

    # ------------------------------------------------------------------
    # Step 3 (optional): Expand seeds to full connected islands
    # ------------------------------------------------------------------
    if loose_parts and after_occlusion:
        final_face_indices = flood_fill_islands(bm, after_occlusion)
    else:
        final_face_indices = after_occlusion

    bm.to_mesh(mesh)
    bm.free()

    report = (
        f"Orientation: {len(orientation_pass)} | "
        f"After occlusion: {len(after_occlusion)}"
        + (f" | Island expanded: {len(final_face_indices)}" if loose_parts else "")
        + f" | Mode: {mode}"
    )

    # ------------------------------------------------------------------
    # Step 4: Write selection back to mesh
    # ------------------------------------------------------------------
    bm2 = bmesh.new()
    bm2.from_mesh(mesh)
    bm2.faces.ensure_lookup_table()
    bm2.verts.ensure_lookup_table()
    bm2.edges.ensure_lookup_table()

    for v in bm2.verts: v.select = False
    for e in bm2.edges: e.select = False
    for f in bm2.faces: f.select = False

    if mode == 'FACE':
        for f in bm2.faces:
            if f.index in final_face_indices:
                f.select = True

    elif mode == 'VERT':
        for f in bm2.faces:
            if f.index in final_face_indices:
                for v in f.verts:
                    v.select = True

    elif mode == 'EDGE':
        verts_in = set()
        for f in bm2.faces:
            if f.index in final_face_indices:
                for v in f.verts:
                    verts_in.add(v.index)
        for e in bm2.edges:
            if e.verts[0].index in verts_in and e.verts[1].index in verts_in:
                e.select = True

    bm2.select_flush_mode()
    bm2.to_mesh(mesh)
    bm2.free()

    bpy.ops.object.mode_set(mode='EDIT')

    return report, None


# ---------------------------------------------------------------------------
# Operator — standard facing select
# ---------------------------------------------------------------------------

class MESH_OT_select_orientation_zdepth(bpy.types.Operator):
    """Select geometry by viewport orientation (front or back facing), with optional occlusion."""
    bl_idname = "mesh.select_orientation_zdepth"
    bl_label = "Select Orientation (Z-Depth)"
    bl_options = {'REGISTER', 'UNDO'}

    select_backfaces: bpy.props.BoolProperty(
        name="Select Back Faces",
        description="Select faces whose normals point AWAY from viewport (back-facing). "
                    "Uncheck for faces pointing TOWARD viewport (front-facing).",
        default=False
    )
    xray: bpy.props.BoolProperty(
        name="X-Ray (Ignore Occlusion)",
        description="Select matching faces even if hidden behind other geometry",
        default=False
    )

    def execute(self, context):
        report, err = run_orientation_selection(
            context,
            select_backfaces=self.select_backfaces,
            xray=self.xray,
            loose_parts=False
        )
        if err:
            self.report({'WARNING'}, err)
            return {'CANCELLED'}
        self.report({'INFO'}, report)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Operator — loose parts (island) select
# ---------------------------------------------------------------------------

class MESH_OT_select_orientation_loose(bpy.types.Operator):
    """Select entire loose mesh islands that contain at least one front/back facing face."""
    bl_idname = "mesh.select_orientation_loose"
    bl_label = "Select Loose Parts (Z-Depth)"
    bl_options = {'REGISTER', 'UNDO'}

    select_backfaces: bpy.props.BoolProperty(
        name="Select Back Faces",
        description="Use back-facing faces as seeds. Uncheck for front-facing.",
        default=False
    )
    xray: bpy.props.BoolProperty(
        name="X-Ray (Ignore Occlusion)",
        description="Select matching loose parts even if seed faces are occluded",
        default=False
    )

    def execute(self, context):
        report, err = run_orientation_selection(
            context,
            select_backfaces=self.select_backfaces,
            xray=self.xray,
            loose_parts=True
        )
        if err:
            self.report({'WARNING'}, err)
            return {'CANCELLED'}
        self.report({'INFO'}, report)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class VIEW3D_PT_select_orientation_zdepth(bpy.types.Panel):
    """N-Panel UI for Select Orientation (Z-Depth)"""
    bl_label = "Select Orientation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Select"  # Own dedicated tab

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        xray = scene.select_orientation_xray

        # ---- Standard facing buttons ----
        layout.label(text="By Vertices:")
        row = layout.row(align=True)
        row.scale_y = 1.3

        op = row.operator("mesh.select_orientation_zdepth", text="Front Facing", icon='NORMALS_FACE')
        op.select_backfaces = False
        op.xray = xray

        op = row.operator("mesh.select_orientation_zdepth", text="Back Facing", icon='OBJECT_HIDDEN')
        op.select_backfaces = True
        op.xray = xray

        layout.separator()

        # ---- Loose parts buttons ----
        layout.label(text="By Loose Part:")
        row = layout.row(align=True)
        row.scale_y = 1.3

        op = row.operator("mesh.select_orientation_loose", text="Front Parts", icon='MESH_DATA')
        op.select_backfaces = True
        op.xray = xray

        op = row.operator("mesh.select_orientation_loose", text="Back Parts", icon='MESH_DATA')
        op.select_backfaces = False
        op.xray = xray

        layout.separator()

        # ---- X-Ray toggle (affects all four buttons) ----
        layout.prop(scene, "select_orientation_xray",
                    text="X-Ray  (Ignore Occlusion)", toggle=True,
                    icon='XRAY')


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def register():
    bpy.types.Scene.select_orientation_xray = bpy.props.BoolProperty(
        name="X-Ray Mode",
        description="Ignore occlusion — select through other geometry",
        default=False
    )
    bpy.utils.register_class(MESH_OT_select_orientation_zdepth)
    bpy.utils.register_class(MESH_OT_select_orientation_loose)
    bpy.utils.register_class(VIEW3D_PT_select_orientation_zdepth)


def unregister():
    bpy.utils.unregister_class(VIEW3D_PT_select_orientation_zdepth)
    bpy.utils.unregister_class(MESH_OT_select_orientation_loose)
    bpy.utils.unregister_class(MESH_OT_select_orientation_zdepth)
    del bpy.types.Scene.select_orientation_xray


if __name__ == "__main__":
    register()