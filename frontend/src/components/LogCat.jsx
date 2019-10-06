import React from "react";

const LogCat = ({ lines }) => (
  <div className="flex">
    {lines.map((line, index) => (
      <div key={index}>{line}</div>
    ))}
  </div>
);

LogCat.defaultProps = {
  lines: []
};

export default LogCat;
