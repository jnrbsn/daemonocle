"""Exceptions used internally by daemonocle"""


class DaemonError(Exception):
    """An exception class that daemonocle can raise for errors."""
    pass


class DaemonEnvironmentError(DaemonError):
    """An error that indicates something is wrong with the environment
    in which daemonocle is running."""
    pass
