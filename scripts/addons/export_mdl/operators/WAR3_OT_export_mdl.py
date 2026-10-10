import os
import shutil
import subprocess

import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, IntProperty
from bpy.types import Operator
from bpy_extras.io_utils import orientation_helper, ExportHelper, axis_conversion
from mathutils import Matrix

from ..classes.War3ExportSettings import War3ExportSettings


class War3ExportMixin:
    """Shared properties/logic of the MDL and MDX export operators."""
    filename_ext = ".mdl"

    filepath: StringProperty(
            subtype="FILE_PATH"
            )

    use_selection: BoolProperty(
            name="Selected Objects",
            description="Export only selected objects on visible layers",
            default=False,
            )

    global_scale: FloatProperty(
            name="Scale",
            min=0.0001,
            max=100000.0,
            default=1,
            )

    optimize_animation: BoolProperty(
            name="Optimize Keyframes",
            description="Remove keyframes if the resulting motion deviates less than the tolerance value."
            )

    demote_to_helper: BoolProperty(
            name="Demote Bones To Helpers",
            description="Save bones not used for mesh as helpers.",
            default=True
            )

    use_actions: BoolProperty(
            name="Use Actions",
            description="Use actions instead of mdl-sequences"
            )

    use_skinweights: BoolProperty(
            name="Use SkinWeights",
            description="Use skin weights instead of vertex groups"
            )

    matrix_weight_threshold: FloatProperty(
            name="Bone Weight Cutoff",
            description="Classic MDX averages all bones of a vertex equally; ignore bones whose weight "
                        "is below this fraction of the vertex's strongest bone",
            min=0.0, max=1.0,
            default=0.3,
            )

    matrix_max_bones: IntProperty(
            name="Max Bones Per Vertex",
            min=1, max=8,
            default=4,
            )

    optimize_tolerance: FloatProperty(
            name="Tolerance",
            min=0.001,
            soft_max=0.1,
            default=0.05,
            subtype='DISTANCE',
            unit='LENGTH'
            )

    def execute(self, context: bpy.types.Context):
        filepath = self.filepath
        filepath = bpy.path.ensure_ext(filepath, self.filename_ext)

        settings: War3ExportSettings = War3ExportSettings()
        settings.global_matrix = axis_conversion(
            to_forward=self.axis_forward,
            to_up=self.axis_up,
        ).to_4x4() @ Matrix.Scale(self.global_scale, 4)

        settings.use_selection = self.use_selection
        settings.optimize_animation = self.optimize_animation
        settings.demote_to_helper = self.demote_to_helper
        settings.optimize_tolerance = self.optimize_tolerance
        settings.use_actions = self.use_actions
        settings.use_skinweights = self.use_skinweights
        settings.matrix_weight_threshold = self.matrix_weight_threshold
        settings.matrix_max_bones = self.matrix_max_bones

        from ..export_mdl import export_mdl
        if self.filename_ext == ".mdx":
            mdl_path = filepath + ".tmp.mdl"
            export_mdl.save(self, context, settings, filepath=mdl_path, mdl_version=800)
            try:
                mdl_to_mdx(mdl_path, filepath)
            except RuntimeError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            finally:
                if os.path.exists(mdl_path):
                    os.remove(mdl_path)
        else:
            export_mdl.save(self, context, settings, filepath=filepath, mdl_version=800)

        return {'FINISHED'}

    def draw(self, context: bpy.types.Context):
        layout = self.layout

        layout.prop(self, "use_selection")
        layout.prop(self, "global_scale")
        layout.prop(self, "axis_forward")
        layout.prop(self, "axis_up")
        layout.separator()
        layout.prop(self, 'optimize_animation')
        layout.prop(self, 'demote_to_helper')
        layout.prop(self, 'use_actions')
        layout.prop(self, 'use_skinweights')
        if not self.use_skinweights:
            layout.prop(self, 'matrix_weight_threshold')
            layout.prop(self, 'matrix_max_bones')
        if self.optimize_animation:
            box = layout.box()
            box.label(text="EXPERIMENTAL", icon='ERROR')
            layout.prop(self, 'optimize_tolerance')
        if self.use_actions:
            box = layout.box()
            box.label(text="EXPERIMENTAL", icon='ERROR')
            box.label(text="Will export action and not marker based sequences. "
                           "This does not yet support Rarity or NonLooping")
        if self.use_skinweights:
            box = layout.box()
            box.label(text="EXPERIMENTAL", icon='ERROR')
            box.label(text="Will export with skin weights and leave vertex groups empty.")
            # layout.prop(self, 'use_actions')


def mdl2mdx_script() -> str:
    # The addon lives in tools/fbx2mdx/scripts/addons/export_mdl (possibly symlinked
    # into a Blender bundle); mdl2mdx.js sits in tools/fbx2mdx.
    env = os.environ.get("FBX2MDX_MDL2MDX")
    if env:
        return env
    addon_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return os.path.join(addon_dir, "..", "..", "..", "mdl2mdx.js")


def find_node() -> str:
    # Prefer the Node.js that setup.sh installs into tools/fbx2mdx/deps.
    env = os.environ.get("FBX2MDX_NODE")
    if env:
        return env
    local = os.path.join(os.path.dirname(os.path.normpath(mdl2mdx_script())), "deps", "node", "bin", "node")
    return local if os.path.exists(local) else shutil.which("node")


def mdl_to_mdx(mdl_path: str, mdx_path: str):
    node = find_node()
    script = os.path.normpath(mdl2mdx_script())
    if node is None:
        raise RuntimeError("MDX export needs Node.js ('node' not found in PATH); export .mdl instead")
    if not os.path.exists(script):
        raise RuntimeError("mdl2mdx.js not found at %s (set FBX2MDX_MDL2MDX)" % script)
    result = subprocess.run([node, script, mdl_path, mdx_path], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("MDL -> MDX conversion failed: %s" % (result.stderr.strip() or result.stdout.strip()))


@orientation_helper(axis_forward='Y', axis_up='Z')
class WAR3_OT_export_mdl(War3ExportMixin, Operator, ExportHelper):
    """MDL Exporter"""
    bl_idname = 'export.mdl_exporter'
    bl_description = 'Warctaft 3 MDL Exporter'
    bl_label = 'Export .MDL'
    filename_ext = ".mdl"

    filter_glob: StringProperty(
            default="*.mdl", options={'HIDDEN'}
            )


@orientation_helper(axis_forward='Y', axis_up='Z')
class WAR3_OT_export_mdx(War3ExportMixin, Operator, ExportHelper):
    """MDX Exporter"""
    bl_idname = 'export.mdx_exporter'
    bl_description = 'Warcraft 3 MDX Exporter (writes MDL, converts with mdl2mdx.js)'
    bl_label = 'Export .MDX'
    filename_ext = ".mdx"

    filter_glob: StringProperty(
            default="*.mdx", options={'HIDDEN'}
            )
