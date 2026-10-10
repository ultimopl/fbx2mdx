
class War3Texture:
    def __init__(self, texture_path="Textures\\white.blp", replaceable_id=0):
        self.texture_path: str = texture_path
        self.replaceable_id: int = replaceable_id
        self.wrap_width: bool = False
        self.wrap_height: bool = False

    def _key(self):
        return self.texture_path, self.replaceable_id, self.wrap_width, self.wrap_height

    # Layers pointing at the same image share one texture entry.
    def __eq__(self, other):
        if isinstance(other, War3Texture):
            return self._key() == other._key()
        return NotImplemented

    def __hash__(self):
        return hash(self._key())
