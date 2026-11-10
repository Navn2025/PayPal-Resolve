// Compile once and serve a local optimized build without sharing next dev output.
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root=resolve(dirname(fileURLToPath(import.meta.url)),"..");
const mode=process.argv[2];
if(!["build","start"].includes(mode))throw new Error("Use build or start.");
const port=Number(process.env.PORT??3000);
if(!Number.isInteger(port)||port<1024||port>65535)throw new Error("Use a port between 1024 and 65535.");
const child=spawn(process.execPath,[resolve(root,"node_modules/next/dist/bin/next"),mode,...(mode==="build"?["--webpack"]:["--hostname","127.0.0.1","--port",String(port)])],{
  cwd:root,stdio:"inherit",windowsHide:true,
  env:{...process.env,NODE_ENV:"production",RESOLVE_UI_PREVIEW:"1",NEXT_TELEMETRY_DISABLED:"1"},
});
child.on("error",()=>{console.error("Could not start Next.js. Install frontend dependencies first.");process.exitCode=1;});
child.on("exit",code=>{process.exitCode=code??1;});
for(const signal of ["SIGINT","SIGTERM"])process.on(signal,()=>child.kill(signal));
