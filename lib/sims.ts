'use client';

import { useCallback, useEffect, useState } from 'react';
import type { WorldObject } from '@/lib/world';

export type Sim = {
  id: string;
  name: string;
  robotSource: string; // 'default' or an upload id on the backend
  robotName: string;
  world?: WorldObject[];
  createdAt: number;
  updatedAt: number;
};

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

  const create = useCallback(() => {
    const now = Date.now();
    const sim: Sim = {
      id: Math.random().toString(36).slice(2, 10),
      name: `Simulation ${read().length + 1}`,
      robotSource: 'default',
      robotName: 'KUKA iiwa arm',
      createdAt: now,
      updatedAt: now,
    };
    write([sim, ...read()]);
    return sim;
  }, []);

  const update = useCallback(
    (id: string, patch: Partial<Omit<Sim, 'id'>>) => {
      commit(read().map((s) => (s.id === id ? { ...s, ...patch, updatedAt: Date.now() } : s)));
    },
    [commit],
  );

  const remove = useCallback((id: string) => commit(read().filter((s) => s.id !== id)), [commit]);

  return { sims, ready, create, update, remove };
}
