"""send_to goes through the public `hermes send` CLI: text over stdin, failures raised."""

import os
import stat
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psychopomp_store as store  # noqa: E402

FAKE = """#!/bin/sh
cat > "$(dirname "$0")/stdin.txt"
echo "$@" > "$(dirname "$0")/args.txt"
if [ "$3" = "telegram:fail" ]; then echo '{"error": "Platform not configured"}'; exit 1; fi
echo '{"success": true}'
"""


class SendTo(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        exe = Path(self.dir, "hermes")
        exe.write_text(FAKE)
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
        self.path = os.environ["PATH"]
        os.environ["PATH"] = self.dir + os.pathsep + self.path

    def tearDown(self):
        os.environ["PATH"] = self.path

    def test_text_goes_over_stdin_not_argv(self):
        store.send_to("telegram:111", "Sealed words stay out of ps")
        self.assertEqual(Path(self.dir, "stdin.txt").read_text(), "Sealed words stay out of ps")
        args = Path(self.dir, "args.txt").read_text()
        self.assertEqual(args.split(), ["send", "--to", "telegram:111", "--json"])
        self.assertNotIn("Sealed", args)

    def test_failure_raises_with_the_reason(self):
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            store.send_to("telegram:fail", "x")

    def test_missing_cli_raises(self):
        os.environ["PATH"] = tempfile.mkdtemp()
        with mock.patch("importlib.util.find_spec", return_value=None), \
                self.assertRaisesRegex(RuntimeError, "not on PATH"):
            store.send_to("telegram:111", "x")


if __name__ == "__main__":
    unittest.main()
