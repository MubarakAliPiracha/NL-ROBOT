import type { WorldObject } from '@/lib/world';
import type { SimPreset } from '@/lib/sims';

/* Preloaded starting scenes. Sizes follow the TB3 scale guide the planner uses:
 * aisles wider than ~0.8 m, walls 0.8 m tall, graspable blocks under ~5 cm.
 * The robot spawns at the origin facing +X. */

let n = 0;
const obj = (o: Omit<WorldObject, 'id'>): WorldObject => ({ id: `preset${(n++).toString(36)}${Date.now().toString(36)}`, ...o });

const steel = '#64748b';
const lightSteel = '#8a94a6';
const green = '#3ecf8e';
const slate = '#566a7f';

export function warehouseWorld(): WorldObject[] {
  return [
    obj({ kind: 'box', name: 'Wall north', x: 3, y: 3, z: 0, w: 8, d: 0.2, h: 0.8, yaw: 0, color: lightSteel }),
    obj({ kind: 'box', name: 'Wall south', x: 3, y: -3, z: 0, w: 8, d: 0.2, h: 0.8, yaw: 0, color: lightSteel }),
    obj({ kind: 'box', name: 'Wall east', x: 7, y: 0, z: 0, w: 0.2, d: 6.2, h: 0.8, yaw: 0, color: lightSteel }),
    obj({ kind: 'box', name: 'Wall west', x: -1, y: 0, z: 0, w: 0.2, d: 6.2, h: 0.8, yaw: 0, color: lightSteel }),
    obj({ kind: 'box', name: 'Shelf row A', x: 3.5, y: 1.2, z: 0, w: 3, d: 0.4, h: 0.9, yaw: 0, color: steel }),
    obj({ kind: 'box', name: 'Shelf row B', x: 3.5, y: -1.2, z: 0, w: 3, d: 0.4, h: 0.9, yaw: 0, color: steel }),
    obj({ kind: 'box', name: 'Crate 1', x: 1.6, y: 0.5, z: 0, w: 0.3, d: 0.3, h: 0.3, yaw: 20, color: slate, dynamic: true }),
    obj({ kind: 'box', name: 'Crate 2', x: 5.4, y: -0.4, z: 0, w: 0.3, d: 0.3, h: 0.3, yaw: -10, color: slate, dynamic: true }),
  ];
}

export function benchWorld(): WorldObject[] {
  return [
    obj({ kind: 'box', name: 'Table', x: 0.55, y: 0, z: 0, w: 0.8, d: 0.5, h: 0.25, yaw: 0, color: steel }),
    obj({ kind: 'box', name: 'Green block', x: 0.5, y: 0, z: 0.25, w: 0.04, d: 0.04, h: 0.04, yaw: 0, color: green, dynamic: true }),
    obj({ kind: 'box', name: 'Blue block', x: 0.5, y: 0.12, z: 0.25, w: 0.04, d: 0.04, h: 0.04, yaw: 0, color: slate, dynamic: true }),
    obj({ kind: 'box', name: 'Steel block', x: 0.5, y: -0.12, z: 0.25, w: 0.04, d: 0.04, h: 0.04, yaw: 0, color: lightSteel, dynamic: true }),
  ];
}

export const STARTING_POINTS: { key: string; title: string; blurb: string; preset: () => SimPreset }[] = [
  {
    key: 'warehouse',
    title: 'Mobile base · warehouse',
    blurb: 'Aisles, shelves and crates to patrol.',
    preset: () => ({ name: 'tb3 · warehouse', named: true, world: warehouseWorld() }),
  },
  {
    key: 'bench',
    title: 'Arm · pick-and-place bench',
    blurb: 'A table with blocks within reach.',
    preset: () => ({ name: 'tb3 · bench', named: true, world: benchWorld() }),
  },
  {
    key: 'empty',
    title: 'Empty workspace',
    blurb: 'Blank floor - bring your own URDF.',
    preset: () => ({}),
  },
];

export const EXAMPLE_COMMANDS: { label: string; command: string; preset: () => SimPreset }[] = [
  {
    label: 'Drive forward until you see the wall',
    command: 'Drive forward until you see the wall, then turn left',
    preset: () => ({ world: warehouseWorld() }),
  },
  {
    label: 'Patrol the aisles, avoid obstacles',
    command: 'Patrol the aisles and avoid obstacles for 20 seconds',
    preset: () => ({ world: warehouseWorld() }),
  },
  {
    label: 'Pick up the green block',
    command: 'Pick up the green block',
    preset: () => ({ world: benchWorld() }),
  },
  {
    label: 'Raise the arm 45 degrees',
    command: 'Raise the arm 45 degrees',
    preset: () => ({ world: benchWorld() }),
  },
];
