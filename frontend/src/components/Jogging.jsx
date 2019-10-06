import React from "react"
import {
  MdHome,
  MdKeyboardArrowDown,
  MdKeyboardArrowLeft,
  MdKeyboardArrowRight,
  MdKeyboardArrowUp,
} from "react-icons/md"

const RadioButton = ({ style, className, ...props }) => (
  <div
    style={{ fontSize: 11, ...style }}
    className={[
      "flex inline-block items-center justify-center p-2 rounded",
      className,
    ].join(" ")}
    {...props}
  />
)

const Button = ({ className, ...props }) => (
  <div
    {...props}
    className={[
      "flex items-center justify-center h-10 w-10 m-1 rounded bg-gray-500 text-white",
      className,
    ].join(" ")}
  />
)

export default () => (
  <div className="flex flex-auto justify-around">
    <div className="flex flex-col">
      <div className="flex">
        <Button className="mx-auto">
          <Button>
            <MdKeyboardArrowUp size={32} />
          </Button>
        </Button>
      </div>
      <div className="flex">
        <Button>
          <MdKeyboardArrowLeft size={32} />
        </Button>
        <Button>
          <MdHome size={32} />
        </Button>
        <Button>
          <MdKeyboardArrowRight size={32} />
        </Button>
      </div>
      <div className="flex">
        <Button className="mx-auto">
          <MdKeyboardArrowDown size={32} />
        </Button>
      </div>
    </div>
    <div className="flex items-center">
      <div className="flex flex-col">
        <div className="flex">
          <Button className="mx-auto">
            <MdKeyboardArrowUp size={32} />
          </Button>
        </div>

        <div className="flex">
          <Button>
            <MdHome size={32} />
          </Button>
        </div>
        <div className="flex">
          <Button className="mx-auto">
            <MdKeyboardArrowDown size={32} />
          </Button>
        </div>
      </div>
      <div className="flex-auto flex-col inline-flex ml-3 rounded bg-gray-500">
        <RadioButton className="bg-blue-600 text-white">0.1</RadioButton>
        <RadioButton>0.5</RadioButton>
        <RadioButton>1.0</RadioButton>
        <RadioButton>5.0</RadioButton>
        <RadioButton>10.0</RadioButton>
      </div>
    </div>
  </div>
)
