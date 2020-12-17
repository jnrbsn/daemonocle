daemonocle
==========

*A Python library for creating super fancy Unix daemons*

-----

.. image:: https://img.shields.io/github/workflow/status/jnrbsn/daemonocle/build/master?style=flat-square
    :target: https://github.com/jnrbsn/daemonocle/actions?query=workflow:build+branch:master

.. image:: https://img.shields.io/coveralls/jnrbsn/daemonocle/master.svg?style=flat-square
    :target: https://coveralls.io/github/jnrbsn/daemonocle

.. image:: https://img.shields.io/pypi/v/daemonocle.svg?style=flat-square
    :target: https://pypi.org/project/daemonocle/

.. image:: https://img.shields.io/pypi/pyversions/daemonocle?style=flat-square
    :target: https://docs.python.org/whatsnew/index.html

.. image:: https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20unix-lightgrey?style=flat-square
    :target: https://en.wikipedia.org/wiki/Unix-like

.. image:: https://img.shields.io/github/license/jnrbsn/daemonocle?style=flat-square
    :target: https://github.com/jnrbsn/daemonocle/blob/master/LICENSE

|

daemonocle is a library for creating your own Unix-style daemons written in Python. It solves many
problems that other daemon libraries have and provides some really useful features you don't often
see in other daemons.

.. contents:: **Table of Contents**
  :backlinks: none

Installation
------------

To install via pip::

    pip install daemonocle

Or download the source code and install manually::

    git clone https://github.com/jnrbsn/daemonocle.git
    cd daemonocle/
    python setup.py install

Basic Usage
-----------

Here's a **really really** basic example:

.. code:: python

    import sys
    import time

    import daemonocle

    # This is your daemon. It sleeps, and then sleeps again.
    def main():
        while True:
            time.sleep(10)

    if __name__ == '__main__':
        daemon = daemonocle.Daemon(
            worker=main,
            pid_file='/var/run/daemonocle_example.pid',
        )
        daemon.do_action(sys.argv[1])

And here's the same example with logging and a `Shutdown Callback`_:

.. code:: python

    import logging
    import sys
    import time

    import daemonocle

    def cb_shutdown(message, code):
        logging.info('Daemon is stopping')
        logging.debug(message)

    def main():
        logging.basicConfig(
            filename='/var/log/daemonocle_example.log',
            level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s',
        )
        logging.info('Daemon is starting')
        while True:
            logging.debug('Still running')
            time.sleep(10)

    if __name__ == '__main__':
        daemon = daemonocle.Daemon(
            worker=main,
            shutdown_callback=cb_shutdown,
            pid_file='/var/run/daemonocle_example.pid',
        )
        daemon.do_action(sys.argv[1])

And here's what it looks like when you run it::

    user@host:~$ python example.py start
    Starting example.py ... OK
    user@host:~$ python example.py status
    example.py -- pid: 1234, status: running, uptime: 1m, %cpu: 0.0, %mem: 0.0
    user@host:~$ python example.py stop
    Stopping example.py ... OK
    user@host:~$ cat /var/log/daemonocle_example.log
    2014-05-04 12:39:21,090 [INFO] Daemon is starting
    2014-05-04 12:39:21,091 [DEBUG] Still running
    2014-05-04 12:39:31,091 [DEBUG] Still running
    2014-05-04 12:39:41,091 [DEBUG] Still running
    2014-05-04 12:39:51,093 [DEBUG] Still running
    2014-05-04 12:40:01,094 [DEBUG] Still running
    2014-05-04 12:40:07,113 [INFO] Daemon is stopping
    2014-05-04 12:40:07,114 [DEBUG] Terminated by SIGTERM (15)

For more details, see the `Detailed Usage`_ section below.

Rationale
---------

