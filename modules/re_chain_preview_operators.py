import bpy

from .re_chain_physics import (
    get_chain_nodes,
    find_chain_armature,
    ensure_physics_bones,
    enable_physics_preview,
    disable_physics_preview,
)
from .blender_re_chain import setChainBoneColor


class WM_OT_CreatePhysicsBones(bpy.types.Operator):
    bl_label = "Add Physics Bones"
    bl_idname = "re_chain.create_physics_bones"
    bl_description = "Create or update armature bones for the active chain so they can be previewed and baked in Blender"
    bl_options = {'UNDO'}

    def execute(self, context):
        tool = context.scene.re_chain_toolpanel
        chain_collection = tool.chainCollection
        if chain_collection is None:
            self.report({'ERROR'}, "Active chain collection is not set.")
            return {'CANCELLED'}
        armature, nodes, created = ensure_physics_bones(chain_collection)
        if armature is None or not nodes:
            self.report({'ERROR'}, "Unable to find chain nodes or a target armature for the active collection.")
            return {'CANCELLED'}
        setChainBoneColor(armature)
        if created > 0:
            self.report({'INFO'}, f"Created {created} physics bone{'s' if created != 1 else ''} on '{armature.name}'.")
        else:
            self.report({'INFO'}, f"Physics bones on '{armature.name}' are already up to date.")
        return {'FINISHED'}


class WM_OT_EnablePhysicsPreview(bpy.types.Operator):
    bl_label = "Enable Physics Preview"
    bl_idname = "re_chain.enable_physics_preview"
    bl_description = "Mute chain node constraints so the generated physics bones follow them for realtime preview"
    bl_options = {'UNDO'}

    def execute(self, context):
        tool = context.scene.re_chain_toolpanel
        chain_collection = tool.chainCollection
        if chain_collection is None:
            self.report({'ERROR'}, "Active chain collection is not set.")
            return {'CANCELLED'}
        armature, nodes, _ = ensure_physics_bones(chain_collection)
        if armature is None or not nodes:
            self.report({'ERROR'}, "Unable to find chain nodes or an armature for the active collection.")
            return {'CANCELLED'}
        enable_physics_preview(chain_collection, armature, nodes)
        setChainBoneColor(armature)
        tool.physicsPreviewEnabled = True
        self.report({'INFO'}, f"Physics preview enabled on '{armature.name}'.")
        return {'FINISHED'}


class WM_OT_DisablePhysicsPreview(bpy.types.Operator):
    bl_label = "Disable Physics Preview"
    bl_idname = "re_chain.disable_physics_preview"
    bl_description = "Restore the original chain node constraints and stop the physics preview"
    bl_options = {'UNDO'}

    def execute(self, context):
        tool = context.scene.re_chain_toolpanel
        chain_collection = tool.chainCollection
        if chain_collection is None:
            self.report({'ERROR'}, "Active chain collection is not set.")
            return {'CANCELLED'}
        nodes = get_chain_nodes(chain_collection)
        if not nodes:
            self.report({'ERROR'}, "No chain nodes were found for the active collection.")
            return {'CANCELLED'}
        armature, changed = disable_physics_preview(chain_collection, None, nodes, clear_constraints=False)
        if armature is None or not changed:
            self.report({'ERROR'}, "Physics preview is not active.")
            return {'CANCELLED'}
        tool.physicsPreviewEnabled = False
        self.report({'INFO'}, "Physics preview disabled.")
        return {'FINISHED'}


