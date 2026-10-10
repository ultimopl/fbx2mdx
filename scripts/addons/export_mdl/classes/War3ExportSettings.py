from mathutils import Matrix


class War3ExportSettings:
    def __init__(self):
        self.global_matrix = Matrix()
        self.use_selection = False
        self.optimize_animation = False
        self.demote_to_helper = True
        self.optimize_tolerance = 0.05
        self.use_actions = False
        self.use_skinweights = False
        # Classic (v800) matrix groups weight every bone equally, so drop bones whose
        # weight is below this fraction of the vertex's strongest bone.
        self.matrix_weight_threshold = 0.3
        self.matrix_max_bones = 4
