import React from 'react';

/* Vector reinterpretation of the NL-Robot mark: a circle enclosing a mechanical R
 * with a power glyph in the bowl and an articulated gripper arm where the R's leg
 * would be. Everything strokes currentColor so it inherits the accent.
 *
 * Two variants:
 *   NlLogoFull - circuit traces, node dots and rim chevrons. Splash only.
 *   NlLogoMark - circle + R + arm, heavier strokes. Header / favicon; stays
 *                legible below 48px where the full detail turns to mud.
 */

function ArmAndR({ strokeWidth }: { strokeWidth: number }) {
  return (
    <g fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      {/* R stem + bowl */}
      <path d="M34 27 V73" />
      <path d="M34 27 H51 Q64 27 64 38.5 Q64 50 51 50 H34" />
      {/* power glyph in the bowl */}
      <path d="M44.5 32 V37.5" strokeWidth={strokeWidth * 0.75} />
      <path d="M41 33.5 A6 6 0 1 0 48 33.5" strokeWidth={strokeWidth * 0.75} />
      {/* articulated arm: shoulder -> elbow -> wrist -> gripper */}
      <circle cx="46" cy="55" r="4.6" />
      <path d="M49.5 58 L60 67" />
      <circle cx="62" cy="68.5" r="3.4" />
      <path d="M64.5 70.5 L71 75.5" />
      <circle cx="72.5" cy="76.5" r="2.2" />
      <path d="M74.5 75.5 L79 73.5 L81.5 76.5" strokeWidth={strokeWidth * 0.8} />
      <path d="M74.5 78.5 L78 82 L76 85" strokeWidth={strokeWidth * 0.8} />
    </g>
  );
}

export function NlLogoFull({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} role="img" aria-label="NL-Robot">
      <g fill="none" stroke="currentColor" strokeWidth={4.5} strokeLinecap="round" strokeLinejoin="round">
        <circle cx="50" cy="50" r="44" />
        {/* circuit traces along the inner rim, with node dots */}
        <path d="M20 38 Q17 50 20 62" strokeWidth={2} />
        <path d="M80 32 Q84 44 82 54" strokeWidth={2} />
        <path d="M38 84 Q50 88 62 85" strokeWidth={2} />
        <path d="M70 22 Q78 28 82 36" strokeWidth={2} />
      </g>
      <g fill="currentColor" stroke="none">
        <circle cx="20" cy="38" r="1.8" />
        <circle cx="20" cy="62" r="1.8" />
        <circle cx="80" cy="32" r="1.8" />
        <circle cx="82" cy="54" r="1.8" />
        <circle cx="38" cy="84" r="1.8" />
        <circle cx="70" cy="22" r="1.8" />
        <circle cx="28" cy="60" r="1.6" />
        <circle cx="28" cy="66" r="1.6" />
        {/* rim chevrons */}
        <path d="M13.5 47 L17.5 50 L13.5 53 Z" />
        <path d="M86.5 47 L82.5 50 L86.5 53 Z" />
        <path d="M47 90.5 L50 86.5 L53 90.5 Z" />
      </g>
      <ArmAndR strokeWidth={4.5} />
    </svg>
  );
}

export function NlLogoMark({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className} role="img" aria-label="NL-Robot">
      <circle cx="50" cy="50" r="44" fill="none" stroke="currentColor" strokeWidth={6} />
      <ArmAndR strokeWidth={6} />
    </svg>
  );
}
