// Tiny fetch helpers around the FastAPI backend. All requests go through
// the Vite dev proxy (vite.config.js) so there's no CORS fiddling in dev.

const BASE = "/api";

async function handle(res) {
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = body.detail;
    } catch {
      // body wasn't JSON — keep the status-code message.
    }
    throw new Error(msg);
  }
  return res.json();
}

export async function fetchRoles() {
  const res = await fetch(`${BASE}/roles`);
  return handle(res);
}

export async function parseResume({
  file,
  role,
  name,
  hours_per_week,
  deadline_weeks,
  learning_style,
}) {
  const body = new FormData();
  body.append("resume", file);
  body.append("role", role);
  if (name) body.append("name", name);
  body.append("hours_per_week", String(hours_per_week));
  body.append("deadline_weeks", String(deadline_weeks));
  body.append("learning_style", learning_style);

  const res = await fetch(`${BASE}/parse-resume`, {
    method: "POST",
    body,
  });
  return handle(res);
}

export async function scoreProfile({ profile, role, plan = true }) {
  const res = await fetch(`${BASE}/score`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile, role, plan }),
  });
  return handle(res);
}
