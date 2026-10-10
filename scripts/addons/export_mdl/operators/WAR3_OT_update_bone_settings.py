import bpy


class WAR3_OT_update_bone_settings(bpy.types.Operator):
    bl_idname = 'warcraft_3.update_bone_settings'
    bl_label = 'Warcraft 3 Update Bone Settings'
    bl_description = 'Warcraft 3 Update Bone Settings'
    bl_options = {'UNDO'}

    def execute(self, context):
        from ..import_stuff.create_armature_object import assign_node_type_group
        curr_object = context.object
        for bone in curr_object.data.bones:
            if not hasattr(bone, 'warcraft_3'):
                continue
            node_type = bone.warcraft_3.nodeType
            if node_type in {'BONE', 'ATTACHMENT', 'COLLISION_SHAPE', 'EVENT', 'HELPER'}:
                assign_node_type_group(curr_object, curr_object.pose.bones[bone.name], node_type.lower())
        return {'FINISHED'}
