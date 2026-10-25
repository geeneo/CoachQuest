// Every call goes through nginx, which checks the session cookie.
// The custom header is the CSRF guard the API requires on writes.

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : "Request failed");
    this.status = status;
  }
}

export async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      "X-Requested-With": "CoachQuest",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    // An HTML error page from a proxy: the API is down, restarting or unreachable.
    throw new ApiError(
      res.status,
      `The server answered with an error page (HTTP ${res.status}). CoachQuest may be restarting or its API ` +
        "container is down. Wait a moment and try again; if it persists, check the api container logs.",
    );
  }
  if (!res.ok) {
    let detail = data?.detail;
    if (Array.isArray(detail)) detail = detail.map((d) => d.msg).join("; ");
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      window.dispatchEvent(new Event("cq:unauthorized"));
    }
    throw new ApiError(res.status, detail || res.statusText);
  }
  return data;
}

// Download a file from the API (e.g. a .zwo or a ZIP). Errors come back as messages, not as a saved JSON file.
export async function download(path) {
  const res = await fetch(path, { credentials: "same-origin", headers: { "X-Requested-With": "CoachQuest" } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, detail);
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || "download";
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
