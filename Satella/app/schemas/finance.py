from pydantic import BaseModel


class FinanceOverview(BaseModel):
    source: str
    simulated: bool
    account_count: int
    balances_by_currency: dict[str, str | float]
