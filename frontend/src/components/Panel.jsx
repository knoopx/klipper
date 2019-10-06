import React from "react"

const Panel = ({ title, className, ...props }) => {
  return (
    <div className={["flex flex-col m-1", className].join(" ")}>
      {title && (
        <div>
          <span className="inline-block px-4 py-2 rounded-t shadow bg-white font-medium">
            {title}
          </span>
        </div>
      )}

      <div
        className="z-10 p-4 rounded-b rounded-tr shadow bg-white"
        {...props}
      />
    </div>
  )
}

export default Panel
