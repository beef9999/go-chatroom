
import tornado
import tornado.tcpserver
import tornado.ioloop

from tornado.gen import coroutine



import datetime
import threading
import queue



COMMAND_NORMAL = 1
COMMAND_QUIT = 2
COMMAND_JOIN = 3
COMMAND_DISMISS = 4
COMMAND_PAUSE = 5
COMMAND_KICK = 6


class Message(object):

    def __init__(self, sender, receiver, command, content, time=None):
        self.sender = sender    # client
        self.receiver = receiver    # room name
        self.command = command
        self.content = content
        self.time = datetime.datetime.now() if time is None else time


class Room(threading.Thread):

    def __init__(self, server, name):
        super(Room, self).__init__()
        self.server = server
        self.name = name
        self.clients = {}
        self.lock = threading.RLock()
        self.queue = queue.Queue()   # message queue

    def run(self):
        while True:
            msg = self.queue.get()
            self.broadcast(msg)

    def receive(self, msg):
        self.lock.acquire()
        if msg.sender.name not in self.clients:
            self.clients[msg.sender.name] = msg.sender
        self.lock.release()
        self.queue.put(msg)
        
    def broadcast(self, msg):
        with self.lock:
            for _, client in self.clients.items():
                tornado.ioloop.IOLoop.instance().add_callback(ChatServer.response, msg, client)


class Client(object):

    def __init__(self, server, name, stream):
        self.server = server
        self.name = name
        self.rooms = {}
        self.stream = stream

    # def process(self, line):
    #     data = line.strip().split(' ')
    #     if len(data) != 2:
    #         return
    #     room_name, content = data[0], data[1]
    #     if room_name in self.rooms:
    #         msg = Message(self, room_name, COMMAND_NORMAL, content)
    #     else:
    #         msg = Message(self, room_name, COMMAND_JOIN, content)
    #     msg = Message(self, room_name, COMMAND_NORMAL, content)
    #     return msg


class ChatServer(tornado.tcpserver.TCPServer):

    def __init__(self, bind_to):
        super(ChatServer, self).__init__()
        self.bind_to = bind_to
        self.rooms = {}
        self.clients = {}

    @coroutine
    def handle_stream(self, stream, address):
        client = self.clients.get(address, None)
        if client is None:
            client = Client(self, address, stream)
            self.clients[address] = client
        line = yield stream.read_until(b'\n')
        data = line.strip().split(b' ')
        if len(data) != 2:
            return
        room_name, content = data[0], data[1]
        msg = Message(client, room_name, COMMAND_NORMAL, content)
        room = self.get_room(room_name)
        room.receive(msg)

    def get_room(self, room_name):
        if room_name in self.rooms:
            return self.rooms[room_name]
        else:
            room = Room(self, room_name)
            room.setDaemon(True)
            room.start()
            self.rooms[room_name] = room
            return room

    @classmethod
    @coroutine
    def response(cls, msg, client):
        response = ("%s %s:%s\n" % (datetime.datetime.now(), msg.sender.name, msg.content.decode())).encode('utf-8')
        yield client.stream.write(response)

if __name__ == '__main__':
    srv = ChatServer('localhost:12345')
    srv.bind(12345)
    srv.start()
    tornado.ioloop.IOLoop.instance().start()


