package main

import "net/http"

func makeHandler(msg string) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(msg))
	})
}

func greet(who string) string {
	return "hi " + who
}
