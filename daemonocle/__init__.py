"""
daemonocle
==========

A Python library for creating super fancy Unix daemons
"""

from .cli import DaemonCLI, pass_daemon
from .core import Daemon, expose_action
from .exceptions import DaemonEnvironmentError, DaemonError

__all__ = [
    'Daemon',
    'DaemonCLI',
    'DaemonEnvironmentError',
    'DaemonError',
    'expose_action',
    'pass_daemon',
]
