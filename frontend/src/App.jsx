import { useEffect, useState } from "react";
import { fetchRoles, parseResume, scoreProfile } from "./api.js";
import RolePicker from "./components/RolePicker.jsx";
import ResumeUpload from "./components/ResumeUpload.jsx";
import Results from "./components/Results.jsx";

/**
 * Simple 3-screen state machine for the hackathon demo:
 *   role  → upload → results
 *
 * We keep all heavy state (profile, report, plan) here so the user can click
 * "start over" without losing the uploaded file's parsed profile between tabs.
 */
export default function App() {
  const [screen, setScreen] = useState("role"); // role | upload | results
  const [roles, setRoles] = useState([]);
  const [role, setRole] = useState(null);
  const [profile, setProfile] = useState(null);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState("");
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchRoles()
      .then(setRoles)
      .catch((e) => setError(`Couldn't load roles: ${e.message}`));
  }, []);

  const handleRolePicked = (r) => {
    setRole(r);
    setScreen("upload");
  };

  const handleSubmitResume = async (form) => {
    setError(null);
    setLoading(true);
    try {
      setLoadingMsg("Parsing your resume…");
      const parsed = await parseResume({ file: form.file, role: role.id, ...form.meta });
      setProfile(parsed);

      setLoadingMsg("Scoring against the market snapshot + building your plan…");
      const scored = await scoreProfile({ profile: parsed, role: role.id, plan: true });
      setReport(scored);
      setScreen("results");
    } catch (e) {
      setError(e.message || "Something went wrong.");
    } finally {
      setLoading(false);
      setLoadingMsg("");
    }
  };

  const reset = () => {
    setRole(null);
    setProfile(null);
    setReport(null);
    setError(null);
    setScreen("role");
  };

  return (
    <div className="min-h-screen">
      <Header onReset={reset} showReset={screen !== "role"} />

      <main className="max-w-6xl mx-auto px-6 py-10">
        {error && (
          <div className="mb-6 p-4 rounded-xl bg-rose-900/40 border border-rose-500/50 text-rose-100">
            <div className="font-semibold mb-1">Heads up</div>
            <div className="text-sm opacity-90">{error}</div>
          </div>
        )}

        {loading && (
          <div className="mb-6 p-6 rounded-2xl bg-indigo-900/30 border border-indigo-500/40">
            <div className="flex items-center gap-3">
              <Spinner />
              <div>
                <div className="font-semibold">{loadingMsg}</div>
                <div className="text-sm text-indigo-200/70">
                  This takes ~15–25 seconds on the first run.
                </div>
              </div>
            </div>
          </div>
        )}

        {screen === "role" && (
          <RolePicker roles={roles} onPick={handleRolePicked} />
        )}

        {screen === "upload" && role && (
          <ResumeUpload
            role={role}
            disabled={loading}
            onBack={() => setScreen("role")}
            onSubmit={handleSubmitResume}
          />
        )}

        {screen === "results" && report && (
          <Results
            report={report}
            profile={profile}
            role={role}
            onReset={reset}
          />
        )}
      </main>

      <footer className="text-center text-xs text-slate-500 py-10">
        SkillScope · hackathon build · {new Date().getFullYear()}
      </footer>
    </div>
  );
}

function Header({ onReset, showReset }) {
  return (
    <header className="border-b border-slate-800/80 bg-slate-950/50 backdrop-blur sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 grid place-items-center font-bold">
            S
          </div>
          <div>
            <div className="font-semibold tracking-tight">SkillScope</div>
            <div className="text-xs text-slate-400">
              Resume → gap report → 12-week learning plan
            </div>
          </div>
        </div>
        {showReset && (
          <button
            onClick={onReset}
            className="text-sm text-slate-300 hover:text-white border border-slate-700 hover:border-slate-500 rounded-lg px-3 py-1.5 transition"
          >
            Start over
          </button>
        )}
      </div>
    </header>
  );
}

function Spinner() {
  return (
    <div className="h-6 w-6 rounded-full border-2 border-indigo-300/30 border-t-indigo-300 animate-spin" />
  );
}
