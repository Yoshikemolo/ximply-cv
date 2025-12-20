# Feature: View (Object Detection)

## Overview
The View feature provides real-time object detection from camera feeds. It displays detected objects with bounding boxes, labels, and confidence scores, matching them against the trained catalog.

## User Stories

### US-001: Start Camera Detection
**As a** user with detection permissions
**I want to** start the camera and see real-time object detection
**So that** I can identify objects in my environment

**Acceptance Criteria:**
- Camera permission is requested
- Camera preview displays
- Detection starts automatically
- Bounding boxes appear around detected objects
- Labels show object name and confidence

### US-002: View Detection Details
**As a** user viewing detection results
**I want to** see detailed information about detected objects
**So that** I can understand what the system has identified

**Acceptance Criteria:**
- Detected objects show confidence percentage
- Matched catalog objects show additional metadata
- Detection list shows recent detections
- Clicking detection highlights it

### US-003: Configure Detection
**As a** user with configuration permissions
**I want to** adjust detection sensitivity
**So that** I can optimize for my use case

**Acceptance Criteria:**
- Confidence threshold can be adjusted
- Changes apply immediately
- Settings persist across sessions

## UI Components

### Camera Preview
- Full-width video element
- Canvas overlay for bounding boxes
- Camera controls (start/stop)
- Camera selection dropdown

### Detection Overlay
- Colored bounding boxes (green = high confidence, yellow = medium, red = low)
- Label with object name
- Confidence percentage
- Catalog match indicator

### Detection Sidebar
- List of recent detections
- Click to highlight
- Filter by confidence
- Show/hide matched only

### Settings Panel
- Confidence threshold slider
- Camera selection
- Resolution settings
- Frame rate display

## Technical Implementation

### Camera Access
```typescript
async startCamera(): Promise<void> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: {
      width: { ideal: 1280 },
      height: { ideal: 720 },
      facingMode: 'environment'
    }
  });
  this.videoElement.srcObject = stream;
}
```

### SSE Connection
```typescript
connectToDetectionStream(): void {
  const eventSource = new EventSource(`${API_URL}/detection/stream`);

  eventSource.addEventListener('detection', (event) => {
    const detection = JSON.parse(event.data);
    this.updateDetections(detection);
  });
}
```

### Bounding Box Rendering
```typescript
renderBoundingBox(ctx: CanvasRenderingContext2D, detection: Detection): void {
  const color = this.getConfidenceColor(detection.confidence);

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.strokeRect(
    detection.bbox.x,
    detection.bbox.y,
    detection.bbox.width,
    detection.bbox.height
  );

  // Draw label background
  const label = `${detection.label} ${(detection.confidence * 100).toFixed(0)}%`;
  ctx.fillStyle = color;
  ctx.fillRect(detection.bbox.x, detection.bbox.y - 25, label.length * 8, 25);

  // Draw label text
  ctx.fillStyle = 'white';
  ctx.font = '14px sans-serif';
  ctx.fillText(label, detection.bbox.x + 5, detection.bbox.y - 7);
}
```

## Permissions Required
- `detection:view` - View camera and detections
- `detection:configure` - Modify detection settings

## Related Features
- [Learn](./learn.md) - Train new objects
- [Catalog](./catalog.md) - Manage object catalog
