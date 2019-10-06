import React from "react"
import ReactDOM from "react-dom"

import App from "./components/App"
import Client from "./support/Client"

const client = new Client("ws://raspberrypi3.local:9090/ws")
ReactDOM.render(<App />, document.getElementById("root"))
