var http = require("http");
var websocket = require("websocket-stream");
var FileDuplex = require("file-duplex");

var klipper = new FileDuplex("/tmp/printer");
var server = http.createServer();

klipper.pipe(process.stdout);

var socket = websocket.createServer(
  {
    perMessageDeflate: false,
    server
  },
  function handle(stream) {
    klipper.pipe(stream);
    stream.pipe(klipper);
    stream.pipe(process.stdout);
  }
);

server.listen(3000);
