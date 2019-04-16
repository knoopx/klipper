import "@babel/polyfill";
import "tailwindcss/dist/tailwind.css";

import React from "react";
import ReactDOM from "react-dom";

import App from "./components/App";
import Client from "./support/Client";

const client = new Client("ws://octopi.local:3000/");
ReactDOM.render(<App />, document.getElementById("root"));
