class ModelError(ValueError):
    """Actionable input or model failure; never substitute zero risk."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ReviewRequired(ModelError):
    """Some records failed validation or hazard lookup; the user must fix them or explicitly run on the rest."""

    def __init__(self, issues, accepted_count):
        self.issues = issues
        self.accepted_count = accepted_count
        errors = sum(i["severity"] == "error" for i in issues)
        super().__init__(
            "portfolio_review_required",
            f"{errors} record(s) cannot be modelled; fix them or explicitly run on the {accepted_count} valid record(s)",
        )
