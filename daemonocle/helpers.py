import os
import posixpath

try:
    from collections.abc import Callable
except ImportError:
    from collections import Callable

from daemonocle._utils import to_bytes


class ExecWorker(Callable):
    """A worker class that simply executes another program"""

    def __init__(self, prog, *args):
        self.prog = to_bytes(prog)
        self.args = tuple(to_bytes(a) for a in args)
        if b'/' in self.prog:
            self.prog = posixpath.realpath(self.prog)

    def __call__(self):  # pragma: no cover
        exec_prog = os.execv if self.prog[0] == b'/' else os.execvp
        exec_prog(self.prog, (self.prog,) + self.args)
