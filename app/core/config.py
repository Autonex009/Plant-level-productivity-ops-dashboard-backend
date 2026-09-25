from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://localhost/plant_ops_dashboard"

    # Browser origins allowed to call the API. The dashboard is served separately
    # (Vite dev server, or a static host in production), so it is always cross-origin.
    # NoDecode keeps pydantic-settings from JSON-decoding the env value, so the
    # validator below can accept a plain comma-separated list.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # Commercial rates. The spec's cost-of-waste formula (waste kg x paper rate
    # + starch + power share) needs prices, and there is no commercial table in
    # the data model, so they are configuration rather than invented data.
    paper_rate_inr_per_kg: float = 42.0
    starch_rate_inr_per_kg: float = 38.0
    power_rate_inr_per_kwh: float = 9.5

    # Starch as a fraction of board weight, used to price the starch that goes
    # out with wasted board.
    starch_share_of_board: float = 0.04

    # Waste the plant budgets for. The alert is on the excess over this, not on
    # the total, since some trim and startup loss is unavoidable.
    planned_waste_pct: float = 6.0

    # Nameplate kW of the diesel genset, used to turn DG kWh into the DG hours
    # the owner actually reacts to.
    dg_kw_rating: float = 320.0

    # What a stopped machine costs per minute, used to rank alerts by money.
    # This is the pacemaker's rate: an idle corrugator holds up the whole plant,
    # so a minute of it is worth roughly a minute of plant output.
    downtime_cost_inr_per_minute: float = 2600.0

    # An order that has not been staged yet is an exposure, not a write-off -
    # most ship a little late rather than never. Priced as a fraction of order
    # value and capped, so a large order cannot dominate the panel on its own.
    order_at_risk_value_fraction: float = 0.12
    order_at_risk_cap_inr: float = 25000.0

    # Lets a request top the demo dataset up when it has gone stale, so the
    # live screens work without a scheduler frequent enough to keep them fresh
    # (see services/dashboard/self_heal.py). Off by default and must stay off
    # anywhere a real feed writes the data - an API that invents production is
    # exactly what the grey "no data" rule exists to prevent.
    demo_self_heal: bool = False

    # Vercel sets this automatically as an env var and stamps cron-triggered
    # requests with `Authorization: Bearer <value>` - checked by the
    # /internal/advance-demo-day endpoint so it can't be hit by anyone else.
    cron_secret: str | None = None

    # DeepSeek key for the dashboard's chat assistant. Server-side only - the
    # browser never sees it, it only ever talks to our own /chat endpoint.
    deepseek_api_key: str | None = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
