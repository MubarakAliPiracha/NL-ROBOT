'use client';

import { useEffect, useRef, useState } from 'react';
import { BACKEND_WS_URL } from '@/lib/config';

export type SensorScan = {
  origin: [number, number, number];
  yaw: number;
  a0: number;
  da: number;
  range: number;
  dist: number[];
  front: number;
};

export type Telemetry = {
  odom?: { x: number; y: number; yaw_deg: number; v: number; w: number };
  imu?: { ax: number; ay: number; az: number; gx: number; gy: number; gz: number };
  lidar?: { front: number | null; min: number | null; rays: number; range_max: number };
};

export type RosLogEntry = { t: number; kind: string; cmd: string };

export type RobotSnapshot = {
  joints: Record<string, number>;
  queued: number;
  active: boolean;
  base?: { pos: [number, number, number]; quat: [number, number, number, number] };
  sensor?: SensorScan;
  objects?: Record<string, number[]>;
  telemetry?: Telemetry;
  roslog?: RosLogEntry[];
};

/**
 * Streams joint state from the backend. The latest frame lives in a ref so the
 * 3D scene can read it every render frame; `snapshot` is a throttled copy for UI.
 */
export function useRobotSocket() {
  const latest = useRef<RobotSnapshot>({ joints: {}, queued: 0, active: false });
  const [snapshot, setSnapshot] = useState<RobotSnapshot>(latest.current);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;

    const connect = () => {
      ws = new WebSocket(BACKEND_WS_URL);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (ev) => {
        try {
          latest.current = JSON.parse(ev.data) as RobotSnapshot;
        } catch {
          /* ignore malformed frame */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 1500);
      };
      ws.onerror = () => ws?.close();
    };
    connect();

    const ui = setInterval(() => setSnapshot(latest.current), 100);
    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(ui);
      ws?.close();
    };
  }, []);

  return { latest, snapshot, connected };
}
