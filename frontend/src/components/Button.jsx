import React from "react"
import classNames from "classnames"

const Button = ({ className, ...props }) => (
  <div
    className={classNames(
      "inline-block px-4 py-2 rounded bg-blue-600 text-white",
      className,
    )}
    {...props}
  />
)

export default Button
