const spacing = {
  "1": "0.25rem",
  "2": "0.5rem",
  "3": "0.75rem",
  "4": "1rem",
  "5": "1.25rem",
  "6": "1.5rem",
  "8": "2rem",
  "10": "2.5rem",
  "12": "3rem",
  "16": "4rem",
  "24": "6rem",
  "32": "8rem",
  "48": "12rem",
  "64": "16rem"
};

const fontSizes = {
  "-2": ".75rem",
  "-1": ".875rem",
  "0": "1rem",
  "1": "1.125rem",
  "2": "1.25rem",
  "3": "1.5rem",
  "4": "1.875rem",
  "5": "2.25rem",
  "6": "3rem"
};

var defaultRules = {
  hover: function(value) {
    defaultRules.s.call(this, ":hover", value);
  },

  focus: function(value) {
    defaultRules.s.call(this, ":focus", value);
  }
};

import builder from "./builder";

const mapKeyToValue = (key, map) => {
  if (key in map) {
    return map[key];
  }
  throw new Error(`${key} is not valid.`);
};

export default builder({
  ...defaultRules,
  text: color => ({
    color: mapKeyToValue(color, colors)
  })
});
