#!/usr/bin/env python3
import tornado
import tornado.tcpserver
from tornado.ioloop import IOLoop, PeriodicCallback
import argparse
from tornado.gen import coroutine
from tornado.queues import Queue
import datetime
import threading
import logging


COMMAND_NORMAL = 1
COMMAND_QUIT = 2
COMMAND_JOIN = 3
COMMAND_DISMISS = 4
COMMAND_PAUSE = 5
COMMAND_KICK = 6

QUEUE_SIZE = 1000

Args = None

SPEED = 0


def show_speed():
    global SPEED
    logging.info(SPEED)
    SPEED = 0


class Message(object):

    def __init__(self, sender, receiver, command, content, time=None):
        self.sender = sender        # client
        self.receiver = receiver    # room name
        self.command = command
        self.content = content
        self.time = datetime.datetime.now() if time is None else time


class Room(object):

    def __init__(self, server, name):
        self.server = server
        self.name = name
        self.clients = {}
        self.lock = threading.RLock()
        self.inqueue = Queue(maxsize=QUEUE_SIZE)

    @coroutine
    def dispatch(self):
        logging.debug('Chatroom: %s opened' % self.name)
        while True:
            msg = yield self.inqueue.get()
            logging.debug("Room got message: room[%s], command[%s], content[%s]",
                          msg.receiver, msg.command, msg.content)
            if msg.command == COMMAND_JOIN:
                logging.debug("%s joined", msg.sender.name)
                self.clients[msg.sender.name] = msg.sender
            elif msg.command == COMMAND_QUIT:
                del self.clients[msg.sender.name]
            yield self.broadcast(msg)

    @coroutine
    def broadcast(self, msg):
        for _, client in self.clients.items():
            yield client.inqueue.put(msg)


class Client(object):

    def __init__(self, server, name, stream):
        self.server = server
        self.name = name
        self.rooms = {}
        self.stream = stream
        self.inqueue = Queue(maxsize=QUEUE_SIZE)
        self.outqueue = Queue(maxsize=QUEUE_SIZE)

    @coroutine
    def forwarding(self):
        while True:
            msg = yield self.outqueue.get()
            if msg.command == COMMAND_QUIT:
                for _, room in self.rooms.items():
                    yield room.inqueue.put(msg)
            elif msg.command == COMMAND_JOIN:
                room_name = msg.receiver
                room = self.server.get_room(room_name)
                self.rooms[room_name] = room
                yield room.inqueue.put(msg)
            else:
                room = self.rooms[msg.receiver]
                yield room.inqueue.put(msg)
            self.outqueue.task_done()

    @coroutine
    def response(self):
        global SPEED
        while True:
            msg = yield self.inqueue.get()
            if msg.command == COMMAND_QUIT:
                self.stream.close()
                return
            else:
                response = ("%s %s:%s\n" % (datetime.datetime.now(),
                                            msg.sender.name,
                                            msg.content.decode()))\
                    .encode('utf-8')
                try:
                    SPEED += 1
                    yield self.stream.write(response)
                except Exception as e:
                    logging.debug(str(e))
                    self.stream.close()

    @coroutine
    def receive(self):
        while True:
            try:
                line = yield self.stream.read_until(b'\n')
            except Exception as e:
                logging.debug(str(e))
                msg = Message(self, '', COMMAND_QUIT, 'CONNECTION ERROR')
                yield self.outqueue.put(msg)
                return
            data = line.strip().split(b' ')
            if len(data) != 2:
                continue
            room_name, content = data[0], data[1]
            if room_name in self.rooms:
                msg = Message(self, room_name, COMMAND_NORMAL, content)
            else:
                msg = Message(self, room_name, COMMAND_JOIN, content)
            yield self.outqueue.put(msg)


class ChatServer(tornado.tcpserver.TCPServer):

    def __init__(self, bind_to):
        super(ChatServer, self).__init__()
        self.bind_to = bind_to
        self.rooms = {}

    @coroutine
    def handle_stream(self, stream, address):
        client = Client(self, address, stream)
        client.forwarding()
        client.response()
        client.receive()

    def get_room(self, room_name):
        if room_name in self.rooms:
            return self.rooms[room_name]
        else:
            room = Room(self, room_name)
            room.dispatch()
            self.rooms[room_name] = room
            return room


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    Args = parser.parse_args()
    logger = logging.getLogger()
    if Args.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    srv = ChatServer('localhost:12345')
    srv.bind(12345)
    srv.start()
    pc = PeriodicCallback(show_speed, 1000)
    pc.start()
    IOLoop.instance().start()
