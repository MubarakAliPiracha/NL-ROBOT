'use client';

import { useEffect, useState } from 'react';
import * as Tooltip from '@radix-ui/react-tooltip';
import { Hand, LocateFixed, MousePointer2, Move, Orbit, RotateCw, Scan, Trash2, type LucideIcon } from 'lucide-react';

export type Tool = 'select' | 'move' | 'rotate' | 'pan' | 'orbit';

/** One tool button with a real tooltip (label + shortcut in mono, below the bar).
 *  Adding a tool later is one <ToolButton> line. */
export function ToolButton({
  icon: Icon,
  label,
  shortcut,
  active,
  disabled,
  destructive,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  shortcut?: string;
  active?: boolean;
  disabled?: boolean;
  destructive?: boolean;
  onClick: () => void;
}) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>
        <button
          onClick={onClick}
          disabled={disabled}
          aria-label={shortcut ? `${label} (${shortcut})` : label}
          aria-pressed={active}
          className={`flex h-9 w-9 items-center justify-center rounded-lg border-b-2 transition focus-visible:outline focus-visible:outline-1 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-35 ${
            active
              ? 'border-brand bg-brand/15 text-brand'
              : destructive
                ? 'border-transparent text-fg hover:bg-danger/15 hover:text-danger'
                : 'border-transparent text-fg hover:bg-brand/10'
          }`}
        >
          <Icon size={18} />
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content
          side="bottom"
          sideOffset={6}
          className="z-30 flex items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg shadow-lift"
        >
          {label}
          {shortcut && <kbd className="rounded-sm bg-surfaceAlt px-1 py-0.5 text-[10px] text-muted">{shortcut}</kbd>}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

const Sep = () => <div className="mx-1 h-6 w-px bg-line" aria-hidden />;

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
  // Contextual onboarding: elevation is undiscoverable the first time the move
  // gizmo appears. Bottom-left, fades after a few seconds, never holds a slot.
  const [hint, setHint] = useState(false);
  const [hintUsed, setHintUsed] = useState(false);
  useEffect(() => {
    if (tool !== 'move' || hintUsed || !hasSelection) return;
    setHint(true);
    const timer = setTimeout(() => {
      setHint(false);
      setHintUsed(true);
    }, 4500);
    return () => clearTimeout(timer);
  }, [tool, hasSelection, hintUsed]);

  return (
    <Tooltip.Provider delayDuration={300}>
      <div className="pointer-events-none absolute left-1/2 top-3 z-10 -translate-x-1/2">
        <div className="pointer-events-auto flex items-center gap-0.5 rounded-xl border border-line bg-surface/95 p-1 shadow-lift backdrop-blur">
          {/* Transform */}
          <ToolButton icon={MousePointer2} label="Select" shortcut="Q" active={tool === 'select'} onClick={() => onTool('select')} />
          <ToolButton icon={Move} label="Move" shortcut="W" active={tool === 'move'} onClick={() => onTool('move')} />
          <ToolButton icon={RotateCw} label="Rotate" shortcut="E" active={tool === 'rotate'} onClick={() => onTool('rotate')} />
          <Sep />
          {/* Camera */}
          <ToolButton icon={Hand} label="Pan camera" shortcut="H" active={tool === 'pan'} onClick={() => onTool('pan')} />
          <ToolButton icon={Orbit} label="Orbit camera" shortcut="O" active={tool === 'orbit'} onClick={() => onTool('orbit')} />
          <Sep />
          {/* View */}
          <ToolButton icon={Scan} label="Fit scene" shortcut="F" onClick={onFit} />
          <ToolButton icon={LocateFixed} label="Follow the robot" shortcut="." active={follow} onClick={onFollow} />
          <Sep />
          {/* Destructive - isolated, red on hover */}
          <ToolButton icon={Trash2} label="Delete selected" shortcut="Del" destructive disabled={!canDelete} onClick={onDelete} />
        </div>
      </div>

      {hint && (
        <div className="pointer-events-none absolute bottom-4 left-4 z-10 rounded-md border border-line bg-surface/95 px-3 py-1.5 text-xs text-muted shadow backdrop-blur transition-opacity">
          <span className="text-brand">tip</span> drag the arrows to move — the up arrow sets elevation
        </div>
      )}
    </Tooltip.Provider>
  );
}
