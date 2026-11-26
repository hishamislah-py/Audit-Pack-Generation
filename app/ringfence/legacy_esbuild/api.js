// The only module that talks to the backend. Every lifecycle rule (status, available actions, progress, ordering)
// comes from the backend responses; this module only transports them.
export class ApiError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}

async function call(method, path, body) {
  const opts = { method, headers: {} };
  if (method === "POST") {
    opts.headers["Content-Type"] = "application/json";
    opts.headers["X-Smartparser-Client"] = "webapp";
    opts.body = JSON.stringify(body || {});
  }
  const r = await fetch("/api/" + path, opts);
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("application/json") ? await r.json() : await r.text();
  if (!r.ok) throw new ApiError(r.status, (data && data.error) || "HTTP_" + r.status, (data && data.message) || String(data));
  return data;
}

export const get = (p) => call("GET", p);
export const post = (p, b) => call("POST", p, b);

export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(",", 2)[1] || "");
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}

export async function stageFile(file) {
  const entries = (await post("staging", { name: file.name, data_b64: await fileToBase64(file) })).entries;
  const e = entries.find((x) => x.staging_id);
  if (!e) throw new ApiError(400, "NOTHING_STAGED", "the file could not be staged");
  return e.staging_id;
}
