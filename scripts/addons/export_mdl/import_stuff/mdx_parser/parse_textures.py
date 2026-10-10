from typing import List

from ...classes.War3Texture import War3Texture
from . import binary_reader


def parse_textures(data: bytes):
    r = binary_reader.Reader(data)
    data_size = len(data)

    if data_size % 268 != 0:
        raise Exception('bad Texture data (size % 268 != 0)')

    textures_count = data_size // 268
    textures: List[War3Texture] = []

    for _ in range(textures_count):
        texture = War3Texture()
        texture.replaceable_id = r.getf('<I')[0]
        texture.image_file_name = r.gets(260)
        texture.texture_path = texture.image_file_name
        flags = r.getf('<I')[0]
        texture.wrap_width = bool(flags & 1)
        texture.wrap_height = bool(flags & 2)
        textures.append(texture)

    return textures
