import React from "react";
import { MdInsertDriveFile } from "react-icons/md";

function humanFileSize(size) {
  if (size > 0) {
    const i = Math.floor(Math.log(size) / Math.log(1024));
    return (
      (size / Math.pow(1024, i)).toFixed(2) * 1 +
      ["B", "kB", "MB", "GB", "TB"][i]
    );
  }
  return "0.00MB";
}

const FileItem = ({ name, size }) => (
  <div className="flex text-grey py-1">
    <MdInsertDriveFile className="mr-1" />
    <div className="flex-auto">{name}</div>
    <div style={{ fontSize: 11 }} className="text-grey-darker">
      {humanFileSize(size)}
    </div>
  </div>
);

const FileList = ({ files }) => (
  <div>
    {files.map(file => (
      <FileItem key={file.name} name={file.name} size={file.size} />
    ))}
  </div>
);

FileList.defaultProps = {
  files: Array.from(Array(10).keys()).map(index => ({
    name: `file${index}.gcode`,
    size: Math.random() * 1024 * 1024
  }))
};

export default FileList;
