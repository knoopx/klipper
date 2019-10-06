export default class Client {
  constructor(uri) {
    this.ws = new WebSocket(uri)
    this.ws.onmessage = this.onMessage
  }

  onMessage(e) {
    const payload = JSON.parse(e.data)
    console.log(payload)
  }
}
