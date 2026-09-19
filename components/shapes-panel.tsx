'use client';

import { useEffect, useState } from 'react';
import { Copy, Trash2 } from 'lucide-react';
import { ShapeIcon } from '@/components/shape-icon';
import { SHAPES, dimMode, newObject, withDims, type WorldObject } from '@/lib/world';

const fmt = (v: number) => String(Math.round(v * 1000) / 1000);

/** Numeric input you can type into freely; commits any valid number >= min as you type. */
function NumField({
  label,
  value,
  onChange,
  unit = 'm',
  step = 0.1,
  min = -Infinity,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  unit?: string;
  step?: number;
  min?: number;
}) {
  const [text, setText] = useState(fmt(value));

  // Follow external changes (e.g. dragging the shape in the viewport) without fighting the cursor.
  useEffect(() => {
    if (parseFloat(text) !== value) setText(fmt(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold text-muted">{label}</span>
      <div className="flex items-center rounded-lg border border-line bg-surface focus-within:border-brand">
        <input
          value={text}
          inputMode="decimal"
          onChange={(e) => {
            setText(e.target.value);
            const n = parseFloat(e.target.value);
            if (Number.isFinite(n) && n >= min) onChange(n);
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
              e.preventDefault();
              const n = Math.max(min, Math.round((value + (e.key === 'ArrowUp' ? step : -step)) * 1000) / 1000);
              setText(fmt(n));
              onChange(n);
            }
          }}
          onBlur={() => setText(fmt(value))}
          className="w-full min-w-0 bg-transparent px-2 py-1.5 text-sm tabular-nums outline-none"
        />
        <span className="pr-2 text-[11px] text-muted">{unit}</span>
      </div>
    </label>
  );
}

const MIN_SIZE = 0.02;

export function ShapesPanel({
  objects,
  selectedId,
  onAdd,
  onChange,
  onDelete,
  onSelect,
}: {
  objects: WorldObject[];
  selectedId: string | null;
  onAdd: (o: WorldObject) => void;
  onChange: (o: WorldObject) => void;
  onDelete: (id: string) => void;
  onSelect: (id: string | null) => void;
}) {
  const selected = objects.find((o) => o.id === selectedId) ?? null;
  const mode = selected ? dimMode(selected.kind) : 'wdh';
  const set = (patch: Partial<WorldObject>) => selected && onChange({ ...selected, ...patch });
  const setDims = (patch: Partial<Pick<WorldObject, 'w' | 'd' | 'h'>>) => selected && onChange(withDims(selected, patch));

  return (
    <div className="space-y-5">
      <section>
        <h2 className="mb-2 text-xs font-bold uppercase tracking-widest text-brand">Shapes</h2>
        <div className="grid grid-cols-3 gap-2">
          {SHAPES.map((def) => (
            <button
              key={def.label}
              onClick={() => onAdd(newObject(def, objects))}
              className="flex flex-col items-center rounded-xl border border-line bg-surfaceAlt px-1 pb-1.5 pt-2 text-xs font-semibold transition hover:-translate-y-0.5 hover:border-brand hover:shadow-card"
            >
              <ShapeIcon kind={def.kind} color={def.color} />
              <span className="mt-1">{def.label}</span>
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">
          Click a shape to drop it in front of the robot, drag it around the floor, then type exact sizes below. The robot
          starts at the origin facing the red axis (+X).
        </p>
      </section>

      {selected && (
        <section className="rounded-xl border-2 border-brand/40 bg-brand/5 p-3">
          <div className="mb-3 flex items-center gap-2">
            <input
              value={selected.name}
              onChange={(e) => set({ name: e.target.value })}
              aria-label="Object name"
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm font-semibold outline-none focus:border-brand"
            />
            <input
              type="color"
              value={selected.color}
              onChange={(e) => set({ color: e.target.value })}
              aria-label="Colour"
              className="h-8 w-9 cursor-pointer rounded-lg border border-line bg-surface p-0.5"
            />
          </div>

          <div className="mb-1 text-[11px] font-bold uppercase tracking-widest text-muted">Size</div>
          <div className="mb-3 grid grid-cols-3 gap-2">
            {mode === 'wdh' && (
              <>
                <NumField label="Width (X)" value={selected.w} min={MIN_SIZE} onChange={(v) => setDims({ w: v })} />
                <NumField label="Depth (Y)" value={selected.d} min={MIN_SIZE} onChange={(v) => setDims({ d: v })} />
                <NumField label="Height (Z)" value={selected.h} min={MIN_SIZE} onChange={(v) => setDims({ h: v })} />
              </>
            )}
            {mode === 'round' && (
              <>
                <NumField label="Diameter" value={selected.w} min={MIN_SIZE} onChange={(v) => setDims({ w: v })} />
                <NumField label="Height (Z)" value={selected.h} min={MIN_SIZE} onChange={(v) => setDims({ h: v })} />
              </>
            )}
            {mode === 'sphere' && (
              <NumField label="Diameter" value={selected.w} min={MIN_SIZE} onChange={(v) => setDims({ w: v })} />
            )}
          </div>

          <div className="mb-1 text-[11px] font-bold uppercase tracking-widest text-muted">Position</div>
          <div className="mb-3 grid grid-cols-3 gap-2">
            <NumField label="X" value={selected.x} onChange={(v) => set({ x: v })} />
            <NumField label="Y" value={selected.y} onChange={(v) => set({ y: v })} />
            <NumField label="Elevation" value={selected.z} min={0} onChange={(v) => set({ z: v })} />
          </div>
          <div className="mb-3 grid grid-cols-3 gap-2">
            <NumField label="Rotation" unit="°" step={15} value={selected.yaw} onChange={(v) => set({ yaw: v })} />
          </div>

          <div className="flex gap-2">
            <button
              onClick={() =>
                onAdd({
                  ...selected,
                  id: Math.random().toString(36).slice(2, 9),
                  name: `${selected.name} copy`,
                  x: selected.x + 0.5,
                  y: selected.y + 0.5,
                })
              }
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-semibold hover:border-brand"
            >
              <Copy size={14} /> Duplicate
            </button>
            <button
              onClick={() => onDelete(selected.id)}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-danger px-3 py-1.5 text-sm font-semibold text-white hover:brightness-110"
            >
              <Trash2 size={14} /> Delete
            </button>
          </div>
        </section>
      )}

      <section>
        <h2 className="mb-2 text-xs font-bold uppercase tracking-widest text-brand">In this world ({objects.length})</h2>
        {!objects.length && <p className="text-xs text-muted">Nothing yet. Add a shape above to build an obstacle course.</p>}
        <ul className="space-y-1.5">
          {objects.map((o) => (
            <li key={o.id}>
              <button
                onClick={() => onSelect(o.id)}
                className={`flex w-full items-center gap-2 rounded-lg border px-2 py-1.5 text-left text-sm transition ${
                  o.id === selectedId ? 'border-brand bg-brand/10' : 'border-line bg-surfaceAlt hover:border-brand/50'
                }`}
              >
                <ShapeIcon kind={o.kind} color={o.color} size={24} />
                <span className="min-w-0 flex-1 truncate">{o.name}</span>
                <span className="text-[11px] tabular-nums text-muted">
                  {fmt(o.x)}, {fmt(o.y)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
