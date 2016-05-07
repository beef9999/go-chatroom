package main
import (
    "sync"
    "chatroom"
)

func main() {
    server := chatroom.NewChatServer("0:12345", make(map[string]*chatroom.Room), new(sync.RWMutex))
    server.ListenAndServe()
}