import React, { useEffect } from "react"
import { inject, observer } from "mobx-react"
import { hot } from "react-hot-loader/root"

import LogCat from "./LogCat"
import Jogging from "./Jogging"
import FileList from "./FileList"
import TemperatureGraph from "./TemperatureGraph"
import Panel from "./Panel"
import Button from "./Button"

const App = ({ store }) => {
  if (!store.isConnected || !store.gotStatus) {
    return <div>Connecting...</div>
  }
  return (
    <div className="flex p-1">
      <div className="flex flex-col w-1/3">
        <Panel title="Status">
          <div className="flex flex-auto mb-4 text-lg">
            <div className="flex flex-auto flex-col items-center">
              {JSON.stringify(store.status.toolhead)}
              <div>
                {store.status.toolhead.position[0]}
                <span className="ml-1 text-grey-darker text-sm font-thin">
                  mm
                </span>
              </div>
              <div className="mt-1 text-white font-bold">X</div>
            </div>
            <div className="flex flex-auto flex-col items-center">
              <div>
                {store.status.toolhead.position[1]}
                <span className="ml-1 text-grey-darker text-sm font-thin">
                  mm
                </span>
              </div>
              <div className="mt-1 text-white font-bold">Y</div>
            </div>
            <div className="flex flex-auto flex-col items-center">
              <div>
                {store.status.toolhead.position[2]}
                <span className="ml-1 text-grey-darker text-sm font-thin">
                  mm
                </span>
              </div>
              <div className="mt-1 text-white font-bold">Z</div>
            </div>
          </div>
        </Panel>
        <Panel title="File List">
          <FileList />
        </Panel>
      </div>

      <div className="flex flex-col w-1/3">
        <Panel title="Temperature">
          <TemperatureGraph
            width={400}
            height={100}
            data={store.temperatureGraphData}
          />
        </Panel>
        <Panel>Something else</Panel>
      </div>

      <div className="flex flex-col w-1/3">
        <Panel title="Axes">
          <Jogging />
        </Panel>
        <Panel title="Temperature">
          <div className="flex flex-col">
            {store.temperatures.map(({ object, temperature }) => (
              <div className="flex">
                <div className="mx-1">{object}</div>
                <div className="mx-1">{temperature}ºC</div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Fans">
          <div className="flex flex-col">
            {store.fans.map(({ object, speed }) => (
              <div className="flex">
                <div className="mx-1">{object}</div>
                <div className="mx-1">{speed} RPM</div>
              </div>
            ))}
          </div>
        </Panel>
        <Panel title="Log">
          <LogCat />
        </Panel>
      </div>
    </div>
  )
}

export default hot(inject("store")(observer(App)))
