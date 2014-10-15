"""Utilities for building command-line interfaces for your daemons"""

import click

from .daemon import Daemon


class DaemonCLI(click.MultiCommand):
    """A Command class for `click <http://click.pocoo.org/>`_.

    This class automatically adds start, stop, restart, and status
    subcommands for daemons.
    """

    def __init__(
            self, callback=None, options_metavar='[<options>]',
            subcommand_metavar='<command> [<args>]...',
            daemon_params=None, daemon_class=Daemon, is_worker=True,
            **attrs):
        """Create a new DaemonCLI object."""
        self.daemon_params = daemon_params or {}
        self.daemon_class = daemon_class
        self.is_worker = is_worker

        if self.is_worker:
            # If the callback is the worker, then don't pass the
            # callback to the parent class so we don't call it twice
            self.daemon_params['worker'] = callback
            callback = None

        # The context object will be a Daemon object
        context_settings = {'obj': self.daemon_class(**self.daemon_params)}

        super(DaemonCLI, self).__init__(
            callback=callback, options_metavar=options_metavar,
            subcommand_metavar=subcommand_metavar, context_settings=context_settings, **attrs
        )

    def list_commands(self, ctx):
        """Get a list of subcommands."""
        return self.daemon_class.list_actions()

    def get_command(self, ctx, name):
        """Get a callable command object."""
        if name not in self.daemon_class.list_actions():
            return None

        # The context object is a Daemon object
        daemon = ctx.obj

        def subcommand(*args, **kwargs):
            """Call a daemonocle action."""
            debug = kwargs.pop('debug', False)
            if daemon.detach and debug:
                daemon.detach = False

            # Pass the arguments of subcommand to the worker function
            worker = daemon.worker
            daemon.worker = lambda: worker(*args, **kwargs)

            daemon.do_action(name)

        # Copy Click-specific attributes of the worker function
        # to subcommand so decorators like click.pass_context can work
        for attr in dir(daemon.worker):
            if attr.startswith('__click'):
                setattr(subcommand, attr, getattr(daemon.worker, attr))

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
        subcommand = click.command(name, options_metavar=self.options_metavar)(subcommand)

        return subcommand


# Make a pass decorator for passing the Daemon object
pass_daemon = click.make_pass_decorator(Daemon)
