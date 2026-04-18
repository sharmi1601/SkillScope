import { useState } from "react";

const LONG_TERM_INITIAL = 5;

export default function Results({ report, profile, role, onReset }) {
  const [showAllLongTerm, setShowAllLongTerm] = useState(false);
  const recs = report.recommendations || {};
  const plan = report.plan;
  const longTerm = report.long_term || [];
  const displayedLongTerm = showAllLongTerm
    ? longTerm
    : longTerm.slice(0, LONG_TERM_INITIAL);

  return (
    <section className="space-y-8">
      <TopSummary report={report} profile={profile} role={role} onReset={onReset} />

      <Bucket
        title="Close gaps"
        tag="quick wins — worth learning now"
        tone="rose"
        items={report.close_gaps}
        recs={recs}
        showDims
      />

      <Bucket
        title="Polish"
        tag="you're most of the way there"
        tone="amber"
        items={report.polish}
        recs={recs}
        showAdjacent
      />

      <LongTermBucket
        items={displayedLongTerm}
        total={longTerm.length}
        expanded={showAllLongTerm}
        onToggle={() => setShowAllLongTerm((v) => !v)}
      />

      {plan && plan.weeks && plan.weeks.length > 0 && (
        <PlanSection plan={plan} />
      )}
      {plan && plan.error && (
        <div className="rounded-xl p-4 bg-amber-900/30 border border-amber-500/40 text-amber-100">
          Couldn't build the week-by-week plan: {plan.error}
        </div>
      )}
    </section>
  );
}

function TopSummary({ report, profile, role, onReset }) {
  const hoursBudget =
    (profile?.hours_per_week || 10) * (profile?.deadline_weeks || 12);
  const close = report.total_hours_close || 0;
  return (
    <div className="rounded-2xl bg-gradient-to-br from-indigo-900/40 to-fuchsia-900/20 border border-indigo-500/30 p-6 sm:p-8">
      <div className="flex flex-wrap gap-4 items-start justify-between">
        <div>
          <div className="text-xs uppercase tracking-widest text-indigo-200/80">
            Gap report
          </div>
          <h2 className="text-3xl font-bold mt-1">
            {profile?.name || "You"} → {role.label}
          </h2>
          <p className="text-slate-300/80 mt-1">
            {profile?.hours_per_week}h/week × {profile?.deadline_weeks} weeks
            = <strong>{hoursBudget}h</strong> of study budget
          </p>
        </div>
        <button
          onClick={onReset}
          className="text-sm text-slate-300 hover:text-white border border-slate-700 hover:border-slate-500 rounded-lg px-3 py-1.5 transition"
        >
          Try another resume
        </button>
      </div>

      <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Close gaps" value={report.close_gaps?.length ?? 0} />
        <Stat label="Polish items" value={report.polish?.length ?? 0} />
        <Stat label="Long-term" value={report.long_term?.length ?? 0} />
        <Stat
          label="Hours to close"
          value={`${close}h`}
          sub={
            report.feasible_in_deadline
              ? "feasible in deadline"
              : "exceeds deadline"
          }
          subTone={report.feasible_in_deadline ? "emerald" : "rose"}
        />
      </div>
    </div>
  );
}

function Stat({ label, value, sub, subTone = "slate" }) {
  const subToneClass = {
    emerald: "text-emerald-300",
    rose: "text-rose-300",
    slate: "text-slate-400",
  }[subTone];
  return (
    <div className="rounded-xl bg-slate-950/50 border border-slate-800 p-4">
      <div className="text-xs uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className="text-2xl font-bold mt-1">{value}</div>
      {sub && <div className={`text-xs mt-1 ${subToneClass}`}>{sub}</div>}
    </div>
  );
}

function Bucket({ title, tag, tone, items, recs, showDims, showAdjacent }) {
  const color = {
    rose: "text-rose-300",
    amber: "text-amber-300",
    slate: "text-slate-300",
  }[tone];
  const dot = {
    rose: "bg-rose-400",
    amber: "bg-amber-400",
    slate: "bg-slate-400",
  }[tone];
  if (!items || items.length === 0) return null;
  return (
    <div>
      <div className="flex items-baseline gap-3 mb-4">
        <div className={`h-2 w-2 rounded-full ${dot}`} />
        <h3 className={`text-xl font-semibold ${color}`}>
          {title}{" "}
          <span className="text-slate-400 font-normal">({items.length})</span>
        </h3>
        <div className="text-xs text-slate-400">{tag}</div>
      </div>
      <div className="space-y-3">
        {items.map((sg) => (
          <SkillCard
            key={sg.skill}
            sg={sg}
            resources={recs[sg.skill] || []}
            showDims={showDims}
            showAdjacent={showAdjacent}
          />
        ))}
      </div>
    </div>
  );
}

