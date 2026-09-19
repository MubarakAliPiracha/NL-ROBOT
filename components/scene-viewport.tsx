'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { OrbitControls, Grid, Edges, Line, TransformControls, ContactShadows } from '@react-three/drei';
import type { Tool } from '@/components/viewport-toolbar';
import * as THREE from 'three';
import URDFLoader, { type URDFRobot } from 'urdf-loader';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { ColladaLoader } from 'three/examples/jsm/loaders/ColladaLoader.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { ConvexGeometry } from 'three/examples/jsm/geometries/ConvexGeometry.js';
import { BACKEND_URL } from '@/lib/config';
import type { RobotInfo } from '@/lib/api';
import type { RobotSnapshot } from '@/lib/use-robot-socket';
import { hullPoints, type WorldObject } from '@/lib/world';

const palette = {
  light: { bg: '#dcebfb', floor: '#eaf3fd', cell: '#9dbfee', section: '#4f86e0', robot: '#ff7a2e' },
  dark: { bg: '#0b1224', floor: '#101a33', cell: '#28407a', section: '#3e74e0', robot: '#ff9a4d' },
};

const GROUND = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
const SNAP = 0.05;
const snap = (v: number) => Math.round(v / SNAP) * SNAP;

function loadMesh(robotColor: string) {
  return (path: string, manager: THREE.LoadingManager, onLoad: (obj: THREE.Object3D, err?: Error) => void) => {
    const ext = path.split('?')[0].split('.').pop()?.toLowerCase();
    const done = onLoad;
    const fail = (e: unknown) => onLoad(new THREE.Object3D(), e instanceof Error ? e : new Error(String(e)));
    const material = () => new THREE.MeshStandardMaterial({ color: robotColor, metalness: 0.25, roughness: 0.5 });

    switch (ext) {
      case 'stl':
        new STLLoader(manager).load(path, (geo) => done(new THREE.Mesh(geo, material())), undefined, fail);
        break;
      case 'obj':
        new OBJLoader(manager).load(
          path,
          (obj) => {
            // OBJ meshes often ship a plain white material; tint those so the robot stands out.
            obj.traverse((c) => {
              if (!(c instanceof THREE.Mesh)) return;
              const m = c.material as THREE.MeshPhongMaterial;
              if (m.color && m.color.r + m.color.g + m.color.b > 2.4) c.material = material();
            });
            done(obj);
          },
          undefined,
          fail,
        );
        break;
      case 'dae':
        new ColladaLoader(manager).load(path, (c) => done(c.scene), undefined, fail);
        break;
      case 'glb':
      case 'gltf':
        new GLTFLoader(manager).load(path, (g) => done(g.scene), undefined, fail);
        break;
      default:
        fail(new Error(`Unsupported mesh format: ${path}`));
    }
  };
}

function RobotModel({
  info,
  latest,
  robotColor,
  onError,
  onReady,
}: {
  info: RobotInfo;
  latest: MutableRefObject<RobotSnapshot>;
  robotColor: string;
  onError: (msg: string | null) => void;
  onReady: () => void;
}) {
  const [robot, setRobot] = useState<URDFRobot | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRobot(null);
    onError(null);

    const manager = new THREE.LoadingManager();
    const loader = new URDFLoader(manager);
    loader.loadMeshCb = loadMesh(robotColor);
    loader.packages = (pkg: string) => `${BACKEND_URL}${info.root_url}/${pkg}`;
    loader.load(
      BACKEND_URL + info.urdf_url,
      (r) => {
        if (cancelled) return;
        r.traverse((c) => {
          c.castShadow = true;
        });
        setRobot(r);
        onReady();
      },
      undefined,
      (e) => !cancelled && onError(`Couldn't render this robot in the viewport: ${String(e)}`),
    );
    return () => {
      cancelled = true;
    };
    // robotColor intentionally excluded: recolouring reloads the model, which is not worth it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [info.source, info.urdf_url]);

  useFrame(() => {
    if (!robot) return;
    const snap = latest.current;
    for (const [name, value] of Object.entries(snap.joints)) robot.setJointValue(name, value);
    if (info.mobile && snap.base) {
      robot.position.set(...snap.base.pos);
      robot.quaternion.set(...snap.base.quat);
    }
  });

  return robot ? <primitive object={robot} /> : null;
}