class WM_OT_BakePhysicsPreview(bpy.types.Operator):
    bl_label = "Bake Physics Preview"
    bl_idname = "re_chain.bake_physics_preview"
    bl_description = "Bake the physics preview bones to keyframes over the specified frame range"
    bl_options = {'UNDO'}

    frame_start: bpy.props.IntProperty(name="Start Frame", description="First frame to bake", default=1)
    frame_end: bpy.props.IntProperty(name="End Frame", description="Last frame to bake", default=250)
    clear_preview_constraints: bpy.props.BoolProperty(
        name="Disable Preview After Bake",
        description="Re-enable the original chain constraints and remove preview constraints after baking",
        default=False,
    )

    def invoke(self, context, event):
        scene = context.scene
        self.frame_start = scene.frame_start
        self.frame_end = scene.frame_end
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "frame_start")
        layout.prop(self, "frame_end")
        layout.prop(self, "clear_preview_constraints")

    def execute(self, context):
        tool = context.scene.re_chain_toolpanel
        chain_collection = tool.chainCollection
        if chain_collection is None:
            self.report({'ERROR'}, "Active chain collection is not set.")
            return {'CANCELLED'}
        nodes = get_chain_nodes(chain_collection)
        if not nodes:
            self.report({'ERROR'}, "No chain nodes were found for the active collection.")
            return {'CANCELLED'}
        armature = find_chain_armature(chain_collection, nodes)
        if armature is None:
            self.report({'ERROR'}, "Unable to find an armature for the active collection.")
            return {'CANCELLED'}
        armature, nodes, _ = ensure_physics_bones(chain_collection, armature, nodes)
        if armature is None or not nodes:
            self.report({'ERROR'}, "Unable to prepare physics bones for baking.")
            return {'CANCELLED'}
        if self.frame_end < self.frame_start:
            self.frame_start, self.frame_end = self.frame_end, self.frame_start
        was_enabled = tool.physicsPreviewEnabled
        if not was_enabled:
            enable_physics_preview(chain_collection, armature, nodes)
        pose_bones = [armature.pose.bones.get(node.name) for node in nodes if armature.pose.bones.get(node.name) is not None]
        pose_bones = [pb for pb in pose_bones if pb is not None]
        if not pose_bones:
            if not was_enabled or self.clear_preview_constraints:
                disable_physics_preview(chain_collection, armature, nodes, clear_constraints=self.clear_preview_constraints)
                tool.physicsPreviewEnabled = False
            self.report({'ERROR'}, "No physics bones were found to bake.")
            return {'CANCELLED'}
        view_layer = context.view_layer
        original_active = view_layer.objects.active
        original_selected = list(context.selected_objects)
        original_mode = original_active.mode if original_active else 'OBJECT'
        original_bone_selection = []
        if original_active == armature and armature.mode == 'POSE':
            original_bone_selection = [pb.bone.name for pb in armature.pose.bones if pb.bone.select]
        try:
            if view_layer.objects.active and view_layer.objects.active.mode != 'OBJECT':
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass
            for obj in context.selected_objects:
                obj.select_set(False)
            armature.select_set(True)
            view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode='POSE')
            for pb in armature.pose.bones:
                pb.bone.select = False
                pb.bone.select_head = False
                pb.bone.select_tail = False
            for pb in pose_bones:
                pb.bone.select = True
                pb.bone.select_head = True
                pb.bone.select_tail = True
            armature.data.bones.active = pose_bones[0].bone
            try:
                result = bpy.ops.nla.bake(
                    frame_start=self.frame_start,
                    frame_end=self.frame_end,
                    only_selected=True,
                    visual_keying=True,
                    clear_constraints=False,
                    use_current_action=True,
                    bake_types={'POSE'},
                )
                if 'FINISHED' not in result:
                    raise RuntimeError("Bake operator did not finish")
            except Exception as error:
                if not was_enabled or self.clear_preview_constraints:
                    disable_physics_preview(chain_collection, armature, nodes, clear_constraints=self.clear_preview_constraints)
                    tool.physicsPreviewEnabled = False
                else:
                    tool.physicsPreviewEnabled = True
                self.report({'ERROR'}, f"Failed to bake physics preview: {error}")
                return {'CANCELLED'}
        finally:
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass
            for obj in context.selected_objects:
                obj.select_set(False)
            for obj in original_selected:
                obj.select_set(True)
            view_layer.objects.active = original_active
            if original_active == armature and original_mode == 'POSE':
                try:
                    bpy.ops.object.mode_set(mode='POSE')
                    for pb in armature.pose.bones:
                        pb.bone.select = False
                        pb.bone.select_head = False
                        pb.bone.select_tail = False
                    for name in original_bone_selection:
                        bone = armature.data.bones.get(name)
                        if bone:
                            bone.select = True
                            bone.select_head = True
                            bone.select_tail = True
                except Exception:
                    pass
            if original_active and original_mode != 'OBJECT':
                try:
                    bpy.ops.object.mode_set(mode=original_mode)
                except Exception:
                    pass
        if not was_enabled or self.clear_preview_constraints:
            disable_physics_preview(chain_collection, armature, nodes, clear_constraints=self.clear_preview_constraints)
            tool.physicsPreviewEnabled = False
        else:
            tool.physicsPreviewEnabled = True
        self.report({'INFO'}, f"Baked physics preview for {len(pose_bones)} bone{'s' if len(pose_bones) != 1 else ''}.")
        return {'FINISHED'}
