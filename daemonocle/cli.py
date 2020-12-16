"""Utilities for building command-line interfaces for your daemons"""

import inspect
import sys
from functools import wraps

import click

from .core import Daemon


def _parse_cli_options(func):
    """Parse click options from a function signature (Python 3 only)"""
    if sys.version_info.major < 3:
        return []

    options = []
    for param in inspect.signature(func).parameters.values():
        if param.kind not in {param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY}:
            # Only keyword arguments are currently supported
            continue

        option_name = '--' + param.name.lower().replace('_', '-').strip('-')
        kwargs = {}
        if param.annotation in {str, int, float, bool}:
            # Only basic types are currently supported
            kwargs['type'] = param.annotation

        if param.default != param.empty:
            kwargs['default'] = param.default
        else:
            # If the param doesn't have a default, then it's required
            kwargs['required'] = True

        if param.annotation == bool or isinstance(param.default, bool):
            if param.default is True:
                # If the default of a boolean option is ``True``, then add a
                # ``--no-x` off switch
                option_name += '/--no-' + option_name.lstrip('-')
            else:
                # If the default is ``False``, just make it a basic flag
                kwargs['is_flag'] = True

        args = (option_name, param.name)

        options.append((args, kwargs))

    # Reverse it so the decorators are applied in the correct order
    return options[::-1]


class DaemonCLI(click.MultiCommand):
    """A Command class for `click <http://click.pocoo.org/>`_.

    This class automatically adds start, stop, restart, and status
    subcommands for daemons.
    """

    def __init__(
            self, callback=None, daemon_params=None, is_worker=True,
            daemon_class=Daemon, daemon=None, **kwargs):
        """Create a new DaemonCLI object."""
        self.daemon_params = daemon_params or {}
        self.daemon_class = (
            daemon_class if daemon is None else daemon.__class__)
        self.is_worker = (
            is_worker and callback is not None and callable(callback))

        if daemon is None:
            daemon = self.daemon_class(**self.daemon_params)

        if ((not daemon.worker or not callable(daemon.worker)) and
                self.is_worker):
            # If the callback is the worker, then don't pass the
            # callback to the parent class so we don't call it twice
            daemon.worker = callback
            callback = None

        # The context object will be the Daemon object
        context_settings = {'obj': daemon}

        if not kwargs.get('help'):
            kwargs['help'] = daemon.worker.__doc__

        super(DaemonCLI, self).__init__(
            callback=callback, context_settings=context_settings, **kwargs)

    def list_commands(self, ctx):
        """Get a list of subcommands."""
        return self.daemon_class.list_actions()

    def get_command(self, ctx, name):
        """Get a callable command object."""
        if name not in self.daemon_class.list_actions():
            return None

        # The context object is a Daemon object
        daemon = ctx.obj

        action = daemon.get_action(name)

        @wraps(action)
        def subcommand(*args, **kwargs):
            return action(*args, **kwargs)

        if name in {'start', 'stop', 'restart'}:
            if name in {'start', 'restart'}:
                subcommand = click.option(
                    '--debug', is_flag=True,
                    help='Do NOT detach and run in the background.',
                )(subcommand)
            if name in {'stop', 'restart'}:
                subcommand = click.option(
                    '--force', is_flag=True,
                    help='Kill the daemon forcefully after the timeout.',
                )(subcommand)
                subcommand = click.option(
                    '--timeout', type=int, default=None,
                    help=('Number of seconds to wait for the daemon to stop. '
                          'Overrides "stop_timeout" from daemon definition.'),
                )(subcommand)
        elif name == 'status':
            subcommand = click.option(
                '--fields', type=str, default=None,
                help='Comma-separated list of process info fields to display.',
            )(subcommand)
            subcommand = click.option(
                '--json', is_flag=True,
                help='Show the status in JSON format.',
            )(subcommand)
        else:
            # This is a custom action so try to parse the CLI options
            # by inspecting the function
            for option_args, option_kwargs in _parse_cli_options(action):
                subcommand = click.option(
                    *option_args, **option_kwargs)(subcommand)

        # Make it into a click command
        subcommand = click.command(name)(subcommand)

        return subcommand


def cli(**daemon_params):
    return click.command(cls=DaemonCLI, daemon_params=daemon_params)


# Make a pass decorator for passing the Daemon object
pass_daemon = click.make_pass_decorator(Daemon)
