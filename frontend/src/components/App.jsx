import React, { useEffect } from "react"
import { inject, observer } from "mobx-react"
import { hot } from "react-hot-loader/root"

import LogCat from "./LogCat"
import Jogging from "./Jogging"
import FileList from "./FileList"
import TemperatureGraph from "./TemperatureGraph"
import Panel from "./Panel"
import Button from "./Button"
import DefinitionList from "./DefinitionList"
import Position from "./Position"

const SubHeading = (props) => <div className="mb-2 font-medium" {...props} />

const App = ({ store }) => {
  if (!store.isConnected || !store.gotStatus) {
    return <div>Connecting...</div>
  }
  return (
    <div className="flex p-1">
      <div className="flex flex-col w-1/3">
        <Panel title="Status">
          <DefinitionList object={store.status.toolhead} />
          <DefinitionList object={store.status.virtual_sdcard} />
          <DefinitionList object={store.status.pause_resume} />
          <DefinitionList object={store.status.idle_timeout} />

          {/* <Position position={store.status.toolhead.position} /> */}
        </Panel>
        <Panel title="Log">
          <LogCat lines={store.log} />
        </Panel>

        {/* <Panel title="Axes">
          <Jogging />
        </Panel> */}

        {/* <Panel title="File List">
          <FileList />
        </Panel> */}
      </div>

      <div className="flex flex-col w-1/3">
        {/* <Panel title="Temperature">
          <TemperatureGraph
            width={400}
            height={100}
            data={store.temperatureGraphData}
          />
        </Panel> */}
        <Panel title="Macros">
          <DefinitionList object={store.lookupObjects("gcode_macro")} />
        </Panel>
        <Panel title="GCode">
          <DefinitionList object={store.status.gcode} />
        </Panel>
      </div>

      <div className="flex flex-col w-1/3">
        <Panel title="Extruder">
          <DefinitionList object={store.status.extruder0} />
          <DefinitionList object={store.status.firmware_retraction} />
        </Panel>

        <Panel title="Heater Bed">
          <DefinitionList object={store.status.heater_bed} />
        </Panel>
        <Panel title="Probe Temperature">
          <DefinitionList object={store.status.probe_temp} />
        </Panel>
        <Panel title="Fan">
          <DefinitionList object={store.status.fan} />
        </Panel>
        <Panel title="Nozzle Cooling Fan">
          <DefinitionList
            object={store.status["heater_fan nozzle_cooling_fan"]}
          />
        </Panel>

        <Panel title="tmc2209">
          <DefinitionList object={store.lookupObjects("tmc2209")} />
        </Panel>
      </div>
    </div>
  )
}

export default hot(inject("store")(observer(App)))
