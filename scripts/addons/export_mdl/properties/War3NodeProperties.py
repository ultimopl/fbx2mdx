import bpy


def set_bone_node_type(self, context):
    bone = context.active_bone
    if bone and hasattr(bone, 'warcraft_3'):
        from ..import_stuff.create_armature_object import assign_node_type_group
        node_type = bone.warcraft_3.nodeType
        if node_type in {'BONE', 'ATTACHMENT', 'COLLISION_SHAPE', 'EVENT', 'HELPER'}:
            pose_bone = context.object.pose.bones[bone.name]
            assign_node_type_group(context.object, pose_bone, node_type.lower())


class War3NodeProperties(bpy.types.PropertyGroup):
    bpy_type = bpy.types.Bone
    nodeType: bpy.props.EnumProperty(
        items=[
            ('NONE', 'None', ''),
            ('BONE', 'Bone', ''),
            ('HELPER', 'Helper', ''),
            ('ATTACHMENT', 'Attachment', ''),
            ('EVENT', 'Event', ''),
            ('COLLISION_SHAPE', 'Collision Shape', '')
            ],
        name='Node Type',
        update=set_bone_node_type,
        default='NONE'
        )

