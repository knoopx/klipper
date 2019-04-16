import React from "react";
import colors from "../theming/colors";

const Button = ({ className, ...props }) => (
  <div
    style={{ backgroundColor: colors.blueDarker }}
    className={["inline-block text-white rounded px-4 py-2", className].join(
      " "
    )}
    {...props}
  />
);

export default Button;
