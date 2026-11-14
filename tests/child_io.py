"""Reading from and waiting for child processes with a time limit.

A test that reads a child's output with a bare ``readline()`` or waits with a bare ``wait()`` hangs for ever when one
byte is lost (a reused pty name, a child that died early, a machine under load). ``Child`` makes every read and every
wait finite: the stream is read by daemon threads, ``readline`` waits at most ``timeout`` seconds, and a miss fails the
test with a message that names what was awaited, the child's state and its stderr. A child that is still running when
the ``with`` block ends is killed, so a failed test leaves no process behind.
"""
from __future__ import annotations

import queue
import subprocess
import threading
import time
from collections.abc import Sequence
from typing import IO, Any

SLOW_S = 20.0  # a read that normally takes milliseconds; generous for a loaded machine, still finite
SETTLE_S = 2.0  # how long the end of stdout waits for the child to be reaped and for its stderr to run dry
_EOF = object()


class ChildTimeout(AssertionError):
    """The child did not deliver a line (or did not end) within the time limit."""


class ChildEnded(AssertionError):
    """The child's output ended before the awaited line came."""


def _pump(stream: IO[str], sink: queue.Queue) -> None:
    try:
        for line in iter(stream.readline, ""):
            sink.put(line)
    except (ValueError, OSError):
        pass  # the stream was closed under the reader
    finally:
        sink.put(_EOF)


class Child:
    """A child process with time-limited stdout lines and a time-limited end.

    Use as a context manager. ``stdin`` is a pipe (``send`` / ``finish``), stdout and stderr are text pipes read by
    background threads, so neither a silent child nor a chatty one can block the test.
    """

    def __init__(self, argv: Sequence[str], *, env: dict[str, str] | None = None, cwd: Any = None,
                 default_timeout: float = SLOW_S, settle_timeout: float = SETTLE_S):
        self.argv = [str(a) for a in argv]
        self.default_timeout = default_timeout
        self.settle_timeout = settle_timeout
        self.proc = subprocess.Popen(
            self.argv, env=env, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self._out: queue.Queue = queue.Queue()
        self._err: queue.Queue = queue.Queue()
        self.stderr_lines: list[str] = []
        self.stdout_lines: list[str] = []  # every line seen by readline
        self._ended = False
        self._threads = [threading.Thread(target=_pump, args=(self.proc.stdout, self._out), daemon=True),
                         threading.Thread(target=_pump, args=(self.proc.stderr, self._err), daemon=True)]
        for t in self._threads:
            t.start()

    # -- state -------------------------------------------------------------------------------------------------------
    @property
    def returncode(self) -> int | None:
        return self.proc.poll()

    def stderr_text(self) -> str:
        """The child's stderr so far."""
        self._drain_err()
        return "".join(self.stderr_lines)

    def _drain_err(self) -> None:
        while True:
            try:
                item = self._err.get_nowait()
            except queue.Empty:
                return
            if item is not _EOF:
                self.stderr_lines.append(item)

    def _settle(self) -> None:
        """After the end of stdout: give the child a bounded time to be reaped and its stderr reader to finish.

        A child closes its pipes while it exits, before ``poll()`` can see the exit code, and the stderr reader can
        trail the stdout reader. Asking at once would report "still running" (and miss the last stderr lines) for a
        child that ends a moment later. One deadline covers both waits, so a child that closed stdout but runs on
        costs ``settle_timeout`` seconds, not a hang, and is then reported as still running, which is true.
        """
        deadline = time.monotonic() + self.settle_timeout
        try:
            self.proc.wait(timeout=self.settle_timeout)
        except subprocess.TimeoutExpired:
            pass
        self._threads[1].join(timeout=max(0.0, deadline - time.monotonic()))

    def _describe(self) -> str:
        rc = self.proc.poll()
        state = "still running" if rc is None else f"exited with {rc}"
        seen = "".join(self.stdout_lines)[-500:]
        return f"child {self.argv[-3:]!r} {state}; stdout so far: {seen!r}; stderr: {self.stderr_text()[-1500:]!r}"

    # -- reading -----------------------------------------------------------------------------------------------------
    def readline(self, what: str = "a line", timeout: float | None = None) -> str:
        """The next stdout line (with its newline). Fails with ChildTimeout after ``timeout`` seconds and with
        ChildEnded when the output is at its end."""
        limit = self.default_timeout if timeout is None else timeout
        if self._ended:
            raise ChildEnded(f"waited for {what}, but the output of the child had ended already; {self._describe()}")
        try:
            item = self._out.get(timeout=limit)
        except queue.Empty:
            raise ChildTimeout(f"no {what} from the child within {limit:g} s; {self._describe()}") from None
        if item is _EOF:
            self._ended = True
            self._settle()
            raise ChildEnded(f"the output of the child ended while waiting for {what}; {self._describe()}")
        self.stdout_lines.append(item)
        return item

    def read_remaining(self, timeout: float | None = None) -> str:
        """Everything the child still writes until it closes its stdout (time-limited)."""
        limit = self.default_timeout if timeout is None else timeout
        deadline = time.monotonic() + limit
        out: list[str] = []
        while not self._ended:
            try:
                item = self._out.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                raise ChildTimeout(f"the output of the child did not end within {limit:g} s; {self._describe()}") from None
            if item is _EOF:
                self._ended = True
            else:
                self.stdout_lines.append(item)
                out.append(item)
        return "".join(out)

    # -- writing and ending ------------------------------------------------------------------------------------------
    def send(self, text: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(text)
        self.proc.stdin.flush()

    def finish(self, stdin_text: str = "\n", timeout: float | None = None) -> int:
        """Send ``stdin_text``, close stdin and wait for the end. A child that does not end within ``timeout`` seconds
        is killed and the call fails with ChildTimeout. Returns the exit code."""
        limit = self.default_timeout if timeout is None else timeout
        try:
            if self.proc.stdin is not None and not self.proc.stdin.closed:
                try:
                    self.proc.stdin.write(stdin_text)
                    self.proc.stdin.close()
                except (BrokenPipeError, ValueError, OSError):
                    pass  # the child is gone already; its exit code tells the rest
            try:
                self.proc.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                described = self._describe()
                self.kill()
                raise ChildTimeout(f"the child did not end within {limit:g} s after its input; {described}") from None
        finally:
            self._reap()
        return self.proc.returncode

    def kill(self) -> None:
        """End the child now (no error if it is gone) and close the pipes."""
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL not delivered within 10 s
            pass
        self._reap()

    def _reap(self) -> None:
        """Let the reader threads see the end of the streams, then close the pipes (no ResourceWarning)."""
        for t in self._threads:
            t.join(timeout=5)
        # a reader thread still blocked in read() (a grandchild holds the pipe open) owns the buffer lock: closing
        # would block as well, so only streams whose reader has ended are closed
        streams = [(self.proc.stdin, None), (self.proc.stdout, self._threads[0]), (self.proc.stderr, self._threads[1])]
        for stream, reader in streams:
            if stream is not None and not stream.closed and (reader is None or not reader.is_alive()):
                try:
                    stream.close()
                except (ValueError, OSError):
                    pass
        self._drain_err()

    def __enter__(self) -> Child:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.kill()
