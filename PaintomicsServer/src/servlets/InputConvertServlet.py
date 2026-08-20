"""HTTP surface for the input-conversion agent.

The route is a stateless proxy. It holds the API key, checks the session,
enforces a quota and a concurrency cap, and returns one action. It keeps no
conversation: the browser owns the loop state and sends it back each turn, which
means a worker restart cannot strand a conversion and there is nothing to clean
up when a user closes the tab.

It does NOT wait for the model inline. paintomics4.ini runs processes=1,
threads=4, so four threads serve every request on the site; the CSIC gateway
takes ~120 s per attempt. An inline call would hold a quarter of the site's
capacity per conversion and take the site down at four concurrent users. The
work is enqueued and the browser polls, exactly as aiInterpretInitiate does.
"""

import logging
import os
import threading
import time

from src.common.ServerErrorManager import handleException
from src.common.UserSessionManager import UserSessionManager


logger = logging.getLogger(__name__)


def _converter_enabled():
    """Whether this deployment has opted in.

    Read defensively. `src/conf/serverconf.py` is gitignored and PROTECTED from
    the deploy rsync, so an already-installed server keeps a config that predates
    this setting -- and a bare `from src.conf.serverconf import AI_INPUT_CONVERTER`
    then raises ImportError at the use site rather than reporting the feature as
    off. Measured on paintomics.uv.es straight after the first deploy: the route
    answered with an ImportError instead of "not enabled on this server".

    See the note on adding a serverconf setting: the value goes in the local
    config, in example_serverconf.py for fresh installs, AND behind a fallback
    here for every server already running.
    """
    try:
        from src.conf.serverconf import AI_INPUT_CONVERTER
        return bool(AI_INPUT_CONVERTER)
    except ImportError:
        return os.getenv("AI_INPUT_CONVERTER", "false").lower() == "true"

# At most this many conversions may be in flight across the whole server. Each
# holds a queue slot and a share of the gateway's rate limit, which is shared
# with AI report generation -- an unbounded burst here would degrade reports for
# users who are not converting anything.
MAX_CONCURRENT_CONVERSIONS = 2
_inflight = threading.BoundedSemaphore(MAX_CONCURRENT_CONVERSIONS)

# Per-user daily budget. Every attempt costs a gateway call that the server pays
# for, so a runaway client cannot be allowed to spend without limit.
MAX_TURNS_PER_USER_PER_DAY = 120
_usage = {}
_usage_lock = threading.Lock()


def _spend_turn(user_id):
    day = int(time.time() // 86400)
    with _usage_lock:
        used_day, used = _usage.get(user_id, (day, 0))
        if used_day != day:
            used_day, used = day, 0
        if used >= MAX_TURNS_PER_USER_PER_DAY:
            _usage[user_id] = (used_day, used)
            return False
        _usage[user_id] = (used_day, used + 1)
        return True


def _reject_if_carrying_data(state):
    """The profile must not contain measurement rows.

    The privacy claim made in the UI -- that values never leave the machine --
    is only true if it is enforced here rather than trusted to the client. A
    payload carrying raw rows is refused outright instead of being forwarded.
    """
    banned = ("rows", "data", "values", "records", "first_rows_full")
    def walk(node, depth=0):
        if depth > 6:
            return None
        if isinstance(node, dict):
            for k, v in node.items():
                if k in banned and isinstance(v, list) and len(v) > 60:
                    return k
                found = walk(v, depth + 1)
                if found:
                    return found
        elif isinstance(node, list):
            for v in node[:40]:
                found = walk(v, depth + 1)
                if found:
                    return found
        return None
    return walk(state)


def inputConvertTurn(REQUEST, RESPONSE, QUEUE_INSTANCE, JOB_ID):
    """POST /input_convert/turn -> {ticket}. The browser then polls for it."""
    try:
        userID = REQUEST.cookies.get("userID")
        sessionToken = REQUEST.cookies.get("sessionToken")
        UserSessionManager().isValidUser(userID, sessionToken)

        if not _converter_enabled():
            raise Exception("AI file conversion is not enabled on this server.")

        state = REQUEST.get_json(force=True, silent=True) or {}

        offending = _reject_if_carrying_data(state)
        if offending:
            raise Exception(
                "The conversion request carried a %r field that looks like raw data. "
                "Only the file's structure is sent." % offending)

        if not _spend_turn(userID):
            raise Exception("Daily conversion limit reached for this account.")

        if not _inflight.acquire(blocking=False):
            raise Exception("The server is converting other files right now. "
                            "Please try again in a moment.")

        def work(payload):
            try:
                from src.classes.InputConvert.agent_turn import next_action
                return next_action(payload)
            finally:
                _inflight.release()

        # PySiQ takes (fn, args) -- the callable and a tuple, not a closure.
        QUEUE_INSTANCE.enqueue(fn=work, args=(state,), job_id=JOB_ID, timeout=300)
        RESPONSE.setContent({"success": True, "ticket": JOB_ID})
    except Exception as ex:
        _release_quietly()
        handleException(RESPONSE, ex, __file__, "inputConvertTurn")
    finally:
        return RESPONSE


def _release_quietly():
    try:
        _inflight.release()
    except ValueError:
        pass  # was never acquired on this path


def inputConvertResult(REQUEST, RESPONSE, QUEUE_INSTANCE, ticket):
    """GET /input_convert/turn/<ticket> -> {state, action}."""
    try:
        userID = REQUEST.cookies.get("userID")
        sessionToken = REQUEST.cookies.get("sessionToken")
        UserSessionManager().isValidUser(userID, sessionToken)

        job = QUEUE_INSTANCE.fetch_job(ticket)
        if job is None:
            RESPONSE.setContent({"success": True, "state": "unknown"})
            return RESPONSE

        status = str(getattr(job, "status", ""))
        if "FINISHED" in status.upper():
            action = QUEUE_INSTANCE.get_result(ticket, remove=True)
            RESPONSE.setContent({"success": True, "state": "done", "action": action})
        elif "FAILED" in status.upper():
            RESPONSE.setContent({"success": True, "state": "error"})
        else:
            RESPONSE.setContent({"success": True, "state": "running"})
    except Exception as ex:
        handleException(RESPONSE, ex, __file__, "inputConvertResult")
    finally:
        return RESPONSE
