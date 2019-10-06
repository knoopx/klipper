import React from "react"

export default ({ position }) => (
  <div className="flex flex-auto mb-4 text-lg">
    <div className="flex flex-auto flex-col items-center">
      <div>
        {position[0]}
        <span className="ml-1 text-grey-darker text-sm font-thin">mm</span>
      </div>
      <div className="mt-1 text-white font-bold">X</div>
    </div>
    <div className="flex flex-auto flex-col items-center">
      <div>
        {position[1]}
        <span className="ml-1 text-grey-darker text-sm font-thin">mm</span>
      </div>
      <div className="mt-1 text-white font-bold">Y</div>
    </div>
    <div className="flex flex-auto flex-col items-center">
      <div>
        {position[2]}
        <span className="ml-1 text-grey-darker text-sm font-thin">mm</span>
      </div>
      <div className="mt-1 text-white font-bold">Z</div>
    </div>
  </div>
)
