import { BACKEND_URL } from '@/lib/config';
import type { WorldObject } from '@/lib/world';

export type JointInfo = {
  index: number;
  name: string;
  type: 'revolute' | 'prismatic' | 'continuous' | 'fixed' | string;
  lower_limit: number | null;
  upper_limit: number | null;
};

export type SensorInfo = {
  name: string;
  type: string;
  link: string;
  topic: string;
  rate_hz?: number;
  range_m?: [number, number];
  samples?: number;
};

export type RobotInfo = {
  source: string;
  name: string;
  urdf_url: string;
  root_url: string;
  joints: JointInfo[];
  mobile: boolean;
  wheels: string[];
  sensors?: SensorInfo[];
  scale?: { unit_m: number; spawn_x: number; factor: number };
  warnings?: string[];
};

export type Health = { ok: boolean; ollama: boolean; model: string; robot: RobotInfo };

export type CommandResult = {
  ok: boolean;
  source: string;
  reply: string | null;
  plan: Record<string, unknown>[];
  repeat: boolean;
  world: WorldObject[] | null;
  warnings: string[];
  llm: { provider: string | null; model: string | null };
  llm_error: string | null;
  path?: [number, number][];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BACKEND_URL + path, init);
  } catch {
    throw new Error('Backend is offline. Start it with "npm run backend".');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'content-type': 'application/json' },
  body: JSON.stringify(body),
});

export const api = {
  health: () => request<Health>('/api/health'),
  selectRobot: (source: string) => request<RobotInfo>('/api/robot/select', json({ source })),
  uploadRobot: (files: File[]) => {
    const form = new FormData();
    for (const f of files) {
      const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath;
      form.append('files', f, rel || f.name);
    }
    return request<RobotInfo>('/api/robot/upload', { method: 'POST', body: form });
  },
  resetRobot: () => request<RobotInfo>('/api/robot/reset', { method: 'POST' }),
  command: (text: string, mode: 'robot' | 'map' = 'robot') => request<CommandResult>('/api/command', json({ text, mode })),
  setWorld: (objects: WorldObject[]) => request<{ ok: boolean }>('/api/world', { ...json({ objects }), method: 'PUT' }),
  stop: () => request<{ ok: boolean }>('/api/stop', { method: 'POST' }),
};
