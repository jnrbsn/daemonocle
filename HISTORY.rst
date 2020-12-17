Release History
---------------

v1.1.0 (2020-12-16)
~~~~~~~~~~~~~~~~~~~~~~~~~

* Official support for Python 3.9
* Added back official support for Python 3.5
* Increased test coverage to over 95%.
* All tests now pass on macOS (Intel) and the GitHub Actions build now runs on
  macOS 10.15 in addition to Ubuntu.
* Fixed the ``close_open_files`` option to be much more reliable and consistent
  across different platforms.
* Fixed a race condition with the self-reload functionality where the PID file
  of the parent process was being deleted while the child process was trying to
  read it.
* Added ``stdout_file`` and ``stderr_file`` arguments to ``Daemon``. If these
  arguments are provided when ``detach=True``, STDOUT and STDERR will be
  redirected to these files. In non-detached mode, these arguments are ignored.
* When ``chrootdir`` is given, all other paths are now always considered
  relative to the chroot directory, even with a leading slash.
* Actions can now take arbitrary arguments, and (on Python 3) CLI options are
  auto-generated from the function signature. The auto-generated CLI options
  work best when your action's function signature contains type annotations and
  default values where applicable.
* Added ``timeout`` and ``force`` arguments to the built-in ``stop`` action,
  accessible from the CLI as ``--timeout`` and ``--force``.
* Added ``json`` and ``fields`` arguments to the built-in ``status`` action,
  accessible from the CLI as ``--json`` and ``--fields``.
* Added colored output when the output stream is attached to a terminal.
* Fixed a bug where the daemon wouldn't respond properly to ``docker stop``
  when running in a docker container.
* The worker function can now be a method called ``worker`` on a ``Daemon``
  subclass.
* Some more secret experimental stuff. :)

v1.0.2 (2020-07-12)
~~~~~~~~~~~~~~~~~~~

* Official support for Python 2.7, 3.6, 3.7, and 3.8.
* Fixed bug checking if a stream is a socket on Python 3.8.
* Closing open files is now more efficient on systems with a very high limit
  on the number of open files.
* Improved detection of running inside a container.

v1.0.1 (2016-04-17)
~~~~~~~~~~~~~~~~~~~

* No changes in this release. Bumped version only to re-upload to PyPI.

v1.0.0 (2016-04-17)
~~~~~~~~~~~~~~~~~~~

* Added official support for Python 2.7, 3.3, 3.4, and 3.5.
* Added a comprehensive suite of unit tests with over 90% code coverage.
* Dependencies (click and psutil) are no longer pinned to specific versions.
* Fixed bug with ``atexit`` handlers not being called in intermediate processes.
* Fixed bug when PID file is a relative path.
* Fixed bug when STDIN doesn't have a file descriptor number.
* Fixed bug when running in non-detached mode in a Docker container.
* A TTY is no longer checked for when deciding how to run in non-detached mode.
  The behavior was inconsistent across different platforms.
* Fixed bug when a process stopped before having chance to check if it stopped.
* Fixed bug where an exception could be raised if a PID file is already gone
  when trying to remove it.
* Subdirectories created for PID files now respect the ``umask`` setting.
* The pre-``umask`` mode for PID files is now ``0o666`` instead of ``0o777``,
  which will result in a default mode of ``0o644`` instead of ``0o755`` when
  using the default ``umask`` of ``0o22``.

v0.8 (2014-08-01)
~~~~~~~~~~~~~~~~~

* Upgraded click to version 2.5.
* Status action now returns exit code 1 if the daemon is not running.

v0.7 (2014-06-23)
~~~~~~~~~~~~~~~~~

* Fixed bug that was causing an empty PID file on Python 3.
* Upgraded click to version 2.1.
* Open file discriptors are no longer closed by default. This functionality is now optional via the
  ``close_open_files`` argument to ``Daemon()``.
* Added ``is_worker`` argument to ``DaemonCLI()`` as well as the ``pass_daemon`` decorator.

v0.6 (2014-06-10)
~~~~~~~~~~~~~~~~~

* Upgraded click to version 2.0.

v0.5 (2014-06-09)
~~~~~~~~~~~~~~~~~

* Fixed literal octal formatting to work with Python 3.

v0.4 (2014-05-19)
~~~~~~~~~~~~~~~~~

* Fixed bug with uptime calculation in status action.
* Upgraded click to version 0.7.

v0.3 (2014-05-14)
~~~~~~~~~~~~~~~~~

* Reorganized package and cleaned up code.

v0.2 (2014-05-12)
~~~~~~~~~~~~~~~~~

* Renamed ``Daemon.get_actions()`` to ``Daemon.list_actions()``.
* Improvements to documentation.
* Fixed bug with non-detached mode when parent is in the same process group.

v0.1 (2014-05-11)
~~~~~~~~~~~~~~~~~

* Initial release.
