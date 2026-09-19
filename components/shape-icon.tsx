import { useId } from 'react';
import type { ShapeKind } from '@/lib/world';

/** Mix a #rrggbb colour toward white (t > 0) or black (t < 0). */
function shade(hex: string, t: number) {
  const n = parseInt(hex.slice(1), 16);
  const target = t < 0 ? 0 : 255;
  const k = Math.abs(t);
  const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => Math.round(c + (target - c) * k));
  return `rgb(${ch[0]},${ch[1]},${ch[2]})`;
}

export function ShapeIcon({ kind, color, size = 44 }: { kind: ShapeKind; color: string; size?: number }) {
  const gid = useId().replace(/:/g, '');
  const light = shade(color, 0.35);
  const mid = color;
  const dark = shade(color, -0.3);

  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <defs>
        <radialGradient id={`${gid}-s`} cx="35%" cy="30%" r="75%">
          <stop offset="0%" stopColor={shade(color, 0.55)} />
          <stop offset="55%" stopColor={mid} />
          <stop offset="100%" stopColor={dark} />
        </radialGradient>
        <linearGradient id={`${gid}-c`} x1="0" x2="1">
          <stop offset="0%" stopColor={dark} />
          <stop offset="45%" stopColor={light} />
          <stop offset="100%" stopColor={dark} />
        </linearGradient>
      </defs>
      <ellipse cx="24" cy="43" rx="14" ry="3" fill="rgba(0,0,0,0.14)" />
      {kind === 'box' && (
        <>
          <polygon points="24,6 41,14 24,22 7,14" fill={light} />
          <polygon points="7,14 24,22 24,42 7,34" fill={mid} />
          <polygon points="41,14 24,22 24,42 41,34" fill={dark} />
        </>
      )}
      {kind === 'cylinder' && (
        <>
          <path d="M9 12 V34 A15 6 0 0 0 39 34 V12 Z" fill={`url(#${gid}-c)`} />
          <ellipse cx="24" cy="12" rx="15" ry="6" fill={light} />
        </>
      )}
      {kind === 'sphere' && <circle cx="24" cy="24" r="17" fill={`url(#${gid}-s)`} />}
      {kind === 'cone' && (
        <>
          <path d="M24 5 L39 35 A15 6 0 0 1 9 35 Z" fill={`url(#${gid}-c)`} />
        </>
      )}
      {kind === 'pyramid' && (
        <>
          <polygon points="24,5 7,34 24,41" fill={mid} />
          <polygon points="24,5 41,34 24,41" fill={dark} />
          <polygon points="24,5 7,34 24,30 41,34" fill="none" />
        </>
      )}
      {kind === 'wedge' && (
        <>
          <polygon points="6,36 6,30 34,12 34,18" fill={light} />
          <polygon points="6,36 34,18 42,24 14,42" fill={mid} />
          <polygon points="34,12 42,18 42,24 34,18" fill={dark} />
          <polygon points="6,30 34,12 42,18 14,36" fill={light} opacity="0.5" />
        </>
      )}
    </svg>
  );
}
