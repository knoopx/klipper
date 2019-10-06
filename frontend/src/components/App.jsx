import React, { useEffect } from "react"
import { hot } from "react-hot-loader/root"

import LogCat from "./LogCat"
import Jogging from "./Jogging"
import FileList from "./FileList"
import TemperatureGraph from "./TemperatureGraph"
import Panel from "./Panel"
import Button from "./Button"

const App = () => {
  return (
    <div className="flex flex-auto p-1">
      <div className="flex flex-auto flex-col">
        <Panel title="Status">
          <div className="flex flex-auto mb-4 text-lg">
            <div className="flex flex-auto flex-col items-center">
              <div>
                0.000
                <span className="ml-1 text-grey-darker text-sm font-thin">
                  mm
                </span>
              </div>
              <div className="mt-1 text-white font-bold">X</div>
            </div>
            <div className="flex flex-auto flex-col items-center">
              <div>
                0.000
                <span className="ml-1 text-grey-darker text-sm font-thin">
                  mm
                </span>
              </div>
              <div className="mt-1 text-white font-bold">Y</div>
            </div>
            <div className="flex flex-auto flex-col items-center">
              <div>
                0.000
                <span className="ml-1 text-grey-darker text-sm font-thin">
                  mm
                </span>
              </div>
              <div className="mt-1 text-white font-bold">Z</div>
            </div>
          </div>
          <Button>Disconnect</Button>
        </Panel>
        <Panel title="File List">
          <FileList />
        </Panel>
      </div>

      <div className="flex flex-auto flex-col">
        <Panel title="Temperature">
          <TemperatureGraph width={400} height={100} />
        </Panel>
        <Panel>Something else</Panel>
      </div>

      <div className="flex flex-auto flex-col">
        <Panel title="Axes">
          <Jogging />
        </Panel>
        <Panel title="Temperature">
          <div className="flex flex-col">
            <div className="flex">
              <div className="mx-1">T0</div>
              <div className="mx-1">220ºC</div>
            </div>
            <div className="flex">
              <div className="mx-1 text-white font-bold">B</div>
              <div className="mx-1 text-red-500">220ºC</div>
            </div>
            <div className="flex">
              <div className="mx-1">P</div>
              <div className="mx-1">220ºC</div>
            </div>
          </div>
        </Panel>
        <Panel title="Log">
          <LogCat />
        </Panel>
      </div>
    </div>
  )
}

export default hot(App)
