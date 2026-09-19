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
  { kind: 'box', label: 'Box', color: '#e5403b', size: [1, 1, 1], dims: 'wdh' },
  { kind: 'cylinder', label: 'Cylinder', color: '#f28c1b', size: [1, 1, 1], dims: 'round' },
  { kind: 'sphere', label: 'Sphere', color: '#2f8de4', size: [1, 1, 1], dims: 'sphere' },
  { kind: 'cone', label: 'Cone', color: '#8e44c2', size: [1, 1, 1], dims: 'round' },
  { kind: 'pyramid', label: 'Pyramid', color: '#f2c21b', size: [1, 1, 1], dims: 'wdh' },
  { kind: 'wedge', label: 'Ramp', color: '#3aa655', size: [1.5, 1, 0.6], dims: 'wdh' },
  { kind: 'box', label: 'Wall', color: '#ff8a5c', size: [0.2, 3, 1], dims: 'wdh', preset: 'wall' },
];

export const dimMode = (kind: ShapeKind): DimMode =>
  kind === 'sphere' ? 'sphere' : kind === 'cylinder' || kind === 'cone' ? 'round' : 'wdh';

const SPAWN_Y = [0, 1.5, -1.5, 3, -3];

export function newObject(def: ShapeDef, existing: WorldObject[]): WorldObject {
  const n = existing.length;
  const [w, d, h] = def.size;
  const sameName = existing.filter((o) => o.name.startsWith(def.label)).length;
  return {
    id: Math.random().toString(36).slice(2, 9),
    kind: def.kind,
    name: sameName ? `${def.label} ${sameName + 1}` : def.label,
    // Drop new shapes in front of the robot, fanning out sideways so they don't overlap.
    x: 2 + Math.floor(n / SPAWN_Y.length) * 1.5,
    y: SPAWN_Y[n % SPAWN_Y.length],
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
