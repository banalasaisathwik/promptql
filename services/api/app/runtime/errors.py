pass

from uuid import UUID


class RunRepositoryError(RuntimeError):
    pass

    def __init__(self, message: str, run_id: UUID | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id


class RunPersistenceError(RunRepositoryError):
    pass


class RunStateConflictError(RunRepositoryError):
    pass


class RunRecordInvalidError(RunRepositoryError):
    pass
