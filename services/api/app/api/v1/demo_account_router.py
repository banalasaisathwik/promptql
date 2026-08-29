from fastapi import APIRouter, Depends

from app.config import DemoAccountSettings
from app.connectors.models import ContractModel

router = APIRouter(prefix="/v1", tags=["demo-account"])


class DemoAccountResponse(ContractModel):
    email: str
    password: str


def get_demo_account_settings() -> DemoAccountSettings:
    return DemoAccountSettings.from_environment()


@router.get("/demo-account", response_model=DemoAccountResponse)
def get_demo_account(
    settings: DemoAccountSettings = Depends(get_demo_account_settings),
) -> DemoAccountResponse:
    return DemoAccountResponse(email=settings.email, password=settings.password)
