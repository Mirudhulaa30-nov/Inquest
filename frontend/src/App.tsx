import { useEffect, useMemo, useState } from "react";
import {
  Activity, AlertTriangle, ArrowUpRight, BarChart3,
  Check, ChevronDown, CircleHelp, Clock3, Command, Cpu, Database,
  FlaskConical, Inbox, LoaderCircle, Play, Shield, ShieldAlert,
  ShieldCheck, Sparkles, TerminalSquare, X,
} from "lucide-react";

type CaseInfo = {
  id: string; kind: string; style: string; task: string; headline: boolean;
  required_calls: { tool: string; args: Record<string, string> }[];
  attacker_goal: { tool: string; args: Record<string, string> } | null;
};
type EventItem = Record<string, any> & { kind: string };
type ArmSummary = Record<string, any>;
type ResultsData = { available: boolean; summary: { arms: Record<string, ArmSummary>; total_runs: number; simulated: boolean; mixed_modes?: boolean } | null };
type RunOutcome = { case_id: string; arm: string; model_name: string; task_completed: boolean; attack_succeeded: boolean | null; final_text: string; steps: number; model_calls: number; error: string | null };

const arms = ["naive", "strict", "causal"] as const;

function AgentOrb({ active }: { active: boolean }) {
  return <div className={`agent-orb ${active ? "is-active" : ""}`} aria-label={active ? "Model is processing" : "Model ready"}>
    <div className="orb-core" /><div className="orb-glint" /><div className="orb-ring" />
  </div>;
}

