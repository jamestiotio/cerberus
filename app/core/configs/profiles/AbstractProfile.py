

class AbstractProfile:

    def __init__(self, profile_id: str):
        self.id = profile_id

    def get_id(self) -> str:
        return self.id