If you think about it, a lot of Unix daemons don't really know what the hell they're doing. Have you
ever found yourself in a situation that looked something like this? ::

    user@host:~$ sudo example start
    starting example ... ok
    user@host:~$ ps aux | grep example
    user      1234  0.0  0.0   1234  1234 pts/1    S+   12:34   0:00 grep example
    user@host:~$ sudo example start
    starting example ... ok
    user@host:~$ echo $?
    0
    user@host:~$ tail -f /var/log/example.log
    ...

Or something like this? ::

    user@host:~$ sudo example stop
    stopping example ... ok
    user@host:~$ ps aux | grep example
    user       123  0.0  0.0   1234  1234 ?        Ss   00:00   0:00 /usr/local/bin/example
    user      1234  0.0  0.0   1234  1234 pts/1    S+   12:34   0:00 grep example
    user@host:~$ sudo example stop
    stopping example ... ok
    user@host:~$ ps aux | grep example
    user       123  0.0  0.0   1234  1234 ?        Ss   00:00   0:00 /usr/local/bin/example
    user      1240  0.0  0.0   1234  1234 pts/1    S+   12:34   0:00 grep example
    user@host:~$ sudo kill -9 123
    ...

Or something like this? ::

    user@host:~$ sudo example status
    Usage: example {start|stop|restart}
    user@host:~$ ps aux | grep example
    ...

These are just a few examples of unnecessarily common problems. It doesn't have to be this way.

    **Note:** You might be thinking, "Why not just write a smarter start/stop shell script wrapper
    for your daemon that checks whether or not it actually started, actually stopped, etc.?"
    Seriously? **It doesn't have to be this way.** I believe daemons should be more self-aware. They
    should handle their own problems most of the time, and your start/stop script should only be a
    very thin wrapper around your daemon or simply a symlink to your daemon.

The Problem
~~~~~~~~~~~

If you've ever dug deep into the nitty-gritty details of how daemonization works, you're probably
familiar with the `standard "double fork" paradigm <http://bit.ly/stevens-daemon>`_ first introduced
by W. Richard Stevens in the book `Advanced Programming in the UNIX Environment
<http://amzn.com/0321637739>`_. One of the problems with the standard way to implement this is that
if the final child dies immediately when it gets around to doing real work, the original parent
process (the one that actually had control of your terminal) is long gone. So all you know is that
the process got forked, but you have no idea if it actually kept running for more than a fraction of
a second. And let's face it, one of the most likely times for a daemon to die is immediately after
it starts (due to bad configuration, permissions, etc.).

The next problem mentioned in the section above is when you try to stop a daemon, it doesn't
actually stop, and you have no idea that it didn't actually stop. This happens when a process
doesn't respond properly to a ``SIGTERM`` signal. It happens more often than it should. The problem
is not necessarily the fact that it didn't stop. It's the fact that you didn't *know* that it didn't
stop. The start/stop script knows that it successfully sent the signal and so it assumes success.
This also becomes a problem when your ``restart`` command blindly calls ``stop`` and then ``start``,
because it will try to start a new instance of the daemon before the previous one has exited.

These are the biggest problems most daemons have in my opinion. daemonocle solves these problems and
provides many other "fancy" features.

The Solution
~~~~~~~~~~~~

The problem with the daemon immediately dying on startup and you not knowing about it is solved by
having the first child (the immediate parent of the final child) sleep for one second and then call
``os.waitpid(pid, os.WNOHANG)`` to see if the process is still running. This is what daemonocle
does. So if you're daemon dies within one second of starting, you'll know about it.

This problem with the daemon not stopping and you not knowing about it is solved by simply waiting
for the process to finish (with a timeout). This is what daemonocle does. (Note: When a timeout
occurs, it doesn't try to send a ``SIGKILL``. This is not always what you'd want and often not a
good idea.)

Other Useful Features
~~~~~~~~~~~~~~~~~~~~~

Below are some other useful features that daemononcle provides that you might not find elsewhere.

The ``status`` Action
+++++++++++++++++++++

