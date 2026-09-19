"""Print the structure of a URDF: joints, sensors, plugins, mesh URIs."""

import re
import sys
import xml.etree.ElementTree as ET

path = sys.argv[1]
root = ET.parse(path).getroot()

joints = [(j.get("name"), j.get("type")) for j in root.findall("joint")]
print("links :", len(root.findall("link")))
print("joints:", len(joints))
for name, kind in joints:
    if kind != "fixed":
        print("   %-30s %s" % (name, kind))

print()
print("gazebo blocks:", len(root.findall("gazebo")))
for block in root.findall("gazebo"):
    for plugin in block.findall("plugin"):
        print("   plugin:", plugin.get("filename"), "|", plugin.get("name"))
    for sensor in block.findall(".//sensor"):
        print("   sensor:", sensor.get("name"), "type=", sensor.get("type"))

print()
print("ros2_control blocks:", [c.get("name") for c in root.findall("ros2_control")])
for control in root.findall("ros2_control"):
    for hardware in control.findall("hardware"):
        for plugin in hardware.findall("plugin"):
            print("   hardware plugin:", (plugin.text or "").strip())
    print("   joints:", [j.get("name") for j in control.findall("joint")])

text = open(path).read()
meshes = sorted({m for m in re.findall(r'filename="([^"]+)"', text) if m.lower().endswith((".stl", ".dae"))})
print()
print("mesh URIs:", len(meshes))
for mesh in meshes[:4]:
    print("   ", mesh)
