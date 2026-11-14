import os
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from wokwi_process import WokwiProcess, ProcessTransport, Redactor, find_cli


class WokwiProcessTests(unittest.TestCase):
    def finish(self, runner):
        runner.thread.join(4)
        self.assertFalse(runner.busy)
        lines = []
        while True:
            try:
                lines.append(runner.logs.get_nowait())
            except queue.Empty:
                break
        return "\n".join(lines)

    def test_redaction_every_split_and_immediate_line(self):
        secret = "wok_" + "X" * 40
        for split in range(1, len(secret)):
            r = Redactor([secret])
            parts = [
                r.feed("prefix " + secret[:split]),
                r.feed(secret[split:] + "\n"),
                r.feed("", final=True),
            ]
            text = "".join(parts)
            self.assertNotIn(secret, text)
            self.assertIn("[token skryt]", text)
        r = Redactor([secret])
        self.assertEqual(r.feed("ready\n"), "ready\n")

    def test_interactive_transport_and_secret_redaction(self):
        token = "wok_" + "Z" * 40
        code = "import os,sys; t=os.environ['WOKWI_CLI_TOKEN']; print(t,flush=True); print(sys.stdin.readline().strip(),flush=True)"
        runner = WokwiProcess()
        try:
            runner.start(
                [sys.executable, "-u", "-c", code],
                Path.cwd(),
                token=token,
                capture_frames=True,
            )
            transport = ProcessTransport(runner)
            self.assertTrue(runner.started.wait(1))
            transport.open()
            transport.write(b'{"hello":1}\n')
            self.assertEqual(runner.frames.get(timeout=2), b'{"hello":1}\n')
            text = self.finish(runner)
            self.assertNotIn(token, text)
            self.assertIn("[token skryt]", text)
            self.assertEqual(runner.state, "completed")
            self.assertEqual(runner.exit_code, 0)
            transport.close()
        finally:
            runner.close()

    def test_failure_and_missing_executable(self):
        runner = WokwiProcess()
        try:
            runner.start([sys.executable, "-c", "raise SystemExit(7)"], Path.cwd())
            self.finish(runner)
            self.assertEqual(runner.exit_code, 7)
            self.assertEqual(runner.state, "failed")
            runner.start(["/nonexistent/wokwi-cli"], Path.cwd())
            self.assertTrue(self.finish(runner))
            self.assertEqual(runner.state, "failed")
        finally:
            runner.close()

    def test_stop_owns_process_group(self):
        code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print('ready',flush=True); time.sleep(60)"
        runner = WokwiProcess()
        runner.start([sys.executable, "-u", "-c", code], Path.cwd())
        self.assertTrue(runner.started.wait(1))
        self.assertEqual(runner.logs.get(timeout=2), "ready")
        runner.close()
        self.assertFalse(runner.busy)
        self.assertEqual(runner.state, "stopped")

    def test_bounded_log_and_frame_queues(self):
        runner = WokwiProcess(log_capacity=3, frame_capacity=2)
        try:
            runner.start(
                [sys.executable, "-c", "for i in range(100): print('{\"i\":%d}'%i)"],
                Path.cwd(),
                capture_frames=True,
            )
            self.finish(runner)
            self.assertGreater(runner.dropped_logs, 0)
            self.assertGreater(runner.dropped_frames, 0)
            self.assertTrue(runner.transport_fault.is_set())
            self.assertLessEqual(runner.frames.qsize(), 2)
        finally:
            runner.close()

    def test_reject_concurrent_start(self):
        runner = WokwiProcess()
        try:
            runner.start([sys.executable, "-c", "import time; time.sleep(60)"], Path.cwd())
            with self.assertRaises(RuntimeError):
                runner.start([sys.executable, "--version"], Path.cwd())
        finally:
            runner.close()

    def test_cli_discovery(self):
        cli = find_cli()
        if cli:
            self.assertTrue(Path(cli).is_file() and os.access(cli, os.X_OK))
