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

        if six.PY3:
            # per pep 3333 :(
            headers = [h.decode('latin-1') for h in headers]

        return dict(zip(*[iter(headers)] * 2))


class SCGIRequestProcessor(object):

    @classmethod
    def from_sock(cls, sock):
        instream = sock.makefile('r')
        outstream = sock.makefile('w')
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

    def _start_response(self, status, response_headers, exc_info=None):
        if exc_info is not None:
            try:
                if self._headers_sent:
                    six.reraise(*exc_info)
            finally:
                exc_info = None
        elif self._headers_sent or self._headers is not None:
            raise RuntimeError()
        t.RESPONSE_STARTED(status=status).write()
        self._headers = 'Status: %s\r\n%s\r\n\r\n' % (
            status,
            '\r\n'.join('%s: %s' % header for header in response_headers))
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
        self._outstream.flush()


class SocketPassProcessor(object):
    def __init__(self, sock):
        self._sock = sock

    @classmethod
    def from_handoff_socket(cls, sock, action=None):
        sock.sendall('\n')
        data, ancillary, flags = recvmsg(sock)
        [fd] = struct.unpack('i', ancillary[0][2])
        if not data.endswith('\n'):
            data += sock.makefile('r').readline()
        socket_params = struct.unpack('iiix', data)
        new_sock = socket.fromfd(fd, *socket_params)
        new_sock.setblocking(True)
        ret = cls(new_sock)
        if action is not None:
            action.add_success_fields(
                **dict(zip(('family', 'type', 'proto'), socket_params)))
        return ret

    @classmethod
    def from_path(cls, path):
        with t.HANDOFF(path=path) as action:
            sock = socket.socket(socket.AF_UNIX)
            with socket_shutdown(sock):
                sock.connect(path)
                return cls.from_handoff_socket(sock, action)

    def handle_request(self, app):
        new_sock, addr = self._sock.accept()
        t.SCGI_ACCEPTED().write()
        new_sock.setblocking(True)
        with t.SCGI_REQUEST(), socket_shutdown(new_sock):
            SCGIRequestProcessor.from_sock(new_sock).run_app(app)


def cinje_app(environ, start_response):
    from cinje import stream
    from cinje.benchmark import bigtable_stream
    start_response('200 OK', [])
    return stream(bigtable_stream(), encoding='utf8')


def get_pyramid_app():
    from pyramid.paster import bootstrap
    env = bootstrap(sys.argv[2])
    return env['app']


def main():
    eliot.to_file(sys.stdout)
    for sig in range(1, signal.NSIG):
        try:
            signal.siginterrupt(sig, False)
        except RuntimeError as e:
            if e.args[0] != errno.EINVAL:
                raise

    proc = SocketPassProcessor.from_path(sys.argv[1])
    app = get_pyramid_app()
    while True:
        proc.handle_request(app)


if __name__ == '__main__':
    main()