There is a ``status`` action that not only displays whether or not the daemon is running and its
PID, but also the uptime of the daemon and the % CPU and % memory usage of all the processes in the
same process group as the daemon (which are probably its children). So if you have a daemon that
launches mulitple worker processes, the ``status`` action will show the % CPU and % memory usage of
all the workers combined.

It might look something like this::

    user@host:~$ python example.py status
    example.py -- pid: 1234, status: running, uptime: 12d 3h 4m, %cpu: 12.4, %mem: 4.5

You can even get JSON output if you call the action like this:

.. code:: python

    daemon.do_action('status', json=True)

If you use the `Integration with click`_ described below, this option is available via the
``--json`` CLI option. You can also just get a ``dict`` directly and programatically without
printing it to STDOUT by calling ``Daemon.get_status()``.

Slightly Smarter ``restart`` Action
+++++++++++++++++++++++++++++++++++

Have you ever tried to restart a daemon only to realize that it's not actually running? Let me
guess: it just gave you an error and didn't start the daemon. A lot of the time this is not a
problem, but if you're trying to restart the daemon in an automated way, it's more annoying to have
to check if it's running and do either a ``start`` or ``restart`` accordingly. With daemonocle, if
you try to restart a daemon that's not running, it will give you a warning saying that it wasn't
running and then start the daemon. This is often what people expect.

Self-Reload
+++++++++++

Daemons that use daemonocle have the ability to reload themselves by simply calling
``daemon.reload()`` where ``daemon`` is your ``daemonocle.Daemon`` instance. The execution of the
current daemon halts wherever ``daemon.reload()`` was called, and a new daemon is started up to
replace the current one. From your code's perspective, it's pretty much the same as a doing a
``restart`` except that it's initiated from within the daemon itself and there's no signal handling
involved. Here's a basic example of a daemon that watches a config file and reloads itself when the
config file changes:

.. code:: python

    import os
    import sys
    import time

    import daemonocle

    class FileWatcher(object):

        def __init__(self, filename, daemon):
            self._filename = filename
            self._daemon = daemon
            self._file_mtime = os.stat(self._filename).st_mtime

        def file_has_changed(self):
            current_mtime = os.stat(self._filename).st_mtime
            if current_mtime != self._file_mtime:
                self._file_mtime = current_mtime
                return True
            return False

        def watch(self):
            while True:
                if self.file_has_changed():
                    self._daemon.reload()
                time.sleep(1)

    if __name__ == '__main__':
        daemon = daemonocle.Daemon(pid_file='/var/run/daemonocle_example.pid')
        fw = FileWatcher(filename='/etc/daemonocle_example.conf', daemon=daemon)
        daemon.worker = fw.watch
        daemon.do_action(sys.argv[1])

Shutdown Callback
+++++++++++++++++

You may have noticed from the `Basic Usage`_ section above that a ``shutdown_callback`` was defined.
This function gets called whenever the daemon is shutting down in a catchable way, which should be
most of the time except for a ``SIGKILL`` or if your server crashes unexpectedly or loses power or
something like that. This function can be used for doing any sort of cleanup that your daemon needs
to do. Also, if you want to log (to the logger of your choice) the reason for the shutdown and the
intended exit code, you can use the ``message`` and ``code`` arguments that will be passed to your
callback (your callback must take these two arguments).

Non-Detached Mode
+++++++++++++++++

This is not particularly interesting per se, but it's worth noting that in non-detached mode, your
daemon will do everything else you've configured it to do (i.e. ``setuid``, ``setgid``, ``chroot``,
etc.) except actually detaching from your terminal. So while you're testing, you can get an
extremely accurate view of how your daemon will behave in the wild. It's also worth noting that
self-reloading works in non-detached mode, which was a little tricky to figure out initially.

File Descriptor Handling
++++++++++++++++++++++++