/** Fan of range-sensor rays: red where something is hit, faint blue where clear. */
function SensorRays({ latest }: { latest: MutableRefObject<RobotSnapshot> }) {
  const MAX = 96;
  const { geometry, positions, colors } = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const pos = new Float32Array(MAX * 2 * 3);
    const col = new Float32Array(MAX * 2 * 3);
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    g.setDrawRange(0, 0);
    return { geometry: g, positions: pos, colors: col };
  }, []);
  useEffect(() => () => geometry.dispose(), [geometry]);

  useFrame(() => {
    const s = latest.current.sensor;
    if (!s) {
      geometry.setDrawRange(0, 0);
      return;
    }
    const n = Math.min(MAX, s.dist.length);
    for (let i = 0; i < n; i++) {
      const a = s.a0 + i * s.da;
      const d = s.dist[i];
      const hit = d < s.range - 0.01;
      const o = i * 6;
      positions[o] = s.origin[0];
      positions[o + 1] = s.origin[1];
      positions[o + 2] = s.origin[2];
      positions[o + 3] = s.origin[0] + d * Math.cos(s.yaw + a);
      positions[o + 4] = s.origin[1] + d * Math.sin(s.yaw + a);
      positions[o + 5] = s.origin[2];
      // Hits carry information -> amber and loud. Clear rays are context -> nearly
      // invisible, so the fan stops shouting over the robot.
      const [r, g, b] = hit ? [1.0, 0.62, 0.08] : [0.09, 0.16, 0.24];
      for (let k = 0; k < 2; k++) {
        colors[o + k * 3] = r;
        colors[o + k * 3 + 1] = g;
        colors[o + k * 3 + 2] = b;
      }
    }
    geometry.setDrawRange(0, n * 2);
    geometry.attributes.position.needsUpdate = true;
    geometry.attributes.color.needsUpdate = true;
  });

  return (
    <lineSegments geometry={geometry} frustumCulled={false}>
      <lineBasicMaterial vertexColors transparent opacity={0.9} />
    </lineSegments>
  );
}

/** CAD-style grid: cell size steps with camera distance so lines stay legible
 *  from tabletop zoom to full-scene overview. State updates only on tier change --
 *  never per frame. */
const GRID_TIERS = [
  { upTo: 12, cell: 0.25 },
  { upTo: 45, cell: 1 },
  { upTo: 160, cell: 5 },
  { upTo: Infinity, cell: 20 },
];

function AdaptiveGrid({ cellColor, sectionColor }: { cellColor: string; sectionColor: string }) {
  const [tier, setTier] = useState(1);
  const current = useRef(1);
  useFrame(({ camera }) => {
    const d = camera.position.length();
    const next = GRID_TIERS.findIndex((g) => d <= g.upTo);
    if (next !== current.current) {
      current.current = next;
      setTier(next);
    }
  });
  const cell = GRID_TIERS[tier].cell;
  return (
    <Grid
      cellSize={cell}
      sectionSize={cell * 5}
      cellColor={cellColor}
      sectionColor={sectionColor}
      cellThickness={0.5}
      sectionThickness={1.2}
      fadeDistance={Math.max(100, cell * 30)}
      fadeStrength={1}
      infiniteGrid
    />
  );
}

/** Soft emissive ring under the robot so it reads as the focus object. */
function FocusRing({ latest, k }: { latest: MutableRefObject<RobotSnapshot>; k: number }) {
  const ref = useRef<THREE.Mesh>(null);
  useFrame(() => {
    const base = latest.current.base;
    if (ref.current && base) ref.current.position.set(base.pos[0], base.pos[1], 0.008);
  });
  return (
    <mesh ref={ref} renderOrder={1}>
      <ringGeometry args={[0.3 * k, 0.4 * k, 48]} />
      <meshBasicMaterial color="#3ecf8e" transparent opacity={0.35} depthWrite={false} />
    </mesh>
  );
}

