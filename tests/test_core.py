"""The switch must never deliver early, and must deliver once confirmed."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psychopomp_core as core  # noqa: E402

D = core.DAY


def armed():
    s = core.new_state(now=0)
    s.update(armed=True, silence_days=30, checkin_every_days=3, checkins=3)
    s["owner"] = {"name": "Ana", "channels": ["telegram:111", "email:ana@example.com"]}
    s["trusted"] = {"name": "Leo", "channels": ["email:leo@example.com"]}
    core.seal_letter(s, "Mar", "mar@example.com", "For you", "Te quiero.", now=0)
    return s


class SwitchTest(unittest.TestCase):
    def test_full_path_to_delivery(self):
        s = armed()
        self.assertEqual(core.tick(s, 29 * D), [])
        a = core.tick(s, 30 * D)
        self.assertEqual(s["phase"], "checking_in")
        self.assertEqual(len(a), 2)  # both owner channels
        core.tick(s, 33 * D)
        core.tick(s, 36 * D)
        self.assertEqual(s["checkins_sent"], 3)
        self.assertEqual(core.tick(s, 37 * D), [])  # not before the interval
        a = core.tick(s, 39 * D)
        self.assertEqual(s["phase"], "awaiting_trusted")
        self.assertIn(s["code"], a[0]["text"])
        # nothing is ever delivered without the code
        self.assertEqual(core.tick(s, 400 * D), [])
        self.assertIsNone(s["letters"][0]["delivered_at"])
        # wrong code is swallowed, right code (from any channel, any case) delivers
        a, handled = core.inbound(s, "whatsapp:999", "PSY-000000", 401 * D)
        self.assertTrue(handled)
        self.assertEqual(s["phase"], "awaiting_trusted")
        a, handled = core.inbound(s, "telegram:555", f"here: {s['code'].lower()}", 402 * D)
        self.assertTrue(handled)
        self.assertEqual(s["phase"], "delivered")
        emails = [x for x in a if x["type"] == "letter"]
        self.assertEqual(emails[0]["to"], "mar@example.com")
        self.assertIn("Te quiero.", emails[0]["body"])
        # a refused send is retried on the next tick; a confirmed one is not
        self.assertEqual(len(core.tick(s, 403 * D)), 1)
        core.mark_delivered(s, emails[0]["id"], 404 * D)
        self.assertEqual(core.tick(s, 405 * D), [])

    def test_owner_on_any_channel_resets(self):
        s = armed()
        core.tick(s, 30 * D)
        for t in (33, 36, 39):
            core.tick(s, t * D)
        self.assertEqual(s["phase"], "awaiting_trusted")
        a, handled = core.inbound(s, "Telegram:111", "sorry, was hiking", 40 * D)
        self.assertFalse(handled)  # the owner's message still goes to the model
        self.assertEqual(s["phase"], "watching")
        self.assertIsNone(s["code"])
        self.assertEqual(a[0]["target"], "email:leo@example.com")  # trusted contact is told

    def test_guessing_rotates_the_code(self):
        s = armed()
        for t in (30, 33, 36, 39):
            core.tick(s, t * D)
        first = s["code"]
        for _ in range(core.MAX_BAD_CODES):
            a, _ = core.inbound(s, "telegram:666", "PSY-123456", 40 * D)
        self.assertNotEqual(s["code"], first)
        self.assertIn(s["code"], a[-1]["text"])
        self.assertEqual(s["phase"], "awaiting_trusted")

    def test_disarmed_never_acts_and_view_hides_secrets(self):
        s = armed()
        s["armed"] = False
        self.assertEqual(core.tick(s, 999 * D), [])
        v = core.public_view(s, 0)
        self.assertNotIn("body", v["letters"][0])
        self.assertNotIn("code", v)

    def test_time_dilation(self):
        s = armed()
        s["day_seconds"] = 60
        core.tick(s, 30 * 60)
        self.assertEqual(s["phase"], "checking_in")


if __name__ == "__main__":
    unittest.main()
