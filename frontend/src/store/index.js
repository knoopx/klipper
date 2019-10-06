import { autorun } from "mobx"
import { types } from "mobx-state-tree"

export default types
  .model("Store", {
    isConnected: types.optional(types.boolean, false),
  })
  .volatile((self) => ({
    gotStatus: false,
    status: {},
    temperatureHistory: {},
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
    get temperatureGraphData() {
      console.log(self.temperatureHistory)
      return Object.values(self.temperatureHistory)
    },
  }))
  .actions((self) => ({
    afterCreate: () => {
      self.ws = new WebSocket("ws://raspberrypi3.local:9090/ws")
      self.ws.onmessage = self.onMessage
      self.ws.onopen = () => {
        self.setConnected(true)
      }
      self.ws.onclose = () => {
        self.setConnected(false)
      }

      setInterval(self.updateTemperatureHistory, 1000)
    },
    updateTemperatureHistory() {
      self.temperatures.forEach(({ object, temperature }) => {
        if (!self.temperatureHistory[object]) {
          self.temperatureHistory[object] = []
        }
        self.temperatureHistory[object].push({
          date: Date.now(),
          value: temperature,
        })
      })
    },
    setConnected(value) {
      self.isConnected = value
    },
    onMessage: (e) => {
      const payload = JSON.parse(e.data)
      if (payload.status) {
        self.gotStatus = true
        self.status = payload.status
        // console.log(self.status)
      }
    },
  }))