/** Trail of where the robot has driven. Clears whenever `resetKey` changes (new request, reset, new robot). */
function PathTrace({
  latest,
  resetKey,
  planned,
}: {
  latest: MutableRefObject<RobotSnapshot>;
  resetKey: string;
  planned: [number, number][] | null;
}) {
  const points = useRef<[number, number, number][]>([]);
  const dirty = useRef(false);
  const lastPush = useRef(0);
  const [shown, setShown] = useState<[number, number, number][]>([]);

  // Cumulative arc length along the planned route, and how far along it the robot has got.
  const cum = useMemo(() => {
    if (!planned || planned.length < 2) return null;
    const L = [0];
    for (let i = 1; i < planned.length; i++) {
      L.push(L[i - 1] + Math.hypot(planned[i][0] - planned[i - 1][0], planned[i][1] - planned[i - 1][1]));
    }
    return L;
  }, [planned]);
  const progress = useRef(0);
  const lastSplit = useRef(-1);
  const [split, setSplit] = useState(0);
  useEffect(() => {
    progress.current = 0;
    lastSplit.current = -1;
    setSplit(0);
  }, [planned]);

  useEffect(() => {
    points.current = [];
    dirty.current = false;
    setShown([]);
  }, [resetKey]);

  useFrame(() => {
    const s = latest.current;
    const src = s.sensor ? s.sensor.origin : s.base?.pos; // footprint centre, so long robots trace their middle
    if (!src) return;
    if (planned && cum) {
      // Where along the route is the robot? Project it onto the current and next segment; progress only moves forward.
      let seg = 0;
      while (seg < cum.length - 2 && cum[seg + 1] <= progress.current) seg++;
      let best = progress.current;
      let bestD = Infinity;
      for (let j = seg; j <= Math.min(seg + 1, planned.length - 2); j++) {
        const [ax, ay] = planned[j];
        const [bx, by] = planned[j + 1];
        const len = cum[j + 1] - cum[j];
        if (len < 1e-6) continue;
        const t = Math.max(0, Math.min(1, ((src[0] - ax) * (bx - ax) + (src[1] - ay) * (by - ay)) / (len * len)));
        const d = Math.hypot(src[0] - (ax + t * (bx - ax)), src[1] - (ay + t * (by - ay)));
        if (d < bestD) {
          bestD = d;
          best = cum[j] + t * len;
        }
      }
      if (best > progress.current) progress.current = best;
      if (Math.abs(progress.current - lastSplit.current) > 0.02) {
        lastSplit.current = progress.current;
        setSplit(progress.current);
      }
    }
    const p: [number, number, number] = [src[0], src[1], 0.03];
    const last = points.current[points.current.length - 1];
    if (!last || Math.hypot(p[0] - last[0], p[1] - last[1]) > 0.05) {
      points.current.push(p);
      if (points.current.length > 5000) points.current.shift();
      dirty.current = true;
    }
    const now = performance.now();
    if (dirty.current && now - lastPush.current > 100) {
      lastPush.current = now;
      dirty.current = false;
      setShown(points.current.slice());
    }
  });

  // Google-Maps style: remaining route in strong blue, the part already driven in grey.
  let done: [number, number, number][] = [];
  let ahead: [number, number, number][] = [];
  if (planned && cum) {
    const p3 = (pt: [number, number]): [number, number, number] => [pt[0], pt[1], 0.02];
    let k = 0;
    while (k < cum.length - 2 && cum[k + 1] < split) k++;
    const segLen = cum[k + 1] - cum[k] || 1;
    const t = Math.max(0, Math.min(1, (split - cum[k]) / segLen));
    const here: [number, number, number] = [
      planned[k][0] + t * (planned[k + 1][0] - planned[k][0]),
      planned[k][1] + t * (planned[k + 1][1] - planned[k][1]),
      0.02,
    ];
    done = [...planned.filter((_, i) => cum[i] < split).map(p3), here];
    ahead = [here, ...planned.filter((_, i) => cum[i] > split).map(p3)];
  }
  const end = planned && planned.length > 1 ? planned[planned.length - 1] : null;
  return (
    <>
      {ahead.length > 1 && <Line points={ahead} color="#1a73e8" lineWidth={7} renderOrder={2} />}
      {done.length > 1 && <Line points={done} color="#a9b4c6" lineWidth={7} renderOrder={3} />}
      {!planned && shown.length > 1 && <Line points={shown} color="#a9b4c6" lineWidth={7} renderOrder={3} />}
      {end && (
        <mesh position={[end[0], end[1], 0.07]} renderOrder={4}>
          <sphereGeometry args={[0.06, 16, 12]} />
          <meshBasicMaterial color="#ea4335" />
        </mesh>
      )}
    </>
  );
}

