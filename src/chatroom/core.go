package chatroom
import (
    "sync"
    "net"
    "time"
    "bufio"
    "fmt"
    "strings"
    "github.com/op/go-logging"
)

var log = logging.MustGetLogger("chatroom")

// ---------- MESSAGE --------------

const (                 // command
    _ = iota
    NORMAL
    QUIT
    JOIN
    DISMISS
    PAUSE
    KICK
)

type Message struct {
    Sender   *Client
    Receiver string // room name
    Command  int    // command
    Content  interface{}
    Time     time.Time
}

// ---------- ROOM --------------

type Room struct {
    Server  *ChatServer
    Name    string
    lock    *sync.RWMutex
    Clients map[string]*Client
    In      chan *Message
}

// 给每个新产生的房间都分配一个goroutine loop，接收room.In的消息，根据room里登记的Clients信息，向每个client.In广播消息
func (room *Room) Dispatcher() {
    log.Debug("Chatroom: %s opened\n", room.Name)
    for msg := range room.In {
        log.Debugf("Room got message: room[%v], command[%v], content[%v]", msg.Receiver, msg.Command, msg.Content)
        switch msg.Command {
        case QUIT:
            room.lock.Lock()
            delete(room.Clients, msg.Sender.Name)
            room.lock.Unlock()
            room.broadcast(msg)
        case JOIN:
            log.Debugf("%s joined\n", msg.Sender.Name)
            room.lock.Lock()
            room.Clients[msg.Sender.Name] = msg.Sender
            room.lock.Unlock()
            room.broadcast(msg)
        default:
            room.broadcast(msg)
        }
    }
}

func (room *Room) broadcast(msg *Message) {
    room.lock.RLock()
    defer room.lock.RUnlock()
    for _, c := range room.Clients {
        c.In <- msg
    }
}

// ---------- SERVER --------------

type ChatServer struct {
    BindTo string           // 服务器监听地址
    Rooms  map[string]*Room // 房间的map，key为房间名称，房间名根据用户输入自动创建
    lock   *sync.RWMutex    // 保护房间map
}

func NewChatServer(bindTo string, rooms map[string]*Room, lock *sync.RWMutex) *ChatServer {
    return &ChatServer{bindTo, rooms, lock}
}

func (server *ChatServer) ListenAndServe() {
    listener, err := net.Listen("tcp", server.BindTo)
    if err != nil {
        log.Fatal(err)
    }
    defer listener.Close()

    for {
        conn, err := listener.Accept()
        if err != nil {
            log.Fatal("Accept error:", err.Error())
            time.Sleep(time.Second)
            continue
        }

        // 每个链接都新建一个client对象，将TCP connection保存在client里
        client := Client{
            Server: server,
            Name: conn.RemoteAddr().String(),
            Conn: conn,
            lock: new(sync.RWMutex),
            Rooms: make(map[string]*Room),
            In:     make(chan *Message, 100),
            Out:    make(chan *Message, 100),
            Quit:   make(chan struct {}),
        }
        go client.Forwarding()
        go client.Response()
        go client.Receive()
    }
}

func (server *ChatServer) GetRoom(name string) *Room {
    // not thread-safe, needs lock protection
    server.lock.Lock()
    defer server.lock.Unlock()

    room, ok := server.Rooms[name]
    if ok {
        return room
    } else {
        room = &Room{
            Server: server,
            Name: name,
            lock: new(sync.RWMutex),
            Clients: make(map[string]*Client),
            In: make(chan *Message),
        }
        go room.Dispatcher()
        server.Rooms[name] = room
        return room
    }
}

// ---------- CLIENT --------------

type Client struct {
    Server *ChatServer
    Name   string
    Conn   net.Conn
    lock   *sync.RWMutex
    Rooms  map[string]*Room
    In     chan *Message
    Out    chan *Message
    Quit   chan struct {}
}

// 每个connection分配一个goroutine进行loop，接收client.Out的消息，根据消息指定的房间，发送到room.In
func (client *Client) Forwarding() {
    for msg := range client.Out {
        switch msg.Command {
        case QUIT:  // quit: 向该client登录的所有房间广播
            client.lock.RLock()
            for _, room := range client.Rooms {
                room.In <- msg
            }
            client.lock.RUnlock()
            client.Quit <- struct {}{}
            return
        case JOIN:  // 加入一个房间，不存在则创建
            roomName := msg.Receiver
            room := client.Server.GetRoom(roomName)
            client.lock.Lock()
            client.Rooms[roomName] = room
            client.lock.Unlock()
            room.In <- msg
        default:    // 向某个房间发信息，不存在room找不到的情况，因为Command是在Receive的时候由server自动填的
            client.lock.RLock()
            room := client.Rooms[msg.Receiver]
            client.lock.RUnlock()
            room.In <- msg
        }
    }
}

// 每个connection分配一个goroutine进行loop，接收client.In的消息，通过connection写回给客户端
func (client *Client) Response() {
    buf := bufio.NewWriter(client.Conn)
    isClosed := false

    isCriticalError := func(err error) bool {
        ne, ok := err.(net.Error)
        if ok && (ne.Temporary() || ne.Timeout()) {
            log.Debug("Temporary error at response:", err, "will not closed")
            return false
        } else {
            log.Debug("Network error, closed", err)
            return true
        }

    }

    for {
        select {
        case msg := <-client.In:
            if isClosed {
                continue
            }

            _, err := buf.Write([]byte(fmt.Sprintf(
                "%s %s:%s\n",
                msg.Time.Format(time.RFC3339),
                msg.Sender.Name,
                msg.Content,
            )))
            if err != nil {
                if isCriticalError(err) {
                    isClosed = true
                }
                continue
            }

            err = buf.Flush()
            if err != nil {
                if isCriticalError(err) {
                    isClosed = true
                }
                continue
            }

        case <-client.Quit:
            if ! isClosed {
                buf.Flush()
            }
            client.Conn.Close()
            close(client.Out)
            close(client.In)
            close(client.Quit)
            client = nil
            return  // end loop
        }
    }
}

// 每个connection分配一个goroutine进行loop，按行分割接受到的消息，从client.Out发出去
func (client *Client) Receive() {
    scanner := bufio.NewScanner(client.Conn)
    var msg *Message
    for scanner.Scan() {
        line := scanner.Text()
        data := strings.Split(strings.TrimSpace(line), " ")
        if len(data) != 2 {
            continue
        }
        room, content := data[0], data[1]
        msg = &Message{
            Sender: client,
            Receiver: room,
            Content: content,
            Time: time.Now(),
        }

        client.lock.RLock()
        if _, ok := client.Rooms[room]; ok {
            msg.Command = NORMAL
        } else {
            msg.Command = JOIN
        }
        client.lock.RUnlock()

        client.Out <- msg
    }

    if err := scanner.Err(); err != nil {           // other network error
        log.Debug(client.Conn.RemoteAddr(), "Error:", err)
        msg = &Message{client, "", QUIT, fmt.Sprintf("%s CONNECTION ERROR", client.Name), time.Now()}
    } else {                                        // EOF error
        log.Debug(client.Name, " Remote Closed")
        msg = &Message{client, "", QUIT, fmt.Sprintf("%s DISCONNECT", client.Name), time.Now()}
    }
    client.Out <- msg
}