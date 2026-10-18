"""Background jobs: a Postgres/SQLite table plus an in-process worker (PRD uses Procrastinate).

Jobs run when run_at <= clock.now(), so advancing the simulated clock drives polling, the
72-hour auto-approve sweep and settlement. Every handler is idempotent on its args.
"""
import logging
import threading
import time
import traceback
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from .. import clock
from ..db import SessionLocal
from ..models import Job

log = logging.getLogger("flu.jobs")
HANDLERS: dict = {}
RECURRING: dict[str, timedelta] = {
    "money.auto_approve_sweep": timedelta(minutes=15),
    "money.settle_payouts": timedelta(hours=1),
    "money.reconcile": timedelta(days=1),
    "connections.refresh_tokens": timedelta(days=1),
    "scoring.nightly_batch": timedelta(days=1),
    "ai.refresh_trend_corpus": timedelta(hours=6),
}
_run_lock = threading.Lock()


def task(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


def enqueue(db, kind: str, args: dict | None = None, run_at=None, dedupe: str | None = None) -> Job | None:
    if dedupe and db.query(Job).filter_by(dedupe_key=dedupe).first():
        return None
    job = Job(kind=kind, args=args or {}, run_at=run_at or clock.now(), dedupe_key=dedupe)
    try:
        with db.begin_nested():
            db.add(job)
    except IntegrityError:
        return None
    return job


def ensure_recurring(db):
    for kind in RECURRING:
        if not db.query(Job).filter_by(kind=kind, status="queued").first():
            enqueue(db, kind, {}, clock.now())
    db.commit()


def _run_one(job_id: str):
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if not job or job.status != "queued":
            return
        job.status, job.attempts = "running", job.attempts + 1
        db.commit()
        handler = HANDLERS.get(job.kind)
        try:
            if handler is None:
                raise RuntimeError(f"no handler for {job.kind}")
            handler(db, **job.args)
            db.commit()
            job = db.get(Job, job_id)
            job.status, job.finished_at = "done", clock.now()
            if job.kind in RECURRING:
                enqueue(db, job.kind, {}, job.run_at + RECURRING[job.kind])
            db.commit()
        except Exception as e:  # retry with backoff, max 3 attempts
            db.rollback()
            job = db.get(Job, job_id)
            job.last_error = f"{e}\n{traceback.format_exc()[-1500:]}"
            if job.attempts < 3:
                job.status, job.run_at = "queued", clock.now() + timedelta(minutes=5 * job.attempts)
            else:
                job.status, job.finished_at = "failed", clock.now()
                if job.kind in RECURRING:
                    enqueue(db, job.kind, {}, clock.now() + RECURRING[job.kind])
            db.commit()
            log.warning("job %s %s failed: %s", job.kind, job_id, e)
    finally:
        db.close()


def run_due(limit: int = 200) -> int:
    """Run every job due at the current (possibly simulated) time. Returns how many ran."""
    with _run_lock:
        ran = 0
        while ran < limit:
            db = SessionLocal()
            try:
                ids = [j.id for j in db.query(Job).filter(Job.status == "queued", Job.run_at <= clock.now())
                       .order_by(Job.run_at).limit(25).all()]
            finally:
                db.close()
            if not ids:
                break
            for jid in ids:
                _run_one(jid)
                ran += 1
        return ran


def advance(hours: float, step_hours: float = 1.0) -> dict:
    """Move simulated time forward in steps, running due jobs at each step."""
    from ..db import session_scope
    ran, done = 0, 0.0
    while done < hours:
        step = min(step_hours, hours - done)
        clock.set_offset(clock.offset_hours() + step)
        done += step
        ran += run_due(limit=2000)
    with session_scope() as db:
        clock.persist(db)
    return {"advanced_hours": hours, "jobs_run": ran, "now": clock.now().isoformat(),
            "offset_hours": clock.offset_hours()}


class Worker:
    def __init__(self, interval: float = 2.0):
        self.interval, self._stop = interval, threading.Event()
        self.thread = threading.Thread(target=self._loop, name="flu-worker", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                run_due()
            except Exception:
                log.exception("worker loop")
            self._stop.wait(self.interval)
            time.sleep(0)
