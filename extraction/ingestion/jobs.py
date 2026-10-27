"""Ingest jobs with progress (kept from the chatbot repo's ingest_jobs.py).

One worker thread: concurrent OCR jobs would multiply memory and the rate of Gemini calls, and uploads come a few
at a time. Job state is in memory; the result of a job is in knowledge.db, which survives a restart. Documents left
QUEUED or EXTRACTING by a restart are queued again by `Knowledge.resume_pending`.

`inline=True` runs each job at once in the caller's thread (tests and the command line).
"""
import logging
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from ingestion.store import now

log = logging.getLogger(__name__)
_MAX_REMEMBERED = 100


class JobQueue:
    def __init__(self, inline: bool = False):
        self.inline = inline
        self._jobs: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()
        self._executor = None if inline else ThreadPoolExecutor(max_workers=1, thread_name_prefix="ingest")

    def submit(self, document_id: str, file_name: str, work: Callable[[Callable], None], title: str = "") -> str:
        """`work(progress)` does the job; `progress(stage, done, total)` updates the job record."""
        job_id = "job_" + uuid.uuid4().hex[:10]
        with self._lock:
            self._jobs[job_id] = {"job_id": job_id, "document_id": document_id, "file_name": file_name,
                                  "title": title or file_name,
                                  "status": "QUEUED", "stage": "queued", "done": 0, "total": 0, "detail": None,
                                  "created_at": now(), "finished_at": None}
            self._prune()
        if self.inline:
            self._run(job_id, work)
        else:
            self._executor.submit(self._run, job_id, work)
        return job_id

    def _run(self, job_id: str, work) -> None:
        """Never raises: every outcome is written on the job."""
        def progress(stage: str, done: int, total: int) -> None:
            self._update(job_id, stage=stage, done=done, total=total)

        self._update(job_id, status="RUNNING", stage="extracting")
        try:
            work(progress)
            self._update(job_id, status="DONE", stage="done", finished_at=now())
        except Exception as e:
            log.exception("job %s failed", job_id)
            self._update(job_id, status="FAILED", stage="failed", detail=str(e)[:400], finished_at=now())

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def _prune(self) -> None:
        done = [j for j in self._jobs.values() if j["status"] in ("DONE", "FAILED")]
        for j in done[: max(0, len(done) - _MAX_REMEMBERED)]:
            self._jobs.pop(j["job_id"], None)

    def list(self) -> list[dict]:
        with self._lock:
            return sorted((dict(j) for j in self._jobs.values()), key=lambda j: j["created_at"], reverse=True)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            j = self._jobs.get(job_id)
            return dict(j) if j else None

    def wait_idle(self, timeout: float = 600) -> None:
        """Block until every queued job has finished (scripts and tests)."""
        if self._executor is None:
            return
        self._executor.submit(lambda: None).result(timeout=timeout)
