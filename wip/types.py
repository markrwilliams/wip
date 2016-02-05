import eliot


HANDOFF = eliot.ActionType(
    u'wip:handoff',
    eliot.fields(
        path=str),
    eliot.fields(
        family=int, type=int, proto=int),
    u'A listening socket is being handed off.')

SCGI_ACCEPTED = eliot.MessageType(
    u'wip:scgi_accepted',
    [],
    u'A listening SCGI socket has accepted a connection.')

SCGI_REQUEST = eliot.ActionType(
    u'wip:scgi_request',
    [],
    [],
    u'An SCGI request is being handled.')

SCGI_PARSE = eliot.ActionType(
    u'wip:scgi_parse',
    [],
    [],
    u'A new SCGI request is being parsed.')

WSGI_REQUEST = eliot.ActionType(
    u'wip:wsgi_request',
    eliot.fields(
        path=str),
    [],
    u'A WSGI application is being called.')

RESPONSE_STARTED = eliot.MessageType(
    u'wip:response_started',
    eliot.fields(
        status=str),
    u'A WSGI application has called start_response.')
