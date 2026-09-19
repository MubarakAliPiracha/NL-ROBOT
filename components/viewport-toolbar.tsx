'use client';

import { Hand, LocateFixed, MousePointer2, Move, Orbit, RotateCw, Scan, Trash2, type LucideIcon } from 'lucide-react';

export type Tool = 'select' | 'move' | 'rotate' | 'pan' | 'orbit';

const TOOLS: { key: Tool; label: string; hotkey: string; icon: LucideIcon; hint: string }[] = [
  { key: 'select', label: 'Select', hotkey: 'V', icon: MousePointer2, hint: 'Click a shape to select it, drag it to slide it around the floor' },
  { key: 'move', label: 'Move', hotkey: 'M', icon: Move, hint: 'Select a shape, then drag the arrows (up arrow = elevation)' },
  { key: 'rotate', label: 'Rotate', hotkey: 'R', icon: RotateCw, hint: 'Select a shape, then drag the ring to turn it' },
  { key: 'pan', label: 'Pan', hotkey: 'H', icon: Hand, hint: 'Drag to slide the view sideways' },
  { key: 'orbit', label: 'Orbit', hotkey: 'O', icon: Orbit, hint: 'Drag to look around the scene' },
];

function Btn({
  active,
  disabled,
  title,
  onClick,
  children,
}: {
  active?: boolean;
  disabled?: boolean;
  title: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      aria-pressed={active}
      className={`flex h-9 w-9 items-center justify-center rounded-lg transition disabled:cursor-not-allowed disabled:opacity-35 ${
        active ? 'bg-brand text-white shadow' : 'text-fg hover:bg-brand/10'
      }`}
    >
      {children}
    </button>
  );
}

export function ViewportToolbar({
  tool,
  onTool,
  follow,
  onFollow,
  onFit,
  canDelete,
  onDelete,
  hasSelection,
}: {
  tool: Tool;
  onTool: (t: Tool) => void;
  follow: boolean;
  onFollow: () => void;
  onFit: () => void;
  canDelete: boolean;
  onDelete: () => void;
  hasSelection: boolean;
}) {
  const current = TOOLS.find((t) => t.key === tool)!;
  const needsSelection = (tool === 'move' || tool === 'rotate') && !hasSelection;
  return (
    <div className="pointer-events-none absolute left-1/2 top-3 z-10 flex -translate-x-1/2 flex-col items-center gap-1.5">
      <div className="pointer-events-auto flex items-center gap-0.5 rounded-xl border border-line bg-surface/95 p-1 shadow-lift backdrop-blur">
        {TOOLS.map(({ key, label, hotkey, icon: Icon }) => (
          <Btn key={key} active={tool === key} title={`${label} (${hotkey})`} onClick={() => onTool(key)}>
            <Icon size={18} />
          </Btn>
        ))}
        <div className="mx-1 h-6 w-px bg-line" />
        <Btn title="Fit view (F)" onClick={onFit}>
          <Scan size={18} />
        </Btn>
        <Btn active={follow} title="Follow the robot" onClick={onFollow}>
          <LocateFixed size={18} />
        </Btn>
        <div className="mx-1 h-6 w-px bg-line" />
        <Btn title="Delete selected (Del)" disabled={!canDelete} onClick={onDelete}>
          <Trash2 size={18} />
        </Btn>
      </div>
      <div className="pointer-events-none rounded-full bg-surface/90 px-3 py-1 text-[11px] font-medium text-muted shadow backdrop-blur">
        {needsSelection ? `${current.label}: click a shape first` : current.hint}
      </div>
    </div>
  );
}
