import "@babel/polyfill";
import React, { useEffect } from "react";
import ReactDOM from "react-dom";
import { observable, autorun } from "mobx";

const LOG_HISTORY_LENGTH = 1000;
const TEMP_HISTORY_LENGTH = 3600;

const readLines = onLine => {
  var buffer = "";

  return chunk => {
    buffer += chunk;
    var lines = buffer.match(/.*?(?:\r\n|\r|\n)|.*?$/g);
    while (lines.length > 1) onLine(lines.shift());
    buffer = lines[0] || "";
  };
};

const awaitReply = onReply => {
  var buffer = "";

  return chunk => {
    buffer += chunk;
    if (chunk.startsWith("ok")) {
      onReply(buffer);
      buffer = "";
    }
  };
};

class Client {
  @observable queue = [];
  @observable isBusy = true;

  constructor(endpoint) {
    this.socket = new WebSocket(endpoint);
    this.parse = awaitReply(this.onReply);
    this.write = readLines(this.parse);
    this.socket.onmessage = this.onRead;
    this.socket.onopen = this.onConnect;

    autorun(() => {
      if (!this.isBusy) {
        if (this.queue.length > 0) {
          this.isBusy = true;
          const next = this.queue.shift();
          console.log("> " + next);
          this.socket.send(`${next}\n`);
        } else {
          this.onIdle();
        }
      }
    });
  }

  onConnect = () => {
    console.log("connected");
    this.isBusy = false;

    this.send("M20");
    setInterval(() => {
      if (this.queue.indexOf("M105") === -1) {
        this.send("M105");
      }
    }, 1000);
  };

  onRead = async e => {
    const response = new Response(e.data);
    const data = await response.text();
    this.write(data);
  };

  onReply = message => {
    this.isBusy = false;
    console.log("< " + message);
  };

  onIdle = () => {
    // console.log("idle");
  };

  send = command => {
    this.queue.push(command);
  };
}

function App() {
  useEffect(() => {
    const client = new Client("ws://octopi.local:3000/");
  }, []);

  return <div />;
}

const rootElement = document.getElementById("root");
ReactDOM.render(<App />, rootElement);
