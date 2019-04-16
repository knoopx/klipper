import React, { useEffect } from "react";
import colors from "../theming/colors";
import LogCat from "./LogCat";
import Jogging from "./Jogging";
import FileList from "./FileList";
import TemperatureGraph from "./TemperatureGraph";
import Panel from "./Panel";
import Button from "./Button";

const App = () => {
  return (
    <div
      className="flex flex-auto p-1"
      style={{ backgroundColor: colors.greyDarkest }}
    >
      <div className="flex flex-col flex-auto">
        <Panel title="Status">
          <div className="flex flex-auto text-lg mb-4">
            <div className="flex flex-col flex-auto items-center">
              <div>
                0.000
                <span className="ml-1 text-sm font-thin text-grey-darker">
                  mm
                </span>
              </div>
              <div className="text-white font-bold mt-1">X</div>
            </div>
            <div className="flex flex-col flex-auto items-center">
              <div>
                0.000
                <span className="ml-1 text-sm font-thin text-grey-darker">
                  mm
                </span>
              </div>
              <div className="text-white font-bold mt-1">Y</div>
            </div>
            <div className="flex flex-col flex-auto items-center">
              <div>
                0.000
                <span className="ml-1 text-sm font-thin text-grey-darker">
                  mm
                </span>
              </div>
              <div className="text-white font-bold mt-1">Z</div>
            </div>
          </div>
          <Button>Disconnect</Button>
        </Panel>
        <Panel title="File List">
          <FileList />
        </Panel>
      </div>

      <div className="flex flex-col flex-auto">
        <Panel title="Temperature">
          <TemperatureGraph width={400} height={100} />
        </Panel>
        <Panel>Something else</Panel>
      </div>

      <div className="flex flex-col flex-auto">
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
              <div className="mx-1" style={{ color: colors.red }}>
                220ºC
              </div>
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
  );
};

export default App;
