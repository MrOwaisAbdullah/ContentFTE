// Layout probe: connects to Chrome via CDP and reports horizontal overflow
// and render failures for every console route at several viewports.
import { createHmac } from "node:crypto";
import { request } from "node:http";

const CDP = 9223;
const BASE = "http://127.0.0.1:3001";
const SECRET = "change-me-to-a-long-random-string";
const exp = Math.floor(Date.now() / 1000) + 3600;
const sig = createHmac("sha256", SECRET).update(`v1.${exp}.console-session`).digest("hex");
const COOKIE = `v1.${exp}.${sig}`;

const routes = [
  "/", "/approvals", "/publish", "/articles", "/articles/keywords",
  "/articles/research", "/articles/briefs", "/media", "/logs", "/insights",
  "/stages", "/sites", "/instances", "/provision", "/articles/53",
];

const viewports = [
  { w: 1440, h: 900, name: "desktop" },
  { w: 768, h: 1024, name: "tablet" },
  { w: 375, h: 812, name: "mobile" },
];

function httpJson(path) {
  return new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port: CDP, path, method: path.startsWith("/json/new") ? "PUT" : "GET" }, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (c) => (body += c));
      res.on("end", () => {
        try { resolve(JSON.parse(body)); } catch { resolve(body); }
      });
    });
    req.on("error", reject);
    req.end();
  });
}

let id = 0;
const pending = new Map();
let ws;

function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const msgId = ++id;
    pending.set(msgId, { resolve, reject });
    ws.send(JSON.stringify({ id: msgId, method, params }));
  });
}

async function evalJs(expression) {
  const res = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.text || "evaluate failed");
  return res.result?.value;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

  console.error("ws ok");
  const created = await httpJson("/json/new?about:blank");
  console.error("created", JSON.stringify(created).slice(0, 200));
  const targetId = created.id || created.targetId;
  const attach = await send("Target.attachToTarget", { targetId, flatten: true });
  const sessionId = attach.sessionId;
  // Wrap sends with sessionId for page-level calls.
  const pageSend = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const msgId = ++id;
      pending.set(msgId, { resolve, reject });
      ws.send(JSON.stringify({ id: msgId, sessionId, method, params }));
    });
  const pageEval = async (expression) => {
    const res = await pageSend("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (res.exceptionDetails) throw new Error(res.exceptionDetails.text || "evaluate failed");
    return res.result?.value;
  };

  await pageSend("Page.enable");
  await pageSend("Runtime.enable");
  await pageSend("Network.enable");
  await pageSend("Network.setCookie", {
    name: "console_session", value: COOKIE, domain: "127.0.0.1", path: "/",
  });

  const report = [];
  for (const vp of viewports) {
    await pageSend("Emulation.setDeviceMetricsOverride", {
      width: vp.w, height: vp.h, deviceScaleFactor: 1, mobile: vp.w < 600,
    });
    for (const route of routes) {
      try {
        await pageSend("Page.navigate", { url: BASE + route });
        await sleep(vp.name === "desktop" ? 4000 : 1500);
        const info = await pageEval(`(() => {
          const vw = window.innerWidth;
          const de = document.documentElement;
          const overflow = [];
          const all = document.querySelectorAll("body *");
          for (const el of all) {
            const cs = getComputedStyle(el);
            if (cs.position === "fixed" || cs.display === "none" || cs.visibility === "hidden") continue;
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.height === 0) continue;
            if (r.right > vw + 1 || r.left < -1) {
              overflow.push({
                tag: el.tagName.toLowerCase(),
                cls: (el.className || "").toString().slice(0, 90),
                left: Math.round(r.left), right: Math.round(r.right), width: Math.round(r.width),
                text: (el.textContent || "").trim().slice(0, 40),
              });
            }
          }
          const err = (document.body.innerText || "").match(/(Application error|Internal Server Error|Unhandled Runtime Error|500\\b)/i);
          const main = document.querySelector("main");
          const mr = main ? main.getBoundingClientRect() : null;
          const firstChild = main?.firstElementChild?.getBoundingClientRect?.() ?? null;
          return {
            title: document.title,
            vw,
            scrollWidth: de.scrollWidth,
            clientWidth: de.clientWidth,
            hScroll: de.scrollWidth > de.clientWidth + 1,
            mainWidth: mr ? Math.round(mr.width) : null,
            bodyText: (document.body.innerText || "").slice(0, 160).replace(/\\s+/g, " "),
            error: err ? err[0] : null,
            overflow: overflow.slice(0, 8),
          };
        })()`);
        report.push({ vp: vp.name, route, ...info });
      } catch (e) {
        report.push({ vp: vp.name, route, error: String(e) });
      }
    }
  }

  console.log(JSON.stringify(report, null, 2));
  await httpJson(`/json/close/${targetId}`);
  ws.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
