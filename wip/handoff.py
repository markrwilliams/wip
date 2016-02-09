import os
import struct
import sys

from twisted.internet import defer, endpoints, protocol, task
from twisted import logger

from wip.common import describe_socket, READY_BYTE


class AlwaysAbortFactory(protocol.Factory):
    log = logger.Logger()

    def buildProtocol(self, addr):
        self.log.warn('rejecting incoming connection: {addr}', addr=addr)
        return None


class HandoffProtocol(protocol.Protocol):
    done = False

    def dataReceived(self, datum):
        if self.done or datum != READY_BYTE:
            return
        self.transport.write(self.factory.handoff_data)
        self.transport.sendFileDescriptor(self.factory.handoff_fd)
        self.transport.loseConnection()
        self.done = True


@defer.inlineCallbacks
def main(reactor, server_endpoint_string, handoff_endpoint_string):
    logger.globalLogBeginner.beginLoggingTo(
        [logger.textFileLogObserver(sys.stderr)])
    server_endpoint = endpoints.serverFromString(
        reactor, server_endpoint_string)
    server_port = yield server_endpoint.listen(AlwaysAbortFactory())
    handoff_factory = protocol.Factory.forProtocol(HandoffProtocol)
    handoff_factory.handoff_fd = os.dup(server_port.fileno())
    handoff_factory.handoff_data = describe_socket(server_port.socket)
    reactor.removeReader(server_port)

    handoff_endpoint = endpoints.serverFromString(
        reactor, handoff_endpoint_string)
    yield handoff_endpoint.listen(handoff_factory)
    yield defer.Deferred()


if __name__ == '__main__':
    task.react(main, sys.argv[1:])
