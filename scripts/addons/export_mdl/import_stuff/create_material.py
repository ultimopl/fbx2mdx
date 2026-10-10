import re
import os
from pathlib import Path
from typing import List, Dict

import bpy


def set_input(node, names, value):
    # Principled BSDF sockets were renamed/reordered in Blender 4.0
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return

from export_mdl import constants
from export_mdl.classes.War3Material import War3Material
from export_mdl.classes.War3Model import War3Model
from export_mdl.classes.War3Texture import War3Texture
from export_mdl.import_stuff.War3BpyMaterial import War3BpyMaterial
from export_mdl.properties.War3Preferences import War3Preferences


# def create_material(model: War3Model, team_color: str) -> Dict[str, bpy.types.Material]:
def create_material(model: War3Model, team_color: str) -> Dict[str, War3BpyMaterial]:
    print("creating materials")
    # The addon entry is missing from preferences when it was enabled without
    # default_set (e.g. headless scripts); fall back to the property defaults.
    addon = bpy.context.preferences.addons.get('export_mdl')
    preferences: War3Preferences = addon.preferences if addon else None
    folders = get_folders(getattr(preferences, "alternativeResourceFolder", ""),
                          getattr(preferences, "resourceFolder", ""), model.file)
    texture_ext = get_texture_ext(getattr(preferences, "textureExtension", ".png"))

    bpy_images: Dict[str, bpy.types.Image] = {}
    for texture in model.textures:
        bpy_image = get_image(folders, team_color, texture, texture_ext)
        bpy_images[texture.texture_path] = bpy_image

    # bpy_materials: Dict[str, bpy.types.Material] = {}
    bpy_materials: Dict[str, War3BpyMaterial] = {}
    for i, material in enumerate(model.materials):
        print("material #" + str(i), material)
        bpy_images_of_layer: List[bpy.types.Image] = []
        for layer in material.layers:
            bpy_images_of_layer.append(bpy_images[layer.texture.texture_path])

        bpy_material = create_bpy_material(bpy_images_of_layer, material)
        store_mdl_layers(bpy_material.bpy_material, material)

        bpy_materials[str(i)] = bpy_material

    return bpy_materials


REPLACEABLE_TYPES = {'1', '2', '11', '31', '32', '33', '34', '35'}


def store_mdl_layers(bpy_material: bpy.types.Material, material: War3Material):
    """Keep the original WC3 layer settings so a re-export writes the same paths/flags."""
    for i, layer in enumerate(material.layers):
        mdl_layer = bpy_material.mdl_layers.add()
        mdl_layer.name = "Layer %d" % i
        replaceable_id = str(layer.texture.replaceable_id) if layer.texture else '0'
        if replaceable_id == '0':
            mdl_layer.texture_type = '0'
            mdl_layer.path = layer.texture.texture_path if layer.texture else layer.texture_path
        elif replaceable_id in REPLACEABLE_TYPES:
            mdl_layer.texture_type = replaceable_id
        else:
            mdl_layer.texture_type = '36'
            mdl_layer.replaceable_id = int(replaceable_id)
        if layer.filter_mode in {'None', 'Blend', 'Transparent', 'Additive', 'AddAlpha', 'Modulate', 'Modulate2x'}:
            mdl_layer.filter_mode = layer.filter_mode
        mdl_layer.unshaded = layer.unshaded
        mdl_layer.two_sided = layer.two_sided
        mdl_layer.no_depth_test = layer.no_depth_test
        mdl_layer.no_depth_set = layer.no_depth_set
        mdl_layer.alpha = layer.alpha_value


