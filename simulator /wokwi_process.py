"""Vlastněný CLI proces: omezené fronty, neblokující GUI, oddělená data a log."""
import codecs
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
from threading import Event, Lock, Thread
from time import monotonic, sleep


def find_cli():
    candidates = [Path(sys.executable).parent/'wokwi-cli',
                  Path(__file__).resolve().parent/'.venv/bin/wokwi-cli']
    located = shutil.which('wokwi-cli')
    if located:
        candidates.append(Path(located))
    return next((str(p) for p in candidates if p.is_file() and os.access(p, os.X_OK)), '')


def find_pio():
    candidates = [shutil.which('pio'), shutil.which('platformio'),
                  str(Path(sys.executable).parent/'pio'),
                  str(Path.home()/'.platformio/penv/bin/pio')]
    return next((str(p) for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), '')


class Redactor:
    """Zadrží konec bloku, aby neunikl ani token rozdělený mezi dvě čtení."""
    def __init__(self, secrets):
        self.secrets = tuple(s for s in secrets if s)
        self.pending = ''

    def feed(self, text, final=False):
        text = self.pending+text
        for secret in self.secrets:
            text = text.replace(secret, '[token skryt]')
        keep = 0
        if not final:
            for secret in self.secrets:
                for length in range(1, min(len(secret), len(text)+1)):
                    if text.endswith(secret[:length]):
                        keep = max(keep, length)
        cut = len(text)-keep
        result, self.pending = text[:cut], text[cut:]
        return result


