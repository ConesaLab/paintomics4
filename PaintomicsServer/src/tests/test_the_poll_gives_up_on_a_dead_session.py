"""A poll must retry a transport blip and give up on an expired session.

PR #36 fixed the opposite bug: one dropped request ended the chain for good and
the widget sat at "Generating interpretation..." forever. The fix made every
failure retry -- including failures that can never clear.

Measured on the live server 2026-08-19: a restart invalidated one user's
in-process session, and their browser polled /ai_interpret_status every 31 s for
FOUR HOURS, about 460 requests, each answered
"400 CredentialException: User not valid ... please log-in again", with nothing
shown to them. Retrying cannot un-expire a session.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
JS = os.path.join(ROOT, "PaintomicsClient", "public_html", "app", "view",
                  "PathwayAcquisitionViews", "PA_Step3Views.js")


def _handler(src):
    """The ajax error handler for pollAIStatus."""
    poll = src.split("this.pollAIStatus = function()")[1]
    poll = poll.split("this.cleanupAIWidget")[0]
    return poll.split("error: function(")[1]


class PollGivesUpOnADeadSession(unittest.TestCase):

    def setUp(self):
        with open(JS) as fh:
            self.src = fh.read()
        self.h = _handler(self.src)

    def test_the_handler_reads_the_status_code(self):
        """Without it, every failure looks identical -- which was the bug."""
        self.assertIn("jqXHR", self.h)
        self.assertIn("status", self.h)

    def test_401_and_403_stop_the_chain(self):
        self.assertRegex(self.h, r"code\s*===\s*401")
        self.assertRegex(self.h, r"code\s*===\s*403")

    def test_a_400_stops_only_when_the_body_says_session(self):
        """The servlet also returns 400 for handled errors a retry may clear.

        Treating every 400 as permanent would reintroduce PR #36's bug in a new
        place: a chain that dies on something transient.
        """
        self.assertIn("400", self.h)
        self.assertRegex(self.h, r"responseText")
        self.assertRegex(self.h, r"/session\|log-in\|log in\|not valid/i")

    def test_a_permanent_failure_returns_without_scheduling(self):
        """The whole point: no further poll."""
        # Slice to the early return, not by counting braces: the block
        # contains nested braces and a naive split runs past the if and picks
        # up the retry path that follows it -- which is present and correct.
        expired = self.h.split("if (expired)")[1]
        self.assertIn("return", expired)
        expired = expired[:expired.index("return")]
        self.assertNotIn("schedule(", expired,
                         "a permanent failure must not schedule another poll")

    def test_a_transport_failure_still_backs_off_and_retries(self):
        """PR #36's fix must survive this one."""
        tail = self.h.split("if (expired)")[1]
        self.assertIn("aiPollFailures", tail)
        self.assertIn("schedule(", tail)
        self.assertIn("BACKOFF_CEILING", tail)

    def test_the_user_is_told_what_happened(self):
        """Silence for four hours is the actual harm."""
        self.assertIn("updateProgress", self.h)
        self.assertRegex(self.h, r"expired")
        self.assertRegex(self.h, r"sign in again|log in again|My Jobs")

    def test_it_says_the_job_is_safe(self):
        """The job survives on the server; only the session died."""
        self.assertRegex(self.h, r"safe on the server|job is safe")

    def test_the_error_status_gives_them_a_retry_button(self):
        """updateProgress('error', ...) renders a Retry, which is the right
        affordance here: after signing back in, retry is exactly the move."""
        view = os.path.join(os.path.dirname(JS), "PA_AIInterpretView.js")
        with open(view) as fh:
            v = fh.read()
        branch = v.split('} else if (status === "error")')[1][:600]
        self.assertIn("ai-retry-btn", branch)


if __name__ == "__main__":
    r = unittest.TextTestRunner(verbosity=2).run(
        unittest.TestLoader().loadTestsFromTestCase(PollGivesUpOnADeadSession))
    sys.exit(0 if r.wasSuccessful() else 1)
