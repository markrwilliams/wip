import sys
import io
import socket
import unicodedata

import pytest

from eliot.testing import LoggedAction
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
                'X_LATIN_1': unicodedata.lookup('INVERTED QUESTION MARK')}

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


class TestSCGIRequestProcessor(object):
    _MISSING = '<missing>'
    _FAKE_INSTREAM = 'fake instream'
    _fake_io_factory = lambda self=None: 'fake io'

    @pytest.mark.parametrize(
        'https_environ,https_expected', [
            ({'HTTPS': 'on'}, {'wsgi.url_scheme': 'https'}),
            ({'HTTPS': '1'}, {'wsgi.url_scheme': 'https'}),
            ({'HTTPS': 'ignored'}, {}),
            ({}, {}),
        ])
    @pytest.mark.parametrize(
        'content_length_environ,content_length_expected', [
            ({'CONTENT_LENGTH': '27'}, {'wsgi.input': _FAKE_INSTREAM}),
            ({'CONTENT_LENGTH': '0'}, {'wsgi.input': _fake_io_factory()}),
        ])
    @pytest.mark.parametrize(
        'request_uri_environ,request_uri_expected', [
            ({'REQUEST_URI': 'http://blah/foo?bar=1'},
             {'PATH_INFO': 'http://blah/foo',
              'QUERY_STRING': 'bar=1'}),
            ({'REQUEST_URI': 'http://blah/?bar=1'},
             {'PATH_INFO': 'http://blah/',
              'QUERY_STRING': 'bar=1'}),
            ({'REQUEST_URI': 'http://blah/'},
             {'PATH_INFO': 'http://blah/'})
        ])
    def test__determine_environment(
            self,
            https_environ, https_expected,
            content_length_environ, content_length_expected,
            request_uri_environ, request_uri_expected):
        environ = {'X_PASSED_THROUGH': '1'}
        expected = environ.copy()
        expected.update({'wsgi.version': (1, 0),
                         'wsgi.url_scheme': 'http',
                         'wsgi.errors': sys.stderr,
                         'wsgi.multithread': False,
                         'wsgi.multiprocess': True,
                         'wsgi.run_once': False,
                         'SCRIPT_NAME': '',
                         'QUERY_STRING': '',
                         'PATH_INFO': ''})
        for update in (https_environ, content_length_environ,
                       request_uri_environ):
            environ.update(update)
            expected.update(update)

        for update in (https_expected, content_length_expected,
                       request_uri_expected):
            expected.update(update)

        def fake_read_headers(instream):
            assert instream is self._FAKE_INSTREAM
            return environ.copy()

        processor = receiver.SCGIRequestProcessor(self._FAKE_INSTREAM, None)
        actual = processor._determine_environment(
            _read_headers=fake_read_headers,
            _io_factory=self._fake_io_factory)

        assert actual == expected

    _OK_STATUS = '200 OK'
    _OK_HEADERS = [('X-Is-Ok', 'true')]
    _OK_STATUS_HEADERS_PREPARED = (b'Status: 200 OK\r\n'
                                   b'X-Is-Ok: true\r\n'
                                   b'\r\n')
    _BAD_STATUS = '500 Internal Server Error'
    _BAD_HEADERS = [('X-Is-Not-Ok', 'true')]
    _BAD_STATUS_HEADERS_PREPARED = (b'Status: 500 Internal Server Error\r\n'
                                    b'X-Is-Not-Ok: true\r\n'
                                    b'\r\n')

    @pytest.fixture
    def null_processor(self):
        return receiver.SCGIRequestProcessor(instream=None, outstream=None)

    def test__start_response(self, null_processor):
        null_processor._start_response(self._OK_STATUS, self._OK_HEADERS)
        assert null_processor._headers == self._OK_STATUS_HEADERS_PREPARED

    def test__start_response_exc_info_no_headers(self, null_processor):
        try:
            raise ValueError
        except ValueError:
            null_processor._start_response(self._BAD_STATUS, self._BAD_HEADERS,
                                           exc_info=sys.exc_info())
        assert null_processor._headers == self._BAD_STATUS_HEADERS_PREPARED

    def test__start_response_exc_info_existing_headers(self, null_processor):
        null_processor._start_response(self._OK_STATUS, self._OK_HEADERS)
        assert null_processor._headers == self._OK_STATUS_HEADERS_PREPARED
        try:
            raise ValueError
        except ValueError:
            null_processor._start_response(self._BAD_STATUS, self._BAD_HEADERS,
                                           exc_info=sys.exc_info())
        assert null_processor._headers == self._BAD_STATUS_HEADERS_PREPARED

    @pytest.fixture
    def outstream(self):
        return io.BytesIO()

    @pytest.fixture
    def writable_processor(self, outstream):
        return receiver.SCGIRequestProcessor(instream=None,
                                             outstream=outstream)

    def test__start_response_headers_sent(self, writable_processor, outstream):
        writable_processor._start_response(self._OK_STATUS, self._OK_HEADERS)
        assert not outstream.getvalue()

        writable_processor._write(b'some data')
        assert outstream.getvalue() == (self._OK_STATUS_HEADERS_PREPARED
                                        + b'some data')

    def test__write_without_headers_fails(self, writable_processor):
        with pytest.raises(RuntimeError):
            writable_processor._write(b'some data')

    def test__start_response_after_write_fails(self, writable_processor):
        writable_processor._start_response(self._OK_STATUS, self._OK_HEADERS)
        writable_processor._write(b'some data')
        with pytest.raises(RuntimeError):
            writable_processor._start_response(self._BAD_STATUS,
                                               self._BAD_HEADERS)

    def test__start_response_with_exc_info_after_write_reraises(
            self, writable_processor):
        writable_processor._start_response(self._OK_STATUS, self._OK_HEADERS)
        writable_processor._write(b'some data')
        with pytest.raises(ValueError):
            try:
                raise ValueError
            except ValueError:
                writable_processor._start_response(self._BAD_STATUS,
                                                   self._BAD_HEADERS,
                                                   exc_info=sys.exc_info())

    @pytest.fixture
    def writable_environed_processor(self, writable_processor):
        def _determine_environment():
            return self._expected_environ
        writable_processor._determine_environment = _determine_environment
        return writable_processor

    def _hello_world_returns_iterable(self, environ, start_response):
        assert self._expected_environ == environ
        start_response(self._OK_STATUS, self._OK_HEADERS)
        self._expected_response = (self._OK_STATUS_HEADERS_PREPARED
                                   + b'some data')
        return [b'some data']

    def _hello_world_returns_iterable_file(self, environ, start_response):
        assert self._expected_environ == environ
        start_response(self._OK_STATUS, self._OK_HEADERS)

        response = io.BytesIO(b'some data')

        self._expected_response = (self._OK_STATUS_HEADERS_PREPARED
                                   + b'some data')

        def assert_io_closed():
            assert response.closed

        self._additional_assertion = assert_io_closed

        return response

    def _hello_world_returns_empty_iterable(self, environ, start_response):
        assert self._expected_environ == environ
        start_response(self._OK_STATUS, self._OK_HEADERS)
        self._expected_response = self._OK_STATUS_HEADERS_PREPARED
        return []

    @pytest.fixture(params=['_hello_world_returns_iterable',
                            '_hello_world_returns_iterable_file',
                            '_hello_world_returns_empty_iterable'])
    def hello_world(self, request):
        self._expected_environ = {'PATH_INFO': 'blah'}
        self._expected_response = None
        self._additional_assertion = lambda: None

        def cleanup():
            self._expected_environ = None
            self._expected_response = None

        request.addfinalizer(cleanup)
        return getattr(self, request.param)

    def test_run_app(self,
                     capture_logging,
                     writable_environed_processor,
                     outstream,
                     hello_world):

        with capture_logging() as logger:
            writable_environed_processor.run_app(hello_world)

        assert outstream.getvalue() == self._expected_response
        self._additional_assertion()

        fail_actions = LoggedAction.ofType(logger.messages, types.WSGI_REQUEST)
        assert fail_actions and fail_actions[0].succeeded
