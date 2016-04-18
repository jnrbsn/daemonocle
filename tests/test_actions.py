import pytest

from daemonocle import Daemon, DaemonError, expose_action


def test_default_actions():
    daemon = Daemon()
    assert daemon.list_actions() == ['start', 'stop', 'restart', 'status']
    assert daemon.get_action('start') == daemon.start
    assert daemon.get_action('stop') == daemon.stop
    assert daemon.get_action('restart') == daemon.restart
    assert daemon.get_action('status') == daemon.status
    with pytest.raises(DaemonError):
        daemon.get_action('banana')


def test_custom_actions():
    class BananaDaemon(Daemon):
        @expose_action
        def banana(self):
            pass

        def plantain(self):
            pass

    daemon = BananaDaemon()
    assert daemon.list_actions() == [
        'start', 'stop', 'restart', 'status', 'banana']
    assert daemon.get_action('banana') == daemon.banana
    with pytest.raises(DaemonError):
        daemon.get_action('plantain')
