from typing import List, Set, Optional, Tuple

import bpy
from mathutils import Matrix, Vector

from export_mdl.classes.War3AnimationAction import War3AnimationAction
from export_mdl.classes.War3AnimationCurve import War3AnimationCurve
from export_mdl.classes.War3Bone import War3Bone
from export_mdl.classes.animation_curve_utils.transform_rot import transform_rot
from export_mdl.classes.animation_curve_utils.transform_vec import transform_vec1
from export_mdl.classes.bpy_helpers.BpySceneObjects import BpySceneObjects
from export_mdl.classes.model_utils.is_animated_ugg import get_loc_rot_scale, get_baked_loc_rot_scale


def parse_armatures(bpy_scene_objects: BpySceneObjects,
                    global_matrix: Matrix,
                    optimize_tolerance: float,
                    actions: List[bpy.types.Action],
                    sequences: List[War3AnimationAction],
                    global_seqs: Set[int]) -> List[War3Bone]:
    print("parsing armature!")
    bones: List[War3Bone] = []
    for armature in bpy_scene_objects.armatures:
        animation_data: bpy.types.AnimData = armature.animation_data
        matrix_world = Matrix(armature.matrix_world)
        for pose_bone in bpy_scene_objects.bpy_nodes[armature.name]:
            bone = get_wc3_bone(armature, animation_data, global_matrix, global_seqs, matrix_world, pose_bone, actions,
                                sequences, optimize_tolerance)
            bones.append(bone)
    if len(bones) == 0 and len(bpy_scene_objects.geosets) == 0:
        bones.append(War3Bone("No_Bones_Found"))
    return bones


def get_wc3_bone(armature: bpy.types.Object, animation_data: bpy.types.AnimData,
                 global_matrix: Matrix,
                 global_seqs: Set[int],
                 matrix_world: Matrix,
                 pose_bone: bpy.types.PoseBone,
                 actions: List[bpy.types.Action],
                 sequences: List[War3AnimationAction],
                 optimize_tolerance: float) -> War3Bone:
    data_path = 'pose.bones[\"' + pose_bone.name + '\"].%s'
    anim_loc, anim_rot, anim_scale = get_animation_data(armature, animation_data, pose_bone, data_path, global_matrix,
                                                        global_seqs,
                                                        matrix_world, actions, sequences, optimize_tolerance)
    b_parent = pose_bone.parent
    bone_p_name = None if b_parent is None else b_parent.name
    pivot_ = matrix_world @ Vector(pose_bone.bone.head_local)  # Armature space to world space
    pivot = global_matrix @ Vector(pivot_)  # Axis conversion
    bone = War3Bone(pose_bone.name, pivot, bone_p_name, anim_loc, anim_rot, anim_scale, pose_bone.matrix_basis)
    return bone


def get_animation_data(armature: bpy.types.Object, animation_data: bpy.types.AnimData,
                       pose_bone: bpy.types.PoseBone,
                       data_path: str,
                       global_matrix: Matrix,
                       global_seqs: Set[int],
                       matrix_world: Matrix,
                       actions: List[bpy.types.Action],
                       sequences: List[War3AnimationAction],
                       optimize_tolerance: float) \
        -> Tuple[Optional[War3AnimationCurve], Optional[War3AnimationCurve], Optional[War3AnimationCurve]]:
    if not pose_bone.is_in_ik_chain and len(pose_bone.constraints) == 0:
        anim_loc, anim_rot, anim_scale = get_loc_rot_scale(sequences, global_seqs, data_path, actions, animation_data,
                                                           optimize_tolerance)
    else:
        anim_loc, anim_rot, anim_scale = get_baked_loc_rot_scale(armature, actions, pose_bone, sequences,
                                                                 optimize_tolerance)

    if anim_loc is not None:
        m = matrix_world @ pose_bone.bone.matrix_local
        to__x_ = m.to_3x3().to_4x4()
        x_ = global_matrix @ to__x_
        transform_vec1(anim_loc, x_)
    if anim_rot is not None:
        mat_pose_ws = matrix_world @ pose_bone.bone.matrix_local
        # mat_rest_ws = matrix_world @ b.matrix
        transform_rot(anim_rot.keyframes, mat_pose_ws)
        transform_rot(anim_rot.keyframes, global_matrix)
    return anim_loc, anim_rot, anim_scale



