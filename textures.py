"""Turn whatever colours a model's materials into BLP textures MDX can use.

An MDX layer can only sample a texture, so every material is classified by what
feeds its shader's Base Color and handled as one of:

  image  an image texture (packed in a .glb/.fbx or a file on disk) -> converted
  flat   a constant colour                                          -> colour atlas
  vcol   vertex colours, one colour per face                        -> colour atlas
  bake   anything else (gradients, procedurals, image x colour)     -> Cycles bake

Atlas and bake materials get a new UV layer `fbx2mdx` (made active, which is
what the exporter reads); it starts as a copy of the old active layer so faces
of image materials keep their UVs.
"""
import math
import os
import re

import bpy
import numpy as np

import blp

UV_NAME = "fbx2mdx"


def srgb(lin):
    lin = np.clip(np.asarray(lin, np.float64), 0, 1)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)


# --- material inspection --------------------------------------------------

def upstream(socket):
    """(node, output socket) feeding `socket`, skipping reroutes; None when unlinked."""
    while socket.is_linked:
        link = socket.links[0]
        node = link.from_node
        if node.type != 'REROUTE':
            return node, link.from_socket
        socket = node.inputs[0]
    return None


def find_upstream(socket, node_type):
    """First node of `node_type` anywhere upstream of `socket` (depth-first)."""
    src = upstream(socket)
    if src is None:
        return None
    node = src[0]
    if node.type == node_type:
        return src
    for inp in node.inputs:
        found = find_upstream(inp, node_type)
        if found:
            return found
    return None


def shader_inputs(mat):
    """(base colour socket, alpha socket or None) of the material's surface shader."""
    if mat is None or mat.node_tree is None:
        return None, None
    nt = mat.node_tree
    out = nt.get_output_node('ALL') or next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if out is None:
        return None, None
    src = upstream(out.inputs["Surface"])
    if src is None:
        return None, None
    shader = src[0]
    base = shader.inputs.get("Base Color") or shader.inputs.get("Color")
    return base, shader.inputs.get("Alpha")


def color_attribute(mesh, name=""):
    attrs = mesh.color_attributes
    if name:
        return attrs.get(name)
    if not len(attrs):
        return None
    idx = attrs.render_color_index
    return attrs[idx if 0 <= idx < len(attrs) else 0]


def classify(mat, meshes, use_vertex_colors):
    """Return a dict describing where the material's colour comes from."""
    base, alpha = shader_inputs(mat)
    if base is None:
        # No shader with a colour input (or no nodes): use the viewport colour.
        color = tuple(mat.diffuse_color) if mat is not None else (0.8, 0.8, 0.8, 1.0)
        return {"kind": "flat", "color": color}

    src = upstream(base)
    if src is None:
        color = tuple(base.default_value)
        if use_vertex_colors and any(color_attribute(m) for m in meshes):
            return {"kind": "vcol", "attr": "", "factor": color, "socket": None}
        return {"kind": "flat", "color": color}

    node, out = src
    image = {"kind": "image", "alpha": alpha, "blend": getattr(mat, "surface_render_method", "") == 'BLENDED'}
    if node.type == 'TEX_IMAGE' and out.name == "Color" and node.image is not None:
        return dict(image, node=node)
    if node.type == 'VERTEX_COLOR' and out.name == "Color":
        return {"kind": "vcol", "attr": node.layer_name, "factor": (1, 1, 1, 1), "socket": out}
    tinted = image_times_vcol(node)
    if tinted:
        # glTF COLOR_0 x texture; mostly an all-white COLOR_0, checked in build().
        return dict(image, node=tinted[0], attr=tinted[1], socket=out)
    return {"kind": "bake", "socket": out}


def image_times_vcol(node):
    """(image node, colour attribute name) when `node` multiplies an image by vertex colours."""
    if node.type == 'MIX' and node.data_type == 'RGBA':
        fac, a, b = node.inputs["Factor"], node.inputs[6], node.inputs[7]
    elif node.type == 'MIX_RGB':
        fac, a, b = node.inputs["Fac"], node.inputs["Color1"], node.inputs["Color2"]
    else:
        return None
    if node.blend_type != 'MULTIPLY' or fac.is_linked or fac.default_value < 0.999:
        return None
    ends = [upstream(s) for s in (a, b)]
    if None in ends:
        return None
    by_type = {n.type: (n, o) for n, o in ends}
    img, vc = by_type.get('TEX_IMAGE'), by_type.get('VERTEX_COLOR')
    if not img or not vc or img[1].name != "Color" or vc[1].name != "Color" or img[0].image is None:
        return None
    return img[0], vc[0].layer_name


