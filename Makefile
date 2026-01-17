PYTHON ?= python

# Stream source/pipeline knobs (for run-backend target)
# --- APP MODE ---
APP_STREAM_SOURCE      ?= pi                    # cap | pi
APP_CAM_INDEX          ?= 0                     # camera index when STREAM_SOURCE=cap (Debug: cap stream source only)
APP_STREAM_RESIZE      ?= 0.8                   # Resize factor for input stream (Debug: cap stream source only)
APP_STREAM_URL         ?= http://100.124.216.108:8000 # MJPEG stream URL when STREAM_SOURCE=cap
APP_VIDEO_JPEG_QUALITY ?= 70                    # JPEG quality for video stream
APP_DETIC_INTERVAL     ?= 4                     # Interval between Detic detections
APP_TRACK_MIN_INTERVAL ?= 0.1                   # Min interval between track detections
APP_FACE_MIN_INTERVAL  ?= 1.0                   # Min interval between face detections
APP_STREAM_MAX_FPS     ?= 30                    # Max FPS for stream source
APP_STATE_WS           ?= 1                     # Enable backend state WS server
APP_PUB_WS_HOST        ?= 0.0.0.0               # Backend state WS host
APP_STATE_WS_PORT      ?= 8765                  # Backend state WS port
APP_WS_INTERVAL        ?= 0.4                   # Backend state WS publish interval
APP_PI_STATE_WS_PORT   ?= 8766                  # Pi state WS port
APP_PI_STATE_HOST      ?= 100.124.216.108             # Pi state WS host
APP_PI_REST_URL        ?= http://100.124.216.108:8081 # Pi REST server URL
APP_VIDEO_WS_PORT      ?= 8890                  # Video WebSocket port
APP_PS2_LOG_EVENTS     ?= 0                     # Log PS2 controller events (event store)
APP_PS2_BAUD           ?= 115200                # PS2 controller serial baud rate
APP_PS2_FAKE_INPUT     ?= 0                     # Enable fake PS2 input for testing without a PS2 controller
APP_REST               ?= 1                     # Enable backend REST server
APP_REST_HOST          ?= 0.0.0.0               # Backend REST server host
APP_REST_PORT          ?= 8080                  # Backend REST server port
# DEBUG MODE
APP_DEBUG_TRACE        ?= 0                     # Enable backend viztrace logging
APP_DEBUG_TRACE_OUT    ?= backend_threads.json          # Output file for debug trace

# Pi-side knobs
# --- PI MODE ---
PI_DEBUG_LOCAL         ?= 0                     # Enable local debug output (pygame window), use local camera simulation
PI_BASE_WIDTH          ?= 0.30
PI_STATE_WS            ?= 1
PI_PUB_STATE_WS_HOST   ?= 0.0.0.0               # Pi state WS host
PI_PUB_STATE_WS_PORT   ?= 8766                  # Pi state WS port
PI_PUB_WS_INTERVAL     ?= 0.3                   # Pi state WS publish interval
PI_SUB_STATE_WS_HOST   ?= 100.110.140.48             # Backend state WS host
PI_SUB_STATE_WS_PORT   ?= 8765                  # Backend state WS port
PI_SUB_STATE_WS_MAX_SIZE ?= 2097152             # Max message size for PI state WS (2 MB)
PI_DRIVE_LINEAR        ?= 0.8                   # Linear speed multiplier
PI_DRIVE_ANGULAR       ?= 0.6                   # Angular speed multiplier
PI_REST                ?= 1                     # Enable PI REST server
PI_REST_HOST           ?= 0.0.0.0               # PI REST server host
PI_REST_PORT           ?= 8081                  # PI REST server port
# DEBUG MODE
PI_DEBUG_TRACE        ?= 0                     # Enable backend viztrace logging
PI_DEBUG_TRACE_OUT    ?= pi_threads.json          # Output file for debug trace

# Deploy/rsync
RSYNC_DEST            ?= alex@100.124.216.108:~/uofthack2026
RSYNC_FLAGS           ?= -av --delete --exclude='.git' --filter=':- .gitignore'

