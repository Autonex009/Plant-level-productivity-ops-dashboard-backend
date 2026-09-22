import enum

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """A Postgres ENUM column that stores the member's .value (e.g. "board_manufacturing")
    rather than SQLAlchemy's default of the member name (e.g. "BOARD_MANUFACTURING")."""

    return SAEnum(enum_cls, name=name, values_callable=lambda obj: [e.value for e in obj])


class Stage(str, enum.Enum):
    BOARD_MANUFACTURING = "board_manufacturing"
    PRINTING = "printing"
    BUNDLING = "bundling"


class LineType(str, enum.Enum):
    AUTOMATIC = "automatic"
    SEMI_AUTOMATIC = "semi_automatic"


class MetricCategory(str, enum.Enum):
    """The five measurement categories applied to every machine."""

    MATERIAL = "material"
    THROUGHPUT = "throughput"
    QUALITY = "quality"
    TIME = "time"
    PARAMETERS = "parameters"


class TimeCategory(str, enum.Enum):
    """Every shift-minute is classified as one of these."""

    RUNNING = "running"
    SETUP = "setup"
    BREAKDOWN = "breakdown"
    WAITING = "waiting"
    IDLE = "idle"


class MaterialType(str, enum.Enum):
    KRAFT_PAPER = "kraft_paper"
    BOARD = "board"
    INK = "ink"
    STARCH = "starch"


class ParameterSource(str, enum.Enum):
    """Where a ParameterReading value came from."""

    PLC_LIVE = "plc_live"
    QA_SAMPLE = "qa_sample"
    MANUAL = "manual"


class PowerSource(str, enum.Enum):
    GRID = "grid"
    DG = "dg"
