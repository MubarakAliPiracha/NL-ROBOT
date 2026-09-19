FROM ros:humble-ros-base

# Gazebo Fortress + ros2_control + the ros_gz bridge.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-humble-ros-gz \
      ros-humble-gz-ros2-control \
      ros-humble-ros2-control \
      ros-humble-ros2-controllers \
      ros-humble-robot-state-publisher \
      ros-humble-xacro \
      ros-humble-turtlebot3-description \
      ros-humble-turtlebot3-manipulation-description \
      ros-humble-turtlebot3-manipulation-bringup \
      python3-pip curl \
 && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
      fastapi "uvicorn[standard]" python-multipart anthropic requests numpy "Brotli>=1.1"

WORKDIR /app
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
