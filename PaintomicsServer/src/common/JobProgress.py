#***************************************************************
#  This file is part of Paintomics v4
#
#  Paintomics is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as
#  published by the Free Software Foundation, either version 3 of
#  the License, or (at your option) any later version.
#
#  Paintomics is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Paintomics.  If not, see <http://www.gnu.org/licenses/>.
#**************************************************************
"""In-process ledger of what a running job is actually doing.

WHY A PLAIN DICT IS THE RIGHT MECHANISM HERE

uWSGI runs `processes = 1` (mandatory: PySiQ holds the queue in process memory)
and the PySiQ worker is a `threading.Thread`. So the code doing the work and the
`check_job_status` handler answering the browser live in the *same interpreter*.
A module-level dict is therefore shared state between writer and reader with no
IPC, no serialization, and no clock skew — a read is a dict lookup, which cannot
block a request handler. Every heavier mechanism considered (Manager proxies,
mmap'd ring buffers, an events collection in Mongo) exists to cross a process
boundary that, for phase transitions, does not need crossing.

WHAT IS EXACT AND WHAT IS NOT

Exact, to the resolution of `time.monotonic()` (~1us, and it cannot step
backwards the way `time.time()` does on an NTP correction):
  - which phase the job is in, and when it entered
  - `done`/`total` for loops that run in the worker thread

NOT exact, and deliberately not presented as such:
  - the fraction of *time* elapsed, hence the ETA. Roughly 98% of a mapper
    child's runtime is inside opaque MongoDB `aggregate()` calls with no
    observable internal state, so between anchors the fraction is interpolated
    from phase weights. `remaining()` returns a *band*, never a point estimate.

Phase weights are measured medians (see PROGRESS.md). A weight being wrong makes
the bar move at the wrong speed inside that phase; it can never make the bar go
backwards or exceed the phase's own band, because progress is clamped to the
plan.
"""

import logging
import threading
import time

# jobID -> _JobRecord. Bounded by the number of jobs in flight (N_WORKERS=4 plus
# whatever is queued); entries are removed by finish(). A single long-lived
# process means a leaked entry is permanent, so every caller must use finish()
# in a `finally`.
_records = {}
_lock = threading.Lock()

# How far the bar may creep inside a phase on interpolation alone, as a fraction
# of that phase's weight. Interpolation is a guess; it must never let the bar
# arrive at the next phase's boundary before the work does, or the bar would
# stall visibly at a wall. 0.9 leaves a visible 10% for the real transition.
_MAX_INTERPOLATED = 0.9


class _JobRecord(object):
    """One running job's phase plan and position in it."""

    __slots__ = ("epoch", "plan", "weights", "index", "started", "phaseStarted",
                 "done", "total", "span", "detail", "anchors", "expectedTotal")

    def __init__(self, epoch, plan, expectedTotal=None):
        self.epoch = epoch
        # plan: ordered [(name, label, weight), ...]. Weights are normalised so a
        # caller can pass measured seconds, relative sizes, or percentages and get
        # the same behaviour.
        totalWeight = float(sum(max(0.0, float(w)) for _, _, w in plan)) or 1.0
        self.plan = [(name, label) for name, label, _ in plan]
        self.weights = [max(0.0, float(w)) / totalWeight for _, _, w in plan]
        self.index = -1
        self.started = time.monotonic()
        self.phaseStarted = self.started
        self.done = 0
        self.total = 0
        self.span = 0
        self.detail = ""
        # Optional shared counter (multiprocessing.RawArray) written by forked
        # children; see anchors(). Read-only from this side.
        self.anchors = None
        # Seconds. Only ever used to interpolate inside uncountable phases, and
        # re-estimated from this job's own elapsed time at each phase boundary.
        self.expectedTotal = float(expectedTotal) if expectedTotal else 0.0


