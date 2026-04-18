import { useState } from "react";

export default function ResumeUpload({ role, disabled, onBack, onSubmit }) {
  const [file, setFile] = useState(null);
  const [name, setName] = useState("");
  const [hours, setHours] = useState(10);
  const [weeks, setWeeks] = useState(12);
  const [style, setStyle] = useState("video");

  const canSubmit = !!file && !disabled;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      file,
      meta: {
        name: name || undefined,
        hours_per_week: Number(hours) || 10,
        deadline_weeks: Number(weeks) || 12,
        learning_style: style,
      },
    });
  };

  return (
    <section>
      <button
        onClick={onBack}
        disabled={disabled}
        className="text-sm text-slate-400 hover:text-slate-200 mb-6"
      >
        ← pick a different role
      </button>

      <div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-8">
        <div className="flex items-center gap-3 mb-2">
          <div className="text-xs uppercase tracking-widest text-indigo-300">
            Target role
          </div>
        </div>
        <h2 className="text-3xl font-bold">{role.label}</h2>
        <p className="text-slate-400 mt-1 mb-8">{role.description}</p>

        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label className="block text-sm font-medium mb-2 text-slate-200">
              Resume file <span className="text-rose-400">*</span>
            </label>
            <label
              className={`block rounded-xl border-2 border-dashed cursor-pointer transition p-6 text-center ${
                file
                  ? "border-indigo-500/70 bg-indigo-900/20"
                  : "border-slate-700 hover:border-slate-500 bg-slate-950/40"
              }`}
            >
              <input
                type="file"
                accept=".pdf,.docx,.doc,.txt,.md"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="hidden"
                disabled={disabled}
              />
              {file ? (
                <div>
                  <div className="font-medium text-indigo-100">
                    {file.name}
                  </div>
                  <div className="text-xs text-slate-400 mt-1">
                    {(file.size / 1024).toFixed(1)} KB · click to change
                  </div>
                </div>
              ) : (
                <div>
                  <div className="text-slate-200 font-medium">
                    Drop or click to upload
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    PDF, DOCX, TXT · parsed locally, never stored
                  </div>
                </div>
              )}
            </label>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            <Field
              label="Your name (optional)"
              value={name}
              onChange={setName}
              placeholder="e.g. Sharmi"
              disabled={disabled}
            />
            <Field
              label="Learning style"
              disabled={disabled}
            >
              <select
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                disabled={disabled}
                className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 focus:border-indigo-400 focus:outline-none"
              >
                <option value="video">video (YouTube/courses)</option>
                <option value="reading">reading (docs/books)</option>
                <option value="hands_on">hands-on (interactive)</option>
                <option value="any">any</option>
              </select>
            </Field>

            <Field
              label="Hours/week you can study"
              type="number"
              value={hours}
              onChange={setHours}
              min={1}
              max={60}
              disabled={disabled}
            />
            <Field
              label="Deadline (weeks)"
              type="number"
              value={weeks}
              onChange={setWeeks}
              min={1}
              max={52}
              disabled={disabled}
            />
          </div>

          <button
            type="submit"
            disabled={!canSubmit}
            className="w-full rounded-xl bg-indigo-500 hover:bg-indigo-400 disabled:bg-slate-800 disabled:text-slate-500 font-semibold py-3 transition"
          >
            {disabled ? "Working…" : "Score my resume"}
          </button>
        </form>
      </div>
    </section>
  );
}

function Field({ label, value, onChange, placeholder, type = "text", min, max, disabled, children }) {
  return (
    <div>
      <label className="block text-sm font-medium mb-2 text-slate-200">
        {label}
      </label>
      {children ?? (
        <input
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          min={min}
          max={max}
          disabled={disabled}
          className="w-full rounded-lg bg-slate-950 border border-slate-700 px-3 py-2 focus:border-indigo-400 focus:outline-none"
        />
      )}
    </div>
  );
}
