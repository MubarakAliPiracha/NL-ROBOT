'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type MutableRefObject } from 'react';
import { Canvas, useFrame, useThree, type ThreeEvent } from '@react-three/fiber';
import { OrbitControls, Grid, Edges } from '@react-three/drei';
import * as THREE from 'three';
import URDFLoader, { type URDFRobot } from 'urdf-loader';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js';
import { ColladaLoader } from 'three/examples/jsm/loaders/ColladaLoader.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { ConvexGeometry } from 'three/examples/jsm/geometries/ConvexGeometry.js';
import { BACKEND_URL } from '@/lib/config';
import { useTheme } from '@/lib/theme';
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
}: {
  info: RobotInfo;
  latest: MutableRefObject<RobotSnapshot>;
  robotColor: string;
  onError: (msg: string | null) => void;
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
      const [r, g, b] = hit ? [1, 0.25, 0.2] : [0.25, 0.55, 1];
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
      <lineBasicMaterial vertexColors transparent opacity={0.75} />
    </lineSegments>
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

function WorldShape({
  obj,
  selected,
  onDown,
  latest,
}: {
  obj: WorldObject;
  latest: MutableRefObject<RobotSnapshot>;
  selected: boolean;
  onDown: (e: ThreeEvent<PointerEvent>, obj: WorldObject) => void;
}) {
  const geometry = useMemo(() => makeGeometry(obj), [obj.kind, obj.w, obj.d, obj.h]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => geometry.dispose(), [geometry]);
  const ref = useRef<THREE.Mesh>(null);
  useFrame(() => {
    // Physics objects move on the backend; mirror their pose every frame.
    const pose = obj.dynamic ? latest.current.objects?.[obj.id] : undefined;
    if (pose && ref.current) {
      ref.current.position.set(pose[0], pose[1], pose[2]);
      ref.current.quaternion.set(pose[3], pose[4], pose[5], pose[6]);
    }
  });
  return (
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
  setDragging,
}: {
  latest: MutableRefObject<RobotSnapshot>;
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
          onDown={(e, obj) => {
            onSelect(obj.id);
            startDrag(e, obj);
          }}
        />
      ))}
    </>
  );
}

export function SceneViewport({
  info,
  latest,
  objects,
  selectedId,
  onSelect,
  onMove,
}: {
  info: RobotInfo | null;
  latest: MutableRefObject<RobotSnapshot>;
  objects: WorldObject[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onMove: (id: string, x: number, y: number) => void;
}) {
  const { theme } = useTheme();
  const colors = palette[theme];
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const key = useMemo(() => info?.source ?? 'none', [info]);

  return (
    <div className="relative h-full w-full">
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ position: [3.4, 2.8, 4.6], fov: 45 }}
        onPointerMissed={() => onSelect(null)}
      >
        <color attach="background" args={[colors.bg]} />
        <ambientLight intensity={1.1} />
        <hemisphereLight args={['#ffffff', colors.floor, 0.7]} />
        <directionalLight position={[4, 7, 5]} intensity={2} castShadow />
        <Grid
          args={[30, 30]}
          cellSize={0.25}
          sectionSize={1}
          cellColor={colors.cell}
          sectionColor={colors.section}
          cellThickness={0.6}
          sectionThickness={1.2}
          fadeDistance={22}
          infiniteGrid
        />
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.005, 0]}>
          <planeGeometry args={[60, 60]} />
          <meshBasicMaterial color={colors.floor} toneMapped={false} />
        </mesh>

        {/* URDF / PyBullet are Z-up; three.js is Y-up. Everything physical lives in this rotated group. */}
        <group rotation={[-Math.PI / 2, 0, 0]}>
          <axesHelper args={[0.6]} />
          {info && <RobotModel key={key} info={info} latest={latest} robotColor={colors.robot} onError={setError} />}
          {info?.mobile && <SensorRays latest={latest} />}
          <World latest={latest} objects={objects} selectedId={selectedId} onSelect={onSelect} onMove={onMove} setDragging={setDragging} />
        </group>

        <OrbitControls makeDefault enabled={!dragging} target={[1.2, 0.3, 0]} maxPolarAngle={Math.PI / 2.02} />
      </Canvas>
      {error && (
        <div className="absolute bottom-4 left-1/2 max-w-md -translate-x-1/2 rounded-xl bg-danger px-4 py-2 text-sm text-white shadow-lift">
          {error}
        </div>
      )}
    </div>
  );
}
