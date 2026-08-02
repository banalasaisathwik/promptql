pass

from app.connectors.models import ConnectorRequest


class FixtureNotFoundError(LookupError):
    pass

    def __init__(self, connector_name: str, request: ConnectorRequest) -> None:
                                                                             
                                                                        
        self.connector_name = connector_name
        self.request = request
        super().__init__(
            f"{connector_name} fixture not found for "
            f"{request.repository_owner}/{request.repository_name}"
            f"#{request.pr_number}"
        )
