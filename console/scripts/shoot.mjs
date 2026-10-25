// Screenshot probe: logs in with a signed session cookie and captures pages
// at given viewports via Chrome DevTools Protocol.
import { createHmac } from "node:crypto";
import { request } from "node:http";
import { writeFile } from "node:fs/promises";

const CDP = 9223;
const BASE = "http://127.0.0.1:3001";
const SECRET = "change-me-to-a-long-random-string";
const OUT = process.env.TEMP + "\\console-shots";

const exp = Math.floor(Date.now() / 1000) + 3600;
const sig = createHmac("sha256", SECRET).update(`v1.${exp}.console-session`).digest("hex");
const COOKIE = `v1.${exp}.${sig}`;

function httpJson(path) {
  return new Promise((resolve, reject) => {
    const req = request(
      { host: "127.0.0.1", port: CDP, path, method: path.startsWith("/json/new") ? "PUT" : "GET" },
      (res) => {
        let body = "";
        res.setEncoding("utf8");
        res.on("data", (c) => (body += c));
        res.on("end", () => {
          try { resolve(JSON.parse(body)); } catch { resolve(body); }
        });
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
  const targetId = created.id;
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  const p = (m, params) => send(m, params, sessionId);

  await p("Page.enable");
  await p("Runtime.enable");
  await p("Network.enable");
  await p("Network.setCookie", { name: "console_session", value: COOKIE, domain: "127.0.0.1", path: "/" });

  const shots = [
    { route: "/insights", w: 1440, h: 900, name: "insights-1440" },
    { route: "/insights", w: 1440, h: 900, name: "insights-rollups-1440", scrollTo: "telemetry-rollups" },
    { route: "/insights", w: 1024, h: 900, name: "insights-1024" },
    { route: "/insights", w: 1024, h: 900, name: "insights-rollups-1024", scrollTo: "telemetry-rollups" },
    { route: "/", w: 1280, h: 800, name: "overview-1280" },
  ];

  for (const s of shots) {
    await p("Emulation.setDeviceMetricsOverride", {
      width: s.w, height: s.h, deviceScaleFactor: 1, mobile: false,
    });
    await p("Page.navigate", { url: BASE + s.route });
    await sleep(4500);
    if (s.scrollTo) {
      await p("Runtime.evaluate", {
        expression: `document.getElementById(${JSON.stringify(s.scrollTo)})?.scrollIntoView({block:"center"})`,
      });
      await sleep(600);
    }
    const metrics = await p("Runtime.evaluate", {
      expression: `(() => {
        const de = document.documentElement;
        const over = [...document.querySelectorAll("body *")].filter(el => {
          const cs = getComputedStyle(el); if (cs.position === "fixed" || cs.display === "none") return false;
          const r = el.getBoundingClientRect();
          return r.width > 0 && (r.right > innerWidth + 1 || r.left < -1);
        }).slice(0, 6).map(el => ({ tag: el.tagName, cls: String(el.className).slice(0, 60), right: Math.round(el.getBoundingClientRect().right) }));
        return { vw: innerWidth, scrollW: de.scrollWidth, hScroll: de.scrollWidth > de.clientWidth + 1, over };
      })()`,
      returnByValue: true,
    });
    const shot = await p("Page.captureScreenshot", { format: "png" });
    await writeFile(`${OUT}\\${s.name}.png`, Buffer.from(shot.data, "base64"));
    console.log(JSON.stringify({ name: s.name, ...metrics.result.value }));
  }

  ws.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
