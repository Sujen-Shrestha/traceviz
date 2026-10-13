from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, event
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from traceviz.core.sessions.state import HopStats, TraceState
from traceviz.core.store.models import HopRecord, MonitorSampleRecord, TraceRecord

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000


class SchemaTooNew(RuntimeError):
    """The database was written by a newer traceviz."""


def init_db(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_busy_timeout(dbapi_conn, _record) -> None:
        dbapi_conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")

    with engine.begin() as conn:
        version = conn.exec_driver_sql("PRAGMA user_version").scalar() or 0
        if version > SCHEMA_VERSION:
            raise SchemaTooNew(
                f"database {path} uses schema v{version}, newer than this traceviz "
                f"(v{SCHEMA_VERSION}); upgrade traceviz"
            )
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    try:
        SQLModel.metadata.create_all(engine)
    except OperationalError as e:
        # Another process (CLI vs server) created the tables between our check and create.
        if "already exists" not in str(e):
            raise
        SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
    return engine


def _hop_record(trace_id: int, hop: HopStats) -> HopRecord:
    geo = hop.geo
    return HopRecord(
        trace_id=trace_id,
        hop_index=hop.index,
        ip=hop.ip,
        hostname=hop.hostname,
        sent=hop.sent,
        received=hop.received,
        loss_pct=hop.loss_pct,
        last_ms=hop.last_ms,
        avg_ms=hop.avg_ms,
        best_ms=hop.best_ms,
        worst_ms=hop.worst_ms,
        jitter_ms=hop.jitter_ms,
        geo_status=geo.status if geo else None,
        lat=geo.lat if geo else None,
        lon=geo.lon if geo else None,
        city=geo.city if geo else None,
        country=geo.country if geo else None,
        country_name=geo.country_name if geo else None,
        asn=geo.asn if geo else None,
        org=geo.org if geo else None,
        approximate=geo.approximate if geo else False,
    )


class TraceRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_trace(self, state: TraceState, started_at: datetime) -> int:
        rec = TraceRecord(
            target=state.target,
            target_ip=state.target_ip,
            protocol=state.protocol,
            kind=state.kind,
            status=state.status,
            started_at=started_at,
        )
        with Session(self.engine) as db:
            db.add(rec)
            db.commit()
            db.refresh(rec)
            assert rec.id is not None
            return rec.id

    def finish_trace(self, trace_id: int, state: TraceState, finished_at: datetime) -> None:
        with Session(self.engine) as db:
            rec = db.get(TraceRecord, trace_id)
            if rec is None:
                raise KeyError(trace_id)
            rec.status = state.status
            rec.error = state.error
            rec.finished_at = finished_at
            db.add(rec)
            for old in db.exec(select(HopRecord).where(HopRecord.trace_id == trace_id)):
                db.delete(old)
            db.add_all(_hop_record(trace_id, hop) for hop in state.hops)
            db.commit()

    def add_monitor_samples(self, rows: list[MonitorSampleRecord]) -> None:
        with Session(self.engine) as db:
            db.add_all(rows)
            db.commit()

    def list_traces(self, target: str | None = None, limit: int = 20) -> list[TraceRecord]:
        query = select(TraceRecord).order_by(TraceRecord.id.desc()).limit(limit)
        if target:
            query = query.where(TraceRecord.target == target)
        with Session(self.engine) as db:
            return list(db.exec(query))

    def get_trace(self, trace_id: int) -> tuple[TraceRecord, list[HopRecord]] | None:
        with Session(self.engine) as db:
            rec = db.get(TraceRecord, trace_id)
            if rec is None:
                return None
            hops = db.exec(
                select(HopRecord).where(HopRecord.trace_id == trace_id).order_by(HopRecord.hop_index)
            )
            return rec, list(hops)

    def monitor_samples(self, trace_id: int) -> list[MonitorSampleRecord]:
        query = (
            select(MonitorSampleRecord)
            .where(MonitorSampleRecord.trace_id == trace_id)
            .order_by(MonitorSampleRecord.ts, MonitorSampleRecord.hop_index)
        )
        with Session(self.engine) as db:
            return list(db.exec(query))
