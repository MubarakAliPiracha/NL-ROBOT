'use client';

import { useCallback, useEffect, useState } from 'react';
import type { WorldObject } from '@/lib/world';

export type Sim = {
  id: string;
  name: string;
  robotSource: string; // 'default' or an upload id on the backend
  robotName: string;
  world?: WorldObject[];
  /** Command to send automatically when the workspace opens (example chips). */
  pendingCommand?: string;
  /** True once the sim has been auto-named from its first command. */
  named?: boolean;
  /** Downscaled JPEG data-URL snapshot of the viewport. */
  thumb?: string;
  createdAt: number;
  updatedAt: number;
};

export type SimPreset = Partial<Pick<Sim, 'name' | 'world' | 'pendingCommand' | 'named'>>;

const KEY = 'nl-robot:sims';

function read(): Sim[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Sim[]) : [];
  } catch {
    return [];
  }
}

function write(sims: Sim[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(sims));
  } catch {
    /* storage unavailable: state still lives in memory for this session */
  }
}

export function useSims() {
  const [sims, setSims] = useState<Sim[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setSims(read());
    setReady(true);
  }, []);

  const commit = useCallback((next: Sim[]) => {
    setSims(next);
    write(next);
  }, []);

  const create = useCallback((preset?: SimPreset) => {
    const now = Date.now();
    const sim: Sim = {
      id: Math.random().toString(36).slice(2, 10),
      name: preset?.name ?? `Simulation ${read().length + 1}`,
      robotSource: 'default',
      robotName: 'TurtleBot3 + arm',
      ...preset,
      createdAt: now,
      updatedAt: now,
    };
    write([sim, ...read()]);
    return sim;
  }, []);

  const duplicate = useCallback((id: string) => {
    const source = read().find((s) => s.id === id);
    if (!source) return null;
    const now = Date.now();
    const copy: Sim = { ...source, id: Math.random().toString(36).slice(2, 10),
      name: `${source.name} copy`, pendingCommand: undefined, createdAt: now, updatedAt: now };
    write([copy, ...read()]);
    return copy;
  }, []);

  const update = useCallback(
    (id: string, patch: Partial<Omit<Sim, 'id'>>) => {
      commit(read().map((s) => (s.id === id ? { ...s, ...patch, updatedAt: Date.now() } : s)));
    },
    [commit],
  );

  const remove = useCallback((id: string) => commit(read().filter((s) => s.id !== id)), [commit]);

  return { sims, ready, create, duplicate, update, remove };
}