def begin(jobID, epoch, plan, expectedTotal=None):
    """Start recording `jobID`. `plan` is [(name, label, weight), ...].

    `expectedTotal` is the median run time in seconds for this kind of step. It
    is ONLY used to move the bar inside phases that have nothing countable — the
    alternative is a bar frozen at the phase boundary for the phase's whole
    duration, which is what step 2 did before this existed (0% for 15s, then
    7.9% for the rest of a 31.6s run). It is re-estimated from this job's own
    timings at every phase boundary, so a wrong constant self-corrects.

    Calling begin() twice for the same jobID is legitimate: a job passes through
    step 1, then step 2, then metagenes, all enqueued under the same jobID. Each
    call replaces the plan and restarts the clock, which is what the user sees.
    """
    if not jobID:
        return
    with _lock:
        _records[jobID] = _JobRecord(epoch, plan, expectedTotal)


def enter(jobID, phaseName, total=0, detail=""):
    """Record that the job has entered `phaseName`.

    Unknown phase names are ignored rather than raised: progress reporting must
    never be able to fail a job. A phase missing from the plan shows as the
    previous phase continuing, which is a stale bar, not a broken one.
    """
    with _lock:
        rec = _records.get(jobID)
        if rec is None:
            return
        for i, (name, _label) in enumerate(rec.plan):
            if name == phaseName:
                # Never move backwards: a repeated or out-of-order enter() would
                # otherwise make the bar retreat, which reads as work being undone.
                if i >= rec.index:
                    # Recalibrate from what this job has actually done so far:
                    # the fraction at a phase boundary is exact (all preceding
                    # weights are complete), so elapsed/fraction is a direct
                    # estimate of the total that needs no historical table.
                    now = time.monotonic()
                    startedFraction = sum(rec.weights[:i])
                    # Only recalibrate from a sample worth extrapolating. A phase
                    # boundary crossed in milliseconds (a skipped or trivial
                    # phase) would otherwise drive expectedTotal to ~0, and the
                    # next uncountable phase would saturate its cap instantly.
                    if startedFraction > 0.05 and (now - rec.started) > 2.0:
                        observed = (now - rec.started) / startedFraction
                        rec.expectedTotal = (observed if rec.expectedTotal <= 0
                                             else 0.5 * rec.expectedTotal + 0.5 * observed)
                    rec.index = i
                    rec.phaseStarted = now
                    rec.done = 0
                    rec.total = max(0, int(total))
                    rec.span = 0
                    rec.detail = detail or ""
                    rec.anchors = None
                return
        logging.debug("JobProgress: unknown phase %r for job %s", phaseName, jobID)


def units(jobID, done, total=None, detail=None, span=0):
    """Set the exact unit count inside the current phase.

    `done`/`total` is the part of this design that is genuinely exact, so it is
    preferred over interpolation whenever the caller has a real count.

    `span` is the size of the unit currently IN FLIGHT — the one `done` has not
    counted yet. Given it, anchors reported by forked children interpolate inside
    that unit instead of being ignored, which is the difference between a bar
    that steps once per omic and one that moves continuously. Leave it 0 and the
    count alone decides the position.
    """
    with _lock:
        rec = _records.get(jobID)
        if rec is None:
            return
        if total is not None:
            rec.total = max(0, int(total))
        # Monotone within a phase, for the same reason as enter().
        rec.done = max(rec.done, max(0, int(done)))
        rec.span = max(0, int(span))
        # The in-flight unit just changed, so any anchors still attached describe
        # the PREVIOUS unit and are sitting at 100%. Leaving them would count the
        # new unit as already finished and then visibly rewind when the workers
        # re-attach — measured: the bar ran to 54% and dropped back to 37%.
        rec.anchors = None
        if detail is not None:
            rec.detail = detail


def attachAnchors(jobID, array, perWorker):
    """Attach a shared counter that forked children increment.

    `array` is a `multiprocessing.RawArray` allocated BEFORE the fork, one slot
    per child. RawArray rather than a Manager list on purpose: a Manager is a
    separate server process created per mapping call, so a proxy outliving that
    call points at a dead process and raises inside whichever thread touches it —
    here, a request handler. A RawArray is shared memory: writes are ~20ns stores
    and reads are plain loads that cannot block or raise.

    `perWorker` is how many anchors each child will report, so the reader knows
    the denominator without the children agreeing on one.
    """
    with _lock:
        rec = _records.get(jobID)
        if rec is not None:
            rec.anchors = (array, int(perWorker))


