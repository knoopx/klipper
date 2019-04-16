import React from "react";
import colors from "../theming/colors";

const Panel = ({ title, className, ...props }) => {
  return (
    <div className={["flex flex-col m-1", className].join(" ")}>
      {title && (
        <div className="">
          <span
            className="font-bold inline-block px-4 py-2 text-white rounded-t"
            style={{ backgroundColor: colors.greyDarker }}
          >
            {title}
          </span>
        </div>
      )}

      <div
        className={"p-4 rounded-b rounded-tr"}
        style={{ backgroundColor: colors.greyDarker }}
        {...props}
      />
    </div>
  );
};

export default Panel;
