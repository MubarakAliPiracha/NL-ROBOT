'use client';

import { useEffect, useRef, useState } from 'react';

/* The hero: a replay of a real run, typed out in a terminal window.
 *
 * This transcript is not staged - it is the verified wall-follow demo (the robot
 * stopped 0.4 m from the wall and turned; odometry confirmed it). Replaying a real
 * transcript beats a scripted 3D vignette: the actual simulator is one click away,
 * and a canned canvas next to a real one invites "is that real?".
 *
 * prefers-reduced-motion: the finished frame renders immediately, no typing loop. */

const COMMAND = 'drive forward until you see the wall, then turn left';
const STEPS = [
  { text: 'face  x=1.8 y=0', done: true },
  { text: 'drive  until_front_within=0.4', done: true },
  { text: 'turn  angle=+90°', done: true },
];
const RESULT = 'odom  x 1.42 m  θ +90°   ✓ verified on /odom';

const TYPE_MS = 34;
const STEP_MS = 420;
const LOOP_PAUSE_MS = 3600;

export function HeroReplay() {
  const [chars, setChars] = useState(0);
  const [steps, setSteps] = useState(0);
  const [showResult, setShowResult] = useState(false);
  const [reduced, setReduced] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (mq.matches) {
      setReduced(true);
      setChars(COMMAND.length);
      setSteps(STEPS.length);
      setShowResult(true);
      return;
    }

    let cancelled = false;
    const t = (fn: () => void, ms: number) => timers.current.push(setTimeout(fn, ms));

    const cycle = () => {
      if (cancelled) return;
      setChars(0);
      setSteps(0);
      setShowResult(false);
      for (let i = 1; i <= COMMAND.length; i++) t(() => setChars(i), 300 + i * TYPE_MS);
      const typed = 300 + COMMAND.length * TYPE_MS;
      STEPS.forEach((_, i) => t(() => setSteps(i + 1), typed + STEP_MS * (i + 1)));
      const stepsDone = typed + STEP_MS * (STEPS.length + 1);
      t(() => setShowResult(true), stepsDone);
      t(cycle, stepsDone + LOOP_PAUSE_MS);
    };
    cycle();
    return () => {
      cancelled = true;
      timers.current.forEach(clearTimeout);
    };
  }, []);

  return (
    <div className="w-full max-w-md border border-line bg-app text-xs shadow-lift">
      <div className="flex items-center gap-1.5 border-b border-line px-3 py-2">
        <span className="h-2 w-2 rounded-full bg-danger/70" />
        <span className="h-2 w-2 rounded-full bg-warn/70" />
        <span className="h-2 w-2 rounded-full bg-brand/70" />
        <span className="ml-2 text-[10px] font-bold tracking-widest text-muted">LIVE RUN — GAZEBO</span>
      </div>
      <div className="min-h-[148px] px-3.5 py-3 leading-6">
        <div>
          <span className="text-brand">$ </span>
          <span className="text-fg">{COMMAND.slice(0, chars)}</span>
          {!reduced && chars < COMMAND.length && <span className="cursor-blink" />}
        </div>
        {steps > 0 && (
          <div className="mt-1 text-muted">
            plan <span className="text-fg">{steps}</span>/{STEPS.length}
          </div>
        )}
        {STEPS.slice(0, steps).map((s) => (
          <div key={s.text}>
            <span className="text-brand">{'✓'} </span>
            <span className="text-fg/90">{s.text}</span>
          </div>
        ))}
        {showResult && <div className="mt-1 font-bold text-brand">{RESULT}</div>}
      </div>
    </div>
  );
}