# --- per-face colours -----------------------------------------------------

def loop_faces(mesh):
    """Polygon index of every loop."""
    starts = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    return starts, np.repeat(np.arange(len(mesh.polygons)), np.diff(np.append(starts, len(mesh.loops))))


def face_colors(obj, slots, attr_name, factor):
    """Linear RGBA per polygon of the given material slots, or None unless each face is one colour.

    Returns an array over all polygons; faces outside `slots` are left as zeros."""
    mesh = obj.data
    attr = color_attribute(mesh, attr_name)
    if attr is None or attr.domain not in ('POINT', 'CORNER'):
        return None
    n = len(attr.data)
    values = np.empty(n * 4, np.float32)
    attr.data.foreach_get("color", values)
    values = values.reshape(n, 4)
    if attr.domain == 'POINT':
        vidx = np.empty(len(mesh.loops), np.int32)
        mesh.loops.foreach_get("vertex_index", vidx)
        values = values[vidx]
    starts, loop_face = loop_faces(mesh)
    first = values[starts]
    used = np.isin(material_index_array(mesh), slots)
    loops = used[loop_face]
    if np.abs(values[loops] - first[loop_face[loops]]).max(initial=0) > 1.5 / 255:
        return None
    return np.where(used[:, None], first * np.asarray(factor, np.float32), 0)


def material_face_colors(objs, mat, attr_name, factor):
    """{object name: face_colors} over the objects using `mat`, or None if any face is not uniform."""
    faces = {}
    for o in objs:
        slots = [i for i, m in enumerate(o.data.materials) if m is mat]
        if slots:
            fc = face_colors(o, slots, attr_name, factor)
            if fc is None:
                return None
            faces[o.name] = fc
    return faces


# --- object helpers -------------------------------------------------------

def mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == 'MESH']


def material_index_array(mesh):
    idx = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("material_index", idx)
    return idx


def select_only(objs):
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


def fbx2mdx_uv(mesh):
    """The `fbx2mdx` UV layer, created as a copy of the active one and made active."""
    layer = mesh.uv_layers.get(UV_NAME)
    if layer is None:
        layer = mesh.uv_layers.new(name=UV_NAME, do_init=True)
    mesh.uv_layers.active = layer
    layer.active_render = True
    return layer


def split_mixed(objs, bake_mats):
    """Split objects mixing baked and non-baked materials, so the bake only touches its faces."""
    result = []
    for o in objs:
        mats = {m for m in o.data.materials}
        if mats <= bake_mats or not (mats & bake_mats):
            result.append(o)
            continue
        before = set(bpy.context.scene.objects)
        select_only([o])
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.separate(type='MATERIAL')
        bpy.ops.object.mode_set(mode='OBJECT')
        result += [o] + [n for n in bpy.context.scene.objects if n not in before]
    return result


# --- texture production ---------------------------------------------------

class Writer:
    def __init__(self, args, out_dir, log):
        self.args, self.out_dir, self.log = args, out_dir, log
        self.stems = set()

    def stem(self, name):
        base = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_.") or "texture"
        stem, i = base, 2
        while stem.lower() in self.stems:
            stem, i = "%s_%d" % (base, i), i + 1
        self.stems.add(stem.lower())
        return stem

    def path(self, stem):
        d = self.args.texture_dir
        return "%s\\%s.blp" % (d, stem) if d else stem + ".blp"

    def write(self, stem, rgba, alpha):
        file = os.path.join(self.out_dir, stem + ".blp")
        w, h = blp.write_blp(file, rgba, alpha=alpha, max_size=self.args.texture_size,
                             quality=self.args.texture_quality)
        self.log("texture %s (%dx%d%s) -> %s" % (os.path.basename(file), w, h,
                                                 ", alpha" if alpha else "", self.path(stem)))
        return self.path(stem)


def image_rgba(img):
    """Top-down sRGB float RGBA of a Blender image, or None if it has no pixels."""
    w, h = img.size
    if not w or not h:
        return None
    try:
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
    except (RuntimeError, ValueError):
        return None
    px = px.reshape(h, w, 4)[::-1].astype(np.float64)
    if img.is_float and img.colorspace_settings.name.lower().startswith(("linear", "scene linear")):
        px[..., :3] = srgb(px[..., :3])
    return px


