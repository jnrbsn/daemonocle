"""
daemonocle
==========

A Python library for creating super fancy Unix daemons
"""

from .core import Daemon, expose_action
from .cli import DaemonCLI, pass_daemon
from .exceptions import DaemonError


__all__ = [
    'Daemon',
    'expose_action',
    'DaemonCLI',
    'pass_daemon',
    'DaemonError',
]
