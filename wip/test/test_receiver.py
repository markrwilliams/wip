import io
import socket

import pytest

from wip import receiver


class RecordsFakeSocket(object):

    def __init__(self):
        self.shutdown_calls = []
        self.shutdown_raises = None
        self.close_call_count = 0


class FakeSocket(object):

    def __init__(self, recorder):
        self._recorder = recorder

    def shutdown(self, flag):
        self._recorder.shutdown_calls.append(flag)
        if self._recorder.shutdown_raises:
            raise self._recorder.shutdown_raises

    def close(self):
        self._recorder.close_call_count += 1


def noop(*args, **kwargs):
    return


def raise_exception(exc_type):
    def _raise(*args, **kwargs):
        raise exc_type()
    return _raise


@pytest.mark.parametrize('body', [noop, raise_exception(RuntimeError)])
@pytest.mark.parametrize('shutdown_raises', [None, socket.error])
def test_socket_shutdown(body, shutdown_raises):
    recorder = RecordsFakeSocket()
    recorder.shutdown_raises = shutdown_raises

    a_fake_socket = FakeSocket(recorder)
    with receiver.socket_shutdown(a_fake_socket) as sock:
        assert sock is a_fake_socket
        try:
            body(sock)
        except Exception:
            pass

    assert recorder.shutdown_calls == [socket.SHUT_RDWR]
    assert recorder.close_call_count == 1


@pytest.mark.parametrize('netstring,parsed',
                         [(b'0:,', b''),
                          (b'1:a,', b'a'),
                          (b'5:hello,', b'hello')])
def test_netstring_succeeds(netstring, parsed):
    assert receiver.read_netstring(io.BytesIO(netstring)) == parsed


@pytest.mark.parametrize('bad_netstring,expected_exc',
                         [(b'', RuntimeError),
                          (b'xxx', RuntimeError,),
                          (b'12345678:ignored,', RuntimeError),
                          (b'1:a', RuntimeError)])
def test_netstring_fails(bad_netstring, expected_exc):
    with pytest.raises(expected_exc):
        receiver.read_netstring(io.BytesIO(bad_netstring))


def test_read_headers():
    parseable = io.BytesIO(b'70:'
                           b'CONTENT_LENGTH\x0027\x00'
                           b'SCGI\x001\x00'
                           b'REQUEST_METHOD\x00POST\x00'
                           b'REQUEST_URI\x00/deepthought\x00'
                           b',')
    expected = {b'CONTENT_LENGTH': b'27',
                b'SCGI': b'1',
                b'REQUEST_METHOD': b'POST',
                b'REQUEST_URI': b'/deepthought'}

    assert receiver.read_headers(parseable) == expected

    unparseable = io.BytesIO(b'21:'
                             b'missing trailing null'
                             b',')

    with pytest.raises(RuntimeError):
        receiver.read_headers(unparseable)
