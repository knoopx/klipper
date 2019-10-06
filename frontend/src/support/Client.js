export default class Client {
  constructor(uri) {
    this.ws = new WebSocket(uri)
    this.ws.onmessage = this.onMessage
    // this.ws.open()
  }

  onMessage(e) {
    console.log(e)
  }
}
