"""Správa jednoho běhu: výstup, vstup, návratové kódy a ukončení vlastní skupiny procesů."""

import codecs
import os
import queue
import shlex
import signal
import subprocess
from threading import Event, Lock, Thread


class Runner:
    def __init__(self):
        self.messages = queue.Queue(512)
        self.cancel = Event()
        self.lock = Lock()
        self.process = None
        self.thread = None
        self.stop_thread = None
        self.status = "Připraveno"
        self.exit_code = None
        self.dropped = 0

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def emit(self, text):
        try:
            self.messages.put_nowait(text)
        except queue.Full:
            try:
                self.messages.get_nowait()
            except queue.Empty:
                pass
            self.dropped += 1
            try:
                self.messages.put_nowait(text)
            except queue.Full:
                pass

    def start(self, plan):
        if self.busy or (self.stop_thread and self.stop_thread.is_alive()):
            raise ValueError("Nejdříve dokončete nebo zastavte předchozí běh.")
        while True:
            try:
                self.messages.get_nowait()
            except queue.Empty:
                break
        self.dropped = 0
        self.cancel.clear()
        self.exit_code = None
        self.status = "Běží: " + plan.title
        self.thread = Thread(
            target=self._run, args=(plan,), name="project-launcher", daemon=False
        )
        self.thread.start()

    def _run(self, plan):
        try:
            for command in plan.commands:
                if self.cancel.is_set():
                    break
                self.emit("\n$ " + shlex.join(command) + "\n")
                environment = dict(
                    os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8"
                )
                with self.lock:
                    if self.cancel.is_set():
                        break
                    self.process = process = subprocess.Popen(
                        command,
                        cwd=plan.cwd,
                        env=environment,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        start_new_session=(os.name == "posix"),
                        bufsize=0,
                    )
                os.set_blocking(process.stdin.fileno(), False)
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                try:
                    while chunk := os.read(process.stdout.fileno(), 4096):
                        self.emit(decoder.decode(chunk))
                    self.emit(decoder.decode(b"", final=True))
                    code = process.wait()
                finally:
                    process.stdout.close()
                    if process.stdin and not process.stdin.closed:
                        process.stdin.close()
                    with self.lock:
                        self.process = None
                self.exit_code = code
                if code and not (
                    plan.timeout_is_success
                    and code == 42
                    and command == plan.commands[-1]
                ):
                    if not self.cancel.is_set():
                        self.status = f"Chyba · návratový kód {code}"
                    break
            else:
                self.status = (
                    "Dokončeno"
                    if self.exit_code != 42
                    else "Dokončeno · časový limit Wokwi"
                )
            if self.cancel.is_set():
                self.status = "Zastaveno"
            self.emit("\n[" + self.status + "]\n")
        except (OSError, ValueError) as exc:
            self.status = "Spuštění selhalo: " + str(exc)
            self.emit("\n" + self.status + "\n")

    def send(self, text):
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None or process.stdin.closed:
                raise ValueError("Program právě nepřijímá vstup.")
            try:
                raw = (text + "\n").encode("utf-8")
                if len(raw) > 4096:
                    raise ValueError("Jeden vstupní řádek může mít nejvýše 4096 bajtů.")
                if os.write(process.stdin.fileno(), raw) != len(raw):
                    raise ValueError("Program převzal jen část vstupu.")
            except (BrokenPipeError, OSError) as exc:
                raise ValueError("Program už vstup uzavřel.") from exc
        self.emit("> " + text + "\n")

    def end_input(self):
        with self.lock:
            if self.process and not self.process.stdin.closed:
                self.process.stdin.close()

    @staticmethod
    def _signal(process, sig):
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif sig == signal.SIGKILL:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    def stop(self):
        self.cancel.set()
        if self.stop_thread and self.stop_thread.is_alive():
            return
        with self.lock:
            process = self.process
        if process is not None:
            self.status = "Zastavuji · čekám na úklid programu…"
            self.stop_thread = Thread(target=self._stop, args=(process,), daemon=False)
            self.stop_thread.start()

    def _stop(self, process):
        # SIGINT dovolí ECU zavřít Tk, komunikační vlákna i vlastní Wokwi proces.
        self._signal(process, signal.SIGINT)
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._signal(process, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._signal(process, signal.SIGKILL)

    def drain(self, limit=100):
        chunks = []
        for _ in range(limit):
            try:
                chunks.append(self.messages.get_nowait())
            except queue.Empty:
                break
        return "".join(chunks)
