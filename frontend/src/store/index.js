import { types } from "mobx-state-tree"

export default types
  .model("Store", {
    isConnected: types.optional(types.boolean, false),
  })
  .volatile((self) => ({
    status: {},
  }))
  .views((self) => ({
    get fans() {
      return Object.keys(self.status).reduce((result, object) => {
        const { speed } = self.status[object]
        if (speed) {
          return [...result, { object, speed }]
        }
        return result
      }, [])
    },
    get temperatures() {
      return Object.keys(self.status).reduce((result, object) => {
        const { temperature } = self.status[object]
        if (temperature) {
          return [...result, { object, temperature }]
        }
        return result
      }, [])
    },
  }))
  .actions((self) => ({
    afterCreate: () => {
      self.ws = new WebSocket("ws://raspberrypi3.local:9090/ws")
      self.ws.onmessage = self.onMessage
    },
    onMessage: (e) => {
      const payload = JSON.parse(e.data)
      if (payload.status) {
        self.status = payload.status
        console.log(self.status)
      }
    },
  }))
