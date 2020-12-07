"""Utilities for building command-line interfaces for your daemons"""

import click

from .core import Daemon


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
        self.daemon_class = daemon_class
        self.is_worker = is_worker

        if daemon is None:
            daemon = self.daemon_class(**self.daemon_params)

        if ((not daemon.worker or not callable(daemon.worker))
                and self.is_worker):
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

        def subcommand(debug=False):
            """Call a daemonocle action."""
            if daemon.detach and debug:
                daemon.detach = False

            daemon.do_action(name)

        # Override the docstring for the function so that it shows up
        # correctly in the help output
        subcommand.__doc__ = daemon.get_action(name).__doc__

        if name == 'start':
            # Add a --debug option for start
            subcommand = click.option(
                '--debug', is_flag=True,
                help='Do NOT detach and run in the background.'
            )(subcommand)

        # Make it into a click command
        subcommand = click.command(name)(subcommand)

        return subcommand


def cli(**daemon_params):
    return click.command(cls=DaemonCLI, daemon_params=daemon_params)


# Make a pass decorator for passing the Daemon object
pass_daemon = click.make_pass_decorator(Daemon)
