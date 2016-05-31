#!/usr/bin/env python3
import tornado
import tornado.tcpserver
from tornado.ioloop import IOLoop, PeriodicCallback
import argparse
#from tornado.gen import coroutine
#from tornado.queues import Queue
import datetime
import threading
import logging
import asyncio
from asyncio import Queue


COMMAND_NORMAL = 1
COMMAND_QUIT = 2
COMMAND_JOIN = 3
COMMAND_DISMISS = 4
COMMAND_PAUSE = 5
COMMAND_KICK = 6

QUEUE_SIZE = 100

Args = None

SPEED = 0


async def show_speed():
    global SPEED
    while True:
        logging.info(SPEED)
        SPEED = 0
        await asyncio.sleep(1)


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

    async def dispatch(self):
        logging.debug('Chatroom: %s opened' % self.name)
        while True:
            msg = await self.inqueue.get()
            logging.debug("Room got message: room[%s], command[%s], content[%s]",
                          msg.receiver, msg.command, msg.content)
            if msg.command == COMMAND_JOIN:
                logging.debug("%s joined", msg.sender.name)
                self.clients[msg.sender.name] = msg.sender
            elif msg.command == COMMAND_QUIT:
                del self.clients[msg.sender.name]
            await self.broadcast(msg)
            self.inqueue.task_done()

    async def broadcast(self, msg):
        for _, client in self.clients.items():
            await client.inqueue.put(msg)


class Client(object):

    def __init__(self, server, name, stream):
        self.server = server
        self.name = name
        self.rooms = {}
        self.stream = stream
        self.inqueue = Queue(maxsize=QUEUE_SIZE)
        self.outqueue = Queue(maxsize=QUEUE_SIZE)

    async def forwarding(self):
        while True:
            msg = await self.outqueue.get()
            if msg.command == COMMAND_QUIT:
                for _, room in self.rooms.items():
                    await room.inqueue.put(msg)
            elif msg.command == COMMAND_JOIN:
                room_name = msg.receiver
                room = self.server.get_room(room_name)
                self.rooms[room_name] = room
                await room.inqueue.put(msg)
            else:
                room = self.rooms[msg.receiver]
                await room.inqueue.put(msg)
            self.outqueue.task_done()

    async def response(self):
        global SPEED
        while True:
            msg = await self.inqueue.get()
            self.inqueue.task_done()
            if msg.command == COMMAND_QUIT:
                self.stream.writer.close()
                return
            else:
                response = ("%s %s:%s\n" % (datetime.datetime.now(),
                                            msg.sender.name,
                                            msg.content.decode()))\
                    .encode('utf-8')
                try:
                    SPEED += 1
                    self.stream.writer.write(response)
                    await self.stream.writer.drain()
                except Exception as e:
                    logging.debug(str(e))
                    self.stream.writer.close()

    async def receive(self):
        while True:
            try:
                line = await self.stream.reader.readline()
            except Exception as e:
                logging.debug(str(e))
                msg = Message(self, '', COMMAND_QUIT, 'CONNECTION ERROR')
                await self.outqueue.put(msg)
                return
            data = line.strip().split(b' ')
            if len(data) != 2:
                continue
            room_name, content = data[0], data[1]
            if room_name in self.rooms:
                msg = Message(self, room_name, COMMAND_NORMAL, content)
            else:
                msg = Message(self, room_name, COMMAND_JOIN, content)
            await self.outqueue.put(msg)


class Stream(object):

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer


class ChatServer(object):

    def __init__(self, host, port):
        super(ChatServer, self).__init__()
        self.host = host
        self.port = port
        self.rooms = {}
        self._server = None

    async def handle_stream(self, reader, writer):
        address = writer.get_extra_info('peername')
        stream = Stream(reader, writer)
        client = Client(self, address, stream)
        asyncio.ensure_future(client.forwarding())
        asyncio.ensure_future(client.response())
        asyncio.ensure_future(client.receive())

    def get_room(self, room_name):
        if room_name in self.rooms:
            return self.rooms[room_name]
        else:
            room = Room(self, room_name)
            asyncio.ensure_future(room.dispatch())
            self.rooms[room_name] = room
            return room

    def run(self):
        loop = asyncio.get_event_loop()
        coro = asyncio.start_server(self.handle_stream, self.host, self.port, loop=loop)
        self._server = loop.run_until_complete(coro)
        asyncio.ensure_future(show_speed())
        loop.run_forever()

    def stop(self):
        loop = asyncio.get_event_loop()
        self._server.close()
        loop.run_until_complete(self._server.wait_closed())
        loop.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    Args = parser.parse_args()
    logger = logging.getLogger()
    if Args.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    srv = ChatServer('localhost', 12345)

    try:
        srv.run()
    except KeyboardInterrupt:
        pass

    srv.stop()
