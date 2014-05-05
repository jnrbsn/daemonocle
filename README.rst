daemonocle
==========

*A Python library for creating super fancy Unix daemons*

-----

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
            pidfile='/var/run/daemonocle_example.pid',
        )
        daemon.do_action(sys.argv[1])

Here's another **really** basic example:

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
            pidfile='/var/run/daemonocle_example.pid',
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
        daemon = daemonocle.Daemon(pidfile='/var/run/daemonocle_example.pid')
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
method, then you'll run into problems if you're not careful. **Fortunately, daemonocle only closes
file descriptors that were open when the** ``daemonocle.Daemon`` **class was instantiated.** So if
you open all your files after that, you're good.

Here's an example of the **BAD** way to do it:

.. code:: python

    app = YourApp()  # <--- leaves files open
    daemon = daemonocle.Daemon(worker=app.run)
    daemon.do_action(sys.argv[1])

Here's an example of a **GOOD** way to do it:

.. code:: python

    daemon = daemonocle.Daemon()
    app = YourApp()
    daemon.worker = app.run
    daemon.do_action(sys.argv[1])

Here's another **GOOD** way to do it:

.. code:: python

    def main():
        app = YourApp()
        app.run()

    daemon = daemonocle.Daemon(worker=main)
    daemon.do_action(sys.argv[1])

This is **only** a problem if your class leaves files open upon instantiation. Otherwise, you don't
have to worry about. Oh, and if your using a file handler for your logger, you can probably use the
``delay=True`` option to avoid opening the file before it's needed.

Detailed Usage
--------------

...
