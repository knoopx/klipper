import React, { useEffect } from "react";

const LOG_HISTORY_LENGTH = 1000;
const TEMP_HISTORY_LENGTH = 3600;

const App = () => {
  useEffect(() => {
    const client = new Client("ws://octopi.local:3000/");
  }, []);

  return <div />;
};

export default App;
