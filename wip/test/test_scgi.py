import sys
import io

from eliot.testing import LoggedAction
import pytest

from wip import receiver, types


_MISSING = '<missing>'
_FAKE_INSTREAM = 'fake instream'
_fake_io_factory = lambda: 'fake io'


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
         {'PATH_INFO': 'http://blah/'}),
    ])
def test__determine_environment(
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
        assert instream is _FAKE_INSTREAM
        return environ.copy()

    processor = receiver.SCGIRequestProcessor(_FAKE_INSTREAM, None)
    actual = processor._determine_environment(
        _read_headers=fake_read_headers,
        _io_factory=_fake_io_factory)

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
def null_processor():
    return receiver.SCGIRequestProcessor(instream=None, outstream=None)


def test__start_response(null_processor):
    null_processor._start_response(_OK_STATUS, _OK_HEADERS)
    assert null_processor._headers == _OK_STATUS_HEADERS_PREPARED


def test__start_response_exc_info_no_headers(null_processor):
    try:
        raise ValueError
    except ValueError:
        null_processor._start_response(_BAD_STATUS, _BAD_HEADERS,
                                       exc_info=sys.exc_info())
    assert null_processor._headers == _BAD_STATUS_HEADERS_PREPARED


def test__start_response_exc_info_existing_headers(null_processor):
    null_processor._start_response(_OK_STATUS, _OK_HEADERS)
    assert null_processor._headers == _OK_STATUS_HEADERS_PREPARED
    try:
        raise ValueError
    except ValueError:
        null_processor._start_response(_BAD_STATUS, _BAD_HEADERS,
                                       exc_info=sys.exc_info())
    assert null_processor._headers == _BAD_STATUS_HEADERS_PREPARED


@pytest.fixture
def outstream():
    return io.BytesIO()


@pytest.fixture
def writable_processor(outstream):
    return receiver.SCGIRequestProcessor(instream=None,
                                         outstream=outstream)


def test__start_response_headers_sent(writable_processor, outstream):
    writable_processor._start_response(_OK_STATUS, _OK_HEADERS)
    assert not outstream.getvalue()

    writable_processor._write(b'some data')
    assert outstream.getvalue() == (_OK_STATUS_HEADERS_PREPARED
                                    + b'some data')


def test__write_without_headers_fails(writable_processor):
    with pytest.raises(RuntimeError):
        writable_processor._write(b'some data')


def test__start_response_after_write_fails(writable_processor):
    writable_processor._start_response(_OK_STATUS, _OK_HEADERS)
    writable_processor._write(b'some data')
    with pytest.raises(RuntimeError):
        writable_processor._start_response(_BAD_STATUS,
                                           _BAD_HEADERS)


def test__start_response_with_exc_info_after_write_reraises(
        writable_processor):
    writable_processor._start_response(_OK_STATUS, _OK_HEADERS)
    writable_processor._write(b'some data')
    with pytest.raises(ValueError):
        try:
            raise ValueError
        except ValueError:
            writable_processor._start_response(_BAD_STATUS,
                                               _BAD_HEADERS,
                                               exc_info=sys.exc_info())


@pytest.fixture
def processor_with_environ(writable_processor):
    def add_environ(environ):
        writable_processor._determine_environment = lambda: environ
        return writable_processor
    return add_environ


def test_app_returns_iterable(
        capture_logging, processor_with_environ, outstream):
    expected_environ = {'PATH_INFO': 'blah'}
    expected_response = (_OK_STATUS_HEADERS_PREPARED
                         + b'some data')

    def hello_world(environ, start_response):
        assert expected_environ == environ
        start_response(_OK_STATUS, _OK_HEADERS)
        return [b'some data']

    with capture_logging() as logger:
        processor_with_environ(expected_environ).run_app(hello_world)

    assert outstream.getvalue() == expected_response

    fail_actions = LoggedAction.ofType(logger.messages, types.WSGI_REQUEST)
    assert fail_actions and fail_actions[0].succeeded


def test_app_returns_iterable_file(
        capture_logging, processor_with_environ, outstream):
    expected_environ = {'PATH_INFO': 'blah'}
    expected_response = (_OK_STATUS_HEADERS_PREPARED
                         + b'some data')

    response_obj = io.BytesIO(b'some data')

    def hello_world(environ, start_response):
        assert expected_environ == environ
        start_response(_OK_STATUS, _OK_HEADERS)
        return response_obj

    with capture_logging() as logger:
        processor_with_environ(expected_environ).run_app(hello_world)

    assert outstream.getvalue() == expected_response
    assert response_obj.closed

    fail_actions = LoggedAction.ofType(logger.messages, types.WSGI_REQUEST)
    assert fail_actions and fail_actions[0].succeeded


def test_app_returns_empty_iterable(
        capture_logging, processor_with_environ, outstream):
    expected_environ = {'PATH_INFO': 'blah'}
    expected_response = _OK_STATUS_HEADERS_PREPARED

    def hello_world(environ, start_response):
        assert expected_environ == environ
        start_response(_OK_STATUS, _OK_HEADERS)
        return []

    with capture_logging() as logger:
        processor_with_environ(expected_environ).run_app(hello_world)

    assert outstream.getvalue() == expected_response

    fail_actions = LoggedAction.ofType(logger.messages, types.WSGI_REQUEST)
    assert fail_actions and fail_actions[0].succeeded
