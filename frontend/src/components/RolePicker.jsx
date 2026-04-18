export default function RolePicker({ roles, onPick }) {
  return (
    <section>
      <div className="text-center mb-10">
        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight">
          Which role are you aiming for?
        </h1>
        <p className="mt-3 text-slate-400 max-w-2xl mx-auto">
          We score your resume against real job postings scraped from live
          Greenhouse listings, then build a 12-week plan with real resources.
        </p>
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        {roles.length === 0 && (
          <div className="col-span-2 text-slate-400 text-center py-8">
            Loading roles…
          </div>
        )}
        {roles.map((r) => (
          <button
            key={r.id}
            onClick={() => onPick(r)}
            className="text-left group rounded-2xl border border-slate-800 hover:border-indigo-400/60 bg-slate-900/40 hover:bg-slate-900/70 p-6 transition"
          >
            <div className="flex items-start justify-between">
              <div className="text-xl font-semibold group-hover:text-indigo-200">
                {r.label}
              </div>
              <div className="opacity-0 group-hover:opacity-100 transition text-indigo-300 text-sm">
                select →
              </div>
            </div>
            <p className="mt-2 text-sm text-slate-400 leading-relaxed">
              {r.description}
            </p>
          </button>
        ))}
      </div>
    </section>
  );
}
