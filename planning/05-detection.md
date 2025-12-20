# Milestone 5: Object Detection

## Overview
Implement real-time object detection using camera feeds, displaying detected objects with bounding boxes, labels, and confidence scores. Match detected objects against the trained catalog.

## Tasks

### 5.1 Camera Integration
- [ ] Implement WebRTC camera access
- [ ] Handle camera selection (multiple cameras)
- [ ] Configure resolution and frame rate
- [ ] Handle camera errors gracefully

**Implementation Steps:**

1. Camera configuration:
   ```typescript
   const constraints: MediaStreamConstraints = {
     video: {
       width: { ideal: 1280 },
       height: { ideal: 720 },
       facingMode: 'environment',
       frameRate: { ideal: 30 }
     }
   };
   ```

2. Camera selection:
   - List available devices
   - Allow user to select
   - Remember preference

### 5.2 Detection Backend
- [ ] Load YOLO model on startup
- [ ] Create detection endpoint
- [ ] Implement frame processing
- [ ] Match against custom models
- [ ] Return detection results

**Implementation Steps:**

1. Detection service:
   ```python
   class DetectionService:
       def __init__(self):
           self.base_model = self.load_base_model()
           self.custom_models = {}

       async def detect(self, frame: np.ndarray, user_id: str) -> List[Detection]
       async def load_user_models(self, user_id: str) -> None
   ```

2. Detection result structure:
   ```python
   class Detection:
       label: str
       confidence: float
       bbox: BoundingBox
       object_id: Optional[UUID]  # If matched to catalog
       object_name: Optional[str]
   ```

3. Model loading strategy:
   - Load base YOLO on startup
   - Lazy load custom models per user
   - Cache custom models with TTL
   - Unload unused models

### 5.3 SSE Streaming
- [ ] Implement SSE endpoint for detections
- [ ] Stream detection events in real-time
- [ ] Handle client disconnection
- [ ] Rate limit event frequency

**Implementation Steps:**

1. SSE endpoint:
   ```python
   @router.get("/detection/stream")
   async def stream_detections(user: TokenData = Depends(get_current_user)):
       async def event_generator():
           while True:
               detection = await get_next_detection(user.sub)
               yield {
                   "event": "detection",
                   "data": detection.model_dump_json()
               }
       return EventSourceResponse(event_generator())
   ```

2. Event rate limiting:
   - Max 30 events per second
   - Aggregate if processing slower
   - Include timestamp in events

### 5.4 Frontend Detection View
- [ ] Create detection page layout
- [ ] Implement video canvas overlay
- [ ] Draw bounding boxes
- [ ] Display labels and confidence
- [ ] Show matched object info
- [ ] Handle SSE connection

**Implementation Steps:**

1. View page components:
   - Camera preview (video element)
   - Canvas overlay (for bounding boxes)
   - Detection list sidebar
   - Object info panel
   - Camera controls

2. Canvas overlay:
   ```typescript
   drawDetection(ctx: CanvasRenderingContext2D, detection: Detection) {
     const { x, y, width, height } = detection.bbox;

     // Draw box
     ctx.strokeStyle = this.getColorForConfidence(detection.confidence);
     ctx.lineWidth = 2;
     ctx.strokeRect(x, y, width, height);

     // Draw label
     const label = `${detection.label} ${(detection.confidence * 100).toFixed(1)}%`;
     ctx.fillStyle = ctx.strokeStyle;
     ctx.fillRect(x, y - 20, ctx.measureText(label).width + 10, 20);
     ctx.fillStyle = 'white';
     ctx.fillText(label, x + 5, y - 5);
   }
   ```

3. Detection list:
   - Show recent detections
   - Click to highlight/freeze
   - Show catalog match info
   - Filter by confidence threshold

### 5.5 Detection Logging
- [ ] Log detection events to database
- [ ] Create detection history API
- [ ] Implement detection analytics

**Implementation Steps:**

1. Log detections:
   ```python
   async def log_detection(detection: Detection, user_id: str):
       log = DetectionLogEntity(
           id=uuid7(),
           object_id=detection.object_id,
           detected_label=detection.label,
           confidence=detection.confidence,
           bbox_x=detection.bbox.x,
           # ... other fields
       )
       db.add(log)
       await db.commit()
   ```

2. Analytics endpoints:
   - Detection count by object
   - Detection timeline
   - Confidence distribution

## Verification Checklist

- [ ] Camera access works
- [ ] Camera preview displays
- [ ] Detections appear in real-time
- [ ] Bounding boxes render correctly
- [ ] Labels show with confidence
- [ ] Custom trained objects are detected
- [ ] SSE connection is stable
- [ ] Reconnection handles failures
- [ ] Detection history is logged
- [ ] Performance is acceptable (30fps)

## API Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| GET | /api/v1/detection/stream | SSE detection stream | Yes |
| POST | /api/v1/detection/start | Start detection session | Yes |
| POST | /api/v1/detection/stop | Stop detection session | Yes |
| GET | /api/v1/detection/status | Get detection status | Yes |
| GET | /api/v1/detection/config | Get detection config | Yes |
| PUT | /api/v1/detection/config | Update detection config | Yes |
| GET | /api/v1/detection/history | Get detection history | Yes |

## Next Steps
After completing detection, proceed to Milestone 6: Administration.
