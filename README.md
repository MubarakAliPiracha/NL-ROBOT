# NL-Robot-GZ

Tell a robot what to do in plain English. It does it in **ROS 2 Humble + Gazebo Fortress**.

This is a port of [NL-Robot-Sim](https://github.com/007Aurick/NL-Robot-Sim) off PyBullet and
onto the stack robotics teams actually test on. Same product, real ROS interfaces
underneath — so a plan that runs here maps onto real hardware.

**Why it matters:** the in-depth robot testing people do by hand on ROS 2 (`ros2 topic pub`,
watch, repeat) becomes something you can just *describe*.

---

## Quick start

```bash
# 1. planner key (Anthropic; Ollama on :11434 also works as a fallback)
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 2. sim + ROS + backend (one container, headless)
docker compose up

# 3. frontend, native on the host
npm install && npm run dev                # http://localhost:3000
```

Then type *"build a small maze and drive through it"*.

---

## How it fits together

```
Windows host                 docker (one container, one ROS graph)
┌──────────────┐  HTTP/WS   ┌────────────────────────────────────┐
│ Next.js :3000│ ─────────▶ │ FastAPI + rclpy          :8000     │
│ Three.js view│ ◀───────── │ ign gazebo -s (headless)           │
└──────────────┘  snapshot  │ ros2_control · ros_gz_bridge       │
                            └────────────────────────────────────┘
```

Everything ROS stays inside one container, so DDS never has to cross the WSL2 boundary.
The browser speaks only HTTP and WebSocket.

### The port in one sentence

The frontend was already driven entirely by one WebSocket JSON snapshot, so keeping that
contract byte-for-byte meant **only `Session` had to be rewritten** — the UI, the LLM
planner (`llm.py`), the plan validator (`skills.py`) and the world editor (`world_ops.py`)
are reused unchanged.

| Layer | Status |
|---|---|
| `app/`, `components/`, `lib/` — Next.js + Three.js viewport | reused, untouched |
| `bridge/llm.py`, `world_ops.py` | reused verbatim |
| `bridge/skills.py` | reused; PyBullet import inlined away |
| `bridge/session.py`, `ros_node.py`, `executor.py` | **new** — ROS 2 behind the same seam |
| PyBullet `mobile.py` / `arm.py` / `world.py` | deleted |

---

## Skills

| Skill | Implementation |
|---|---|
| `drive`, `turn` | `/cmd_vel`, closed on ground-truth odometry |
| `go_to`, `face` | P-controller on `/odom` |
| `avoid_obstacles` | reactive sector comparison on `/scan` |
| `set_joints` | `FollowJointTrajectory` → `JointTrajectoryController` |
| `move_ee` | closed-form IK (`kinematics.py`) → same action |
| `grasp` / `release` | jaw trajectory + 20 Hz kinematic carry |
| `wait`, `stop`, `flap`, `circle` | executor-local |

---

## What is real vs. approximated

Being straight about this, because it is a *testing* product and the distinction matters.

| Real ROS 2 / Gazebo | Approximated | Why |
|---|---|---|
| Rigid-body physics, contact, joint limits | — | Gazebo does this properly |
| `/cmd_vel`, `/odom`, `/joint_states`, `/scan`, `FollowJointTrajectory` | — | genuine topics/actions; any ROS node can consume them |
| — | **Lidar is synthesized**, not `gpu_lidar` | no GPU/display in the container; a rendering sensor would publish *nothing*. It raycasts live Gazebo poses (not authored ones), publishes a real `sensor_msgs/LaserScan`, and is deterministic — a feature for regression tests. `gpu_lidar` is a drop-in on a GPU box. |
| — | **Grasp is a kinematic carry** | Fortress `DetachableJoint` can't attach at runtime to models spawned after the robot (`<child_model>` must be named at spawn) |
| — | **cone/pyramid/wedge → nearest primitive** | no SDF primitive exists; the viewport still draws true hulls, so it is invisible |
| — | **Positions, not effort, for the arm** | no PID tuning, no gravity sag |
| — | Ground truth instead of Nav2/AMCL | the PyBullet original also used ground truth — this is parity, not a regression |

Known gaps: wheel joints don't appear in `/joint_states` (the Gazebo `DiffDrive` system
owns them, not `ros2_control`), so wheel spin isn't animated. Robot upload returns a
warning rather than driving an arbitrary URDF, which would need generated
`<ros2_control>` and controller config.

---

## Troubleshooting

```bash
docker compose run --rm sim smoke     # plugin .so name, spawn services, Fortress version
docker compose run --rm sim shell     # poke at the ROS graph by hand
docker compose exec sim bash -lc 'source /opt/ros/humble/setup.bash && ros2 topic list'
```

There is **no Gazebo GUI** — it runs headless by necessity. Debug through the web viewport
and `ros2 topic echo`.
