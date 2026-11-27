// Transport only: JSON, the required client header on mutations, and the backend's structured errors.
export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
  get nothingChanged() { return this.status >= 400 && this.status < 500; }   // refused operations change nothing
}

async function request(method, path, body) {
  const init = { method, headers: { Accept: "application/json" } };
  if (method === "POST") {
    init.headers["Content-Type"] = "application/json";
    init.headers["X-Smartparser-Client"] = "webapp";
    init.body = JSON.stringify(body || {});
  }
  let res;
  try {
    res = await fetch("/api/" + path, init);
  } catch (e) {
    throw new ApiError(0, "NETWORK", "The backend could not be reached. Check that the Ringfence server is running.");
  }
  const type = res.headers.get("Content-Type") || "";
  const data = type.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    throw new ApiError(res.status, (data && data.error) || "HTTP_" + res.status, (data && data.message) || String(data));
  }
  return data;
}

export const get = (path) => request("GET", path);
export const post = (path, body) => request("POST", path, body);

export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(",", 2)[1] || "");
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(file);
  });
}
