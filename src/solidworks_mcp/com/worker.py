"""One dedicated STA thread owns every COM call.

COM is apartment-threaded and thread-affine, and the MCP server runs on an
asyncio loop. All SOLIDWORKS work is serialised through this worker so the
"one COM session, one thread" rule holds by construction.
"""
from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable

import pythoncom

from ..errors import OperationTimeoutError, WorkerBlockedError

log = logging.getLogger(__name__)


class ComWorker:
    def __init__(self, timeout: float = 180.0) -> None:
        self.timeout = timeout
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._run, name="solidworks-com", daemon=True
        )
        self._started = threading.Event()
        self._blocked = False

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    @property
    def blocked(self) -> bool:
        return self._blocked

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()
            self._started.wait(timeout=10)

    def stop(self) -> None:
        if self._thread.is_alive():
            self._queue.put((None, None))
            self._thread.join(timeout=5)

    def _run(self) -> None:
        pythoncom.CoInitialize()
        self._started.set()
        while True:
            job, future = self._queue.get()
            if job is None:
                break
            try:
                future.set_result(job())
            except BaseException as exc:  # noqa: BLE001 - forwarded to caller
                future.set_exception(exc)
        pythoncom.CoUninitialize()

    def call(self, fn: Callable[[], Any], timeout: float | None = None) -> Any:
        """Run ``fn`` on the COM thread and block until it returns."""
        if threading.current_thread() is self._thread:
            return fn()
        if self._blocked:
            raise WorkerBlockedError(
                "the COM worker is blocked; dismiss any SOLIDWORKS dialog and "
                "restart the MCP server"
            )
        if not self.alive:
            raise WorkerBlockedError("the COM worker is not running")
        future: Future = Future()
        self._queue.put((fn, future))
        try:
            result = future.result(timeout=timeout or self.timeout)
        except TimeoutError:
            self._blocked = True
            raise OperationTimeoutError(
                "SOLIDWORKS did not answer in time; a modal dialog may be open"
            ) from None
        self._blocked = False
        return result


_worker: ComWorker | None = None


def set_worker(worker: ComWorker) -> None:
    global _worker
    _worker = worker


def get_worker() -> ComWorker:
    if _worker is None:
        raise WorkerBlockedError("COM worker has not been started")
    return _worker


def run(fn: Callable[[], Any], timeout: float | None = None) -> Any:
    return get_worker().call(fn, timeout=timeout)
