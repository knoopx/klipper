const webpack = require("webpack")

module.exports = {
  style: {
    postcss: {
      plugins: [require("tailwindcss")],
    },
  },
  babel: {
    plugins: ["react-hot-loader/babel"],
  },
  webpack: {
    plugins: [],
    alias: {
      "react-dom": "@hot-loader/react-dom",
    },
    configure: {
      entry: ["react-hot-loader/patch", "./src/global.css"],
    },
  },
  eslint: {
    enable: false,
  },
}