def create_bpy_material(bpy_images_of_layer: List[bpy.types.Image],
                        material: War3Material):
    material_name = re.split(r"[\\/]", bpy_images_of_layer[-1].filepath)[-1].split('.')[0]
    war3_bpy_material = War3BpyMaterial(material_name)

    if material.is_hd:

        diffuse = war3_bpy_material.get_new_node(1, 0, 'ShaderNodeMixRGB')
        diffuse.blend_type = 'COLOR'

        for i, bpy_image in enumerate(bpy_images_of_layer):
            texture_mat_node = war3_bpy_material.get_new_node(3, i, 'ShaderNodeTexImage')
            texture_mat_node.image = bpy_image
            if i == 0:
                war3_bpy_material.connect(texture_mat_node.outputs.get("Color"), diffuse.inputs.get("Color1"))
                war3_bpy_material.connect(diffuse.outputs.get("Color"), war3_bpy_material.mix_node.inputs.get("Color2"))
                war3_bpy_material.connect(texture_mat_node.outputs.get("Alpha"), war3_bpy_material.get_input("Alpha"))
            elif i == 1:
                normal_map = war3_bpy_material.get_new_node(1, i, 'ShaderNodeNormalMap')
                normal_map.colorspace_settings.name = 'NONCOLOR'
                war3_bpy_material.connect(texture_mat_node.outputs.get("Color"), normal_map.inputs.get("Color"))
                war3_bpy_material.connect(normal_map.outputs.get("Normal"), war3_bpy_material.get_input("Normal"))
            elif i == 2:
                orm = war3_bpy_material.get_new_node(2, i, 'ShaderNodeSeparateColor')

                roughthness_inv = war3_bpy_material.get_new_node(1, i, "ShaderNodeMath")
                roughthness_inv.operation = 'SUBTRACT'
                roughthness_inv.inputs[0].default_value = 1

                war3_bpy_material.connect(texture_mat_node.outputs.get("Color"), orm.inputs[0])
                # I don't currently know how to do occlusion
                war3_bpy_material.connect(orm.outputs[1], roughthness_inv.inputs[1])
                war3_bpy_material.connect(roughthness_inv.outputs[0], war3_bpy_material.get_input("Roughness"))
                war3_bpy_material.connect(orm.outputs[2], war3_bpy_material.get_input("Metallic"))
                war3_bpy_material.connect(texture_mat_node.outputs.get("Alpha"), diffuse.inputs[0])
            elif i == 3:
                war3_bpy_material.connect(texture_mat_node.outputs.get("Color"), (war3_bpy_material.get_input("Emission Color") or war3_bpy_material.get_input("Emission")))
            elif i == 4:
                team_color = war3_bpy_material.get_new_node(2, 0, 'ShaderNodeRGB')
                team_color.name = 'Team Color'
                team_color.outputs[0].default_value = (1, 0, 0, 1)
                war3_bpy_material.connect(team_color.outputs.get("Color"), diffuse.inputs.get("Color2"))
            # else:
            # skip the environmental map, possibly change the world's map to it
            print(bpy_image.filepath, " at place ", i)
    else:
        next_color_input = war3_bpy_material.mix_node.inputs.get("Color2")
        next_alpha_input = war3_bpy_material.geo_alpha_node.inputs[0]
        for i, bpy_image in enumerate(bpy_images_of_layer):
            texture_mat_node = war3_bpy_material.get_new_node(i*2+3, i, 'ShaderNodeTexImage')
            texture_mat_node.image = bpy_image
            mix_node = war3_bpy_material.get_new_node(i*2+1.5, i, "ShaderNodeMixRGB")
            mix_node.inputs.get("Color1").default_value = (1, 1, 1, 1)
            war3_bpy_material.connect(texture_mat_node.outputs.get("Color"), mix_node.inputs.get("Color2"))
            war3_bpy_material.connect(texture_mat_node.outputs.get("Alpha"), mix_node.inputs[0])
            war3_bpy_material.connect(mix_node.outputs.get("Color"), next_color_input)
            next_color_input = mix_node.inputs.get("Color2")

            alpha_node = war3_bpy_material.get_new_node(i*2+1, 4, "ShaderNodeMath")
            alpha_node.inputs[1].default_value = 0.0
            alpha_node.use_clamp = True
            war3_bpy_material.connect(texture_mat_node.outputs.get("Alpha"), alpha_node.inputs[0])
            war3_bpy_material.connect(alpha_node.outputs[0], next_alpha_input)
            next_alpha_input = alpha_node.inputs[1]
    return war3_bpy_material


