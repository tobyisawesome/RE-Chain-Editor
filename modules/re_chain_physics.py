import bpy
from mathutils import Vector


PHYSICS_BONE_PROP = "RE_CHAIN_IS_PHYSICS_BONE"
PHYSICS_PREVIEW_CONSTRAINT = "RE Chain Preview"
PHYSICS_NODE_CONSTRAINT_FLAG = "RE_CHAIN_PREVIEW_MUTED"
PHYSICS_BONE_COLLECTION_NAME = "RE Chain Physics"


def get_chain_nodes(chain_collection=None):
    if chain_collection is None:
        chain_collection = bpy.context.scene.re_chain_toolpanel.chainCollection
    if chain_collection is None:
        return []
    return [obj for obj in chain_collection.all_objects if obj.get("TYPE", None) == "RE_CHAIN_NODE"]


def find_chain_armature(chain_collection=None, nodes=None):
    if nodes is None:
        nodes = get_chain_nodes(chain_collection)
    for node in nodes:
        for constraint in node.constraints:
            if constraint.target and constraint.target.type == "ARMATURE":
                return constraint.target
    active = bpy.context.active_object
    if active and active.type == "ARMATURE":
        return active
    for obj in bpy.context.scene.objects:
        if obj.type == "ARMATURE":
            if not nodes:
                return obj
            if any(node.name in obj.data.bones for node in nodes):
                return obj
    return None


def _enter_edit_mode(armature):
    view_layer = bpy.context.view_layer
    previous_active = view_layer.objects.active
    previous_mode = previous_active.mode if previous_active else 'OBJECT'
    previous_selection = list(bpy.context.selected_objects)
    if previous_active and previous_active.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    armature.select_set(True)
    view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='EDIT')
    return previous_active, previous_mode, previous_selection


def _exit_edit_mode(armature, previous_state):
    previous_active, previous_mode, previous_selection = previous_state
    try:
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass
    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for obj in previous_selection:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = previous_active
    if previous_active and previous_mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode=previous_mode)
        except Exception:
            pass


def _update_edit_bone_from_node(edit_bone, node, armature_inv):
    node_world_matrix = node.matrix_world.copy()
    node_local_matrix = armature_inv @ node_world_matrix
    head_world = node_world_matrix.to_translation()
    child_node = None
    for child in node.children:
        if child.get("TYPE", None) == "RE_CHAIN_NODE":
            child_node = child
            break
    if child_node:
        tail_world = child_node.matrix_world.to_translation()
    else:
        tail_world = head_world + (node_world_matrix.to_quaternion() @ Vector((0.0, 0.05, 0.0)))
    head_local = armature_inv @ head_world
    tail_local = armature_inv @ tail_world
    length = (tail_local - head_local).length
    if length < 1e-5:
        length = 0.05
    edit_bone.matrix = node_local_matrix
    edit_bone.length = length
    edit_bone.use_connect = False


def ensure_physics_bones(chain_collection=None, armature=None, nodes=None):
    if nodes is None:
        nodes = get_chain_nodes(chain_collection)
    if not nodes:
        return None, [], 0
    if armature is None:
        armature = find_chain_armature(chain_collection, nodes)
    if armature is None:
        return None, nodes, 0
    armature_inv = armature.matrix_world.inverted()
    created_count = 0
    previous_state = _enter_edit_mode(armature)
    try:
        edit_bones = armature.data.edit_bones
        for node in nodes:
            bone_name = node.name
            if bone_name in edit_bones:
                edit_bone = edit_bones[bone_name]
                managed = bool(armature.data.bones[bone_name].get(PHYSICS_BONE_PROP, False))
            else:
                edit_bone = edit_bones.new(bone_name)
                managed = True
                created_count += 1
            if managed:
                edit_bone[PHYSICS_BONE_PROP] = True
                _update_edit_bone_from_node(edit_bone, node, armature_inv)
            parent_node = node.parent if node.parent and node.parent.get("TYPE", None) == "RE_CHAIN_NODE" else None
            if parent_node and parent_node.name in edit_bones:
                edit_bone.parent = edit_bones[parent_node.name]
            elif managed:
                edit_bone.parent = None
            if bpy.app.version >= (4, 0, 0) and managed:
                bone_collection = armature.data.collections.get(PHYSICS_BONE_COLLECTION_NAME)
                if bone_collection is None:
                    bone_collection = armature.data.collections.new(PHYSICS_BONE_COLLECTION_NAME)
                bone_collection.assign(edit_bone)
            elif bpy.app.version < (4, 0, 0) and managed:
                layers = list(edit_bone.layers)
                if len(layers) == 32:
                    layers = [False] * 32
                    layers[31] = True
                    edit_bone.layers = layers
    finally:
        _exit_edit_mode(armature, previous_state)
    return armature, nodes, created_count


def enable_physics_preview(chain_collection=None, armature=None, nodes=None):
    armature, nodes, _ = ensure_physics_bones(chain_collection, armature, nodes)
    if armature is None:
        return None, []
    pose_bones = armature.pose.bones
    active_bones = []
    for node in nodes:
        pose_bone = pose_bones.get(node.name, None)
        if pose_bone is None:
            continue
        active_bones.append(pose_bone)
        constraint = None
        for entry in pose_bone.constraints:
            if entry.name == PHYSICS_PREVIEW_CONSTRAINT and entry.type == 'COPY_TRANSFORMS':
                constraint = entry
                break
        if constraint is None:
            constraint = pose_bone.constraints.new('COPY_TRANSFORMS')
            constraint.name = PHYSICS_PREVIEW_CONSTRAINT
        constraint.target = node
        constraint.subtarget = ""
        constraint.owner_space = 'WORLD'
        constraint.target_space = 'WORLD'
        constraint.mute = False
        constraint.influence = 1.0
        pose_bone.bone[PHYSICS_BONE_PROP] = True
    for node in nodes:
        for constraint in node.constraints:
            if constraint.type in {'COPY_LOCATION', 'COPY_ROTATION'} and constraint.name in {"BoneName", "BoneRotation"}:
                if not constraint.get(PHYSICS_NODE_CONSTRAINT_FLAG, False):
                    constraint[PHYSICS_NODE_CONSTRAINT_FLAG] = True
                    constraint.mute = True
    return armature, active_bones


def disable_physics_preview(chain_collection=None, armature=None, nodes=None, clear_constraints=False):
    if nodes is None:
        nodes = get_chain_nodes(chain_collection)
    if not nodes:
        return None, False
    if armature is None:
        armature = find_chain_armature(chain_collection, nodes)
    if armature is None:
        return None, False
    changed = False
    for node in nodes:
        for constraint in node.constraints:
            if constraint.get(PHYSICS_NODE_CONSTRAINT_FLAG, False):
                constraint.mute = False
                del constraint[PHYSICS_NODE_CONSTRAINT_FLAG]
                changed = True
    for pose_bone in armature.pose.bones:
        constraint = pose_bone.constraints.get(PHYSICS_PREVIEW_CONSTRAINT, None)
        if constraint:
            if clear_constraints:
                pose_bone.constraints.remove(constraint)
            else:
                constraint.mute = True
            changed = True
    return armature, changed
