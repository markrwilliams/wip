import errno
import os
import stat
import subprocess
import sys
import time
import urllib
from contextlib import contextmanager

import pytest
import pkg_resources
import requests_unixsocket


@contextmanager
def subprocess_context(args, log_file, **kw):
    proc = subprocess.Popen(
        args, stdin=subprocess.PIPE, stdout=log_file, stderr=subprocess.STDOUT,
        **kw)
    try:
        proc.stdin.close()
        yield proc
    finally:
        # XXX: TOCTOU
        proc.poll()
        if proc.returncode is None:
            proc.terminate()
        proc.wait()


def wait_until_accessible_or_death(proc, path, retries=25, delay=0.125):
    path = str(path)
    for ign in range(retries):
        try:
            st = os.lstat(path)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise
        else:
            if stat.S_ISSOCK(st.st_mode):
                return
        if proc.poll() is not None:
            raise RuntimeError('process died waiting for:', path)
        time.sleep(delay)
    raise RuntimeError('never became a socket:', path)


@pytest.fixture(scope='session')
def workdir(request, tmpdir_factory):
    if not request.config.getoption('--runfunctional'):
        pytest.skip('skipping functional tests')
    return tmpdir_factory.mktemp('workdir')


# macOS is fussy about UNIX socket path lengths, so there's a bunch of relative
# paths and symlinks used here because there's no other way to coax it into
# listening/connecting.


@pytest.fixture(scope='session')
def handoff_socket_path(workdir):
    return workdir.join('handoff.sock')


@pytest.fixture(scope='session')
def receiver_socket_path(workdir):
    return workdir.join('receiver.sock')


@pytest.fixture(scope='session')
def running_handoff(receiver_socket_path, handoff_socket_path, workdir):
    with workdir.join('handoff.log').open('w') as handoff_log:
        args = [
            sys.executable, '-m', 'wip.handoff',
            'unix:{}'.format(receiver_socket_path.basename),
            'unix:{}'.format(handoff_socket_path.basename),
        ]
        with subprocess_context(args, handoff_log, cwd=str(workdir)) as proc:
            wait_until_accessible_or_death(proc, receiver_socket_path)
            wait_until_accessible_or_death(proc, handoff_socket_path)
            yield proc


@pytest.fixture(scope='session')
def running_receiver(running_handoff, handoff_socket_path, workdir):
    with workdir.join('receiver.log').open('w') as receiver_log:
        args = [
            sys.executable, '-m', 'wip.receiver',
            handoff_socket_path.basename,
        ]
        with subprocess_context(args, receiver_log, cwd=str(workdir)) as proc:
            yield proc


@pytest.fixture(scope='session')
def nginx_socket_path(workdir):
    return workdir.join('nginx.sock')


@pytest.fixture(scope='session')
def nginx_binary():
    return 'nginx'


@pytest.fixture(scope='session')
def running_nginx(running_receiver, receiver_socket_path,
                  nginx_socket_path, nginx_binary,
                  workdir):
    nginx_conf = pkg_resources.resource_string(__name__, 'nginx.conf')
    workdir.join('nginx.conf').write(nginx_conf)
    with workdir.join('nginx.log').open('w') as nginx_log:
        args = [
            nginx_binary,
            '-c', str(workdir.join('nginx.conf')),
            '-p', str(workdir),
        ]
        with subprocess_context(args, nginx_log, cwd=str(workdir)) as proc:
            wait_until_accessible_or_death(proc, nginx_socket_path)
            yield proc


@pytest.fixture
def session():
    return requests_unixsocket.Session()


@pytest.fixture
def local_nginx_socket(running_nginx, nginx_socket_path, tmpdir):
    sock = tmpdir.join('nginx.sock')
    sock.mksymlinkto(nginx_socket_path)
    tmpdir.chdir()
    return sock.basename


@pytest.fixture
def url(local_nginx_socket):
    def build(path):
        return 'http+unix://{}{}'.format(
            urllib.quote(str(local_nginx_socket), safe=''), path)
    return build