def get_wc3_base_node(material_name: str):
    bpy_material: bpy.types.Material = bpy.data.materials.new(name=material_name)
    if hasattr(bpy_material, 'shadow_method'):
        bpy_material.shadow_method = 'NONE'
    bpy_material.use_nodes = True

    if hasattr(bpy_material, 'surface_render_method'):
        bpy_material.surface_render_method = 'DITHERED'
    elif hasattr(bpy_material, 'blend_method'):
        bpy_material.blend_method = 'HASHED'
    if hasattr(bpy_material, 'shadow_method'):
        bpy_material.shadow_method = 'HASHED'

    bpy_material.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    texture_slot_index = 0
    material_node_tree = bpy_material.node_tree
    shader_node: bpy.types.Node = material_node_tree.nodes.get("Principled BSDF")
    set_input(shader_node, ('Specular IOR Level', 'Specular'), 0.0)  # no specular
    set_input(shader_node, ('Roughness',), 1.0)  # full roughness


    node_width: float = shader_node.width
    color_input_socket = shader_node.inputs.get("Base Color")
    mix_node = get_new_node(node_width + 20, 0, material_node_tree, "ShaderNodeMixRGB")
    mix_node.blend_type = 'MULTIPLY'
    mix_node.inputs[0].default_value = 1.0
    color_node = get_new_node(node_width + 200, 0, material_node_tree, "ShaderNodeRGB")
    color_node.outputs[0].default_value = (1, 1, 1, 1)
    color_node.name = 'Geoset Anim Color'
    material_node_tree.links.new(color_node.outputs.get("Color"), mix_node.inputs.get("Color1"))
    material_node_tree.links.new(color_node.outputs.get("Color"), mix_node.inputs.get("Color1"))
    material_node_tree.links.new(mix_node.outputs.get("Color"), shader_node.inputs.get("Base Color"))

    diffuse = material_node_tree.nodes.new('ShaderNodeMixRGB')
    diffuse.location.x -= node_width + 50
    diffuse.blend_type = 'COLOR'



def get_new_node(loc_x: float,
                 loc_y: float,
                 material_node_tree: bpy.types.NodeTree,
                 node_type: str):
    new_node = material_node_tree.nodes.new(node_type)
    new_node.location.x -= loc_x
    new_node.location.y += loc_y
    return new_node


def get_texture_ext(texture_exc: str):
    if texture_exc == '':
        print("No texture extension to replace blp with set in addon preferences")
        texture_exc = 'png'
    if texture_exc[0] != '.':
        texture_exc = '.' + texture_exc
    return texture_exc


def get_image(folders: List[str],
              team_color: str,
              texture: War3Texture,
              texture_exc: str):
    image_file = get_image_file(team_color, texture, texture_exc)
    print("loading:", image_file)
    file_path_parts = re.split(r"[\\/]", image_file)  # WC3 paths use backslashes

    file_name = file_path_parts[-1].split('.')[0]
    bpy_image = bpy.data.images.new(file_name, 0, 0)
    bpy_image.source = 'FILE'

    bpy_image.filepath = find_file(file_path_parts, folders, image_file)
    return bpy_image


def get_image_file(team_color: str,
                   texture: War3Texture,
                   texture_exc: str) -> str:
    if texture.replaceable_id == 1:  # Team Color
        image_file = constants.TEAM_COLOR_IMAGES[team_color]
    elif texture.replaceable_id == 2:  # Team Glow
        image_file = constants.TEAM_GLOW_IMAGES[team_color]
    else:
        image_file = texture.texture_path
    if image_file.endswith(".blp"):
        image_file = image_file.split(".blp")[0] + texture_exc
    image_file = image_file.replace("/", os.path.sep)
    image_file = image_file.replace("\\", os.path.sep)
    return image_file


def find_file(file_path_parts: List[str],
              folders: List[str],
              image_file: str) -> str:
    image_file = image_file.replace('\\', os.sep)
    for i in range(len(file_path_parts)):
        split = image_file.split(os.path.sep, i)
        image_file = split[len(split) - 1]

        for folder in folders:
            file_path = check_file_path(folder, image_file)
            if 0 < len(file_path):
                return file_path
    return ''


