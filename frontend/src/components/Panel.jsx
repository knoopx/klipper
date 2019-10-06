import React from "react"

const Panel = ({ title, className, ...props }) => {
  return (
    <div className={["flex flex-col m-1", className].join(" ")}>
      {title && (
        <div>
          <span className="inline-block px-4 py-2 rounded-t bg-gray-600 text-white font-bold">
            {title}
          </span>
        </div>
      )}

      <div className="p-4 rounded-b rounded-tr bg-gray-600" {...props} />
    </div>
  )
}

export default Panel
