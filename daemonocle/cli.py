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
            daemon_params=None, daemon_class=Daemon,
            **attrs):
        # Pass None for the callback so that the main command doesn't
        # get called before the subcommand. That would mess things up
        # since subcommands just run the main main command.
        super(DaemonCLI, self).__init__(
            callback=None, options_metavar=options_metavar,
            subcommand_metavar=subcommand_metavar, **attrs
        )

        self.daemon_params = daemon_params if daemon_params is not None else {}
        self.daemon_params['worker'] = callback
        self.daemon_class = daemon_class

    def list_commands(self, ctx):
        """Get a list of subcommands."""
        return self.daemon_class.list_actions()

    def get_command(self, ctx, name):
        """Get a callable command object."""
        if name not in self.daemon_class.list_actions():
            return None

        daemon = self.daemon_class(**self.daemon_params)

        def subcommand(debug=False):
            """Call a daemonocle action"""
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
        subcommand = click.command(name, options_metavar=self.options_metavar)(subcommand)

        return subcommand