function AnimatedFeed({ events, running }: { events: EventItem[]; running: boolean }) {
  if (!events.length && !running) return <div className="feed-empty"><Activity size={18} /><span>Run a case to see live tool activity here.</span></div>;
  return <div className="feed-list" aria-live="polite">
    {events.map((event, index) => {
      const call = event.call ?? {};
      const action = event.kind === "verdict" ? String(event.action ?? "allow") : "tool_call";
      const icon = action === "excise" ? <ShieldAlert size={15} /> : action === "block" ? <X size={15} /> : action === "allow" ? <ShieldCheck size={15} /> : <TerminalSquare size={15} />;
      const title = action === "tool_call" ? call.name ?? "Tool" : `${action} · ${call.name ?? "tool"}`;
      const detail = action === "tool_call" ? JSON.stringify(event.result ?? call.args ?? {}) : (event.reason ?? "Defense decision recorded");
      return <article className={`feed-item ${action}`} key={`${index}-${title}`} style={{ animationDelay: `${Math.min(index * 35, 250)}ms` }}>
        <span className="feed-icon">{icon}</span><div className="feed-copy"><div className="feed-title"><strong>{title.replaceAll("_", " ")}</strong><span>{event.received_at ? new Date(event.received_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : ""}</span></div><p>{detail}</p>
          {event.culprits?.length > 0 && <small>Flagged email{event.culprits.length > 1 ? "s" : ""}: {event.culprits.join(", ")}</small>}
        </div>
      </article>;
    })}
    {running && <div className="feed-wait"><span className="pulse-dot" />Waiting for the next model action…</div>}
  </div>;
}

function MetricBar({ label, value, color }: { label: string; value: number | null | undefined; color: string }) {
  const percent = typeof value === "number" ? Math.round(value * 100) : null;
  return <div className="metric-row"><div className="metric-label"><span>{label}</span><b>{percent === null ? "—" : `${percent}%`}</b></div><div className="metric-track"><span style={{ width: `${percent ?? 0}%`, background: color }} /></div></div>;
}

export default function App() {
  const [cases, setCases] = useState<CaseInfo[]>([]);
  const [selected, setSelected] = useState("demo");
  const [arm, setArm] = useState<(typeof arms)[number]>("causal");
  const [fake, setFake] = useState(true);
  const [tab, setTab] = useState<"run" | "results">("run");
  const [events, setEvents] = useState<EventItem[]>([]);
  const [running, setRunning] = useState(false);
  const [outcome, setOutcome] = useState<RunOutcome | null>(null);
  const [results, setResults] = useState<ResultsData | null>(null);
  const [error, setError] = useState("");
  const [loadingCases, setLoadingCases] = useState(true);

  useEffect(() => {
    fetch("/api/cases").then((r) => { if (!r.ok) throw new Error("Could not load cases. Is the Inquest API running?"); return r.json(); })
      .then((data: CaseInfo[]) => { setCases(data); if (!data.some((c) => c.id === "demo")) setSelected(data[0]?.id ?? ""); })
      .catch((e: Error) => setError(e.message)).finally(() => setLoadingCases(false));
    fetch("/api/results").then((r) => r.ok ? r.json() : null).then((data) => setResults(data)).catch(() => undefined);
  }, []);

  const currentCase = useMemo(() => cases.find((item) => item.id === selected), [cases, selected]);

  async function startRun() {
    if (!currentCase || running) return;
    setError(""); setEvents([]); setOutcome(null); setRunning(true);
    try {
      const response = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: selected, arm, fake }) });
      if (!response.ok || !response.body) throw new Error((await response.text()) || "Could not start the run.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const chunks = buffer.split("\n\n"); buffer = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const line = chunk.split("\n").find((part) => part.startsWith("data: "));
          if (!line) continue;
          const event = JSON.parse(line.slice(6)) as EventItem;
          if (event.kind === "done") {
            setOutcome(event.result);
            if (event.result?.error) setError(event.result.error);
          }
          else if (event.kind === "error") setError(event.message ?? "The run failed.");
          else setEvents((previous) => [...previous, { ...event, received_at: new Date().toISOString() }]);
        }
      }
      setResults(await fetch("/api/results").then((r) => r.json()).catch(() => results));
    } catch (e) { setError(e instanceof Error ? e.message : "Unexpected run error."); }
    finally { setRunning(false); }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><FlaskConical size={18} /></div><div><b>inquest</b><span>RESEARCH CONSOLE</span></div></div>
      <div className="side-label">WORKSPACE</div>
      <button className={`nav-item ${tab === "run" ? "selected" : ""}`} onClick={() => setTab("run")}><Activity size={17} />Live runner<span className="nav-count">01</span></button>
      <button className={`nav-item ${tab === "results" ? "selected" : ""}`} onClick={() => setTab("results")}><BarChart3 size={17} />Results</button>
      <div className="sidebar-bottom"><div className="connection"><span className="pulse-dot" /><div><b>Local session</b><small>Private workspace</small></div><span className="you-chip">YOU</span></div><div className="version"><span>INQUEST LABS</span><span>v1.0</span></div></div>
    </aside>

    <main className="main-area">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><b>{tab === "run" ? "Live runner" : "Results"}</b></div><div className="topbar-right"><span className={`mode-pill ${fake ? "simulated" : "real"}`}><span />{fake ? "SIMULATED MODE" : "LIVE MODEL"}</span><span className="avatar">M</span></div></header>

      {tab === "run" ? <div className="page-content">
        <section className="page-heading"><div><div className="eyebrow"><Sparkles size={13} /> EMAIL AGENT RED-TEAM HARNESS</div><h1>Control room<span className="heading-period">.</span></h1><p>Run a case, inspect each model action, and see the defense respond.</p></div><div className="header-shortcut"><Command size={13} /><span>Local research</span></div></section>

        <section className="run-config panel">
          <div className="config-title"><div className="section-icon"><Inbox size={16} /></div><div><b>Configure a run</b><span>Choose a scenario and defense strategy</span></div></div>
          <div className="config-controls">
            <label className="select-field case-select"><span>CASE SCENARIO</span><div className="select-wrap"><select value={selected} onChange={(e) => setSelected(e.target.value)} disabled={loadingCases || running}><option value="">{loadingCases ? "Loading cases…" : "Choose a case"}</option>{cases.map((item) => <option key={item.id} value={item.id}>{item.id} · {item.style}</option>)}</select><ChevronDown size={15} /></div></label>
            <label className="select-field"><span>DEFENSE ARM</span><div className="select-wrap"><select value={arm} onChange={(e) => setArm(e.target.value as typeof arm)} disabled={running}>{arms.map((item) => <option key={item} value={item}>{item.toUpperCase()}</option>)}</select><ChevronDown size={15} /></div></label>
            <div className="mode-toggle"><div><span>Model mode</span><small>{fake ? "No API key needed" : "Uses configured Gemini key"}</small></div><button className={`switch ${fake ? "on" : ""}`} role="switch" aria-checked={fake} onClick={() => setFake(!fake)} disabled={running}><span /></button></div>
            <button className="run-button" onClick={startRun} disabled={!currentCase || running || loadingCases}>{running ? <LoaderCircle className="spin" size={16} /> : <Play size={15} fill="currentColor" />}{running ? "Running" : "Run case"}<ArrowUpRight size={15} /></button>
          </div>
          {currentCase && <div className="task-preview"><div className={`case-type ${currentCase.kind}`}>{currentCase.kind === "attack" ? <ShieldAlert size={14} /> : <ShieldCheck size={14} />}{currentCase.kind.toUpperCase()}<span>·</span>{currentCase.style.replaceAll("_", " ")}</div><p>{currentCase.task}</p>{currentCase.attacker_goal && <small>ATTACK GOAL <code>{currentCase.attacker_goal.tool} {JSON.stringify(currentCase.attacker_goal.args)}</code></small>}</div>}
        </section>

        <div className="workspace-grid">
          <section className="panel feed-panel"><div className="panel-heading"><div><div className="section-icon violet"><Activity size={16} /></div><div><b>Execution trace</b><span>Live tool and defense events</span></div></div><div className="live-state">{running ? <><i className="pulse-dot" />LIVE</> : outcome ? <><Check size={13} />COMPLETE</> : <><Clock3 size={13} />IDLE</>}</div></div>
            {fake && (running || outcome) && <div className="sim-banner"><FlaskConical size={13} /> SIMULATED — NOT REAL MODEL RESULTS</div>}
            <AnimatedFeed events={events} running={running} />
            {error && <div className="error-banner"><AlertTriangle size={16} /><span>{error}</span><button onClick={() => setError("")} aria-label="Dismiss error"><X size={14} /></button></div>}
          </section>
          <aside className="right-column">
            <section className="panel agent-panel"><div className="panel-heading compact"><div><div><b>Model state</b><span>{running ? "Analyzing the current step" : outcome ? "Run finished" : "Standing by"}</span></div></div><span className="model-chip"><Cpu size={12} />{fake ? "FAKE" : "GEMMA"}</span></div><div className="orb-stage"><div className="orb-halo" /><AgentOrb active={running} /><span className="orb-caption">{running ? "PROCESSING" : "READY"}</span></div><div className="agent-foot"><span><span className={`status-dot ${running ? "active" : ""}`} />{running ? "Model is responding" : "Model connection ready"}</span><CircleHelp size={15} /></div></section>
            <section className="panel outcome-panel"><div className="panel-heading compact"><div><div className="section-icon green"><Shield size={15} /></div><div><b>Run outcome</b><span>Evaluation signals</span></div></div></div>
              <div className="outcome-metrics"><div><span>TASK COMPLETE</span><b className={outcome ? (outcome.task_completed ? "positive" : "negative") : "muted"}>{outcome ? outcome.task_completed ? "Yes" : "No" : "—"}</b></div><div><span>ATTACK EXECUTED</span><b className={outcome?.attack_succeeded === true ? "negative" : outcome?.attack_succeeded === false ? "positive" : "muted"}>{outcome?.attack_succeeded === null || outcome?.attack_succeeded === undefined ? "—" : outcome.attack_succeeded ? "Yes" : "No"}</b></div></div>
              <div className="outcome-foot"><span><TerminalSquare size={14} />{outcome?.steps ?? "—"} steps</span><span><Database size={14} />{outcome?.model_calls ?? "—"} calls</span></div>
            </section>
            {outcome?.final_text && <section className="panel answer-panel"><div className="panel-heading compact"><b>Final response</b></div><p>{outcome.final_text}</p></section>}
          </aside>
        </div>
        <footer className="page-footer"><span><ShieldCheck size={13} /> All actions run in the local simulated inbox</span><span>CAUSAL EXCISION · RESEARCH BUILD</span></footer>
      </div> : <ResultsView data={results} onRefresh={() => fetch("/api/results").then((r) => r.json()).then(setResults)} />}
    </main>
  </div>;
}