One of the things that daemons typically do is close all open file descriptors and establish new
ones for ``STDIN``, ``STDOUT``, ``STDERR`` that just point to ``/dev/null``. This is fine most of
the time, but if your worker is an instance method of a class that opens files in its ``__init__()``
method, then you'll run into problems if you're not careful. This is also a problem if you're
importing a module that leaves open files behind. For example, importing the
`random <https://docs.python.org/3/library/random.html>`_ standard library module in Python 3
results in an open file descriptor for ``/dev/urandom``.

Since this "feature" of daemons often causes more problems than it solves, and the problems it
causes sometimes have strange side-effects that make it very difficult to troubleshoot, this feature
is optional and disabled by default in daemonocle via the ``close_open_files`` option.

Detailed Usage
--------------

The ``daemonocle.Daemon`` class is the main class for creating a daemon using daemonocle. Here's the
constructor signature for the class:

.. code:: python

    class daemonocle.Daemon(
        name=None, worker=None, detach=True,
        pid_file=None, work_dir='/', stdout_file=None, stderr_file=None, chroot_dir=None,
        uid=None, gid=None, umask=0o22, close_open_files=False,
        shutdown_callback=None, stop_timeout=10)

And here are descriptions of all the arguments:

``name``
    The name of your program to use in output messages. Default: ``os.path.basename(sys.argv[0])``

``worker``
    The function that does all the work for your daemon.

``detach``
    Whether or not to detach from the terminal and go into the background. See `Non-Detached Mode`_
    for more details. Default: ``True``

``pid_file``
    The path to a PID file to use. It's not required to use a PID file, but if you don't, you won't
    be able to use all the features you might expect. Make sure the user your daemon is running as
    has permission to write to the directory this file is in.

``work_dir``
    The path to a directory to change to when the daemon starts. Note that a file system cannot be
    unmounted if a process has its working directory on that file system. So if you change the
    default, be careful about what you change it to. Default: ``"/"``

``stdout_file``
    If provided when ``detach=True``, the STDOUT stream will be redirected (appended) to the file
    at the given path. In non-detached mode, this argument is ignored.

    *New in version 1.1.0.*

``stderr_file``
    If provided when ``detach=True``, the STDERR stream will be redirected (appended) to the file
    at the given path. In non-detached mode, this argument is ignored.

    *New in version 1.1.0.*

``chroot_dir``
    The path to a directory to set as the effective root directory when the daemon starts. The
    default is not to do anything.

``uid``
    The user ID to switch to when the daemon starts. The default is to not switch users.

``gid``
    The group ID to switch to when the daemon starts. The default is to not switch groups.

``umask``
    The file creation mask ("umask") for the process. Default: ``0o022``

``close_open_files``
    Whether or not to close all open files when the daemon detaches. Default: ``False``

``shutdown_callback``
    This will get called anytime the daemon is shutting down. It should take a ``message`` and a
    ``code`` argument. The message is a human readable message that explains why the daemon is
    shutting down. It might useful to log this message. The code is the exit code with which it
    intends to exit. See `Shutdown Callback`_ for more details.

``stop_timeout``
    Number of seconds to wait for the daemon to stop before throwing an error. Default: ``10``

Actions
~~~~~~~

The default actions are ``start``, ``stop``, ``restart``, and ``status``. You can get a list of
available actions using the ``daemonocle.Daemon.list_actions()`` method. The recommended way to call
an action is using the ``daemonocle.Daemon.do_action(action)`` method. The string name of an action
is the same as the method name except with dashes in place of underscores.

If you want to create your own actions, simply subclass ``daemonocle.Daemon`` and add the
``@daemonocle.expose_action`` decorator to your action method, and that's it.

Here's an example:

.. code:: python

    import daemonocle

    class MyDaemon(daemonocle.Daemon):

        @daemonocle.expose_action
        def full_status(self):
            """Get more detailed status of the daemon."""
            pass

