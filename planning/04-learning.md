# Milestone 4: Object Learning

## Overview
Implement the object learning system that allows users to train the detection model with new objects by uploading images or capturing them from camera.

## Tasks

### 4.1 Image Capture
- [ ] Implement camera access in browser
- [ ] Create capture preview component
- [ ] Handle camera permissions
- [ ] Support multiple captures per session
- [ ] Auto-capture with bounding box

**Implementation Steps:**

1. Create camera service:
   ```typescript
   @Injectable({ providedIn: 'root' })
   export class CameraService {
     private stream: MediaStream | null = null;

     async requestAccess(): Promise<MediaStream>
     async captureFrame(video: HTMLVideoElement): Promise<Blob>
     stopCamera(): void
   }
   ```

2. Create camera preview component:
   - Video element with camera stream
   - Capture button
   - Retake button
   - Captured images preview
   - Bounding box overlay (for object selection)

### 4.2 Training Data Preparation
- [ ] Implement image annotation (bounding boxes)
- [ ] Create training data export format
- [ ] Validate minimum training images
- [ ] Generate augmented images

**Implementation Steps:**

1. Bounding box annotation:
   - Draw rectangle on image
   - Resize/move annotation
   - Multiple annotations per image (optional)
   - Save annotation coordinates

2. Training data structure:
   ```
   training_data/
     {object_id}/
       images/
         001.jpg
         002.jpg
       annotations/
         001.json  # {x, y, width, height}
         002.json
       metadata.json
   ```

3. Image augmentation (backend):
   - Rotation variants
   - Brightness/contrast variations
   - Flip horizontal
   - Scale variations

### 4.3 Training Pipeline
- [ ] Create training job service
- [ ] Implement YOLO fine-tuning
- [ ] Track training progress
- [ ] Save trained model weights
- [ ] Version model checkpoints

**Implementation Steps:**

1. Training service:
   ```python
   class TrainingService:
       async def start_training(self, object_id: UUID, config: TrainingConfig) -> UUID
       async def get_status(self, job_id: UUID) -> TrainingStatus
       async def cancel_training(self, job_id: UUID) -> bool
   ```

2. Training job worker:
   - Queue training jobs
   - Process sequentially (GPU resource)
   - Update progress via SSE
   - Save model checkpoints

3. Model management:
   ```
   models/
     weights/
       base/
         yolov8n.pt
       custom/
         {object_id}/
           v1/model.pt
           v2/model.pt
   ```

### 4.4 Frontend Learning Page
- [ ] Create learn page layout
- [ ] Implement step wizard
- [ ] Create metadata form
- [ ] Integrate camera capture
- [ ] Show training progress

**Implementation Steps:**

1. Learn page wizard steps:
   - Step 1: Object Information (name, category, metadata)
   - Step 2: Image Capture/Upload
   - Step 3: Review and Annotate
   - Step 4: Start Training
   - Step 5: Training Progress

2. Metadata form fields:
   - Name (required)
   - Description
   - Reference code
   - Category
   - Weight and unit
   - Dimensions (W x H x D)
   - Price and currency
   - Color
   - Materials (multi-select)

3. Training progress display:
   - Progress bar
   - Current epoch / total
   - Loss graph (optional)
   - Estimated time remaining
   - Cancel button

## Verification Checklist

- [ ] Camera permission request works
- [ ] Camera preview displays correctly
- [ ] Images can be captured
- [ ] Multiple images can be captured
- [ ] Images can be uploaded
- [ ] Bounding boxes can be drawn
- [ ] Training can be started
- [ ] Training progress updates in real-time
- [ ] Training can be cancelled
- [ ] Trained model is saved
- [ ] Object status updates to "active" after training

## API Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | /api/v1/training/start | Start training job | Yes |
| GET | /api/v1/training/{jobId}/status | Get training status | Yes |
| POST | /api/v1/training/{jobId}/cancel | Cancel training | Yes |
| GET | /api/v1/training/stream | SSE training events | Yes |

## Next Steps
After completing learning, proceed to Milestone 5: Object Detection.