def get_folders(alt_folder: str,
                resource_folder: str,
                model_file: str) -> List[str]:
    if resource_folder == '':
        print("No resource folder set in addon preferences")

    elif not resource_folder.endswith(os.path.sep):
        # elif not resource_folder.endswith("\\"):
        resource_folder += os.path.sep
    if alt_folder == '':
        print("No alt resource folder set in addon preferences")
    elif not alt_folder.endswith(os.path.sep):
        alt_folder += os.path.sep

    model_folder = str(Path(model_file).parent)
    if not model_folder.endswith(os.path.sep):
        model_folder += os.path.sep
    # print("model folder:", model_folder)
    textures1 = "Textures" + os.path.sep
    textures2 = "textures" + os.path.sep
    folders1 = [model_folder,
                model_folder + textures1, model_folder + textures2,
                resource_folder, alt_folder,
                resource_folder + textures1, resource_folder + textures2,
                alt_folder + textures1, alt_folder + textures2]
    folders = []
    for folder in folders1:
        f = check_file_path(folder, "")
        if f != '' and f not in folders:
            folders.append(f)
    return folders


def check_file_path(folder: str, image_file: str) -> str:
    file_path = folder + image_file
    try:
        if Path(file_path).exists():
            return file_path
    except OSError:
        print("bad path:", file_path)
    return ''
