import math
from operator import itemgetter
from typing import SupportsRound, List, Tuple

decimal_places = 5


def rnd(val: float) -> float:
    return round(val, decimal_places)


def rnd(val: int) -> int:
    return round(val, decimal_places)


# def rnd(val: SupportsRound[_Protocol[T_co]]):
#     return round(val, decimal_places)


def float2str(value: float) -> str:
    return ('%.6f' % value).rstrip('0').rstrip('.')


def calc_bounds_radius(min_ext, max_ext):
    x = (max_ext[0] - min_ext[0])/2
    y = (max_ext[1] - min_ext[1])/2
    z = (max_ext[2] - min_ext[2])/2
    return math.sqrt(math.pow(x, 2) + math.pow(y, 2) + math.pow(z, 2))


def calc_extents(vertices: List[List[float]]) -> Tuple[List[float], List[float]]:
    # max_extents = [max(vertices, key=itemgetter(i))[i] for i in range(3)]
    # min_extents = [min(vertices, key=itemgetter(i))[i] for i in range(3)]

    if not len(vertices):
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]

    max_extents = [-math.inf, -math.inf, -math.inf]
    min_extents = [math.inf, math.inf, math.inf]

    for vertex in vertices:
        for i, v in enumerate(vertex):
            max_extents[i] = max(max_extents[i], v)
            min_extents[i] = min(min_extents[i], v)

    return min_extents, max_extents


def find_action_fcurve(action, data_path, index=-1):
    if action is None:
        return None
    if hasattr(action, 'fcurves'):
        if index >= 0:
            return action.fcurves.find(data_path, index=index)
        else:
            return action.fcurves.find(data_path)
    if hasattr(action, 'layers'):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, 'channelbags'):
                    for cbag in strip.channelbags:
                        fcurve = cbag.fcurves.find(data_path, index=index) if index >= 0 else cbag.fcurves.find(data_path)
                        if fcurve is not None:
                            return fcurve
                if hasattr(action, 'slots'):
                    for slot in action.slots:
                        try:
                            cbag = strip.channelbag(slot)
                            if cbag:
                                fcurve = cbag.fcurves.find(data_path, index=index) if index >= 0 else cbag.fcurves.find(data_path)
                                if fcurve is not None:
                                    return fcurve
                        except Exception:
                            pass
    return None


def get_curve(obj, data_paths):
    if obj.animation_data and obj.animation_data.action:
        for path in data_paths:
            curve = find_action_fcurve(obj.animation_data.action, path)
            if curve is not None:
                return curve
    return None


def get_curves(obj, data_path, indices):
    curves = {}
    if obj.animation_data and obj.animation_data.action:
        for index in indices:
            curve = find_action_fcurve(obj.animation_data.action, data_path, index=index)
            if curve is not None:
                curves[(data_path.split('.')[-1], index)] = curve
    if len(curves):
        return curves
    return None


class FCurvesCompat:
    """Legacy-style `action.fcurves` access for Blender 4.4+ slotted actions.

    Blender 5 removed Action.fcurves; curves live in layer -> strip -> channelbag(slot).
    This wraps the channelbag collection with the old new/find/values/[] interface,
    including the `action_group` argument of FCurves.new.
    """

    def __init__(self, channelbag):
        self.bag = channelbag

    def new(self, data_path, index=0, action_group=""):
        fcurve = self.bag.fcurves.new(data_path, index=index)
        if action_group:
            group = self.bag.groups.get(action_group) or self.bag.groups.new(action_group)
            fcurve.group = group
        return fcurve

    def find(self, data_path, index=0):
        return self.bag.fcurves.find(data_path, index=index)

    def values(self):
        return list(self.bag.fcurves)

    def __getitem__(self, i):
        return self.bag.fcurves[i]

    def __iter__(self):
        return iter(self.bag.fcurves)

    def __len__(self):
        return len(self.bag.fcurves)


def action_fcurves(action, id_type='OBJECT'):
    """Return an fcurve collection for `action`, creating slot/layer/strip as needed."""
    if not hasattr(action, 'layers'):
        return action.fcurves  # Blender < 4.4
    slot = next((s for s in action.slots if s.target_id_type == id_type), None)
    if slot is None:
        slot = action.slots.new(id_type=id_type, name=action.name)
    layer = action.layers[0] if len(action.layers) else action.layers.new("Layer")
    strip = layer.strips[0] if len(layer.strips) else layer.strips.new(type='KEYFRAME')
    return FCurvesCompat(strip.channelbag(slot, ensure=True))


def assign_action(id_data, action):
    """Assign `action` to an ID and pick a matching slot (needed on Blender 4.4+)."""
    if id_data.animation_data is None:
        id_data.animation_data_create()
    anim_data = id_data.animation_data
    anim_data.action = action
    if action is not None and hasattr(anim_data, 'action_slot') and anim_data.action_slot is None:
        slots = anim_data.action_suitable_slots
        if len(slots):
            anim_data.action_slot = slots[0]
