import io
import socket

from eliot.testing import LoggedAction
import pytest
import six

from wip import receiver, types


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


_NULL = b'\0'

SPEC_REQUEST_HEADERS = b''.join([
    b'70:'
    b'CONTENT_LENGTH', _NULL, b'27', _NULL,
    b'SCGI', _NULL, b'1', _NULL,
    b'REQUEST_METHOD', _NULL, b'POST', _NULL,
    b'REQUEST_URI', _NULL, b'/deepthought', _NULL,
    b','])
SPEC_REQUEST_BODY = b'What is the meaning of life?'
SPEC_REQUEST = SPEC_REQUEST_HEADERS + SPEC_REQUEST_BODY


def test_read_headers_succeeds(capture_logging):
    parseable = io.BytesIO(SPEC_REQUEST_HEADERS)
    expected = {'CONTENT_LENGTH': '27',
                'SCGI': '1',
                'REQUEST_METHOD': 'POST',
                'REQUEST_URI': '/deepthought'}

    with capture_logging() as logger:
        assert receiver.read_headers(parseable) == expected

    actions = LoggedAction.ofType(logger.messages, types.SCGI_PARSE)
    assert actions and actions[0].succeeded


@pytest.mark.skipif(not six.PY3, reason='Python 3 only')
def test_read_headers_succeeds_with_latin_1(capture_logging):
    latin1 = io.BytesIO()
    latin1.writelines([b'29:'
                       b'CONTENT_LENGTH', _NULL, b'1', _NULL,
                       b'X_LATIN_1', _NULL, b'\xbf', _NULL,
                       b','])
    latin1.seek(0)

    expected = {'CONTENT_LENGTH': '1',
                'X_LATIN_1': u'\N{INVERTED QUESTION MARK}'}

    with capture_logging() as logger:
        assert receiver.read_headers(latin1) == expected

    actions = LoggedAction.ofType(logger.messages, types.SCGI_PARSE)
    assert actions and actions[0].succeeded


def test_read_headers_fails(capture_logging):
    unparseable = io.BytesIO(b'21:'
                             b'missing trailing null'
                             b',')

    with pytest.raises(RuntimeError), capture_logging() as logger:
        receiver.read_headers(unparseable)

    fail_actions = LoggedAction.ofType(logger.messages, types.SCGI_PARSE)
    assert fail_actions and not fail_actions[0].succeeded