# def get_wc3_bone1(animation_data: bpy.types.AnimData,
#                  global_matrix: Matrix,
#                  global_seqs: Set[int],
#                  matrix_world: Matrix,
#                  pose_bone: bpy.types.PoseBone,
#                  actions: List[bpy.types.Action],
#                  sequences: List[War3AnimationAction],
#                  optimize_tolerance: float) -> War3Bone:
#     data_path = 'pose.bones[\"' + pose_bone.name + '\"].%s'
#     anim_loc, anim_rot, anim_scale = get_animation_data(animation_data, pose_bone, data_path, global_matrix,
#                                                         global_seqs,
#                                                         matrix_world, actions, sequences, optimize_tolerance)
#     b_parent = pose_bone.parent
#     bone_p_name = None if b_parent is None else b_parent.name
#     pivot_ = matrix_world @ Vector(pose_bone.bone.head_local)  # Armature space to world space
#     pivot = global_matrix @ Vector(pivot_)  # Axis conversion
#     bone = War3Bone(pose_bone.name, pivot, bone_p_name, anim_loc, anim_rot, anim_scale, pose_bone.matrix_basis)
#     return bone
#
#
# def get_animation_data1(animation_data: bpy.types.AnimData,
#                        pose_bone: bpy.types.PoseBone,
#                        data_path: str,
#                        global_matrix: Matrix,
#                        global_seqs: Set[int],
#                        matrix_world: Matrix,
#                        actions: List[bpy.types.Action],
#                        sequences: List[War3AnimationAction],
#                        optimize_tolerance: float) \
#         -> Tuple[Optional[War3AnimationCurve], Optional[War3AnimationCurve], Optional[War3AnimationCurve]]:
#     anim_loc, anim_rot, anim_scale = get_loc_rot_scale(sequences, global_seqs, data_path, actions, animation_data,
#                                                        optimize_tolerance)
#
#
#     if anim_loc is not None:
#         m = matrix_world @ pose_bone.bone.matrix_local
#         to__x_ = m.to_3x3().to_4x4()
#         x_ = global_matrix @ to__x_
#         transform_vec1(anim_loc, x_)
#     if anim_rot is not None:
#         mat_pose_ws = matrix_world @ pose_bone.bone.matrix_local
#         # mat_rest_ws = matrix_world @ b.matrix
#         transform_rot(anim_rot.keyframes, mat_pose_ws)
#         transform_rot(anim_rot.keyframes, global_matrix)
#     return anim_loc, anim_rot, anim_scale
#
#
# def bake_action_iter(
#         obj: bpy.types.Object,
#         *,
#         action,
#         do_pose=True,
#         do_clean=False
# ):
#     """
#     An coroutine that bakes action for a single object.
#     :arg obj: Object to bake.
#     :type obj: :class:`bpy.types.Object`
#     :arg action: An action to bake the data into, or None for a new action to be created.
#     :type action: :class:`bpy.types.Action` or None
#     :arg do_pose: Bake pose channels.
#     :type do_pose: bool
#     :arg do_clean: Remove redundant keyframes after baking.
#     :type do_clean: bool
#     :return: an action or None
#     :rtype: :class:`bpy.types.Action`
#     """
#     # -------------------------------------------------------------------------
#     # Helper Functions and vars
#
#     # Note: BBONE_PROPS is a list so we can preserve the ordering
#     BBONE_PROPS = [
#         'bbone_curveinx', 'bbone_curveoutx',
#         'bbone_curveinz', 'bbone_curveoutz',
#         'bbone_rollin', 'bbone_rollout',
#         'bbone_scalein', 'bbone_scaleout',
#         'bbone_easein', 'bbone_easeout'
#     ]
#
#     def pose_frame_info(obj: bpy.types.Object):
#         name_to_matrix: Dict[str, Matrix] = {}
#         for name, pbone in obj.pose.bones.items():
#             # Get the final transform of the bone in its own local space...
#             name_to_matrix[name] = obj.convert_space(pose_bone=pbone, matrix=pbone.matrix, from_space='POSE', to_space='LOCAL')
#
#         return name_to_matrix
#
#     # -------------------------------------------------------------------------
#     # Setup the Context
#
#     pose_info: List[Tuple[Any, Dict[str, Matrix]]] = []
#
#     # -------------------------------------------------------------------------
#     # Collect transformations
#
#     while True:
#         # Caller is responsible for setting the frame and updating the scene.
#         frame = yield None
#
#         # Signal we're done!
#         if frame is None:
#             break
#
#         pose_info.append((frame, *pose_frame_info(obj)))
#
#     # # -------------------------------------------------------------------------
#     # # Clean (store initial data)
#     # if do_clean and action is not None:
#     #     clean_orig_data = {fcu: {p.co[1] for p in fcu.keyframe_points} for fcu in action.fcurves}
#     # else:
#     #     clean_orig_data = {}
#
#     # -------------------------------------------------------------------------
#     # Create action
#
#     # in case animation data hasn't been created
#     atd = obj.animation_data_create()
#     # if action is None:
#     #     action = bpy.data.actions.new("Action")
#
#     # Only leave tweak mode if we actually need to modify the action (T57159)
#     if action != atd.action:
#         # Leave tweak mode before trying to modify the action (T48397)
#         if atd.use_tweak_mode:
#             atd.use_tweak_mode = False
#
#         atd.action = action
#
#     # Baking the action only makes sense in Replace mode, so force it (T69105)
#     if not atd.use_tweak_mode:
#         atd.action_blend_type = 'REPLACE'
#
#     # -------------------------------------------------------------------------
#     # Apply transformations to action
#
#     name_to_bone: Dict[str, bpy.types.PoseBone] = {}
#     # pose
#     for name, pbone in name_to_bone.items():
#
#         data_path = 'pose.bones[\"' + pbone.name + '\"].%s'
#         curves2: Dict[Tuple[str, str, int], bpy.types.FCurve] = {}
#         for index in range(3):
#             curve = action.fcurves.find(data_path % 'location', index=index)
#             if curve is not None:
#                 curves2[(action.name, data_path.split('.')[-1], index)] = curve
#                 # (NAME, TRANSFORMATION TYPE, CHANNEL), eg. ('Stand', 'location', 0[x])
#         for index in range(4):
#             curve = action.fcurves.find(data_path % 'rotation_quaternion', index=index)
#             if curve is not None:
#                 curves2[(action.name, data_path.split('.')[-1], index)] = curve
#                 # (NAME, TRANSFORMATION TYPE, CHANNEL), eg. ('Stand', 'location', 0[x])
#         for index in range(4):
#             curve = action.fcurves.find(data_path % 'rotation_axis_angle', index=index)
#             if curve is not None:
#                 curves2[(action.name, data_path.split('.')[-1], index)] = curve
#                 # (NAME, TRANSFORMATION TYPE, CHANNEL), eg. ('Stand', 'location', 0[x])
#         for index in range(3):
#             curve = action.fcurves.find(data_path % 'rotation_euler', index=index)
#             if curve is not None:
#                 curves2[(action.name, data_path.split('.')[-1], index)] = curve
#                 # (NAME, TRANSFORMATION TYPE, CHANNEL), eg. ('Stand', 'location', 0[x])
#         for index in range(3):
#             curve = action.fcurves.find(data_path % 'scale', index=index)
#             if curve is not None:
#                 curves2[(action.name, data_path.split('.')[-1], index)] = curve
#                 # (NAME, TRANSFORMATION TYPE, CHANNEL), eg. ('Stand', 'location', 0[x])
#
#
#         # Create compatible eulers, quats.
#         euler_prev = None
#         quat_prev = None
#
#         for (f, matrix) in pose_info:
#             pbone.matrix_basis = matrix[name].copy()
#
#             pbone.keyframe_insert("location", index=-1, frame=f, group=name)
#
#             rotation_mode = pbone.rotation_mode
#             if rotation_mode == 'QUATERNION':
#                 if quat_prev is not None:
#                     quat = pbone.rotation_quaternion.copy()
#                     quat.make_compatible(quat_prev)
#                     pbone.rotation_quaternion = quat
#                     quat_prev = quat
#                     del quat
#                 else:
#                     quat_prev = pbone.rotation_quaternion.copy()
#                 pbone.keyframe_insert("rotation_quaternion", index=-1, frame=f, group=name)
#             elif rotation_mode == 'AXIS_ANGLE':
#                 pbone.keyframe_insert("rotation_axis_angle", index=-1, frame=f, group=name)
#             else:  # euler, XYZ, ZXY etc
#                 if euler_prev is not None:
#                     euler = pbone.matrix_basis.to_euler(pbone.rotation_mode, euler_prev)
#                     pbone.rotation_euler = euler
#                     del euler
#                 euler_prev = pbone.rotation_euler.copy()
#                 pbone.keyframe_insert("rotation_euler", index=-1, frame=f, group=name)
#
#             pbone.keyframe_insert("scale", index=-1, frame=f, group=name)
#
#     # # -------------------------------------------------------------------------
#     # # Clean
#     #
#     # if do_clean:
#     #     for fcu in action.fcurves:
#     #         fcu_orig_data = clean_orig_data.get(fcu, set())
#     #
#     #         keyframe_points = fcu.keyframe_points
#     #         i = 1
#     #         while i < len(keyframe_points) - 1:
#     #             val = keyframe_points[i].co[1]
#     #
#     #             if val in fcu_orig_data:
#     #                 i += 1
#     #                 continue
#     #
#     #             val_prev = keyframe_points[i - 1].co[1]
#     #             val_next = keyframe_points[i + 1].co[1]
#     #
#     #             if abs(val - val_prev) + abs(val - val_next) < 0.0001:
#     #                 keyframe_points.remove(keyframe_points[i])
#     #             else:
#     #                 i += 1
#
#     yield action

