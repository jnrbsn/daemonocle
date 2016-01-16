Release History
===============

0.8.1 (2016-01-16)
------------------

* Upgraded click to version 2.5.
* Status action now returns exit code 1 if the daemon is not running.

v0.7 (2014-06-23)
-----------------

* Fixed bug that was causing an empty PID file on Python 3.
* Upgraded click to version 2.1.
* Open file discriptors are no longer closed by default. This functionality is now optional via the
  ``close_open_files`` argument to ``Daemon()``.
* Added ``is_worker`` argument to ``DaemonCLI()`` as well as the ``pass_daemon`` decorator.

v0.6 (2014-06-10)
-----------------

* Upgraded click to version 2.0.

v0.5 (2014-06-09)
-----------------

* Fixed literal octal formatting to work with Python 3.

v0.4 (2014-05-19)
-----------------

* Fixed bug with uptime calculation in status action.
* Upgraded click to version 0.7.

v0.3 (2014-05-14)
-----------------

* Reorganized package and cleaned up code.

v0.2 (2014-05-12)
-----------------

* Renamed ``Daemon.get_actions()`` to ``Daemon.list_actions()``.
* Improvements to documentation.
* Fixed bug with non-detached mode when parent is in the same process group.

v0.1 (2014-05-11)
-----------------

* Initial release.
