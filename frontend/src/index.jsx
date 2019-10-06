import React from "react"
import ReactDOM from "react-dom"
import { Provider } from "mobx-react"

import App from "./components/App"
import Store from "./store"

const store = Store.create()

ReactDOM.render(
  <Provider store={store}>
    <App />
  </Provider>,
  document.getElementById("root"),
)