function makeGeometry(o: WorldObject): THREE.BufferGeometry {
  switch (o.kind) {
    case 'box':
      return new THREE.BoxGeometry(o.w, o.d, o.h);
    case 'cylinder': {
      const g = new THREE.CylinderGeometry(o.w / 2, o.w / 2, o.h, 48);
      g.rotateX(Math.PI / 2); // three's cylinder axis is Y; the world is Z-up
      return g;
    }
    case 'sphere':
      return new THREE.SphereGeometry(o.w / 2, 40, 28);
    default:
      return new ConvexGeometry(hullPoints(o.kind, o.w, o.d, o.h).map(([x, y, z]) => new THREE.Vector3(x, y, z)));
  }
}

type Transform = Partial<Pick<WorldObject, 'x' | 'y' | 'z' | 'yaw'>>;

function WorldShape({
  obj,
  selected,
  tool,
  onDown,
  onTransform,
  latest,
}: {
  obj: WorldObject;
  latest: MutableRefObject<RobotSnapshot>;
  selected: boolean;
  tool: Tool;
  onDown: (e: ThreeEvent<PointerEvent>, obj: WorldObject) => void;
  onTransform: (id: string, patch: Transform) => void;
}) {
  const geometry = useMemo(() => makeGeometry(obj), [obj.kind, obj.w, obj.d, obj.h]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => geometry.dispose(), [geometry]);
  const ref = useRef<THREE.Mesh>(null);
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  useFrame(() => {
    // Physics objects move on the backend; mirror their pose every frame.
    const pose = obj.dynamic ? latest.current.objects?.[obj.id] : undefined;
    if (pose && ref.current) {
      ref.current.position.set(pose[0], pose[1], pose[2]);
      ref.current.quaternion.set(pose[3], pose[4], pose[5], pose[6]);
    }
  });
  const gizmo = selected && mounted && ref.current && (tool === 'move' || tool === 'rotate');
  const r3 = (v: number) => Math.round(v * 1000) / 1000;
  return (
    <>
      <mesh
        ref={ref}
        geometry={geometry}
        position={[obj.x, obj.y, obj.z + obj.h / 2]}
        rotation={[0, 0, (obj.yaw * Math.PI) / 180]}
        onPointerDown={(e) => onDown(e, obj)}
      >
        <meshStandardMaterial color={obj.color} roughness={0.55} metalness={0.05} />
        {selected && <Edges threshold={20} color="#ffb800" />}
      </mesh>
      {gizmo && (
        <TransformControls
          object={ref.current!}
          mode={tool === 'move' ? 'translate' : 'rotate'}
          translationSnap={0.05}
          rotationSnap={Math.PI / 36}
          showX={tool === 'move'}
          showZ={tool === 'move'}
          onObjectChange={() => {
            const m = ref.current;
            if (!m) return;
            const yaw = ((THREE.MathUtils.radToDeg(m.rotation.z) + 540) % 360) - 180; // keep in -180..180
            onTransform(obj.id, { x: r3(m.position.x), y: r3(m.position.y), z: Math.max(0, r3(m.position.z - obj.h / 2)), yaw: r3(yaw) });
          }}
        />
      )}
    </>
  );
}

