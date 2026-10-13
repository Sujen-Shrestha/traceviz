from datetime import datetime

from sqlmodel import Field, SQLModel


class TraceRecord(SQLModel, table=True):
    __tablename__ = "traces"

    id: int | None = Field(default=None, primary_key=True)
    target: str = Field(index=True)
    target_ip: str
    protocol: str
    kind: str
    status: str
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class HopRecord(SQLModel, table=True):
    __tablename__ = "hops"

    id: int | None = Field(default=None, primary_key=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    hop_index: int
    ip: str | None = None
    hostname: str | None = None
    sent: int
    received: int
    loss_pct: float
    last_ms: float | None = None
    avg_ms: float | None = None
    best_ms: float | None = None
    worst_ms: float | None = None
    jitter_ms: float | None = None
    geo_status: str | None = None
    lat: float | None = None
    lon: float | None = None
    city: str | None = None
    country: str | None = None
    country_name: str | None = None
    asn: int | None = None
    org: str | None = None
    approximate: bool = False


class MonitorSampleRecord(SQLModel, table=True):
    __tablename__ = "monitor_samples"

    id: int | None = Field(default=None, primary_key=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    ts: datetime
    hop_index: int
    sent: int
    received: int
    avg_ms: float | None = None