.PHONY: run-frontend run-backend run-raspi rsync-remote install-frontend

run-backend:
	APP_MODE=backend \
	APP_DEBUG_TRACE=$(APP_DEBUG_TRACE) \
	APP_DEBUG_TRACE_OUT=$(APP_DEBUG_TRACE_OUT) \
	APP_STREAM_SOURCE=$(APP_STREAM_SOURCE) \
	APP_STREAM_CAM_INDEX=$(APP_CAM_INDEX) \
	APP_STREAM_URL=$(APP_STREAM_URL) \
	APP_STREAM_RESIZE=$(APP_STREAM_RESIZE) \
	APP_STREAM_MAX_FPS=$(APP_STREAM_MAX_FPS) \
	APP_VIDEO_JPEG_QUALITY=$(APP_VIDEO_JPEG_QUALITY) \
	APP_DETIC_INTERVAL=$(APP_DETIC_INTERVAL) \
	APP_TRACK_MIN_INTERVAL=$(APP_TRACK_MIN_INTERVAL) \
	APP_FACE_MIN_INTERVAL=$(APP_FACE_MIN_INTERVAL) \
	APP_STATE_WS=$(APP_STATE_WS) \
	APP_PUB_WS_HOST=$(APP_PUB_WS_HOST) \
	APP_STATE_WS_PORT=$(APP_STATE_WS_PORT) \
	APP_PI_STATE_WS_PORT=$(APP_PI_STATE_WS_PORT) \
	APP_PI_STATE_HOST=$(APP_PI_STATE_HOST) \
	APP_PI_REST_URL=$(APP_PI_REST_URL) \
	APP_WS_INTERVAL=$(APP_WS_INTERVAL) \
	APP_PS2_BAUD=$(APP_PS2_BAUD) \
	APP_PS2_FAKE_INPUT=$(APP_PS2_FAKE_INPUT) \
	APP_PS2_LOG_EVENTS=$(APP_PS2_LOG_EVENTS) \
	APP_REST=$(APP_REST) \
	APP_REST_HOST=$(APP_REST_HOST) \
	APP_REST_PORT=$(APP_REST_PORT) \
	APP_VIDEO_WS_PORT=$(APP_VIDEO_WS_PORT) \
	$(PYTHON) main.py

run-raspi:
	APP_MODE=raspi \
	PI_BASE_WIDTH=$(PI_BASE_WIDTH) \
	PI_STATE_WS=$(PI_STATE_WS) \
	PI_PUB_STATE_WS_HOST=$(PI_PUB_STATE_WS_HOST) \
	PI_PUB_STATE_WS_PORT=$(PI_PUB_STATE_WS_PORT) \
	PI_PUB_WS_INTERVAL=$(PI_PUB_WS_INTERVAL) \
	PI_SUB_STATE_WS_HOST=$(PI_SUB_STATE_WS_HOST) \
	PI_SUB_STATE_WS_PORT=$(PI_SUB_STATE_WS_PORT) \
	PI_SUB_STATE_WS_MAX_SIZE=$(PI_SUB_STATE_WS_MAX_SIZE) \
	PI_DEBUG_LOCAL=$(PI_DEBUG_LOCAL) \
	PI_DRIVE_LINEAR=$(PI_DRIVE_LINEAR) \
	PI_DRIVE_ANGULAR=$(PI_DRIVE_ANGULAR) \
	PI_REST=$(PI_REST) \
	PI_REST_HOST=$(PI_REST_HOST) \
	PI_REST_PORT=$(PI_REST_PORT) \
	PI_DEBUG_TRACE=$(PI_DEBUG_TRACE) \
	PI_DEBUG_TRACE_OUT=$(PI_DEBUG_TRACE_OUT) \
	$(PYTHON) main.py

rsync-remote:
	rsync $(RSYNC_FLAGS) ./ $(RSYNC_DEST)/

install-frontend:
	git submodule update --init --recursive
	cd ui && npm install

run-frontend:
	cd ui && npm run dev
