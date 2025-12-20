# Feature: Learn (Object Training)

## Overview
The Learn feature allows users to train the detection model with new objects by capturing images from camera or uploading photos, adding metadata, and initiating the training process.

## User Stories

### US-010: Create New Object
**As a** user with training permissions
**I want to** create a new object in the catalog
**So that** I can train the system to recognize it

**Acceptance Criteria:**
- Object name is required
- Optional metadata fields are available
- Object is created in draft status
- User can add images after creation

### US-011: Capture Training Images
**As a** user training a new object
**I want to** capture images directly from camera
**So that** I can quickly add training data

**Acceptance Criteria:**
- Camera preview shows the object
- Capture button takes photo
- Multiple captures allowed
- Preview of captured images shown
- Can delete unwanted captures

### US-012: Upload Training Images
**As a** user training a new object
**I want to** upload existing images
**So that** I can use previously taken photos

**Acceptance Criteria:**
- Drag and drop supported
- Multiple file selection
- Image format validation
- Size limit enforced
- Upload progress shown

### US-013: Start Training
**As a** user with training images
**I want to** start the training process
**So that** the system learns to recognize my object

**Acceptance Criteria:**
- Minimum image requirement met
- Training progress is displayed
- Training can be cancelled
- Success/failure notification
- Object status updates on completion

## UI Components

### Step Wizard
1. **Object Information**
   - Name (required)
   - Description
   - Reference code
   - Category selection

2. **Physical Properties**
   - Weight and unit
   - Dimensions (W x H x D)
   - Color
   - Materials

3. **Commercial Properties**
   - Price and currency
   - Additional metadata

4. **Image Collection**
   - Camera capture option
   - File upload option
   - Image gallery with delete
   - Minimum images indicator

5. **Review and Train**
   - Summary of object details
   - Image count
   - Start training button
   - Training configuration

### Camera Capture
- Live video preview
- Capture button
- Guide overlay (optional)
- Thumbnail strip of captures
- Retake/delete options

### Image Upload
- Drag and drop zone
- File browser button
- Upload progress bars
- Error handling

### Training Progress
- Progress bar
- Current epoch indicator
- Estimated time remaining
- Cancel button
- Success/error message

## Technical Implementation

### Image Capture
```typescript
async captureImage(): Promise<void> {
  const canvas = document.createElement('canvas');
  canvas.width = this.videoElement.videoWidth;
  canvas.height = this.videoElement.videoHeight;

  const ctx = canvas.getContext('2d');
  ctx.drawImage(this.videoElement, 0, 0);

  const blob = await new Promise<Blob>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', 0.9)
  );

  this.capturedImages.push({
    id: uuid(),
    blob,
    preview: URL.createObjectURL(blob)
  });
}
```

### File Upload
```typescript
async uploadImages(objectId: string, files: File[]): Promise<void> {
  for (const file of files) {
    const formData = new FormData();
    formData.append('file', file);

    await this.http.post(
      `${API_URL}/objects/${objectId}/images`,
      formData,
      { reportProgress: true }
    ).subscribe(event => {
      if (event.type === HttpEventType.UploadProgress) {
        this.uploadProgress = event.loaded / event.total;
      }
    });
  }
}
```

### Training Initiation
```typescript
startTraining(objectId: string, config: TrainingConfig): Observable<TrainingStatus> {
  return this.http.post<TrainingStatus>(
    `${API_URL}/training/start`,
    { objectId, ...config }
  );
}
```

## Validation Rules

### Object
- Name: 1-255 characters, required
- Reference: max 100 characters
- Weight: positive number
- Dimensions: positive numbers
- Price: positive number

### Images
- Formats: JPEG, PNG, WebP
- Max size: 10MB per image
- Min images for training: 5
- Recommended: 15-30 images
- Various angles recommended

## Permissions Required
- `objects:write` - Create objects
- `objects:train` - Train models

## Related Features
- [Catalog](./catalog.md) - View trained objects
- [View](./view.md) - Test detection
