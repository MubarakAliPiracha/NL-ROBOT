'use client';

import { useEffect, useRef } from 'react';
import type { RobotSnapshot } from '@/lib/use-robot-socket';
import type { RobotInfo } from '@/lib/api';

/** Live sensor readings plus the ROS commands the bridge is actually issuing —
 *  each entry is the exact CLI you could paste into a terminal yourself. */
export function ConsolePanel({ snapshot, robot }: { snapshot: RobotSnapshot; robot: RobotInfo | null }) {
  const logRef = useRef<HTMLDivElement>(null);
  const t = snapshot.telemetry;
  const log = snapshot.roslog ?? [];

  // Keep the log pinned to the newest entry.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log.length]);

  const row = (label: string, value: string) => (
    <div className="flex justify-between gap-2">
      <span className="text-muted">{label}</span>
      <span className="text-fg">{value}</span>
    </div>
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 text-xs">
      <section className="border border-line bg-surface p-3">
        <div className="mb-2 font-bold text-brand">── TELEMETRY ─────────────</div>
        {t?.odom ? (
          <div className="space-y-1">
            {row('odom.pos', `x ${t.odom.x.toFixed(2)}  y ${t.odom.y.toFixed(2)}  θ ${t.odom.yaw_deg.toFixed(0)}°`)}
            {row('odom.vel', `v ${t.odom.v.toFixed(2)} m/s   ω ${t.odom.w.toFixed(2)} rad/s`)}
            {t.lidar && row('lidar', `front ${t.lidar.front ?? '∞'}  min ${t.lidar.min ?? '∞'}  (${t.lidar.rays} rays, max ${t.lidar.range_max} m)`)}
            {t.imu && row('imu.accel', `${t.imu.ax} ${t.imu.ay} ${t.imu.az} m/s²`)}
            {t.imu && row('imu.gyro', `${t.imu.gx} ${t.imu.gy} ${t.imu.gz} rad/s`)}
          </div>
        ) : (
          <div className="text-muted">waiting for data…</div>
        )}
        <div className="mt-3 mb-1 font-bold text-brand">── JOINTS ────────────────</div>
        <div className="space-y-0.5">
          {Object.entries(snapshot.joints).map(([name, value]) => (
            <div key={name} className="flex justify-between">
              <span className="text-muted">{name}</span>
              <span className="text-fg">{value.toFixed(3)}</span>
            </div>
          ))}
        </div>
        {robot?.sensors && robot.sensors.length > 0 && (
          <>
            <div className="mt-3 mb-1 font-bold text-brand">── SENSORS (from URDF) ───</div>
            <div className="space-y-0.5">
              {robot.sensors.map((s) => (
                <div key={s.name} className="flex justify-between gap-2">
                  <span className="text-muted">{s.type}</span>
                  <span className="truncate text-fg">
                    {s.topic}
                    {s.rate_hz ? ` @ ${s.rate_hz} Hz` : ''}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="flex min-h-0 flex-1 flex-col border border-line bg-surface p-3">
        <div className="mb-2 font-bold text-brand">── ROS 2 COMMANDS ────────</div>
        <div ref={logRef} className="min-h-0 flex-1 space-y-1.5 overflow-y-auto">
          {log.length === 0 && <div className="text-muted">no commands issued yet — tell the robot something</div>}
          {log.map((entry, i) => (
            <div key={`${entry.t}-${i}`} className="break-all">
              <span className="text-brand">$ </span>
              <span className="text-fg/90">{entry.cmd}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