class WokwiProcess:
    def __init__(self, log_capacity=1000, frame_capacity=256):
        self.logs = queue.Queue(log_capacity)
        self.frames = queue.Queue(frame_capacity)
        self.input = queue.Queue(8)
        self.stop_event = Event()
        self.started = Event()
        self.transport_fault = Event()
        self.lock = Lock()
        self.thread = None
        self.process = None
        self.state = 'idle'
        self.exit_code = None
        self.dropped_logs = 0
        self.dropped_frames = 0
        self.error = ''
        self.capture_frames = False

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def log(self, text):
        text = text[:20000]
        try:
            self.logs.put_nowait(text)
        except queue.Full:
            try:
                self.logs.get_nowait()
            except queue.Empty:
                pass
            self.dropped_logs += 1
            try:
                self.logs.put_nowait(text)
            except queue.Full:
                pass

    @staticmethod
    def _clear(q):
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                break

    def start(self, command, cwd, token=None, capture_frames=False):
        if self.busy:
            raise RuntimeError('Před dalším spuštěním zastavte současný proces.')
        if not command:
            raise ValueError('Prázdný příkaz')
        self.stop_event.clear()
        self.started.clear()
        self.transport_fault.clear()
        self._clear(self.input)
        self._clear(self.frames)
        self.exit_code = None
        self.error = ''
        self.capture_frames = capture_frames
        self.state = 'starting'
        self.thread = Thread(target=self._run, args=(list(command), str(cwd), token),
                             name='wokwi-cli', daemon=False)
        self.thread.start()

    def _line(self, line):
        line = line.rstrip('\r')
        self.log(line)
        if self.capture_frames and line.lstrip().startswith('{'):
            raw = (line+'\n').encode()
            if len(raw)>16384:
                self.transport_fault.set()
                self.dropped_frames += 1
                return
            try:
                self.frames.put_nowait(raw)
            except queue.Full:
                self.dropped_frames += 1
                self.transport_fault.set()

    def _read(self, pipe, redactor):
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        pending = ''
        try:
            while True:
                chunk = os.read(pipe.fileno(), 4096)
                if not chunk:
                    pending += redactor.feed(decoder.decode(b'', final=True), final=True)
                    break
                pending += redactor.feed(decoder.decode(chunk))
                while '\n' in pending:
                    line, pending = pending.split('\n', 1)
                    self._line(line)
                if len(pending)>20000:
                    self.log(pending[:20000]+' [dlouhý řádek zkrácen]')
                    pending = ''
                    self.transport_fault.set()
            if pending:
                self._line(pending)
        except (OSError, ValueError) as exc:
            if not self.stop_event.is_set():
                self.log(redactor.feed(str(exc), final=True))
        finally:
            pipe.close()

    def send(self, raw):
        if len(raw)>16384:
            raise ValueError('CLI frame exceeds 16384 bytes')
        if not self.started.is_set() or not self.busy or self.stop_event.is_set():
            raise ConnectionError('Wokwi CLI neběží')
        if self.transport_fault.is_set():
            raise BufferError('Přetečení CLI transportu; zastavte a znovu spusťte běh')
        try:
            self.input.put_nowait(bytes(raw))
        except queue.Full:
            self.transport_fault.set()
            raise BufferError('Plná vstupní fronta Wokwi CLI')

    def _write(self, process):
        try:
            while not self.stop_event.is_set() and process.poll() is None:
                try:
                    raw = self.input.get(timeout=.05)
                except queue.Empty:
                    continue
                data = memoryview(raw)
                while data:
                    written = process.stdin.write(data)
                    if not written:
                        raise BrokenPipeError('CLI stdin closed')
                    data = data[written:]
        except (OSError, ValueError):
            self.transport_fault.set()
        finally:
            process.stdin.close()

    @staticmethod
    def _signal(process, force=False):
        try:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            elif force:
                process.kill()
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    def _run(self, command, cwd, token):
        env = os.environ.copy()
        if token:
            env['WOKWI_CLI_TOKEN'] = token
        redactor = Redactor((env.get('WOKWI_CLI_TOKEN'),))
        process = None
        reader = writer = None
        requested_stop = False
        try:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
                        start_new_session=os.name=='posix')
            with self.lock:
                self.process = process
            self.state = 'running'
            self.started.set()
            reader = Thread(target=self._read, args=(process.stdout, redactor), name='wokwi-cli-output')
            writer = Thread(target=self._write, args=(process,), name='wokwi-cli-input')
            reader.start()
            writer.start()
            stop_at = None
            while process.poll() is None:
                if self.stop_event.wait(.05):
                    requested_stop = True
                    self.state = 'stopping'
                    if stop_at is None:
                        self._signal(process)
                        stop_at = monotonic()+2
                    elif monotonic()>=stop_at:
                        self._signal(process, force=True)
                        stop_at = float('inf')
                    sleep(.02)
            self.exit_code = process.wait()
            writer.join(1)
            reader.join(.5)
            if reader.is_alive():
                # Ukončíme i vlastní potomky, kteří po sobě drží otevřenou pipe.
                self._signal(process, force=True)
                reader.join(2)
            self.state = 'stopped' if requested_stop else ('completed' if self.exit_code==0 else 'failed')
        except Exception as exc:
            self.error = redactor.feed(str(exc), final=True)
            self.log(self.error)
            self.state = 'failed'
        finally:
            if process is not None and process.poll() is None:
                self._signal(process, force=True)
                process.wait(timeout=3)
            for thread in (reader, writer):
                if thread and thread.is_alive():
                    thread.join(2)
            with self.lock:
                self.process = None

    def stop(self):
        self.stop_event.set()

    def close(self):
        self.stop()
        if self.thread is not None:
            self.thread.join(8)
            if self.thread.is_alive():
                raise RuntimeError('Proces Wokwi CLI se nepodařilo ukončit')


class ProcessTransport:
    """Transport pro bridge: CLI --interactive stdin / serial JSON na stdout."""
    def __init__(self, runner):
        self.runner = runner
        self.closed = Event()

    def open(self):
        if not self.runner.started.wait(.1) or not self.runner.busy:
            raise ConnectionError('Čekám na Wokwi CLI')
        if self.runner.transport_fault.is_set():
            raise BufferError('CLI transport ztratil data; je nutné nové spuštění')

    def read(self):
        if self.closed.is_set():
            return b''
        if self.runner.transport_fault.is_set():
            raise BufferError('CLI transport ztratil data')
        try:
            return self.runner.frames.get(timeout=.02)
        except queue.Empty:
            if not self.runner.busy:
                raise ConnectionError('Wokwi CLI skončil')
            return b''

    def write(self, raw):
        if self.closed.is_set():
            raise ConnectionError('Transport uzavřen')
        self.runner.send(raw)

    def close(self):
        self.closed.set()