def alpha_channel(alpha_socket, shape):
    """Alpha plane at `shape` (h, w) from the shader's Alpha input, or None when opaque."""
    if alpha_socket is None:
        return None
    if not alpha_socket.is_linked:
        a = float(alpha_socket.default_value)
        return None if a >= 0.999 else np.full(shape, a)
    found = find_upstream(alpha_socket, 'TEX_IMAGE')
    if found is None or found[0].image is None:
        return None
    node, out = found
    px = image_rgba(node.image)
    if px is None:
        return None
    plane = px[..., 3] if out.name == "Alpha" else px[..., :3].mean(axis=2)
    if plane.shape != shape:
        plane = blp._resize(plane[..., None], *shape)[..., 0]
    return None if plane.min() >= 0.999 else plane


def do_images(entries, writer):
    done = {}
    for mat, info in entries:
        img = info["node"].image
        alpha_src = find_upstream(info["alpha"], 'TEX_IMAGE') if info["alpha"] is not None else None
        key = (img.name, alpha_src[0].image.name if alpha_src and alpha_src[0].image else None)
        if key not in done:
            name = os.path.splitext(bpy.path.basename(img.filepath))[0] if img.filepath else img.name
            name = os.path.splitext(name)[0] if re.search(r"\.(png|jpe?g|tga|bmp|tiff?|webp|exr|dds)$", name, re.I) else name
            rgba = image_rgba(img)
            if rgba is None:
                stem = writer.stem(name)
                writer.log("WARNING: image %s has no pixels (missing file?); write %s yourself"
                           % (img.name, writer.path(stem)))
                done[key] = (writer.path(stem), False)
            else:
                plane = alpha_channel(info["alpha"], rgba.shape[:2])
                if plane is not None:
                    rgba[..., 3] = plane
                done[key] = (writer.write(writer.stem(name), rgba, plane is not None), plane is not None)
        path, has_alpha = done[key]
        set_layer(mat, path, ('Blend' if info["blend"] else 'Transparent') if has_alpha else 'None')


