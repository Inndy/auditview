package main

import (
	"fmt"
	"net/http"
)

func main() {
	h := makeHandler("hello")
	http.Handle("/", h)
	fmt.Println(greet("world"))
	fmt.Println(greet("again"))
}
