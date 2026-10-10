"""Startup script for `edit`: import the given model into a fresh scene."""
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert  # noqa: E402


def load():
    path = sys.argv[sys.argv.index("--") + 1]
    convert.enable_addon()
    for obj in list(bpy.data.objects):  # drop the default cube/camera/light
        bpy.data.objects.remove(obj, do_unlink=True)
    convert.import_model(path)
    for action in bpy.data.actions:
        action.use_fake_user = True
    print("[edit] loaded", path)


load()
