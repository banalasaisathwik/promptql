from app.investigations.planning.models import PlannerFailureCode


class InvestigationPlannerError(RuntimeError):
    def __init__(self, code: PlannerFailureCode, message: str) -> None:
        self.code = code
        super().__init__(message)
