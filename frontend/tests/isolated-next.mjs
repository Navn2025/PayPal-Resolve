// Start Next from a disposable source copy so Next cannot auto-load local .env files.
import { cp, mkdir, mkdtemp, symlink, readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createServer } from "node:http";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const scratch = resolve(frontend, "../.local/ui");
await mkdir(scratch, { recursive: true });
const project = await mkdtemp(join(scratch, "investigations-"));
await cp(frontend, project, { recursive: true, filter: (path) => {
  const name = basename(path);
  return !["node_modules", "test-results", "playwright-report", "tsconfig.tsbuildinfo"].includes(name) && !name.startsWith(".next") && !name.startsWith(".env");
} });
await symlink(join(frontend, "node_modules"), join(project, "node_modules"), "junction");
if (process.argv.includes("--prepare-only")) { console.log(project); process.exit(0); }
const port = Number(process.argv.find(value => value.startsWith("--port="))?.slice(7) ?? 3107);
const backendPort = Number(process.argv.find(value => value.startsWith("--backend-port="))?.slice(15) ?? 8011);
if (![port, backendPort].every(value => Number.isInteger(value) && value >= 1024 && value <= 65535)) throw new Error("Use local unprivileged ports.");
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(RESOLVE_|GROQ_|OPENROUTER_|PAYPAL_)/i.test(key)));
Object.assign(env, { RESOLVE_BACKEND_URL: `http://127.0.0.1:${backendPort}`, RESOLVE_UI_TEST_SERVER: "1", NEXT_TELEMETRY_DISABLED: "1" });
if (process.argv.includes("--in-process")) {
  // Managed Windows hosts may deny child processes; keep test compilation in threads.
  const configPath = join(project, "next.config.ts");
  const config = await readFile(configPath, "utf8");
  await writeFile(configPath, config.replace("export default config;", "config.experimental = { ...config.experimental, workerThreads: true };\nexport default config;"));
  for (const key of Object.keys(process.env)) if (/^(RESOLVE_|GROQ_|OPENROUTER_|PAYPAL_)/i.test(key)) delete process.env[key];
  Object.assign(process.env, env);
  // The source and its node_modules junction both live below this workspace root.
  // next.config.ts uses cwd as its Turbopack root.
  process.chdir(resolve(frontend, ".."));
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error("Use a local unprivileged port.");
  const { default: next } = await import(pathToFileURL(join(frontend, "node_modules/next/dist/server/next.js")).href);
  const app = next({ dev: true, dir: project, hostname: "127.0.0.1", port });
  await app.prepare();
  createServer(app.getRequestHandler()).listen(port, "127.0.0.1");
} else {
const production=process.argv.includes("--production");
if(production){
  env.NODE_ENV="production";
  const build=spawn(process.execPath,[join(frontend,"node_modules/next/dist/bin/next"),"build",project,"--webpack"],{env,stdio:"inherit",windowsHide:true});
  const code=await new Promise((resolve,reject)=>{build.on("exit",resolve);build.on("error",reject);});
  if(code!==0)process.exit(Number(code)||1);
}
const child = spawn(process.execPath, [join(frontend, "node_modules/next/dist/bin/next"), production?"start":"dev", project, ...(production?[]:["--webpack"]), "--hostname", "127.0.0.1", "--port", String(port)], { env, stdio: "inherit", windowsHide: true });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", (code) => process.exit(code ?? 1));
}