function ResultsView({ data, onRefresh }: { data: ResultsData | null; onRefresh: () => void }) {
  const summary = data?.summary;
  const armValues = Object.entries(summary?.arms ?? {});
  return <div className="page-content results-page">
    <section className="page-heading"><div><div className="eyebrow"><BarChart3 size={13} /> EVALUATION SUMMARY</div><h1>Results<span className="heading-period">.</span></h1><p>Review saved runs across the available defense arms.</p></div><button className="refresh-button" onClick={onRefresh}><Activity size={14} />Refresh</button></section>
    {!data?.available || !summary ? <div className="panel empty-results"><div className="empty-icon"><BarChart3 size={22} /></div><h2>No saved evaluation results</h2><p>Run the evaluator to generate an honest summary from your current case set.</p><code>python eval.py --fake</code></div> : <>
      {summary.simulated && <div className="sim-banner results-sim"><FlaskConical size={13} /> SIMULATED — NOT REAL MODEL RESULTS</div>}
      {summary.mixed_modes && <div className="error-banner results-sim"><AlertTriangle size={14} /> Saved runs mix fake and real models. Separate run logs before interpreting these metrics.</div>}
      <section className="result-cards"><div className="panel result-stat"><span>TOTAL RUNS</span><b>{summary.total_runs}</b><small>Recorded evaluations</small></div><div className="panel result-stat"><span>DEFENSE ARMS</span><b>{armValues.length}</b><small>With saved results</small></div><div className="panel result-stat"><span>MODEL</span><b className="model-name">{summary.mixed_modes ? "Mixed modes" : summary.simulated ? "Fake model" : "Gemma"}</b><small>{summary.simulated ? "Simulated data" : summary.mixed_modes ? "Mixed model records" : "Latest recorded model"}</small></div></section>
      <section className="panel comparison-panel"><div className="panel-heading"><div><div className="section-icon violet"><BarChart3 size={16} /></div><div><b>Arm comparison</b><span>Rates from the saved run log</span></div></div><span className="table-note">{summary.total_runs} run records</span></div><div className="comparison-grid"><div className="metrics-chart">{armValues.map(([name, values]) => <div className="arm-card" key={name}><div className="arm-title"><b>{name}</b><span>{values.n_runs ?? 0} runs</span></div><MetricBar label="Attack success" value={values.asr} color="#fb7185" /><MetricBar label="Benign completion" value={values.benign_completion} color="#34d399" /><MetricBar label="Utility under attack" value={values.utility_under_attack} color="#a78bfa" /><MetricBar label="False intervention" value={values.false_intervention_rate} color="#fbbf24" /></div>)}</div></div></section>
      <div className="results-note"><CircleHelp size={14} /> Metrics are read from <code>results/runs.jsonl</code>. Separate model modes before comparing conclusions.</div>
    </>}
  </div>;
}
