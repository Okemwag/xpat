class ModelError(ValueError):
    """Actionable input or model failure; never substitute zero risk."""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
