package main

import (
    "bufio"
    "fmt"
    "io"
    "io/ioutil"
    "log"
    "math/rand"
    "net"
    "runtime"
    "sync/atomic"
    "time"
    "strconv"
)

func init() {
    runtime.GOMAXPROCS(runtime.NumCPU())
}

var (
    numClients int64 = 1000
    numRooms int64 = numClients / 20
    msgInterval int64 = 50    // millisecond

    idxClients int64 = 1
    speed int64 = 0
)

func work(ch chan struct {}) {
    defer func() {
        atomic.AddInt64(&idxClients, -1)
        <-ch
    }()
    var conn net.Conn
    var err error
    atomic.AddInt64(&idxClients, 1)
    conn, err = net.Dial("tcp", "127.0.0.1:12345")
    if err != nil {
        log.Println(err)
        return
    }
    buf := bufio.NewWriter(conn)
    go func() {
        io.Copy(ioutil.Discard, conn)
    }()

    for {
        atomic.AddInt64(&speed, 1)
//        time.Sleep(200 * time.Millisecond)
//        room := strconv.Itoa(((idx-1)/100+1)*10 - 9 + rand.Int()&10)
//        msg := room + " " + strconv.Itoa(rand.Int()) + "\n"
        time.Sleep(time.Duration(msgInterval) * time.Millisecond)
        room := strconv.FormatInt(rand.Int63() % (numClients / numRooms), 10)
        content := strconv.Itoa(rand.Int())
        msg := room + " " + content + "\n"

        _, err := buf.Write([]byte(msg))
        err = buf.Flush()
        if err != nil {
            log.Println(err)
            conn.Close()
            return
        }
    }
}

func main() {
    rand.Seed(time.Now().Unix())
    go func() {
        ticker := time.NewTicker(time.Second)
        for _ = range ticker.C {
            fmt.Println("speed", atomic.LoadInt64(&speed))
            atomic.StoreInt64(&speed, 0)
            fmt.Println("#clients", atomic.LoadInt64(&idxClients))
        }
    }()
    ch := make(chan struct {}, numClients)
    for {
        ch <- struct {}{}
        go work(ch)
        time.Sleep(2 * time.Millisecond)
    }
}
