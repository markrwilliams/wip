import contextlib
import errno
import io
import signal
import socket
import struct
import sys

from twisted.python.sendmsg import recvmsg
import eliot
import six

from wip import types as t
from wip.common import (reconstitute_socket,
                        DESCRIPTION_LENGTH,
                        READY_BYTE,
                        headers_to_native_strings,
                        headers_to_bytes)


@contextlib.contextmanager
def socket_shutdown(s):
    try:
        yield s
    finally:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except socket.error:
            pass
        s.close()


def read_netstring(f):
    length = []
    while len(length) < 7:
        c = f.read(1)
        if c == b':':
            break
        elif not c.isdigit():
            raise RuntimeError()
        else:
            length.append(c)
    else:
        raise RuntimeError()
    length = int(b''.join(length))
    if length:
        ret = f.read(length)
    else:
        ret = b''
    if f.read(1) != b',':
        raise RuntimeError()
    return ret


def read_headers(f):
    with t.SCGI_PARSE():
        whole_header = read_netstring(f)
        headers = whole_header.split(b'\0')
        if headers[-1] != b'':
            raise RuntimeError()
        headers = headers_to_native_strings(headers)
        return dict(zip(*[iter(headers)] * 2))


class SCGIRequestProcessor(object):

    @classmethod
    def from_sock(cls, sock):
        instream = sock.makefile('r')
        # unbuffered writes
        outstream = sock.makefile('w', 0)
        return cls(instream, outstream)

    def __init__(self, instream, outstream):
        self._instream = instream
        self._outstream = outstream
        self._headers = None
        self._headers_sent = False

    def _determine_environment(self,
                               _read_headers=read_headers,
                               _io_factory=io.BytesIO):
        environ = _read_headers(self._instream)

        environ['wsgi.version'] = 1, 0
        environ['wsgi.url_scheme'] = 'http'
        if environ.get('HTTPS') in ('on', '1'):
            environ['wsgi.url_scheme'] = 'https'
        content_length = int(environ['CONTENT_LENGTH'])
        if content_length:
            environ['wsgi.input'] = self._instream
        else:
            environ['wsgi.input'] = _io_factory()
        environ['wsgi.errors'] = sys.stderr
        environ['wsgi.multithread'] = False
        environ['wsgi.multiprocess'] = True
        environ['wsgi.run_once'] = False

        path, _, query = environ.get('REQUEST_URI', '').partition('?')
        environ.setdefault('QUERY_STRING', query)
        environ['SCRIPT_NAME'] = ''
        environ['PATH_INFO'] = path

        return environ

    def _start_response(self, status, response_headers, exc_info=None):
        if exc_info is not None:
            try:
                if self._headers_sent:
                    six.reraise(*exc_info)
            finally:
                exc_info = None
        elif self._headers_sent:
            raise RuntimeError()

        t.RESPONSE_STARTED(status=status).write()
        headers = 'Status: %s\r\n%s\r\n\r\n' % (
            status,
            '\r\n'.join('%s: %s' % header for header in response_headers))

        self._headers = headers_to_bytes(headers)

        return self._write

    def _write(self, data):
        if not self._headers_sent:
            if self._headers is None:
                raise RuntimeError()
            self._outstream.write(self._headers)
            self._headers_sent = True
            self._headers = None
        if data:
            self._outstream.write(data)

    def run_app(self, app):
        environ = self._determine_environment()
        with t.WSGI_REQUEST(path=environ['PATH_INFO']):
            response = app(environ, self._start_response)
            for chunk in response:
                self._write(chunk)
            if not self._headers_sent:
                self._write('')
            close = getattr(response, 'close', None)
            if close is not None:
                close()


class SocketPassProcessor(object):
    def __init__(self, sock):
        self._sock = sock

    @classmethod
    def from_handoff_socket(cls, sock, eliot_action=None):
        sock.sendall(READY_BYTE)
        description, ancillary, flags = recvmsg(sock, maxSize=1)
        # OOB data, like ancillary data, interrupts MSG_WAITALL.  so
        # do this in two syscalls.
        description += sock.recv(DESCRIPTION_LENGTH - 1, socket.MSG_WAITALL)
        [fd] = struct.unpack('i', ancillary[0][2])
        new_sock = reconstitute_socket(fd, description, eliot_action)
        new_sock.setblocking(True)
        ret = cls(new_sock)
        return ret

    @classmethod
    def from_path(cls, path):
        with t.HANDOFF(path=path) as action:
            sock = socket.socket(socket.AF_UNIX)
            with socket_shutdown(sock):
                sock.connect(path)
                return cls.from_handoff_socket(sock, action)

    def handle_request(self, app):
        # TODO: the billion things that go wrong with accept
        new_sock, addr = self._sock.accept()
        t.SCGI_ACCEPTED().write()
        new_sock.setblocking(True)
        with t.SCGI_REQUEST(), socket_shutdown(new_sock):
            SCGIRequestProcessor.from_sock(new_sock).run_app(app)


def test_app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text-plain')])
    if False:
        yield


def main():
    eliot.to_file(sys.stdout)
    allowed_signals = {signal.SIGINT, signal.SIGTERM}
    for sig in range(1, signal.NSIG):
        if sig in allowed_signals:
            continue
        try:
            signal.siginterrupt(sig, False)
        except RuntimeError as e:
            if e.args[0] != errno.EINVAL:
                raise

    from paste import lint
    proc = SocketPassProcessor.from_path(sys.argv[1])
    app = lint.middleware(test_app)
    while True:
        proc.handle_request(app)


if __name__ == '__main__':
    main()
