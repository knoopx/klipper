import React from "react"

const DefinitionList = ({ object }) => {
  return (
    <dl className="table w-full border-collapse">
      {Object.keys(object)
        // .filter((key) => Boolean(object[key]))
        .map((key) => (
          <div className="table-row" key={key}>
            <dt className="table-cell w-1 px-3 border text-right font-medium">
              {key}
            </dt>
            <dd className="table-cell px-3 border">
              {typeof object[key] === "object" ? (
                <DefinitionList object={object[key]} />
              ) : (
                object[key]
              )}
            </dd>
          </div>
        ))}
    </dl>
  )
}

export default DefinitionList
