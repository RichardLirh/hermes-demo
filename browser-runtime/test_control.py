import threading
import unittest
from control import SessionControl, Rejected


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.c = SessionControl("owner", "run", "sandbox", "browser", lambda: self.now)

    def test_handoff_keeps_session_and_rejects_stale_agent(self):
        page = {"value": "agent draft"}
        self.c.transfer("owner", 1, "USER")
        with self.assertRaises(Rejected):
            self.c.operate("owner", 1, "AGENT", lambda: page.update(value="stale"))
        self.c.operate("owner", 2, "USER", lambda: page.update(value="human edit"))
        self.c.transfer("owner", 2, "AGENT")
        self.assertEqual(self.c.operate("owner", 3, "AGENT", lambda: page["value"]), "human edit")
        self.assertEqual(self.c.snapshot()["browserSessionId"], "browser")

    def test_handoff_waits_for_inflight_operation(self):
        started, finish, handed = threading.Event(), threading.Event(), threading.Event()
        def action():
            started.set()
            self.assertTrue(finish.wait(2))
        worker = threading.Thread(target=lambda: self.c.operate("owner", 1, "AGENT", action))
        worker.start()
        self.assertTrue(started.wait(2))
        def handoff():
            self.c.transfer("owner", 1, "USER")
            handed.set()
        transfer = threading.Thread(target=handoff)
        transfer.start()
        self.assertFalse(handed.wait(.05))
        finish.set()
        worker.join(2)
        transfer.join(2)
        self.assertTrue(handed.is_set())

    def test_owner_expiry_and_changed_draft(self):
        with self.assertRaises(Rejected):
            self.c.transfer("intruder", 1, "USER")
        token = self.c.approve("owner", 1, "draft", ttl=5)
        self.now = 106
        with self.assertRaises(Rejected):
            self.c.submit("owner", 1, "AGENT", token, "draft", "a", lambda: 1)
        token = self.c.approve("owner", 1, "draft")
        with self.assertRaises(Rejected):
            self.c.submit("owner", 1, "AGENT", token, "changed", "b", lambda: 1)

    def test_submission_retry_does_not_repeat_side_effect(self):
        effects = []
        token = self.c.approve("owner", 1, "draft")
        def action():
            effects.append("submitted")
            return "receipt"
        self.assertEqual(self.c.submit("owner", 1, "AGENT", token, "draft", "op", action), "receipt")
        self.assertEqual(self.c.submit("owner", 1, "AGENT", token, "draft", "op", action), "receipt")
        self.assertEqual(effects, ["submitted"])

    def test_uncertain_submission_is_not_automatically_replayed(self):
        token = self.c.approve("owner", 1, "draft")
        def action():
            raise TimeoutError("Lost response after send")
        with self.assertRaises(TimeoutError):
            self.c.submit("owner", 1, "AGENT", token, "draft", "op", action)
        with self.assertRaises(Rejected):
            self.c.submit("owner", 1, "AGENT", token, "draft", "op", lambda: "duplicate")

    def test_handoff_invalidates_approval_and_close_blocks_operations(self):
        token = self.c.approve("owner", 1, "draft")
        self.c.transfer("owner", 1, "USER")
        self.c.transfer("owner", 2, "AGENT")
        with self.assertRaises(Rejected):
            self.c.submit("owner", 3, "AGENT", token, "draft", "op", lambda: 1)
        self.c.close("owner", 3)
        with self.assertRaises(Rejected):
            self.c.operate("owner", 4, "AGENT", lambda: 1)


if __name__ == "__main__":
    unittest.main()
