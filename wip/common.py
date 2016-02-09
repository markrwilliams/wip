import struct
import socket
import six


_SOCK_DESCRIPTION = struct.Struct('iii')

DESCRIPTION_LENGTH = _SOCK_DESCRIPTION.size

READY_BYTE = b'!'


def describe_socket(skt):
    return _SOCK_DESCRIPTION.pack(skt.family, skt.type, skt.proto)


def reconstitute_socket(fileno, description, eliot_action=None):
    args = _SOCK_DESCRIPTION.unpack(description)
    skt = socket.fromfd(fileno, *args)
    if eliot_action is not None:
        eliot_action.add_success_fields(
            **dict(zip(('family', 'type', 'proto'), args)))
    return skt


if six.PY3:
    # per pep 3333 :(
    # https://www.python.org/dev/peps/pep-3333/#unicode-issues
    _ENCODING = 'ISO-8859-1'

    def headers_to_native_strings(headers):
        return [h.decode(_ENCODING) for h in headers]

    def headers_to_bytes(header_string):
        return header_string.encode(_ENCODING)
else:
    def headers_to_native_strings(headers):
        return headers

    def headers_to_bytes(header_string):
        return header_string
