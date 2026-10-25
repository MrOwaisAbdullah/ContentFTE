import { createHmac } from "node:crypto";
import { request } from "node:http";

const CDP = 9223;
const BASE = "http://127.0.0.1:3001";
const SECRET = "change-me-to-a-long-random-string";
const exp = Math.floor(Date.now() / 1000) + 3600;
const sig = createHmac("sha256", SECRET).update(`v1.${exp}.console-session`).digest("hex");
const COOKIE = `v1.${exp}.${sig}`;

function httpJson(path) {
  return new Promise((resolve, reject) => {
    const req = request(
      { host: "127.0.0.1", port: CDP, path, method: path.startsWith("/json/new") ? "PUT" : "GET" },
      (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => { try { resolve(JSON.parse(body)); } catch { resolve(body); } });
      },
    );
    req.on("error", reject);
    req.end();
  });
}

let id = 0;
const pending = new Map();
let ws;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function send(method, params = {}, sessionId) {
  return new Promise((resolve, reject) => {
    const msgId = ++id;
    pending.set(msgId, { resolve, reject });
    ws.send(JSON.stringify({ id: msgId, sessionId, method, params }));
  });
}

async function main() {
  const version = await httpJson("/json/version");
  ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    }
  };
  const created = await httpJson("/json/new?about:blank");
  const { sessionId } = await send("Target.attachToTarget", { targetId: created.id, flatten: true });
  const p = (m, params) => send(m, params, sessionId);
  await p("Page.enable");
  await p("Runtime.enable");
  await p("Network.enable");
  await p("Network.setCookie", { name: "console_session", value: COOKIE, domain: "127.0.0.1", path: "/" });

  const logs = [];
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === "Runtime.consoleAPICalled") {
      logs.push(m.params.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 300));
    }
    if (m.method === "Runtime.exceptionThrown") {
      logs.push("EXC: " + (m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text).slice(0, 400));
    }
  });

  await p("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  for (const route of ["/insights", "/sites"]) {
    await p("Page.navigate", { url: BASE + route });
    await sleep(4000);
    const res = await p("Runtime.evaluate", {
      expression: `(() => ({
        route: location.pathname,
        htmlClass: document.documentElement.className,
        theme: localStorage.getItem("theme"),
        cookie: document.cookie,
        prefersDark: matchMedia("(prefers-color-scheme: dark)").matches,
        bg: getComputedStyle(document.body).backgroundColor,
        issue: document.querySelector("[data-nextjs-toast]")?.innerText ?? null,
      }))()`,
      returnByValue: true,
    });
    console.log(JSON.stringify(res.result.value));
  }
  console.log("LOGS:", JSON.stringify(logs.slice(-15), null, 2));
  ws.close();
}
main().catch((e) => { console.error(e); process.exit(1); });