# import os
# from pathlib import Path
# from typing import List, Dict
#
# import bpy
#
# from export_mdl import constants
# from export_mdl.classes.War3Material import War3Material
# from export_mdl.classes.War3Model import War3Model
# from export_mdl.classes.War3Texture import War3Texture
# from export_mdl.properties.War3Preferences import War3Preferences
#
#
# def create_material(model: War3Model, team_color: str) -> Dict[str, bpy.types.Material]:
#     print("creating materials")
#     preferences: War3Preferences = bpy.context.preferences.addons.get('export_mdl').preferences
#
#     folders = get_folders(preferences.alternativeResourceFolder, preferences.resourceFolder, model.file)
#     texture_ext = get_texture_ext(preferences.textureExtension)
#
#     bpy_images: Dict[str, bpy.types.Image] = {}
#     for texture in model.textures:
#         bpy_image = get_image(folders, team_color, texture, texture_ext)
#         bpy_images[texture.texture_path] = bpy_image
#
#     bpy_materials: Dict[str, bpy.types.Material] = {}
#     for i, material in enumerate(model.materials):
#         print("material #" + str(i), material)
#         bpy_images_of_layer: List[bpy.types.Image] = []
#         for layer in material.layers:
#             bpy_images_of_layer.append(bpy_images[layer.texture.texture_path])
#
#         bpy_material = create_bpy_material(bpy_images_of_layer, material)
#
#         bpy_materials[str(i)] = bpy_material
#
#     return bpy_materials
#
#
# def create_bpy_material(bpy_images_of_layer: List[bpy.types.Image], material: War3Material):
#     material_name = bpy_images_of_layer[-1].filepath.split(os.path.sep)[-1].split('.')[0]
#     bpy_material: bpy.types.Material = bpy.data.materials.new(name=material_name)
#     bpy_material.shadow_method = 'NONE'
#     bpy_material.use_nodes = True
#
#     bpy_material.diffuse_color = (1.0, 1.0, 1.0, 1.0)
#     texture_slot_index = 0
#     material_node_tree = bpy_material.node_tree
#     shader_node: bpy.types.Node = material_node_tree.nodes.get("Principled BSDF")
#     node_width: float = shader_node.width
#     color_input_socket = shader_node.inputs.get("Base Color")
#     mix_node = get_new_node(node_width + 200, 0, material_node_tree, "ShaderNodeMixRGB")
#     mix_node.blend_type = 'MULTIPLY'
#     mix_node.inputs[0].default_value = 1.0
#     color_node = get_new_node(node_width + 200, 0, material_node_tree, "ShaderNodeRGB")
#     material_node_tree.links.new(color_node.outputs.get("Color"), mix_node.inputs.get("Color1"))
#     material_node_tree.links.new(color_node.outputs.get("Color"), mix_node.inputs.get("Color1"))
#     material_node_tree.links.new(mix_node.outputs.get("Color"), color_input_socket)
#
#     if material.is_hd:
#         bpy_material.blend_method = 'HASHED'
#         bpy_material.shadow_method = 'HASHED'
#         diffuse = get_new_node(node_width + 50, 0, material_node_tree, 'ShaderNodeMixRGB')
#         diffuse.blend_type = 'COLOR'
#
#         for i, bpy_image in enumerate(bpy_images_of_layer):
#             texture_mat_node = get_new_node(node_width + 350, 200 - 200 * i, material_node_tree, 'ShaderNodeTexImage')
#             texture_mat_node.image = bpy_image
#             if i == 0:
#                 material_node_tree.links.new(texture_mat_node.outputs.get("Color"), diffuse.inputs.get("Color1"))
#                 material_node_tree.links.new(diffuse.outputs.get("Color"), color_input_socket)
#                 material_node_tree.links.new(texture_mat_node.outputs.get("Alpha"), shader_node.inputs.get("Alpha"))
#             elif i == 1:
#                 normal_map = get_new_node(node_width + 50, 200 - 200 * i, material_node_tree, 'ShaderNodeNormalMap')
#                 normal_map.colorspace_settings.name = 'NONCOLOR'
#                 material_node_tree.links.new(texture_mat_node.outputs.get("Color"), normal_map.inputs.get("Color"))
#                 material_node_tree.links.new(normal_map.outputs.get("Normal"), shader_node.inputs.get("Normal"))
#             elif i == 2:
#                 orm = get_new_node(node_width + 50, 200 - 200 * i, material_node_tree, 'ShaderNodeSeparateColor')
#
#                 roughthness_inv = get_new_node(node_width, 200 - 200 * i, material_node_tree, "ShaderNodeMath")
#                 roughthness_inv.operation = 'SUBTRACT'
#                 roughthness_inv.inputs[0].default_value = 1
#
#
#                 material_node_tree.links.new(texture_mat_node.outputs.get("Color"), orm.inputs[0])
#                 # I don't currently know how to do occlusion
#                 material_node_tree.links.new(orm.outputs[1], roughthness_inv.inputs[1])
#                 material_node_tree.links.new(roughthness_inv.outputs[0], shader_node.inputs.get("Roughness"))
#                 material_node_tree.links.new(orm.outputs[2], shader_node.inputs.get("Metallic"))
#                 material_node_tree.links.new(texture_mat_node.outputs.get("Alpha"), diffuse.inputs[0])
#             elif i == 3:
#                 material_node_tree.links.new(texture_mat_node.outputs.get("Color"), shader_node.inputs.get("Emission"))
#             elif i == 4:
#                 team_color = get_new_node(node_width + diffuse.width + 50, 0, material_node_tree, 'ShaderNodeRGB')
#                 team_color.outputs[0].default_value = (1, 0, 0, 1)
#                 material_node_tree.links.new(team_color.outputs.get("Color"), diffuse.inputs.get("Color2"))
#             # else:
#             # skip the environmental map, possibly change the world's map to it
#             print(bpy_image.filepath, " at place ", i)
#     else:
#         for i, bpy_image in enumerate(bpy_images_of_layer):
#             texture_mat_node = get_new_node(node_width + 50, 200 - 100 * i, material_node_tree, 'ShaderNodeTexImage')
#             texture_mat_node.image = bpy_image
#             material_node_tree.links.new(texture_mat_node.outputs.get("Color"), color_input_socket)
#     return bpy_material
#
#
# def get_wc3_base_node(material_name: str):
#     bpy_material: bpy.types.Material = bpy.data.materials.new(name=material_name)
#     bpy_material.shadow_method = 'NONE'
#     bpy_material.use_nodes = True
#
#     bpy_material.blend_method = 'HASHED'
#     bpy_material.shadow_method = 'HASHED'
#
#     bpy_material.diffuse_color = (1.0, 1.0, 1.0, 1.0)
#     texture_slot_index = 0
#     material_node_tree = bpy_material.node_tree
#     shader_node: bpy.types.Node = material_node_tree.nodes.get("Principled BSDF")
#     set_input(shader_node, ('Specular IOR Level', 'Specular'), 0.0)  # no specular
#     set_input(shader_node, ('Roughness',), 1.0)  # full roughness
#
#
#     node_width: float = shader_node.width
#     color_input_socket = shader_node.inputs.get("Base Color")
#     mix_node = get_new_node(node_width + 20, 0, material_node_tree, "ShaderNodeMixRGB")
#     mix_node.blend_type = 'MULTIPLY'
#     mix_node.inputs[0].default_value = 1.0
#     color_node = get_new_node(node_width + 200, 0, material_node_tree, "ShaderNodeRGB")
#     color_node.outputs[0].default_value = (1, 1, 1, 1)
#     color_node.name = 'Geoset Anim Color'
#     material_node_tree.links.new(color_node.outputs.get("Color"), mix_node.inputs.get("Color1"))
#     material_node_tree.links.new(color_node.outputs.get("Color"), mix_node.inputs.get("Color1"))
#     material_node_tree.links.new(mix_node.outputs.get("Color"), shader_node.inputs.get("Base Color"))
#
#     diffuse = material_node_tree.nodes.new('ShaderNodeMixRGB')
#     diffuse.location.x -= node_width + 50
#     diffuse.blend_type = 'COLOR'
#
#
#
# def get_new_node(loc_x: float,
#                  loc_y: float,
#                  material_node_tree: bpy.types.NodeTree,
#                  node_type: str):
#     new_node = material_node_tree.nodes.new(node_type)
#     new_node.location.x -= loc_x
#     new_node.location.y += loc_y
#     return new_node
#
#
# def get_texture_ext(texture_exc: str):
#     if texture_exc == '':
#         print("No texture extension to replace blp with set in addon preferences")
#         texture_exc = 'png'
#     if texture_exc[0] != '.':
#         texture_exc = '.' + texture_exc
#     return texture_exc
#
#
# def get_image(folders: List[str],
#               team_color: str,
#               texture: War3Texture,
#               texture_exc: str):
#     image_file = get_image_file(team_color, texture, texture_exc)
#     print("loading:", image_file)
#     file_path_parts = image_file.split(os.path.sep)
#
#     file_name = file_path_parts[-1].split('.')[0]
#     bpy_image = bpy.data.images.new(file_name, 0, 0)
#     bpy_image.source = 'FILE'
#
#     bpy_image.filepath = find_file(file_path_parts, folders, image_file)
#     return bpy_image
#
#
# def get_image_file(team_color: str,
#                    texture: War3Texture,
#                    texture_exc: str) -> str:
#     if texture.replaceable_id == 1:  # Team Color
#         image_file = constants.TEAM_COLOR_IMAGES[team_color]
#     elif texture.replaceable_id == 2:  # Team Glow
#         image_file = constants.TEAM_GLOW_IMAGES[team_color]
#     else:
#         image_file = texture.texture_path
#     if image_file.endswith(".blp"):
#         image_file = image_file.split(".blp")[0] + texture_exc
#     image_file = image_file.replace("/", os.path.sep)
#     image_file = image_file.replace("\\", os.path.sep)
#     return image_file
#
#
# def find_file(file_path_parts: List[str],
#               folders: List[str],
#               image_file: str) -> str:
#     for i in range(len(file_path_parts)):
#         split = image_file.split(os.path.sep, i)
#         image_file = split[len(split) - 1]
#
#         for folder in folders:
#             file_path = check_file_path(folder, image_file)
#             if 0 < len(file_path):
#                 return file_path
#     return ''
#
#
# def get_folders(alt_folder: str,
#                 resource_folder: str,
#                 model_file: str) -> List[str]:
#     if resource_folder == '':
#         print("No resource folder set in addon preferences")
#
#     elif not resource_folder.endswith(os.path.sep):
#         # elif not resource_folder.endswith("\\"):
#         resource_folder += os.path.sep
#     if alt_folder == '':
#         print("No alt resource folder set in addon preferences")
#     elif not alt_folder.endswith(os.path.sep):
#         alt_folder += os.path.sep
#
#     model_folder = str(Path(model_file).parent)
#     if not model_folder.endswith(os.path.sep):
#         model_folder += os.path.sep
#     # print("model folder:", model_folder)
#     textures1 = "Textures" + os.path.sep
#     textures2 = "textures" + os.path.sep
#     folders1 = [model_folder,
#                 model_folder + textures1, model_folder + textures2,
#                 resource_folder, alt_folder,
#                 resource_folder + textures1, resource_folder + textures2,
#                 alt_folder + textures1, alt_folder + textures2]
#     folders = []
#     for folder in folders1:
#         f = check_file_path(folder, "")
#         if f != '' and f not in folders:
#             folders.append(f)
#     return folders
#
#
# def check_file_path(folder: str, image_file: str) -> str:
#     file_path = folder + image_file
#     try:
#         if Path(file_path).exists():
#             return file_path
#     except OSError:
#         print("bad path:", file_path)
#     return ''