def finish(jobID):
    """Drop the record. MUST be called from a `finally` — see the leak note above."""
    with _lock:
        _records.pop(jobID, None)


def _anchorFraction(rec):
    """Fraction of the in-flight work reported by forked children, or None.

    Reading a RawArray without a lock is safe here: each slot is written by
    exactly one child, the values are word-sized int stores, and the worst a
    racing read can see is a value one anchor stale.
    """
    if rec.anchors is None:
        return None
    array, perWorker = rec.anchors
    denom = len(array) * perWorker
    if denom <= 0:
        return None
    return min(1.0, float(sum(array)) / denom)


def _phaseFraction(rec):
    """How far through the current phase we are, in [0, 1]."""
    anchor = _anchorFraction(rec)

    if rec.total > 0:
        # Exact at every unit boundary. If we also know the size of the unit in
        # flight, the children's anchors interpolate inside it — still bounded by
        # the unit, so this can never overshoot the next confirmed boundary.
        done = float(rec.done)
        if anchor is not None and rec.span > 0:
            done += rec.span * anchor
        return min(1.0, done / rec.total)

    if anchor is not None:
        return anchor

    # Nothing countable in this phase. Advance on the clock against how long this
    # phase is expected to take (its share of expectedTotal), capped so the bar
    # can never arrive at the next boundary on a guess alone. This is the only
    # genuinely modelled number in the ledger, and snapshot() flags it as such
    # by reporting exact=False.
    weight = rec.weights[rec.index] if 0 <= rec.index < len(rec.weights) else 0.0
    budget = rec.expectedTotal * weight
    # A budget under half a second cannot pace anything at a 5s poll interval;
    # treat it as "no idea" and leave the bar at the phase boundary.
    if budget < 0.5:
        return 0.0
    return min(1.0, (time.monotonic() - rec.phaseStarted) / budget)


def snapshot(jobID):
    """Everything the status endpoint needs. A dict lookup and some arithmetic.

    Returns None when the job is not being tracked, which the caller should treat
    as "no progress information", not as an error — jobs enqueued before this
    module existed, and jobs from other servlets, legitimately have no record.
    """
    with _lock:
        rec = _records.get(jobID)
        if rec is None or rec.index < 0:
            return None

        now = time.monotonic()
        elapsed = now - rec.started
        name, label = rec.plan[rec.index]
        before = sum(rec.weights[:rec.index])
        weight = rec.weights[rec.index]
        within = _phaseFraction(rec)

        exact = rec.total > 0 or rec.anchors is not None
        if not exact:
            within = min(within, _MAX_INTERPOLATED)

        fraction = min(0.999, before + weight * within)

        result = {
            "phase": name,
            "label": label,
            "phaseIndex": rec.index + 1,
            "phaseCount": len(rec.plan),
            "fraction": round(fraction, 4),
            "exact": exact,
            "elapsed": round(elapsed, 2),
            "detail": rec.detail,
        }
        if rec.total > 0:
            result["unitsDone"] = rec.done
            result["unitsTotal"] = rec.total

        # Read under the lock; used for the ETA fallback below.
        expectedTotal = rec.expectedTotal

    # Remaining time is a PREDICTION, reported as a band. The point estimate
    # elapsed*(1-f)/f assumes the rate seen so far continues; the band widens that
    # by the run-to-run spread measured on identical input (p90/p50 ~ 1.6-1.9 on
    # this workload). Anything narrower would fabricate precision the system does
    # not have — the previous formula's single number was wrong by +58%.
    point = None
    if exact and fraction > 0.02 and elapsed > 1.0:
        # The fraction is real, so the rate implied by it is meaningful.
        point = elapsed * (1.0 - fraction) / fraction
    elif expectedTotal > 0:
        # The fraction is a clock-based guess, and dividing by it is circular:
        # it is pinned low while elapsed grows, so elapsed*(1-f)/f diverges —
        # measured, it claimed 148-317s left on a 29.6s job. Fall back to the
        # calibrated total, which is what was pacing the bar in the first place.
        point = max(0.0, expectedTotal - elapsed)

    if point is not None:
        result["remainingLow"] = round(point * 0.75, 1)
        result["remainingHigh"] = round(point * 1.6, 1)

    return result
