import React from "react"
import { ScaleSVG } from "@vx/responsive"
import { Group } from "@vx/group"
import { LinePath } from "@vx/shape"
import { scaleTime, scaleLinear, scaleOrdinal } from "@vx/scale"
import { extent, max } from "d3-array"

// accessors
const x = (d) => d.date
const y = (d) => d.value

const TemperatureGraph = ({ width, height, data }) => {
  const xMax = width
  const yMax = height

  const xScale = scaleTime({
    range: [0, xMax],
    domain: extent(data, x),
  })

  const yScale = scaleLinear({
    range: [yMax, 0],
    domain: [0, max(data, y)],
  })

  const colorScale = scaleOrdinal({
    domain: data,
    range: ["red", "blue", "green", "blue"],
  })

  return (
    <ScaleSVG width={width} height={height}>
      {data.map((d, i) => (
        <Group key={`lines-${i}`}>
          <LinePath
            data={d}
            x={(d) => xScale(x(d))}
            y={(d) => yScale(y(d))}
            stroke={colorScale(i)}
            strokeWidth={1}
          />
        </Group>
      ))}
    </ScaleSVG>
  )
}

TemperatureGraph.defaultProps = {
  data: [],
}

export default TemperatureGraph
