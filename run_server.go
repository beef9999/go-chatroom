package main
import (
    "sync"
    "chatroom"
    "github.com/op/go-logging"
    "flag"
)

func main() {
    debug := flag.Bool("debug", false, "Show debug info")
    flag.Parse()
    if *debug {
        logging.SetLevel(logging.DEBUG, "chatroom")
    } else {
        logging.SetLevel(logging.INFO, "chatroom")
    }
    server := chatroom.NewChatServer("0:12345", make(map[string]*chatroom.Room), new(sync.RWMutex))
    server.ListenAndServe()
}