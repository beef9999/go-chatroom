import socket
s = socket.socket()
s.connect(('localhost', 12345))
import time

import threading

def recv():
    while 1:
        print s.recv(1024)

th = threading.Thread(target=recv)
th.setDaemon(True)
th.start()

while 1:
    print 'type in'
    msg = raw_input()
    s.send(msg+ '\n')
