import React from "react";

import {
  MdHome,
  MdKeyboardArrowDown,
  MdKeyboardArrowLeft,
  MdKeyboardArrowRight,
  MdKeyboardArrowUp
} from "react-icons/md";

import Colors from "../theming/colors";

const RadioButton = ({ style, className, ...props }) => (
  <div
    style={{ fontSize: 11, ...style }}
    className={[
      "rounded p-2 flex inline-block justify-center items-center",
      className
    ].join(" ")}
    {...props}
  />
);

const Button = ({ className, ...props }) => (
  <div
    {...props}
    style={{ backgroundColor: Colors.grey }}
    className={[
      "text-white rounded m-1 w-10 h-10 flex justify-center items-center",
      className
    ].join(" ")}
  />
);

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
        <Button className="">
          <MdKeyboardArrowLeft size={32} />
        </Button>
        <Button className="">
          <MdHome size={32} />
        </Button>
        <Button className="">
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
          <Button className="">
            <MdHome size={32} />
          </Button>
        </div>
        <div className="flex">
          <Button className="mx-auto">
            <MdKeyboardArrowDown size={32} />
          </Button>
        </div>
      </div>
      <div
        className="ml-3 inline-flex flex-col flex-auto rounded"
        style={{ backgroundColor: Colors.grey }}
      >
        <RadioButton
          className="text-white"
          style={{ backgroundColor: Colors.blueDarker }}
        >
          0.1
        </RadioButton>
        <RadioButton>0.5</RadioButton>
        <RadioButton>1.0</RadioButton>
        <RadioButton>5.0</RadioButton>
        <RadioButton>10.0</RadioButton>
      </div>
    </div>
  </div>
);
