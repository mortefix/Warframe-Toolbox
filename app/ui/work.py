"""One worker primitive for every off-thread call the screens make.

The Tk app grew six separate `threading.Thread` constructions with 23
`self.after(0, ...)` marshal points between them, each remembering (or
forgetting) its own `winfo_exists()` guard. Qt queues a cross-thread
`Signal.emit()` to the receiver's thread automatically and drops it if the
receiver has been deleted, so all of that collapses to this.

Two things this adds that the Tk version never had:

  * **cancellation.** A `Job` carries a flag the worker checks between items.
    The old market-low sweep had no generation token at all - hitting Refresh
    mid-sweep left the first one running, and both raced to write the same
    labels. Every long sweep here can be cancelled by the next one.
  * **a step signal**, so a per-item sweep reports as it goes instead of
    scheduling one `after()` per item from inside the worker.

Keep the returned Job alive for the duration - a QObject with no other
reference can be garbage collected mid-flight, taking its queued signals with
it. Every caller here parks it in a list or an attribute.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from core import market as core_market


class Job(QObject):
    """One worker thread's outcome, delivered on the GUI thread."""

    done = Signal(object)
    failed = Signal(str)
    step = Signal(object)          # per-item progress, payload is the caller's

    def __init__(self) -> None:
        super().__init__()
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the worker to stop at its next checkpoint. Advisory: a call
        already in flight still completes, it just stops being reported."""
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


#: Jobs with a worker still running. A caller parks its Job in an attribute,
#: but that attribute dies with the page - and a page can be destroyed while
#: its fetch is in flight (navigate away, unlink an account, wipe user data).
#: The Job was then garbage collected and its thread emitted into a deleted
#: C++ object: "RuntimeError: Signal source has been deleted", raised on a
#: worker thread where nothing catches it. Holding a reference until the
#: worker actually finishes is the fix; Qt still drops the queued signal if
#: the RECEIVER is gone, which is the behaviour we want.
_INFLIGHT: set[Job] = set()


def _spawn(job: Job, body: Callable[[], Any]) -> Job:
    _INFLIGHT.add(job)

    def emit(signal, payload) -> None:
        # Belt and braces: the Job can still be torn down between the check
        # and the emit if the interpreter is shutting down.
        try:
            signal.emit(payload)
        except RuntimeError:
            pass

    def work() -> None:
        try:
            try:
                result = body()
            except core_market.MarketError as exc:
                if not job.cancelled:
                    emit(job.failed, str(exc))
                return
            except Exception as exc:                      # noqa: BLE001
                # never let a worker die silently - a blank screen with no
                # message is the worst outcome, and this is the only place
                # left to catch it
                if not job.cancelled:
                    emit(job.failed, str(exc))
                return
            if not job.cancelled:
                emit(job.done, result)
        finally:
            _INFLIGHT.discard(job)
    threading.Thread(target=work, daemon=True).start()
    return job


def run(fn: Callable[[], Any], on_done=None, on_error=None) -> Job:
    """Call `fn()` on a worker thread; deliver the outcome via signals."""
    job = Job()
    if on_done is not None:
        job.done.connect(on_done)
    if on_error is not None:
        job.failed.connect(on_error)
    return _spawn(job, fn)


def run_stepped(fn: Callable[[Job], Any], on_step,
                on_done=None, on_error=None) -> Job:
    """As `run`, but `fn` receives the Job so it can `job.step.emit(payload)`
    as it goes and check `job.cancelled` between items."""
    job = Job()
    job.step.connect(on_step)
    if on_done is not None:
        job.done.connect(on_done)
    if on_error is not None:
        job.failed.connect(on_error)
    return _spawn(job, lambda: fn(job))
