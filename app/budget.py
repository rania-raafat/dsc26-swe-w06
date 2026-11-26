"""Per-request cost estimate and a per-tenant daily spend cap for AI calls.

Keep these names exactly (the public and hidden tests import them).
"""

from collections.abc import Callable
from datetime import UTC, date, datetime
from threading import RLock

from app.providers import LLMProvider


def estimate_cost_usd(
    provider: LLMProvider,
    prompt: str,
    max_output_tokens: int,
) -> float:
    """Calculate the worst-case cost of a provider request."""

    input_tokens = provider.count_tokens(prompt)

    input_cost = input_tokens * provider.price_in_per_mtok
    output_cost = max_output_tokens * provider.price_out_per_mtok

    return (input_cost + output_cost) / 1_000_000


def actual_cost_usd(
    provider: LLMProvider,
    prompt: str,
    output_tokens: int,
) -> float:
    """Calculate the actual cost using the tokens produced."""

    input_tokens = provider.count_tokens(prompt)

    input_cost = input_tokens * provider.price_in_per_mtok
    output_cost = output_tokens * provider.price_out_per_mtok

    return (input_cost + output_cost) / 1_000_000


class DailyBudget:
    """Per-tenant spend limit in USD.

    Budgets are independent for each (tenant, today()) date.
    """

    def __init__(
        self,
        limit_usd: float,
        today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    ):
        if limit_usd < 0:
            raise ValueError("limit_usd cannot be negative")

        self.limit_usd = float(limit_usd)
        self.today = today

        self._accounts: dict[tuple[str, date], dict[str, float]] = {}

        self._lock = RLock()

    def _get_account(self, tenant: str) -> dict[str, float]:
        key = (tenant, self.today())

        if key not in self._accounts:
            self._accounts[key] = {
                "spent": 0.0,
                "reserved": 0.0,
            }

        return self._accounts[key]

    def remaining(self, tenant: str) -> float:
        """Return the remaining budget for this tenant today."""

        with self._lock:
            account = self._get_account(tenant)

            return max(
                0.0,
                self.limit_usd
                - account["spent"]
                - account["reserved"],
            )

    def try_reserve(self, tenant: str, amount: float) -> bool:
        """Reserve an amount only if the tenant can afford it."""

        if amount < 0:
            raise ValueError("Reservation amount cannot be negative")

        with self._lock:
            account = self._get_account(tenant)

            available = (
                self.limit_usd
                - account["spent"]
                - account["reserved"]
            )

            if amount > available:
                return False

            account["reserved"] += amount
            return True

    def settle(
        self,
        tenant: str,
        reserved: float,
        actual: float,
    ) -> None:
        """Replace a reservation with the actual request cost."""

        if reserved < 0 or actual < 0:
            raise ValueError("Costs cannot be negative")

        with self._lock:
            account = self._get_account(tenant)

            account["reserved"] -= reserved
            account["spent"] += actual

            if abs(account["reserved"]) < 1e-12:
                account["reserved"] = 0.0
