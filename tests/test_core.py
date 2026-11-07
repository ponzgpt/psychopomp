"""The invariants that make Psychopomp trustworthy."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psychopomp_core as core  # noqa: E402

D = core.DAY


def armed(t0=0.0):
    s = core.new_state(now=t0)
    s.update(armed=True, silence_days=30, checkin_every_days=3, checkins=3)
    s["owner"] = {"name": "Ana", "channels": ["telegram:111"]}
    s["trusted"] = {"name": "Leo", "channels": ["telegram:222"]}
    core.seal_letter(s, "Mar", "Te quiero.", "For you", "telegram:333", now=t0)
    core.seal_letter(s, "Grandma", "Gracias por todo.", "Gracias", "", now=t0)  # via Leo
    core.write_page(s, "First week", "We shipped Psychopomp.", now=t0)
    return s


def run_to_code(s, t0=0.0):
    """Tick once a day (with a real clock) until the trusted contact has been asked."""
    for d in range(1, 60):
        core.tick(s, t0 + d * D, real_clock=False)
        if s["phase"] == "awaiting_trusted":
            return t0 + d * D
    raise AssertionError("never reached the trusted contact")


def kinds(actions, kind):
    return [a for a in actions if a["type"] == kind]


class SwitchTest(unittest.TestCase):
    def test_full_passage(self):
        s = armed()
        core.tick(s, 29 * D, real_clock=False)
        self.assertEqual(s["phase"], "watching")
        t = run_to_code(s)
        self.assertEqual(t, 39 * D)  # 30 silent + 3 check-ins every 3 days
        self.assertEqual(s["checkins_sent"], 3)
        # never early: a year of ticks without the code delivers nothing
        for d in range(40, 400, 7):
            self.assertEqual(kinds(core.tick(s, d * D, real_clock=False), "letter"), [])
        self.assertEqual(s["trusted_reminders"], core.TRUSTED_REMINDERS)
        a, handled = core.inbound(s, "whatsapp:999", f"here {s['code'].lower()}", 401 * D)
        self.assertTrue(handled)
        self.assertEqual(s["phase"], "delivered")
        letters = kinds(a, "letter")
        self.assertEqual(letters[0]["targets"], ["telegram:333"])
        self.assertEqual(letters[1]["targets"], ["telegram:222"])  # no channel: Leo passes it on
        self.assertIn("Gracias por todo.", letters[1]["text"])
        self.assertEqual(kinds(a, "book")[0]["targets"], ["telegram:222"])
        # a refused send retries; a confirmed one does not
        self.assertEqual(len(kinds(core.tick(s, 402 * D, real_clock=False), "letter")), 2)
        for l in letters:
            core.mark_delivered(s, l["id"], 403 * D)
        self.assertEqual(kinds(core.tick(s, 404 * D, real_clock=False), "letter"), [])

    def test_owner_anywhere_resets(self):
        s = armed()
        run_to_code(s)
        a, handled = core.inbound(s, "Telegram:111", "back from the mountains", 40 * D)
        self.assertFalse(handled)
        self.assertEqual(s["phase"], "watching")
        self.assertIsNone(s["code"])
        self.assertEqual(a[0]["target"], "telegram:222")

    def test_hermes_downtime_is_not_your_silence(self):
        s = armed()
        core.tick(s, 1 * D)
        core.tick(s, 45 * D)  # Hermes was off for 44 days
        self.assertEqual(s["phase"], "watching")

    def test_guessing_rotates_the_code(self):
        s = armed()
        run_to_code(s)
        first = s["code"]
        for _ in range(core.MAX_BAD_CODES):
            a, _ = core.inbound(s, "telegram:666", "PSY-123456", 40 * D)
        self.assertNotEqual(s["code"], first)
        self.assertEqual(s["phase"], "awaiting_trusted")

    def test_invitation_registers_the_trusted_contact(self):
        s = armed()
        code = core.invite(s)
        a, handled = core.inbound(s, "telegram:777", f"hi {code}", 1 * D, reply_to="telegram:777")
        self.assertTrue(handled)
        self.assertIn("telegram:777", core.trusted_channels(s))
        a, handled = core.inbound(s, "telegram:888", f"{code}", 1 * D)
        self.assertNotIn("telegram:888", core.trusted_channels(s))

    def test_views_hide_letters_and_codes(self):
        s = armed()
        run_to_code(s)
        v = core.public_view(s, 40 * D)
        self.assertNotIn("body", v["letters"][0])
        self.assertNotIn(s["code"], str(v))


class BookTest(unittest.TestCase):
    def test_weekly_then_yearly(self):
        s = armed()
        self.assertIsNone(core.page_due(s, 3 * D))
        self.assertEqual(core.page_due(s, 7 * D), "week")
        for w in range(1, 53):
            core.write_page(s, f"Week {w}", "…", now=w * 7 * D)
        self.assertEqual(core.page_due(s, 53 * 7 * D), "year")
        core.write_page(s, "2027", "A good year.", kind="year", now=53 * 7 * D)
        self.assertEqual(core.page_due(s, 54 * 7 * D), "week")
        self.assertIn("A good year.", core.render_book(s))

    def test_nudge_once_per_week(self):
        s = armed()
        self.assertEqual(len(core._book_nudge(s, 8 * D)), 1)
        self.assertEqual(core._book_nudge(s, 9 * D), [])


class RehearsalTest(unittest.TestCase):
    def test_rehearsal_sends_only_to_owner_and_leaves_real_state(self):
        s = armed()
        out = core.rehearsal_start(s, 0)
        for d in range(60):
            out += core.rehearsal_step(s, d)
            if s["rehearsal"]["status"] == "awaiting_code":
                break
        self.assertEqual(s["rehearsal"]["status"], "awaiting_code")
        out += core.inbound(s, "telegram:111", s["rehearsal"]["sim"]["code"], 100)[0]
        self.assertEqual(s["rehearsal"]["status"], "done")
        self.assertTrue(all(a["target"] == "telegram:111" for a in out))
        self.assertTrue(any("Leo" in a["text"] or "telegram:222" in a["text"] for a in out))
        self.assertTrue(any("sealed letter" in a["text"] for a in out))
        self.assertNotIn("Te quiero.", str(out))  # sealed words never appear
        self.assertEqual(s["phase"], "watching")  # the real switch did not move
        self.assertIsNone(s["letters"][0]["delivered_at"])


if __name__ == "__main__":
    unittest.main()