function SkillCard({ sg, resources, showDims, showAdjacent }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <div className="flex flex-wrap items-baseline gap-3 justify-between">
        <div className="flex items-baseline gap-3">
          <div className="text-lg font-semibold">{sg.skill}</div>
          <ScorePill score={sg.total_score} />
        </div>
        <div className="text-xs text-slate-400">
          <span className="text-slate-200 font-medium">
            {sg.hours_to_learn}h
          </span>{" "}
          to learn
          {sg.market_frequency_pct > 0 && (
            <>
              {" · "}
              <span className="text-slate-200 font-medium">
                {sg.market_frequency_pct}%
              </span>{" "}
              of jobs
            </>
          )}
        </div>
      </div>

      {sg.reasoning && (
        <div className="text-sm text-slate-300/90 mt-2">{sg.reasoning}</div>
      )}

      {showDims && sg.dimensions && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {Object.entries(sg.dimensions).map(([k, v]) => (
            <span
              key={k}
              className="text-[11px] px-2 py-0.5 rounded-md bg-slate-800/70 border border-slate-700 text-slate-300"
              title={k}
            >
              {k.slice(0, 4)}={Number(v).toFixed(2)}
            </span>
          ))}
        </div>
      )}

      {showAdjacent &&
        sg.user_has_adjacent &&
        sg.user_has_adjacent.length > 0 && (
          <div className="text-xs text-slate-400 mt-2">
            adjacent:{" "}
            <span className="text-indigo-200">
              {sg.user_has_adjacent.join(", ")}
            </span>
          </div>
        )}

      {resources.length > 0 && (
        <div className="mt-4 space-y-2">
          <div className="text-xs uppercase tracking-widest text-slate-400">
            Recommended resources
          </div>
          {resources.map((r) => (
            <ResourceLink key={r.url} r={r} />
          ))}
        </div>
      )}
    </div>
  );
}

function ScorePill({ score }) {
  const v = Number(score || 0);
  const tone =
    v >= 0.7
      ? "bg-rose-500/20 text-rose-200 border-rose-500/40"
      : v >= 0.5
      ? "bg-amber-500/20 text-amber-200 border-amber-500/40"
      : "bg-slate-700/60 text-slate-200 border-slate-600/40";
  return (
    <span className={`text-xs px-2 py-0.5 rounded-md border ${tone}`}>
      score {v.toFixed(2)}
    </span>
  );
}

function ResourceLink({ r }) {
  return (
    <a
      href={r.url}
      target="_blank"
      rel="noreferrer"
      className="block rounded-lg border border-slate-800 hover:border-indigo-400/60 bg-slate-950/50 hover:bg-slate-950 p-3 transition"
    >
      <div className="flex items-start gap-2">
        <span className="text-[11px] uppercase tracking-widest text-indigo-300 mt-0.5 shrink-0">
          {r.platform}
        </span>
        <div className="min-w-0">
          <div className="font-medium text-slate-100 truncate">{r.title}</div>
          <div className="text-xs text-slate-500 truncate">{r.url}</div>
        </div>
      </div>
    </a>
  );
}

function LongTermBucket({ items, total, expanded, onToggle }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <div className="flex items-baseline gap-3 mb-4">
        <div className="h-2 w-2 rounded-full bg-slate-400" />
        <h3 className="text-xl font-semibold text-slate-300">
          Long-term{" "}
          <span className="text-slate-400 font-normal">({total})</span>
        </h3>
        <div className="text-xs text-slate-400">
          mark these on a longer runway
        </div>
      </div>
      <div className="rounded-xl border border-slate-800 bg-slate-900/30 divide-y divide-slate-800">
        {items.map((sg) => (
          <div key={sg.skill} className="px-4 py-3 flex flex-wrap gap-3 items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="font-medium text-slate-100">{sg.skill}</div>
              <ScorePill score={sg.total_score} />
            </div>
            <div className="text-xs text-slate-400">
              {sg.hours_to_learn}h
            </div>
          </div>
        ))}
      </div>
      {total > LONG_TERM_INITIAL && (
        <button
          onClick={onToggle}
          className="mt-3 text-sm text-indigo-300 hover:text-indigo-200"
        >
          {expanded
            ? "Hide extra long-term items"
            : `Show all ${total} long-term items`}
        </button>
      )}
    </div>
  );
}

function PlanSection({ plan }) {
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-2xl font-bold">Your week-by-week study plan</h3>
        <p className="text-slate-400 mt-1">
          {plan.plan_summary}
        </p>
        <div className="mt-2 text-sm text-slate-400">
          <strong className="text-slate-200">{plan.total_weeks}</strong> weeks ·{" "}
          <strong className="text-slate-200">{plan.total_hours}</strong> hours scheduled
          {plan._sanitization && (
            <>
              {" · "}
              URL safety check swapped{" "}
              {plan._sanitization.hallucinated_urls_swapped ?? 0}, removed{" "}
              {plan._sanitization.activities_removed ?? 0}
            </>
          )}
        </div>
      </div>

      <div className="space-y-3">
        {plan.weeks.map((wk) => (
          <WeekCard key={wk.week_number} wk={wk} />
        ))}
      </div>
    </div>
  );
}

function WeekCard({ wk }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-5">
      <div className="flex flex-wrap items-baseline gap-3 justify-between">
        <div className="flex items-baseline gap-3">
          <div className="text-sm uppercase tracking-widest text-indigo-300">
            Week {wk.week_number}
          </div>
          <div className="font-semibold">{wk.focus}</div>
        </div>
        <div className="text-xs text-slate-400">{wk.hours_planned}h planned</div>
      </div>
      <div className="mt-3 space-y-2">
        {(wk.activities || []).map((act, idx) => (
          <div
            key={`${act.url}-${idx}`}
            className="rounded-lg border border-slate-800 bg-slate-950/50 p-3"
          >
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-[11px] uppercase tracking-widest text-indigo-300">
                {act.skill}
              </span>
              <span className="text-xs text-slate-400">
                · {act.hours}h
              </span>
            </div>
            <a
              href={act.url}
              target="_blank"
              rel="noreferrer"
              className="block font-medium text-slate-100 hover:text-indigo-200 mt-1"
            >
              {act.title}
            </a>
            <div className="text-xs text-slate-500 truncate">{act.url}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
