Release History
---------------

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