/** Drag-to-move on the ground plane, tracked on window so it works even when the cursor leaves the shape. */
function useGroundDrag(onMove: (id: string, x: number, y: number) => void, setDragging: (d: boolean) => void) {
  const { camera, gl } = useThree();
  const drag = useRef<{ id: string; dx: number; dy: number } | null>(null);
  const raycaster = useMemo(() => new THREE.Raycaster(), []);
  const hit = useMemo(() => new THREE.Vector3(), []);

  useEffect(() => {
    const move = (ev: PointerEvent) => {
      const d = drag.current;
      if (!d) return;
      const rect = gl.domElement.getBoundingClientRect();
      const ndc = new THREE.Vector2(((ev.clientX - rect.left) / rect.width) * 2 - 1, -((ev.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(ndc, camera);
      if (raycaster.ray.intersectPlane(GROUND, hit)) onMove(d.id, snap(hit.x + d.dx), snap(-hit.z + d.dy));
    };
    const up = () => {
      if (drag.current) {
        drag.current = null;
        setDragging(false);
      }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
  }, [camera, gl, hit, onMove, raycaster, setDragging]);

  return useCallback(
    (e: ThreeEvent<PointerEvent>, obj: WorldObject) => {
      e.stopPropagation();
      const p = new THREE.Vector3();
      if (!e.ray.intersectPlane(GROUND, p)) return;
      drag.current = { id: obj.id, dx: obj.x - p.x, dy: obj.y + p.z };
      setDragging(true);
    },
    [setDragging],
  );
}

function World({
  latest,
  objects,
  selectedId,
  onSelect,
  onMove,
  onTransform,
  tool,
  setDragging,
}: {
  latest: MutableRefObject<RobotSnapshot>;
  tool: Tool;
  onTransform: (id: string, patch: Transform) => void;
  objects: WorldObject[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
  setDragging: (d: boolean) => void;
}) {
  const startDrag = useGroundDrag(onMove, setDragging);
  return (
    <>
      {objects.map((o) => (
        <WorldShape
          key={o.id}
          obj={o}
          latest={latest}
          selected={o.id === selectedId}
          tool={tool}
          onTransform={onTransform}
          onDown={(e, obj) => {
            if (tool === 'select') {
              onSelect(obj.id);
              startDrag(e, obj);
            } else if (tool === 'move' || tool === 'rotate') {
              e.stopPropagation();
              onSelect(obj.id); // the gizmo does the moving
            }
            // pan / orbit: shapes are inert so drags always move the camera
          }}
        />
      ))}
    </>
  );
}

/** Camera helpers: reset to the default view, and optionally keep following the robot. */
function CameraRig({
  latest,
  viewKey,
  follow,
  k,
  robotKey,
}: {
  latest: MutableRefObject<RobotSnapshot>;
  viewKey: number;
  follow: boolean;
  k: number;
  robotKey: string;
}) {
  const camera = useThree((s) => s.camera);
  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null;
  const prev = useRef<THREE.Vector3 | null>(null);

  useEffect(() => {
    // Frame the robot: bigger robots get a proportionally farther camera. Runs on Fit view and whenever the robot changes.
    if (!controls) return;
    camera.position.set(1.0 + 1.8 * k, 0.5 + 2.4 * k, 3.4 * k);
    controls.target.set(1.0 * k, 0.55, 0);
    controls.update();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, robotKey, !!controls]);

  useFrame(() => {
    if (!follow || !controls) {
      prev.current = null;
      return;
    }
    const s = latest.current;
    const src = s.sensor ? s.sensor.origin : s.base?.pos;
    if (!src) return;
    const cur = new THREE.Vector3(src[0], 0, -src[1]); // Z-up world -> Y-up scene
    if (prev.current) {
      const d = cur.clone().sub(prev.current);
      camera.position.add(d);
      controls.target.add(d);
    }
    prev.current = cur;
  });
  return null;
}

export function SceneViewport({
  info,
  latest,
  objects,
  selectedId,
  onSelect,
  onMove,
  traceKey,
  plannedPath,
  tool,
  follow,
  viewKey,
  cameraScale,
  onTransform,
}: {
  cameraScale: number;
  tool: Tool;
  follow: boolean;
  viewKey: number;
  onTransform: (id: string, patch: Transform) => void;
  info: RobotInfo | null;
  latest: MutableRefObject<RobotSnapshot>;
  traceKey: number;
  plannedPath: [number, number][] | null;
  objects: WorldObject[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
}) {
  const colors = palette.dark;
  const [error, setError] = useState<string | null>(null);
  const [robotReady, setRobotReady] = useState(false);
  const [dragging, setDragging] = useState(false);
  const key = useMemo(() => info?.source ?? 'none', [info]);
  useEffect(() => setRobotReady(false), [key]);

  return (
    <div className="relative h-full w-full">
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ position: [2.8, 3.3, 3.6], fov: 45 }}
        onPointerMissed={() => onSelect(null)}
      >
        <color attach="background" args={[colors.bg]} />
        <ambientLight intensity={1.1} />
        <hemisphereLight args={['#ffffff', colors.floor, 0.7]} />
        <directionalLight position={[4, 7, 5]} intensity={2} castShadow />
        <AdaptiveGrid cellColor={colors.cell} sectionColor={colors.section} />
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.002, 0]}>
          <planeGeometry args={[400, 400]} />
          <meshBasicMaterial color={colors.floor} toneMapped={false} />
        </mesh>
        <ContactShadows position={[0, 0.012, 0]} opacity={0.45} scale={20} blur={2.4} far={3.5} />

        {/* URDF / PyBullet are Z-up; three.js is Y-up. Everything physical lives in this rotated group. */}
        <group rotation={[-Math.PI / 2, 0, 0]}>
          <axesHelper args={[0.6]} />
          {info && (
            <RobotModel
              key={key}
              info={info}
              latest={latest}
              robotColor={colors.robot}
              onError={setError}
              onReady={() => setRobotReady(true)}
            />
          )}
          {info?.mobile && <FocusRing latest={latest} k={cameraScale} />}
          {info?.mobile && <SensorRays latest={latest} />}
          {info?.mobile && <PathTrace latest={latest} resetKey={`${traceKey}-${info.source}`} planned={plannedPath} />}
          <World
            latest={latest}
            objects={objects}
            selectedId={selectedId}
            onSelect={onSelect}
            onMove={onMove}
            onTransform={onTransform}
            tool={tool}
            setDragging={setDragging}
          />
        </group>

        <CameraRig latest={latest} viewKey={viewKey} follow={follow} k={cameraScale} robotKey={key} />
        <OrbitControls
          makeDefault
          enabled={!dragging}
          target={[1.2, 0.3, 0]}
          maxPolarAngle={Math.PI / 2.02}
          maxDistance={400}
          mouseButtons={{
            LEFT: tool === 'pan' ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE,
            MIDDLE: THREE.MOUSE.DOLLY,
            RIGHT: THREE.MOUSE.PAN,
          }}
        />
      </Canvas>
      {info && !robotReady && !error && (
        <div className="absolute inset-0 flex items-center justify-center bg-app/60">
          <div className="border border-line bg-surface px-4 py-2.5 text-xs text-muted">
            <span className="text-brand">$</span> loading robot meshes<span className="cursor-blink" />
          </div>
        </div>
      )}
      {error && (
        <div className="absolute bottom-4 left-1/2 max-w-md -translate-x-1/2 rounded-xl bg-danger px-4 py-2 text-sm text-white shadow-lift">
          {error}
        </div>
      )}
    </div>
  );
}
