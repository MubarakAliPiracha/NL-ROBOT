'use client';

import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { NlLogoFull } from '@/components/ui/nl-logo';

const LINES = ['mounting workcell', 'loading urdf parser', 'connecting planner', 'ready'];
const LINE_MS = 240;
const HOLD_MS = 260;
const KEY = 'nlr:splash-shown';

/** First-load splash. The landing page stays mounted underneath; this overlay
 *  fades away, so there is never a flash of empty background. Any click or key
 *  dismisses it. Set NEXT_PUBLIC_NO_SPLASH=1 to disable during development. */
export function SplashScreen() {
  const reduced = useReducedMotion();
  const [show, setShow] = useState(false);
  const [step, setStep] = useState(0);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    if (process.env.NEXT_PUBLIC_NO_SPLASH === '1') return;
    if (sessionStorage.getItem(KEY)) return;
    sessionStorage.setItem(KEY, '1');
    setShow(true);

    const dismiss = () => setShow(false);
    if (reduced) {
      // Reduced motion: final state, briefly, then out.
      setStep(LINES.length);
      timers.current.push(setTimeout(dismiss, 500));
    } else {
      LINES.forEach((_, i) =>
        timers.current.push(setTimeout(() => setStep(i + 1), LINE_MS * (i + 1))),
      );
      timers.current.push(setTimeout(dismiss, LINE_MS * LINES.length + HOLD_MS));
    }

    window.addEventListener('pointerdown', dismiss);
    window.addEventListener('keydown', dismiss);
    return () => {
      timers.current.forEach(clearTimeout);
      window.removeEventListener('pointerdown', dismiss);
      window.removeEventListener('keydown', dismiss);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const done = step >= LINES.length;

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          key="splash"
          initial={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.3 } }}
          className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-8 overflow-hidden bg-app"
          aria-hidden
        >
          {/* The logo's own circle is the ring; the glow pulses while booting,
              then settles on "ready". No extra enclosure. */}
          <motion.div
            animate={
              done || reduced
                ? { opacity: 1, scale: 1 }
                : { opacity: [0.75, 1, 0.75], scale: [0.99, 1, 0.99] }
            }
            transition={done || reduced ? { duration: 0.25 } : { duration: 1.1, repeat: Infinity }}
          >
            <NlLogoFull className="w-56 text-brand drop-shadow-[0_0_28px_rgba(62,207,142,0.45)]" />
          </motion.div>

          <div className="w-[320px] border border-line bg-surface">
            <div className="flex items-center gap-1.5 border-b border-line px-3 py-2">
              <span className="h-2 w-2 rounded-full bg-danger/70" />
              <span className="h-2 w-2 rounded-full bg-warn/70" />
              <span className="h-2 w-2 rounded-full bg-brand/70" />
              <span className="ml-2 text-[10px] font-bold tracking-widest text-muted">NL-ROBOT.SH</span>
            </div>
            <div className="min-h-[104px] px-3 py-2.5 text-xs">
              {LINES.slice(0, step).map((line, i) => (
                <div key={line} className="leading-5">
                  <span className="text-brand">$ →</span>{' '}
                  <span className={line === 'ready' ? 'font-bold text-brand' : 'text-fg'}>{line}</span>
                  {i === step - 1 && <span className="cursor-blink" />}
                </div>
              ))}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