def do_atlas(entries, objs, writer, out_stem):
    """Constant and per-face vertex colours -> one atlas, UVs snapped to cell centres."""
    colors = {}  # 8-bit sRGB tuple -> cell index

    def cell(lin):
        key = tuple(int(round(v * 255)) for v in srgb(lin[:3])) + (255,)
        return colors.setdefault(key, len(colors))

    plans = []  # (obj, material slot index, per-face cell array or single cell)
    for mat, info in entries:
        for o in objs:
            for slot, m in enumerate(o.data.materials):
                if m is not mat:
                    continue
                if info["kind"] == "flat":
                    plans.append((o, slot, cell(np.asarray(info["color"]))))
                else:
                    fc = info["faces"][o.name]
                    cells = np.zeros(len(fc), np.int64)
                    for f in np.flatnonzero(material_index_array(o.data) == slot):
                        cells[f] = cell(fc[f])
                    plans.append((o, slot, cells))

    n = len(colors)
    grid = 1 << max(0, math.ceil(math.log2(math.ceil(math.sqrt(n)))))
    cell_px = max(4, min(16, writer.args.texture_size // grid))
    size = grid * cell_px
    img = np.zeros((size, size, 4))
    for key, i in colors.items():
        y, x = divmod(i, grid)
        img[y * cell_px:(y + 1) * cell_px, x * cell_px:(x + 1) * cell_px] = np.asarray(key) / 255.0
    path = writer.write(writer.stem(out_stem + "_colors"), img, False)

    centers = np.array([((i % grid + 0.5) / grid, 1 - (i // grid + 0.5) / grid) for i in range(n)])
    for o, slot, cells in plans:
        mesh = o.data
        uv = fbx2mdx_uv(mesh)
        loop_uv = np.empty(len(mesh.loops) * 2, np.float32)
        uv.data.foreach_get("uv", loop_uv)
        loop_uv = loop_uv.reshape(-1, 2)
        mat_idx = material_index_array(mesh)
        _, loop_face = loop_faces(mesh)
        mask = mat_idx[loop_face] == slot
        face_cells = np.broadcast_to(cells, mat_idx.shape) if np.ndim(cells) == 0 else cells
        loop_uv[mask] = centers[face_cells[loop_face[mask]]]
        uv.data.foreach_set("uv", loop_uv.ravel())
    for mat, _ in entries:
        set_layer(mat, path, 'None')


def do_bake(entries, objs, writer, out_stem):
    mats = {mat for mat, _ in entries}
    objs = [o for o in split_mixed(objs, mats) if set(o.data.materials) & mats]
    size = writer.args.texture_size
    scene = bpy.context.scene

    for o in objs:
        fbx2mdx_uv(o.data)
    select_only(objs)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(island_margin=4.0 / size)
    bpy.ops.object.mode_set(mode='OBJECT')

    image = bpy.data.images.new("fbx2mdx_bake", size, size, alpha=False)
    temp = []      # (node tree, node) to remove afterwards
    restore = []   # (node tree, output node, original surface socket or None)
    for mat, info in entries:
        nt = mat.node_tree
        if nt is None:
            mat.use_nodes = True
            nt = mat.node_tree
        out = nt.get_output_node('ALL') or nt.nodes.new("ShaderNodeOutputMaterial")
        surface = upstream(out.inputs["Surface"])
        restore.append((nt, out, surface[1] if surface else None))

        color = info.get("socket")
        if info["kind"] == "vcol" and color is None:  # vertex colours the importer left unwired
            attr = nt.nodes.new("ShaderNodeVertexColor")
            attr.layer_name = info["attr"]
            mul = nt.nodes.new("ShaderNodeVectorMath")
            mul.operation = 'MULTIPLY'
            mul.inputs[1].default_value = info["factor"][:3]
            nt.links.new(attr.outputs["Color"], mul.inputs[0])
            color = mul.outputs[0]
            temp += [(nt, attr), (nt, mul)]
        emit = nt.nodes.new("ShaderNodeEmission")
        if color is not None:
            nt.links.new(color, emit.inputs["Color"])
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        nt.nodes.active = tex
        temp += [(nt, emit), (nt, tex)]

    armatures = [(a, a.data.pose_position) for a in bpy.data.objects if a.type == 'ARMATURE']
    for a, _ in armatures:
        a.data.pose_position = 'REST'
    engine = scene.render.engine
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    try:
        bpy.ops.object.bake(type='EMIT', margin=4, use_clear=True, target='IMAGE_TEXTURES')
    finally:
        scene.render.engine = engine
        for a, pose in armatures:
            a.data.pose_position = pose
        for nt, out, socket in restore:
            for link in list(out.inputs["Surface"].links):
                nt.links.remove(link)
            if socket is not None:
                nt.links.new(socket, out.inputs["Surface"])
        for nt, node in temp:
            nt.nodes.remove(node)

    path = writer.write(writer.stem(out_stem), image_rgba(image), False)
    bpy.data.images.remove(image)
    for mat in mats:
        set_layer(mat, path, 'None')


def set_layer(mat, path, filter_mode):
    layer = mat.mdl_layers.add()
    layer.name = "Layer 0"
    layer.texture_type = '0'
    layer.path = path
    layer.filter_mode = filter_mode


def build(args, materials, fallback, out_stem, out_dir, log):
    """Write BLPs for `materials` (those without hand-made MDL layers) and point their layers at them."""
    objs = mesh_objects()
    users = {m: [o.data for o in objs if m in list(o.data.materials)] for m in materials}
    writer = Writer(args, out_dir, log)
    images, atlas, bake = [], [], []
    for mat in sorted(materials, key=lambda m: m.name):
        if mat is fallback and not any(color_attribute(m) for m in users[mat]):
            # No material and no colours at all: the texture is made by hand, as before.
            path = writer.path(writer.stem(out_stem))
            log("material %s -> %s (no colour information; texture not generated)" % (mat.name, path))
            set_layer(mat, path, 'None')
            continue
        info = classify(mat, users[mat], not args.no_vertex_colors)
        if info["kind"] == "image" and "attr" in info:
            faces = material_face_colors(objs, mat, info["attr"], (1, 1, 1, 1))
            # face_colors zeroes the faces of other materials, so only look at this one's.
            white = faces is not None and all(
                faces[o.name][np.isin(material_index_array(o.data), slots)].min(initial=1) >= 254 / 255
                for o in objs if o.name in faces
                for slots in [[i for i, m in enumerate(o.data.materials) if m is mat]])
            if not white:
                info = {"kind": "bake", "socket": info["socket"]}
        elif info["kind"] == "vcol":
            faces = material_face_colors(objs, mat, info["attr"], info["factor"])
            if faces is not None:
                info = dict(info, kind="atlas", faces=faces)
            elif info["socket"] is not None:
                info = {"kind": "bake", "socket": info["socket"]}
        {"image": images, "flat": atlas, "atlas": atlas, "vcol": bake, "bake": bake}[info["kind"]].append((mat, info))
        log("material %s: %s" % (mat.name, "baked" if info["kind"] in ("vcol", "bake") else info["kind"]))

    if images:
        do_images(images, writer)
    if atlas:
        do_atlas(atlas, objs, writer, out_stem)
    if bake:
        do_bake(bake, mesh_objects(), writer, out_stem)
