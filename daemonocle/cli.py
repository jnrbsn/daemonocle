"""Utilities for building command-line interfaces for your daemons"""

import inspect
from functools import wraps

import click

from .core import Daemon
from .helpers import MultiDaemon


def _parse_cli_options(func):
    """Parse click options from a function signature"""
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
        daemon_params = daemon_params or {}
        if daemon is None:
            self.daemon = daemon_class(**daemon_params)
        else:
            self.daemon = daemon

        self.is_worker = (
            is_worker and callback is not None and callable(callback))

        if ((not self.daemon.worker or not callable(self.daemon.worker)) and
                self.is_worker):
            # If the callback is the worker, then don't pass the
            # callback to the parent class so we don't call it twice
            self.daemon.worker = callback
            callback = None

        # The context object will be the Daemon object
        context_settings = {'obj': self.daemon}

        if not kwargs.get('help'):
            kwargs['help'] = self.daemon.worker.__doc__

        super(DaemonCLI, self).__init__(
            callback=callback, context_settings=context_settings, **kwargs)

    def list_commands(self, ctx):
        """Get a list of subcommands."""
        return self.daemon.list_actions()

    def get_command(self, ctx, name):
        """Get a callable command object."""
        if name not in self.daemon.list_actions():
            return None

        action = self.daemon.get_action(name)

        @wraps(action)
        def command(*args, **kwargs):
            return action(*args, **kwargs)

        if name in {'start', 'stop', 'restart'}:
            if name in {'start', 'restart'}:
                command = click.option(
                    '--debug', is_flag=True,
                    help='Do NOT detach and run in the background.',
                )(command)
            if name in {'stop', 'restart'}:
                command = click.option(
                    '--force', is_flag=True,
                    help='Kill the daemon forcefully after the timeout.',
                )(command)
                command = click.option(
                    '--timeout', type=int, default=None,
                    help=('Number of seconds to wait for the daemon to stop. '
                          'Overrides "stop_timeout" from daemon definition.'),
                )(command)
            if isinstance(self.daemon, MultiDaemon):
                command = click.option(
                    '--worker-id', type=int, default=None,
                    help='The ID of the worker to {}.'.format(name),
                )(command)
        elif name == 'status':
            command = click.option(
                '--fields', type=str, default=None,
                help='Comma-separated list of process info fields to display.',
            )(command)
            command = click.option(
                '--json', is_flag=True,
                help='Show the status in JSON format.',
            )(command)
            if isinstance(self.daemon, MultiDaemon):
                command = click.option(
                    '--worker-id', type=int, default=None,
                    help='The ID of the worker whose status to get.',
                )(command)
        else:
            # This is a custom action so try to parse the CLI options
            # by inspecting the function
            for option_args, option_kwargs in _parse_cli_options(action):
                command = click.option(
                    *option_args, **option_kwargs)(command)

        # Make it into a click command
        command = click.command(name)(command)

        return command


def cli(**daemon_params):
    return click.command(cls=DaemonCLI, daemon_params=daemon_params)


# Make a pass decorator for passing the Daemon object
pass_daemon = click.make_pass_decorator(Daemon)
