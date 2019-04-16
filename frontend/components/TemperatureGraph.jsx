import React from "react";
import { ScaleSVG } from "@vx/responsive";
import { Group } from "@vx/group";
import { LinePath } from "@vx/shape";
import { curveMonotoneX } from "@vx/curve";
import { genDateValue } from "@vx/mock-data";
import { scaleTime, scaleLinear } from "@vx/scale";
import { extent, max } from "d3-array";
import { scaleOrdinal } from "@vx/scale";

import Colors from "../theming/colors";

function genLines(num) {
  return new Array(num).fill(1).map(() => {
    return genDateValue(25);
  });
}

const series = genLines(3);
const data = series.reduce((rec, d) => {
  return rec.concat(d);
}, []);

// accessors
const x = d => d.date;
const y = d => d.value;

export default ({ width, height }) => {
  const xMax = width;
  const yMax = height;

  const xScale = scaleTime({
    range: [0, xMax],
    domain: extent(data, x)
  });

  const yScale = scaleLinear({
    range: [yMax, 0],
    domain: [0, max(data, y)]
  });

  const colorScale = scaleOrdinal({
    domain: series,
    range: [Colors.red, Colors.blue, Colors.green, Colors.blue]
  });

  return (
    <ScaleSVG width={width} height={height}>
      {series.map((d, i) => (
        <Group key={`lines-${i}`}>
          <LinePath
            data={d}
            x={d => xScale(x(d))}
            y={d => yScale(y(d))}
            stroke={colorScale(i)}
            strokeWidth={1}
          />
        </Group>
      ))}
    </ScaleSVG>
  );
};
