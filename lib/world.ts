// User-built world objects. Coordinates are Z-up metres, matching the URDF / PyBullet frame:
// the robot starts at the origin facing +X. `z` is the elevation of an object's bottom face.

export type ShapeKind = 'box' | 'cylinder' | 'sphere' | 'cone' | 'pyramid' | 'wedge';

export type WorldObject = {
  id: string;
  kind: ShapeKind;
  name: string;
  x: number;
  y: number;
  z: number;
  w: number;
  d: number;
  h: number;
  yaw: number; // degrees
  color: string;
  dynamic?: boolean;
};

/** Which dimension fields a shape exposes, and how they are tied together. */
export type DimMode = 'wdh' | 'round' | 'sphere';

export type ShapeDef = {
  kind: ShapeKind;
  label: string;
  color: string;
  size: [number, number, number];
  dims: DimMode;
  preset?: string;
};

export const SHAPES: ShapeDef[] = [
  { kind: 'box', label: 'Box', color: '#64748b', size: [1, 1, 1], dims: 'wdh' },
  { kind: 'cylinder', label: 'Cylinder', color: '#7d8b99', size: [1, 1, 1], dims: 'round' },
  { kind: 'sphere', label: 'Sphere', color: '#566a7f', size: [1, 1, 1], dims: 'sphere' },
  { kind: 'cone', label: 'Cone', color: '#6e7f8d', size: [1, 1, 1], dims: 'round' },
  { kind: 'pyramid', label: 'Pyramid', color: '#8494a3', size: [1, 1, 1], dims: 'wdh' },
  { kind: 'wedge', label: 'Ramp', color: '#5b6c7d', size: [1.5, 1, 0.6], dims: 'wdh' },
  { kind: 'box', label: 'Wall', color: '#8a94a6', size: [0.2, 3, 1], dims: 'wdh', preset: 'wall' },
];

export const dimMode = (kind: ShapeKind): DimMode =>
  kind === 'sphere' ? 'sphere' : kind === 'cylinder' || kind === 'cone' ? 'round' : 'wdh';

const SPAWN_Y = [0, 1.5, -1.5, 3, -3];

export type RobotScale = { unit_m: number; spawn_x: number; factor: number };

/** Default shape sizes are for a 0.4 m-wide rover; `scale` grows or shrinks them (and their spawn spot) for the loaded robot. */
export function newObject(def: ShapeDef, existing: WorldObject[], scale?: RobotScale): WorldObject {
  const n = existing.length;
  const f = Math.max(0.3, Math.min(15, scale?.factor ?? 1));
  const sz = (v: number) => Math.max(0.02, Math.round(v * f * 100) / 100);
  const [w, d, h] = def.size.map(sz);
  const sameName = existing.filter((o) => o.name.startsWith(def.label)).length;
  return {
    id: Math.random().toString(36).slice(2, 9),
    kind: def.kind,
    name: sameName ? `${def.label} ${sameName + 1}` : def.label,
    // Drop new shapes in front of the robot, fanning out sideways so they don't overlap.
    x: (scale?.spawn_x ?? 2) + Math.floor(n / SPAWN_Y.length) * 1.5 * f,
    y: SPAWN_Y[n % SPAWN_Y.length] * f,
    z: 0,
    w,
    d,
    h,
    yaw: 0,
    color: def.color,
  };
}

/** Apply a dimension edit while keeping round shapes round. */
export function withDims(obj: WorldObject, patch: Partial<Pick<WorldObject, 'w' | 'd' | 'h'>>): WorldObject {
  const next = { ...obj, ...patch };
  const mode = dimMode(obj.kind);
  if (mode === 'sphere') {
    const s = patch.w ?? patch.d ?? patch.h ?? obj.w;
    return { ...next, w: s, d: s, h: s };
  }
  if (mode === 'round') {
    const s = patch.w ?? patch.d ?? obj.w;
    return { ...next, w: s, d: s };
  }
  return next;
}

const CONE_SEGMENTS = 32;

/** Convex-hull vertices for cone / pyramid / wedge. Must match hull_points in backend/world.py. */
export function hullPoints(kind: ShapeKind, w: number, d: number, h: number): [number, number, number][] {
  if (kind === 'cone') {
    const ring: [number, number, number][] = [];
    for (let i = 0; i < CONE_SEGMENTS; i++) {
      const a = (2 * Math.PI * i) / CONE_SEGMENTS;
      ring.push([(w / 2) * Math.cos(a), (d / 2) * Math.sin(a), -h / 2]);
    }
    return [...ring, [0, 0, h / 2]];
  }
  if (kind === 'pyramid') {
    return [
      [-w / 2, -d / 2, -h / 2],
      [w / 2, -d / 2, -h / 2],
      [w / 2, d / 2, -h / 2],
      [-w / 2, d / 2, -h / 2],
      [0, 0, h / 2],
    ];
  }
  // wedge: ramp rising toward +x
  return [
    [-w / 2, -d / 2, -h / 2],
    [w / 2, -d / 2, -h / 2],
    [w / 2, -d / 2, h / 2],
    [-w / 2, d / 2, -h / 2],
    [w / 2, d / 2, -h / 2],
    [w / 2, d / 2, h / 2],
  ];
}
