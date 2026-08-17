"""The AI status poll must survive a request that does not land.

``pollAIStatus`` (PA_Step3Views.js) is a self-rescheduling chain: each answer
schedules the next poll. It rescheduled only from its ``success`` handler and
declared no ``error`` handler at all, so the chain was one dropped request from
being over -- permanently, and silently.

Measured in Chrome against a real job (2026-08-17): five healthy polls, the
server restarted, the sixth answered ``ERR http=0``, and the page never issued
another status request. The interpretation finished and was stored; the widget
sat at "Generating interpretation..." with an empty message area until the user
reloaded the page. That is the whole of the reported bug -- the finished report
only appearing after a refresh -- and an AI run is 5 to 15 minutes of polling
every 3 seconds, so one blip (a deploy, a sleep/wake, a VPN reconnect) is
enough.

A non-answer is not a verdict about the job. Only ``done``, ``error`` and
``cancelled`` end the chain; everything else must try again.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_ai_status_poll_survives_a_failed_request
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

CLIENT_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "PaintomicsClient", "public_html"))
STEP3_VIEWS = os.path.join(CLIENT_ROOT, "app", "view",
                           "PathwayAcquisitionViews", "PA_Step3Views.js")

HEADER = "this.pollAIStatus = function()"


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def extract_block(source, header):
    """`header` plus the brace-matched block that follows it."""
    start = source.find(header)
    if start == -1:
        raise AssertionError("%s is missing from PA_Step3Views.js" % header)
    opening = source.index("{", start + len(header) - 1)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise AssertionError("unbalanced braces after %s" % header)


# The real function, lifted out and driven by a stubbed jQuery. `respond`
# decides what the single ajax call does, which is the only variable here.
HARNESS = """
const results = {};

function drive(respond) {
    const scheduled = [];
    const calls = [];
    const setTimeout_ = function (fn, delay) { scheduled.push({delay: delay}); return scheduled.length; };
    const AI_POLL_INTERVAL = 3000;
    const SERVER_URL_AI_INTERPRET_STATUS = "/ai_interpret_status";

    const $ = function () { return {}; };
    $.ajax = function (opts) {
        calls.push(opts.url);
        respond(opts);
    };

    function View() {
        this.aiWidget = {updateProgress: function () {}};
        this.getModel = function () { return {getJobID: function () { return "JOB"; }}; };
        const setTimeout = setTimeout_;
        %(poll)s
    }

    const view = new View();
    view.pollAIStatus();
    return {polls: calls.length, scheduled: scheduled.length,
            firstDelay: scheduled.length ? scheduled[0].delay : null};
}

// A request that never landed: jQuery calls `error`, or nothing at all when no
// error handler was declared.
results.transportFailure = drive(function (opts) {
    if (opts.error) { opts.error({status: 0}); }
});

// The server answered, but with success:false (the servlet does this for any
// handled exception -- an expired session, a Mongo hiccup).
results.unsuccessfulAnswer = drive(function (opts) {
    opts.success({success: false});
});

// Healthy in-progress answer: the chain must continue.
results.stillRunning = drive(function (opts) {
    opts.success({success: true, status: "interpreting", percent: 45, detail: "..."});
});

// Terminal answers: the chain must stop.
results.done = drive(function (opts) {
    opts.success({success: true, status: "done", percent: 100, detail: "Ready"});
});
results.cancelled = drive(function (opts) {
    opts.success({success: true, status: "cancelled", percent: 0, detail: ""});
});
results.errored = drive(function (opts) {
    opts.success({success: true, status: "error", percent: 0, detail: "boom"});
});

console.log(JSON.stringify(results));
"""


def run_node(script):
    directory = tempfile.mkdtemp(prefix="paintomics-poll-")
    try:
        path = os.path.join(directory, "check.js")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
        completed = subprocess.run(["node", path], capture_output=True,
                                   text=True, timeout=60)
        if completed.returncode != 0:
            raise AssertionError("node failed:\n%s" % completed.stderr)
        return json.loads(completed.stdout)
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class StatusPollChainTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        block = extract_block(read(STEP3_VIEWS), HEADER)
        cls.results = run_node(HARNESS % {"poll": block})

    def test_a_dropped_request_does_not_end_the_chain(self):
        """The measured bug: one ERR http=0 and the widget never updates again."""
        outcome = self.results["transportFailure"]
        self.assertEqual(
            outcome["scheduled"], 1,
            "a status request that did not land scheduled no retry, so the "
            "poll chain is dead: the report will only appear if the user "
            "reloads the page")

    def test_an_unsuccessful_answer_does_not_end_the_chain(self):
        outcome = self.results["unsuccessfulAnswer"]
        self.assertEqual(
            outcome["scheduled"], 1,
            "success:false ended the poll chain; the servlet returns that for "
            "any handled exception, which says nothing about the job")

    def test_a_running_job_keeps_polling(self):
        self.assertEqual(self.results["stillRunning"]["scheduled"], 1)

    def test_terminal_states_stop_the_chain(self):
        for state in ("done", "cancelled", "errored"):
            with self.subTest(state=state):
                self.assertEqual(
                    self.results[state]["scheduled"], 0,
                    "%s is terminal; polling on after it wastes requests "
                    "forever" % state)

    def test_the_retry_is_not_faster_than_the_normal_cadence(self):
        """A failing server must not be hammered harder than a healthy one."""
        delay = self.results["transportFailure"]["firstDelay"]
        self.assertIsNotNone(delay, "no retry was scheduled at all")
        self.assertGreaterEqual(delay, 3000, "retry is faster than AI_POLL_INTERVAL")


def main():
    suite = unittest.TestLoader().loadTestsFromModule(__import__(__name__))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