Then, if you did the basic ``daemon.do_action(sys.argv[1])`` like in all the examples above, you can
call your action with a command like ``python example.py full-status``.

Integration with click
~~~~~~~~~~~~~~~~~~~~~~

daemonocle also provides an integration with `click <http://click.pocoo.org/>`_, the "Command Line
Interface Creation Kit". The integration is in the form of a custom command class
``daemonocle.cli.DaemonCLI`` that you can use in conjunction with the ``@click.command()`` decorator
to automatically generate a command line interface with subcommands for all your actions. It also
automatically daemonizes the decorated function. The decorated function becomes the worker, and the
actions are automatically mapped from click to daemonocle.

Here's an example:

.. code:: python

    import time

    import click
    from daemonocle.cli import DaemonCLI

    @click.command(cls=DaemonCLI, daemon_params={'pid_file': '/var/run/example.pid'})
    def main():
        """This is my awesome daemon. It pretends to do work in the background."""
        while True:
            time.sleep(10)

    if __name__ == '__main__':
        main()

Here are all the help pages for the default actions::

    user@host:~$ python example.py --help
    Usage: example.py [OPTIONS] COMMAND [ARGS]...

      This is my awesome daemon. It pretends to do work in the background.

    Options:
      --help  Show this message and exit.

    Commands:
      start    Start the daemon.
      stop     Stop the daemon.
      restart  Stop then start the daemon.
      status   Get the status of the daemon.

    user@host:~$ python example.py start --help
    Usage: example.py start [OPTIONS]

      Start the daemon.

    Options:
      --debug  Do NOT detach and run in the background.
      --help   Show this message and exit.

    user@host:~$ python example.py stop --help
    Usage: example.py stop [OPTIONS]

      Stop the daemon.

    Options:
      --timeout INTEGER  Number of seconds to wait for the daemon to stop.
                         Overrides "stop_timeout" from daemon definition.
      --force            Kill the daemon uncleanly if the timeout is reached.
      --help             Show this message and exit.

    user@host:~$ python example.py restart --help
    Usage: example.py restart [OPTIONS]

      Stop then start the daemon.

    Options:
      --timeout INTEGER  Number of seconds to wait for the daemon to stop.
                         Overrides "stop_timeout" from daemon definition.
      --force            Kill the daemon forcefully after the timeout.
      --debug            Do NOT detach and run in the background.
      --help             Show this message and exit.

    user@host:~$ python example.py status --help
    Usage: example.py status [OPTIONS]

      Get the status of the daemon.

    Options:
      --json         Show the status in JSON format.
      --fields TEXT  Comma-separated list of process info fields to display.
      --help         Show this message and exit.

The ``daemonocle.cli.DaemonCLI`` class also accepts a ``daemon_class`` argument that can be a
subclass of ``daemonocle.Daemon``. It will use your custom class, automatically create subcommands
for any custom actions you've defined, and use the docstrings of the action methods as the help text
just like click usually does.

This integration is entirely optional. daemonocle doesn't enforce any sort of argument parsing. You
can use argparse, optparse, or just plain ``sys.argv`` if you want.

Starting with version 1.1.0, you can also use a couple different shorter ways of invoking the CLI.

Like this:

.. code:: python

    from daemonocle.cli import cli

    @cli(pid_file='/var/run/example.pid')
    def main():
        """Do stuff"""
        ...

    if __name__ == '__main__':
        main()

Or like this:

.. code:: python

    from daemonocle import Daemon

    def main():
        """Do stuff"""
        ...

    if __name__ == '__main__':
        daemon = Daemon(worker=main, pid_file='/var/run/example.pid')
        daemon.cli()

The above two examples are equivalent. Use whichever way works best for you.


Bugs, Requests, Questions, etc.
-------------------------------

Please create an `issue on GitHub <https://github.com/jnrbsn/daemonocle/issues>`_.
