'use client';

import type { RobotSnapshot } from '@/lib/use-robot-socket';

export type PlanStep = { primitive: string; params?: Record<string, unknown> };

/** The active plan as a live checklist: done, executing, queued.
 *
 * Status is derived client-side from the snapshot's queue depth — the executor pops one
 * step at a time, so for the most recent plan of N steps:
 *   remaining = queued, executing = active ? 1 : 0, done = N - remaining - executing.
 * (If a second plan is queued behind this one the math skews conservative; acceptable.)
 */
export function PlanSteps({ steps, snapshot }: { steps: PlanStep[]; snapshot: RobotSnapshot }) {
  if (!steps.length) return null;

  const remaining = Math.min(snapshot.queued, steps.length);
  const executing = snapshot.active && remaining < steps.length ? 1 : 0;
  const done = Math.max(0, steps.length - remaining - executing);
  const finished = !snapshot.active && snapshot.queued === 0;

  const stateOf = (i: number): 'done' | 'executing' | 'queued' => {
    if (finished || i < done) return 'done';
    if (executing && i === done) return 'executing';
    return 'queued';
  };

  const dot = {
    done: 'bg-brand',
    executing: 'bg-warn animate-pulse',
    queued: 'bg-line',
  } as const;

  const fmt = (params?: Record<string, unknown>) => {
    const entries = Object.entries(params ?? {}).filter(([, v]) => typeof v !== 'object');
    if (!entries.length) return '';
    return entries.map(([k, v]) => `${k}=${typeof v === 'number' ? +Number(v).toFixed(2) : v}`).join('  ');
  };

  return (
    <div className="border border-line bg-surfaceAlt p-2.5">
      <div className="mb-1.5 text-[11px] font-bold uppercase tracking-widest text-muted">
        plan · {done + executing}/{steps.length}
      </div>
      <div className="space-y-1">
        {steps.map((s, i) => {
          const st = stateOf(i);
          return (
            <div
              key={i}
              className="plan-row flex items-center gap-2 text-xs"
              style={{ animationDelay: `${Math.min(i * 60, 400)}ms` }}
            >
              <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot[st]}`} />
              <span className={st === 'queued' ? 'text-muted' : 'text-fg'}>{s.primitive}</span>
              <span className="truncate text-muted">{fmt(s.params)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
