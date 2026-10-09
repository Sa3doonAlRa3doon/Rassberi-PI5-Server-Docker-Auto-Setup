# ChronoSnap timelapse

ChronoSnap is the package's scheduled timelapse service. It is selected in the
setup panel like every other application and is **on demand by default**. The
installer does not download its image until ChronoSnap is selected and the
storage layout has been reviewed.

After installation, open:

```text
http://PI_PRIVATE_IP:8101/
```

Create a capture job in the web UI. The supported source types are:

- **RTSP/RTSPS** for a security camera or NVR stream.
- **HTTP/HTTPS** for an image endpoint, webcam snapshot or other URL that
  returns an image.
- **Local device** for an explicitly passed USB webcam or Raspberry Pi camera.

The first two source types work with the package as installed. Use the UI's
source test before saving a job. Choose a capture interval, optional time
window, naming pattern and output frame rate; then build an MP4 or GIF from the
captured frames. A 5-second interval can create gigabytes per day at 1080p, so
start with a longer interval and check the bulk-drive dashboard.

The SQLite database and settings are kept on the selected SSD at
`/srv/docker/appdata/chronosnap`. Captures, finished videos and server-side
imports use the selected bulk destination:

```text
/mnt/hdd/Timelapse/captures
/mnt/hdd/Timelapse/timelapses
/mnt/hdd/Timelapse/imports
```

The setup panel can move these declared bulk paths to another reviewed HDD,
SSD or microSD. The guard checks the exact filesystem UUID, mount point,
filesystem type and writability before it creates them. If that drive is absent,
ChronoSnap stays stopped and is queued for storage-resume only when it was
selected for startup.

## USB webcam or CSI camera

The installer intentionally does not guess `/dev/video0`; doing so would make
an installation fail on machines without a camera or pass the wrong camera to a
container. RTSP/HTTP jobs need no device mapping.

On a Pi with a local camera, identify the device first:

```bash
ls /dev/video*
v4l2-ctl --list-devices
```

Set only the actual device in the private Compose environment file. The
package maps `/dev/null` by default, so a machine without a camera still
starts normally and never receives a guessed device. For a USB camera:

```bash
sudo sh -c 'printf "\\nCHRONOSNAP_CAMERA_DEVICE=/dev/video0\\n" >> /srv/docker/compose/chronosnap/.env'
sudo /srv/docker/start-all.sh chronosnap
```

The equivalent reviewed Compose fragment is preserved in
`compose/chronosnap/camera-compose.example.yml` for reference. Change
`/dev/video0` to the device returned by `v4l2-ctl`; do not add a device that
does not exist. Changing this setting requires stopping and starting the app.

For a Raspberry Pi CSI camera, the current rpicam stack may also require
`/dev/vchiq` and OS-specific rpicam shared libraries. Verify the camera on the
host with `rpicam-hello --list-cameras` and `rpicam-still -o test.jpg` before
adding those reviewed mounts. Do not add a device that does not exist.

## Start and stop

```bash
sudo /srv/docker/start-all.sh chronosnap
sudo /srv/docker/stop-all.sh chronosnap
sudo /srv/docker/status.sh
```

The service is capped at 2 GiB and two CPU cores. Keep it on demand on a 8 GB
Pi, and start it only while you are capturing or building videos. The manager
will reject a start if the aggregate caps would leave less than 2 GiB for the
OS.

Sources: [ChronoSnap README](https://github.com/kernelkaribou/chronosnap),
[upstream Compose file](https://raw.githubusercontent.com/kernelkaribou/chronosnap/main/docker-compose.yml).
