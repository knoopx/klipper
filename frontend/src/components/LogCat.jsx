import React from "react"

const LogCat = ({ lines }) => (
  <div className="flex flex-col text-xs">
    {lines.map((line, index) => (
      <div key={index}>{line}</div>
    ))}
  </div>
)

LogCat.defaultProps = {
  lines: [],
}

export default LogCat
