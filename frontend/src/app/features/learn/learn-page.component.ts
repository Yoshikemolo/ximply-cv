import { Component, OnDestroy, OnInit, inject, signal, ElementRef, ViewChild, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule, ActivatedRoute } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { DetectionService, DetectionResult } from '@core/services/detection.service';
import { ObjectsService, CatalogObject } from '@core/services/objects.service';
import { Subscription } from 'rxjs';

// Color palette for different detection classes
const DETECTION_COLORS = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
];

@Component({
  selector: 'app-learn-page',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './learn-page.component.html',
  styleUrl: './learn-page.component.scss',
})
export class LearnPageComponent implements OnInit, OnDestroy {
  @ViewChild('videoElement') videoElement!: ElementRef<HTMLVideoElement>;
  @ViewChild('canvasElement') canvasElement!: ElementRef<HTMLCanvasElement>;
  @ViewChild('annotationCanvas') annotationCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('annotationImage') annotationImage!: ElementRef<HTMLImageElement>;
  @ViewChild('imageReel') imageReel!: ElementRef<HTMLDivElement>;

  private readonly detectionService = inject(DetectionService);
  private readonly objectsService = inject(ObjectsService);
  private readonly route = inject(ActivatedRoute);

  // Learning mode: 'images' for static upload, 'camera' for live capture
  learningMode = signal<'images' | 'camera'>('images');

  // Retrain mode - when editing an existing object
  isRetrainMode = signal(false);
  retrainObject = signal<CatalogObject | null>(null);

  currentStep = signal<'upload' | 'annotate' | 'train' | 'complete'>('upload');
  uploadedImages = signal<UploadedImage[]>([]);
  selectedImage = signal<UploadedImage | null>(null);
  objectName = signal('');
  objectDescription = signal('');
  isTraining = signal(false);
  trainingProgress = signal(0);
  trainingMessage = signal('');
  errorMessage = signal<string | null>(null);

  constructor() {
    // Watch training progress from service
    effect(() => {
      const progress = this.objectsService.trainingProgress();
      if (progress) {
        this.trainingProgress.set(progress.progress);
        this.trainingMessage.set(progress.message || '');
        if (progress.status === 'error') {
          this.errorMessage.set(progress.message || 'Training failed');
          this.isTraining.set(false);
        }
      }
    });
  }

  // Annotation state
  isDrawing = signal(false);
  drawStart = signal<{ x: number; y: number } | null>(null);
  currentBox = signal<{ x: number; y: number; width: number; height: number } | null>(null);
  selectedAnnotationId = signal<string | null>(null);
  dragMode = signal<'none' | 'draw' | 'move' | 'resize'>('none');
  resizeHandle = signal<string | null>(null); // 'nw', 'ne', 'sw', 'se'
  dragOffset = signal<{ x: number; y: number }>({ x: 0, y: 0 });

  // Camera mode state
  isStreaming = signal(false);
  isLoading = signal(false);
  availableCameras = signal<MediaDeviceInfo[]>([]);
  selectedCamera = signal<string>('');
  detections = signal<Detection[]>([]);
  selectedDetection = signal<Detection | null>(null);
  capturedImages = signal<CapturedImage[]>([]);
  confidenceThreshold = signal(0.5);
  isCapturing = signal(false);

  private mediaStream: MediaStream | null = null;
  private animationFrameId: number | null = null;
  private detectionInterval: ReturnType<typeof setInterval> | null = null;
  private isDetecting = false;
  private currentSubscription: Subscription | null = null;
  private annotationAnimationId: number | null = null;

  ngOnInit(): void {
    // Check for retrain mode via query params
    this.route.queryParams.subscribe(params => {
      const objectId = params['objectId'];
      if (objectId) {
        this.loadObjectForRetrain(objectId);
      }
    });
  }

  ngOnDestroy(): void {
    this.stopCamera();
  }

  private async loadObjectForRetrain(objectId: string): Promise<void> {
    try {
      const object = await this.objectsService.getObject(objectId).toPromise();
      if (object) {
        this.isRetrainMode.set(true);
        this.retrainObject.set(object);
        this.objectName.set(object.name);
        this.objectDescription.set(object.description || '');
      }
    } catch (error) {
      console.error('Failed to load object for retrain:', error);
      this.errorMessage.set('Failed to load object');
    }
  }

  setLearningMode(mode: 'images' | 'camera'): void {
    if (this.learningMode() === mode) return;

    // Reset state when switching modes
    if (mode === 'images') {
      this.stopCamera();
    }

    this.learningMode.set(mode);
    this.resetWizard();
  }

  // ===== Image Upload Mode Methods =====

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = input.files;

    if (!files || files.length === 0) return;

    Array.from(files).forEach(file => {
      if (!file.type.startsWith('image/')) return;

      const reader = new FileReader();
      reader.onload = (e) => {
        const preview = e.target?.result as string;

        // Load image to get natural dimensions for full-image annotation
        const tempImg = new Image();
        tempImg.onload = () => {
          // Create full-image bounding box by default (same as "Select All" button)
          const fullImageAnnotation: Annotation = {
            id: crypto.randomUUID(),
            x: 0,
            y: 0,
            width: tempImg.naturalWidth,
            height: tempImg.naturalHeight,
            label: this.objectName() || 'object',
          };

          const image: UploadedImage = {
            id: crypto.randomUUID(),
            file,
            preview,
            annotations: [fullImageAnnotation],
          };
          this.uploadedImages.update(imgs => [...imgs, image]);
        };
        tempImg.src = preview;
      };
      reader.readAsDataURL(file);
    });

    input.value = '';
  }

  removeImage(imageId: string): void {
    this.uploadedImages.update(imgs => imgs.filter(img => img.id !== imageId));
    if (this.selectedImage()?.id === imageId) {
      this.selectedImage.set(null);
    }
  }

  selectImage(image: UploadedImage): void {
    this.selectedImage.set(image);
    // Reset drawing state and redraw canvas after image loads
    this.currentBox.set(null);
    this.isDrawing.set(false);
    this.selectedAnnotationId.set(null);
    // Wait for image to load then render
    setTimeout(() => this.renderAnnotationCanvas(), 50);
  }

  onReelWheel(event: WheelEvent): void {
    const reel = this.imageReel?.nativeElement;
    if (!reel) return;

    // Convert vertical scroll to horizontal scroll
    event.preventDefault();
    reel.scrollLeft += event.deltaY;
  }

  // ===== Annotation Drawing Methods =====

  onAnnotationImageLoad(): void {
    this.renderAnnotationCanvas();
  }

  onAnnotationMouseDown(event: MouseEvent): void {
    const canvas = this.annotationCanvas?.nativeElement;
    const image = this.annotationImage?.nativeElement;
    const selectedImg = this.selectedImage();
    if (!canvas || !image || !selectedImg) return;

    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;

    // Calculate scale between display and natural size
    const scaleX = image.offsetWidth / image.naturalWidth;
    const scaleY = image.offsetHeight / image.naturalHeight;

    // Check if clicking on a resize handle of selected annotation
    const selectedId = this.selectedAnnotationId();
    if (selectedId) {
      const selectedAnnotation = selectedImg.annotations.find(a => a.id === selectedId);
      if (selectedAnnotation) {
        const handle = this.getResizeHandleAtPoint(x, y, selectedAnnotation, scaleX, scaleY);
        if (handle) {
          this.dragMode.set('resize');
          this.resizeHandle.set(handle);
          this.drawStart.set({ x, y });
          return;
        }
      }
    }

    // Check if clicking inside an existing annotation
    for (const annotation of selectedImg.annotations) {
      const ax = annotation.x * scaleX;
      const ay = annotation.y * scaleY;
      const aw = annotation.width * scaleX;
      const ah = annotation.height * scaleY;

      if (x >= ax && x <= ax + aw && y >= ay && y <= ay + ah) {
        this.selectedAnnotationId.set(annotation.id);
        this.dragMode.set('move');
        this.dragOffset.set({ x: x - ax, y: y - ay });
        this.drawStart.set({ x, y });
        this.renderAnnotationCanvas();
        return;
      }
    }

    // Clear selection and start drawing new box
    this.selectedAnnotationId.set(null);
    this.dragMode.set('draw');
    this.isDrawing.set(true);
    this.drawStart.set({ x, y });
    this.currentBox.set(null);
  }

  onAnnotationMouseMove(event: MouseEvent): void {
    const canvas = this.annotationCanvas?.nativeElement;
    const image = this.annotationImage?.nativeElement;
    const selectedImg = this.selectedImage();
    if (!canvas || !image || !selectedImg) return;

    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(event.clientX - rect.left, canvas.width));
    const y = Math.max(0, Math.min(event.clientY - rect.top, canvas.height));

    const scaleX = image.offsetWidth / image.naturalWidth;
    const scaleY = image.offsetHeight / image.naturalHeight;

    const mode = this.dragMode();
    const start = this.drawStart();

    if (mode === 'draw' && this.isDrawing() && start) {
      const box = {
        x: Math.min(start.x, x),
        y: Math.min(start.y, y),
        width: Math.abs(x - start.x),
        height: Math.abs(y - start.y),
      };
      this.currentBox.set(box);
      this.renderAnnotationCanvas();
    } else if (mode === 'move' && start) {
      const selectedId = this.selectedAnnotationId();
      if (selectedId) {
        const offset = this.dragOffset();
        const newX = (x - offset.x) / scaleX;
        const newY = (y - offset.y) / scaleY;

        this.updateAnnotation(selectedId, { x: newX, y: newY });
        this.renderAnnotationCanvas();
      }
    } else if (mode === 'resize' && start) {
      const selectedId = this.selectedAnnotationId();
      const handle = this.resizeHandle();
      if (selectedId && handle) {
        this.resizeAnnotation(selectedId, handle, x, y, scaleX, scaleY);
        this.renderAnnotationCanvas();
      }
    } else {
      // Update cursor based on hover position
      this.updateCursor(x, y, scaleX, scaleY);
    }
  }

  onAnnotationMouseUp(event: MouseEvent): void {
    const mode = this.dragMode();

    if (mode === 'draw' && this.isDrawing() && this.currentBox()) {
      const box = this.currentBox()!;
      const image = this.annotationImage?.nativeElement;

      if (image && box.width >= 10 && box.height >= 10) {
        // Convert display coordinates to natural image coordinates
        const scaleX = image.offsetWidth / image.naturalWidth;
        const scaleY = image.offsetHeight / image.naturalHeight;

        const annotation: Annotation = {
          id: crypto.randomUUID(),
          x: box.x / scaleX,
          y: box.y / scaleY,
          width: box.width / scaleX,
          height: box.height / scaleY,
          label: this.objectName() || 'object',
        };

        const selectedImg = this.selectedImage();
        if (selectedImg) {
          this.uploadedImages.update(images =>
            images.map(img =>
              img.id === selectedImg.id
                ? { ...img, annotations: [...img.annotations, annotation] }
                : img
            )
          );
          const updated = this.uploadedImages().find(img => img.id === selectedImg.id);
          if (updated) {
            this.selectedImage.set(updated);
          }
          // Select the newly created annotation
          this.selectedAnnotationId.set(annotation.id);
        }
      }
    }

    this.isDrawing.set(false);
    this.drawStart.set(null);
    this.currentBox.set(null);
    this.dragMode.set('none');
    this.resizeHandle.set(null);
    this.renderAnnotationCanvas();
  }

  onAnnotationMouseLeave(): void {
    if (this.isDrawing() || this.dragMode() !== 'none') {
      this.isDrawing.set(false);
      this.drawStart.set(null);
      this.currentBox.set(null);
      this.dragMode.set('none');
      this.resizeHandle.set(null);
      this.renderAnnotationCanvas();
    }
  }

  private getResizeHandleAtPoint(
    x: number, y: number,
    annotation: Annotation,
    scaleX: number, scaleY: number
  ): string | null {
    const handleSize = 8;
    const ax = annotation.x * scaleX;
    const ay = annotation.y * scaleY;
    const aw = annotation.width * scaleX;
    const ah = annotation.height * scaleY;

    const handles: { [key: string]: { x: number; y: number } } = {
      'nw': { x: ax, y: ay },
      'ne': { x: ax + aw, y: ay },
      'sw': { x: ax, y: ay + ah },
      'se': { x: ax + aw, y: ay + ah },
    };

    for (const [handle, pos] of Object.entries(handles)) {
      if (Math.abs(x - pos.x) <= handleSize && Math.abs(y - pos.y) <= handleSize) {
        return handle;
      }
    }
    return null;
  }

  private updateAnnotation(id: string, updates: Partial<Annotation>): void {
    const selectedImg = this.selectedImage();
    if (!selectedImg) return;

    this.uploadedImages.update(images =>
      images.map(img =>
        img.id === selectedImg.id
          ? {
              ...img,
              annotations: img.annotations.map(a =>
                a.id === id ? { ...a, ...updates } : a
              ),
            }
          : img
      )
    );

    const updated = this.uploadedImages().find(img => img.id === selectedImg.id);
    if (updated) {
      this.selectedImage.set(updated);
    }
  }

  private resizeAnnotation(
    id: string,
    handle: string,
    mouseX: number,
    mouseY: number,
    scaleX: number,
    scaleY: number
  ): void {
    const selectedImg = this.selectedImage();
    if (!selectedImg) return;

    const annotation = selectedImg.annotations.find(a => a.id === id);
    if (!annotation) return;

    const image = this.annotationImage?.nativeElement;
    if (!image) return;

    // Convert mouse position to natural coordinates
    const mx = mouseX / scaleX;
    const my = mouseY / scaleY;

    let newX = annotation.x;
    let newY = annotation.y;
    let newWidth = annotation.width;
    let newHeight = annotation.height;

    switch (handle) {
      case 'nw':
        newWidth = annotation.x + annotation.width - mx;
        newHeight = annotation.y + annotation.height - my;
        newX = mx;
        newY = my;
        break;
      case 'ne':
        newWidth = mx - annotation.x;
        newHeight = annotation.y + annotation.height - my;
        newY = my;
        break;
      case 'sw':
        newWidth = annotation.x + annotation.width - mx;
        newHeight = my - annotation.y;
        newX = mx;
        break;
      case 'se':
        newWidth = mx - annotation.x;
        newHeight = my - annotation.y;
        break;
    }

    // Ensure minimum size
    if (newWidth >= 10 && newHeight >= 10) {
      // Clamp to image bounds
      newX = Math.max(0, Math.min(newX, image.naturalWidth - 10));
      newY = Math.max(0, Math.min(newY, image.naturalHeight - 10));
      newWidth = Math.min(newWidth, image.naturalWidth - newX);
      newHeight = Math.min(newHeight, image.naturalHeight - newY);

      this.updateAnnotation(id, { x: newX, y: newY, width: newWidth, height: newHeight });
    }
  }

  private updateCursor(x: number, y: number, scaleX: number, scaleY: number): void {
    const canvas = this.annotationCanvas?.nativeElement;
    const selectedImg = this.selectedImage();
    if (!canvas || !selectedImg) return;

    const selectedId = this.selectedAnnotationId();
    if (selectedId) {
      const annotation = selectedImg.annotations.find(a => a.id === selectedId);
      if (annotation) {
        const handle = this.getResizeHandleAtPoint(x, y, annotation, scaleX, scaleY);
        if (handle) {
          canvas.style.cursor = handle === 'nw' || handle === 'se' ? 'nwse-resize' : 'nesw-resize';
          return;
        }
      }
    }

    // Check if hovering over any annotation
    for (const annotation of selectedImg.annotations) {
      const ax = annotation.x * scaleX;
      const ay = annotation.y * scaleY;
      const aw = annotation.width * scaleX;
      const ah = annotation.height * scaleY;

      if (x >= ax && x <= ax + aw && y >= ay && y <= ay + ah) {
        canvas.style.cursor = 'move';
        return;
      }
    }

    canvas.style.cursor = 'crosshair';
  }

  selectAllImage(): void {
    const image = this.annotationImage?.nativeElement;
    const selectedImg = this.selectedImage();
    if (!image || !selectedImg) return;

    const annotation: Annotation = {
      id: crypto.randomUUID(),
      x: 0,
      y: 0,
      width: image.naturalWidth,
      height: image.naturalHeight,
      label: this.objectName() || 'object',
    };

    this.uploadedImages.update(images =>
      images.map(img =>
        img.id === selectedImg.id
          ? { ...img, annotations: [...img.annotations, annotation] }
          : img
      )
    );

    const updated = this.uploadedImages().find(img => img.id === selectedImg.id);
    if (updated) {
      this.selectedImage.set(updated);
    }
    this.selectedAnnotationId.set(annotation.id);
    this.renderAnnotationCanvas();
  }

  removeAnnotation(annotationId: string): void {
    const selectedImg = this.selectedImage();
    if (!selectedImg) return;

    this.uploadedImages.update(images =>
      images.map(img =>
        img.id === selectedImg.id
          ? { ...img, annotations: img.annotations.filter(a => a.id !== annotationId) }
          : img
      )
    );

    const updated = this.uploadedImages().find(img => img.id === selectedImg.id);
    if (updated) {
      this.selectedImage.set(updated);
    }
    this.renderAnnotationCanvas();
  }

  renderAnnotationCanvas(): void {
    const canvas = this.annotationCanvas?.nativeElement;
    const image = this.annotationImage?.nativeElement;
    const selectedImg = this.selectedImage();

    if (!canvas || !image || !selectedImg) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Set canvas size to match image display size
    canvas.width = image.offsetWidth;
    canvas.height = image.offsetHeight;

    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Calculate scale between natural and display size
    const scaleX = image.offsetWidth / image.naturalWidth;
    const scaleY = image.offsetHeight / image.naturalHeight;

    const selectedId = this.selectedAnnotationId();

    // Draw existing annotations
    selectedImg.annotations.forEach((annotation, index) => {
      const color = DETECTION_COLORS[index % DETECTION_COLORS.length];
      const isSelected = annotation.id === selectedId;

      const ax = annotation.x * scaleX;
      const ay = annotation.y * scaleY;
      const aw = annotation.width * scaleX;
      const ah = annotation.height * scaleY;

      // Draw selection highlight
      if (isSelected) {
        ctx.fillStyle = `${color}22`;
        ctx.fillRect(ax, ay, aw, ah);
      }

      ctx.strokeStyle = color;
      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.strokeRect(ax, ay, aw, ah);

      // Draw label
      const label = annotation.label;
      ctx.font = '12px Inter, sans-serif';
      const textMetrics = ctx.measureText(label);
      const textHeight = 18;

      ctx.fillStyle = color;
      ctx.fillRect(ax, ay - textHeight, textMetrics.width + 8, textHeight);

      ctx.fillStyle = '#ffffff';
      ctx.fillText(label, ax + 4, ay - 5);

      // Draw resize handles for selected annotation
      if (isSelected) {
        this.drawResizeHandles(ctx, ax, ay, aw, ah, color);
      }
    });

    // Draw current box being drawn
    const currentBox = this.currentBox();
    if (currentBox && this.isDrawing()) {
      ctx.strokeStyle = '#3b82f6';
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 5]);
      ctx.strokeRect(currentBox.x, currentBox.y, currentBox.width, currentBox.height);
      ctx.setLineDash([]);

      // Draw semi-transparent fill
      ctx.fillStyle = 'rgba(59, 130, 246, 0.1)';
      ctx.fillRect(currentBox.x, currentBox.y, currentBox.width, currentBox.height);
    }
  }

  private drawResizeHandles(
    ctx: CanvasRenderingContext2D,
    x: number, y: number,
    width: number, height: number,
    color: string
  ): void {
    const handleSize = 8;
    const handles = [
      { x: x, y: y },                     // nw
      { x: x + width, y: y },             // ne
      { x: x, y: y + height },            // sw
      { x: x + width, y: y + height },    // se
    ];

    handles.forEach(handle => {
      // White fill with colored border
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(
        handle.x - handleSize / 2,
        handle.y - handleSize / 2,
        handleSize,
        handleSize
      );
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(
        handle.x - handleSize / 2,
        handle.y - handleSize / 2,
        handleSize,
        handleSize
      );
    });
  }

  // ===== Camera Mode Methods =====

  async loadCameras(): Promise<void> {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoDevices = devices.filter(d => d.kind === 'videoinput');
      this.availableCameras.set(videoDevices);

      if (videoDevices.length > 0 && !this.selectedCamera()) {
        this.selectedCamera.set(videoDevices[0].deviceId);
      }
    } catch (error) {
      this.errorMessage.set('learn.camera.errors.permission');
    }
  }

  async startCamera(): Promise<void> {
    if (this.isStreaming()) return;

    this.isLoading.set(true);
    this.errorMessage.set(null);

    try {
      await this.loadCameras();

      // Build video constraints
      const videoConstraints: MediaTrackConstraints = {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        frameRate: { ideal: 30 },
      };

      // Only add deviceId constraint if we have a valid selection
      const cameraId = this.selectedCamera();
      if (cameraId && cameraId.length > 0) {
        videoConstraints.deviceId = { exact: cameraId };
      }

      const constraints: MediaStreamConstraints = {
        video: videoConstraints,
      };

      this.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);

      if (this.videoElement?.nativeElement) {
        this.videoElement.nativeElement.srcObject = this.mediaStream;
        await this.videoElement.nativeElement.play();
        this.isStreaming.set(true);
        this.startDetectionLoop();
      }
    } catch (error: any) {
      console.error('Camera error:', error);
      this.errorMessage.set('learn.camera.errors.streamFailed');
    } finally {
      this.isLoading.set(false);
    }
  }

  stopCamera(): void {
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }

    if (this.detectionInterval) {
      clearInterval(this.detectionInterval);
      this.detectionInterval = null;
    }

    if (this.currentSubscription) {
      this.currentSubscription.unsubscribe();
      this.currentSubscription = null;
    }

    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }

    if (this.videoElement?.nativeElement) {
      this.videoElement.nativeElement.srcObject = null;
    }

    this.isStreaming.set(false);
    this.detections.set([]);
    this.isDetecting = false;
  }

  onCameraChange(event: Event): void {
    const select = event.target as HTMLSelectElement;
    this.selectedCamera.set(select.value);

    if (this.isStreaming()) {
      this.stopCamera();
      this.startCamera();
    }
  }

  onThresholdChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.confidenceThreshold.set(parseFloat(input.value));
  }

  private startDetectionLoop(): void {
    const renderFrame = (): void => {
      if (!this.isStreaming()) return;
      this.renderDetections();
      this.animationFrameId = requestAnimationFrame(renderFrame);
    };

    this.animationFrameId = requestAnimationFrame(renderFrame);

    // Start detection interval (send frames to backend every 300ms)
    this.detectionInterval = setInterval(() => {
      this.sendFrameForDetection();
    }, 300);
  }

  private sendFrameForDetection(): void {
    if (this.isDetecting || !this.isStreaming()) return;

    const video = this.videoElement?.nativeElement;
    if (!video || video.videoWidth === 0) return;

    this.isDetecting = true;

    try {
      const imageBase64 = this.detectionService.captureFrame(video, 0.7);

      this.currentSubscription = this.detectionService
        .detect(imageBase64, this.confidenceThreshold())
        .subscribe({
          next: (response) => {
            const newDetections: Detection[] = response.detections.map((d, i) => ({
              id: `${d.label}-${i}-${Date.now()}`,
              label: d.label,
              confidence: d.confidence,
              bbox: d.bbox,
              color: DETECTION_COLORS[d.classId ? d.classId % DETECTION_COLORS.length : i % DETECTION_COLORS.length],
            }));
            this.detections.set(newDetections);
            this.isDetecting = false;
          },
          error: () => {
            this.isDetecting = false;
          },
        });
    } catch (error) {
      this.isDetecting = false;
    }
  }

  private renderDetections(): void {
    const canvas = this.canvasElement?.nativeElement;
    const video = this.videoElement?.nativeElement;

    if (!canvas || !video) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    ctx.drawImage(video, 0, 0);
    this.drawDetections(ctx);
  }

  private drawDetections(ctx: CanvasRenderingContext2D): void {
    const detections = this.detections();
    const selected = this.selectedDetection();

    detections.forEach(detection => {
      if (detection.confidence < this.confidenceThreshold()) return;

      const { x, y, width, height } = detection.bbox;
      const isSelected = selected?.id === detection.id;

      // Draw bounding box
      ctx.strokeStyle = detection.color || '#22c55e';
      ctx.lineWidth = isSelected ? 4 : 2;
      ctx.strokeRect(x, y, width, height);

      // Draw selection highlight
      if (isSelected) {
        ctx.fillStyle = `${detection.color}33`;
        ctx.fillRect(x, y, width, height);
      }

      // Draw label background
      const label = `${detection.label} ${(detection.confidence * 100).toFixed(0)}%`;
      ctx.font = '14px Inter, sans-serif';
      const textMetrics = ctx.measureText(label);
      const textHeight = 20;

      ctx.fillStyle = detection.color || '#22c55e';
      ctx.fillRect(x, y - textHeight, textMetrics.width + 8, textHeight);

      // Draw label text
      ctx.fillStyle = '#ffffff';
      ctx.fillText(label, x + 4, y - 6);
    });
  }

  selectDetection(detection: Detection): void {
    if (this.selectedDetection()?.id === detection.id) {
      this.selectedDetection.set(null);
    } else {
      this.selectedDetection.set(detection);
    }
  }

  onCanvasClick(event: MouseEvent): void {
    const canvas = this.canvasElement?.nativeElement;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;

    const x = (event.clientX - rect.left) * scaleX;
    const y = (event.clientY - rect.top) * scaleY;

    // Find which detection was clicked
    const detections = this.detections();
    for (const detection of detections) {
      const { x: bx, y: by, width, height } = detection.bbox;
      if (x >= bx && x <= bx + width && y >= by && y <= by + height) {
        this.selectDetection(detection);
        return;
      }
    }

    // Clicked outside any detection
    this.selectedDetection.set(null);
  }

  captureSelectedObject(): void {
    const detection = this.selectedDetection();
    const video = this.videoElement?.nativeElement;

    if (!detection || !video) return;

    this.isCapturing.set(true);

    try {
      // Capture the full frame
      const frameBase64 = this.detectionService.captureFrame(video, 0.9);

      // Crop the detection region
      const croppedImage = this.cropDetection(video, detection.bbox);

      const captured: CapturedImage = {
        id: crypto.randomUUID(),
        preview: croppedImage,
        fullFrame: frameBase64,
        bbox: detection.bbox,
        label: detection.label,
        confidence: detection.confidence,
      };

      this.capturedImages.update(imgs => [...imgs, captured]);
    } finally {
      this.isCapturing.set(false);
    }
  }

  private cropDetection(
    video: HTMLVideoElement,
    bbox: { x: number; y: number; width: number; height: number }
  ): string {
    const canvas = document.createElement('canvas');
    canvas.width = bbox.width;
    canvas.height = bbox.height;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('Failed to get canvas context');
    }

    ctx.drawImage(
      video,
      bbox.x, bbox.y, bbox.width, bbox.height,
      0, 0, bbox.width, bbox.height
    );

    return canvas.toDataURL('image/jpeg', 0.9);
  }

  removeCapturedImage(imageId: string): void {
    this.capturedImages.update(imgs => imgs.filter(img => img.id !== imageId));
  }

  // ===== Navigation Methods =====

  nextStep(): void {
    const steps: Array<'upload' | 'annotate' | 'train' | 'complete'> = [
      'upload', 'annotate', 'train', 'complete'
    ];
    const currentIndex = steps.indexOf(this.currentStep());
    if (currentIndex < steps.length - 1) {
      // When moving from upload to annotate in camera mode, stop camera
      if (this.currentStep() === 'upload' && this.learningMode() === 'camera') {
        this.stopCamera();
      }

      // When moving to annotate step, auto-select first image
      if (this.currentStep() === 'upload' && this.learningMode() === 'images') {
        const images = this.uploadedImages();
        if (images.length > 0) {
          this.selectImage(images[0]);
          if (images[0].annotations.length > 0) {
            this.selectedAnnotationId.set(images[0].annotations[0].id);
          }
        }
      }

      this.currentStep.set(steps[currentIndex + 1]);
    }
  }

  previousStep(): void {
    const steps: Array<'upload' | 'annotate' | 'train' | 'complete'> = [
      'upload', 'annotate', 'train', 'complete'
    ];
    const currentIndex = steps.indexOf(this.currentStep());
    if (currentIndex > 0) {
      this.currentStep.set(steps[currentIndex - 1]);
    }
  }

  canProceed(): boolean {
    const minImages = 5;

    switch (this.currentStep()) {
      case 'upload':
        if (this.learningMode() === 'camera') {
          return this.capturedImages().length >= minImages && this.objectName().trim().length > 0;
        }
        return this.uploadedImages().length >= minImages && this.objectName().trim().length > 0;
      case 'annotate':
        if (this.learningMode() === 'camera') {
          // Camera mode auto-annotates via detection
          return this.capturedImages().length >= minImages;
        }
        return this.uploadedImages().every(img => img.annotations.length > 0);
      case 'train':
        return !this.isTraining();
      default:
        return false;
    }
  }

  async startTraining(): Promise<void> {
    this.isTraining.set(true);
    this.trainingProgress.set(0);
    this.trainingMessage.set('Preparing images...');
    this.errorMessage.set(null);

    try {
      // Prepare images with annotations/bboxes
      const images = this.prepareTrainingImages();

      if (images.length === 0) {
        throw new Error('No images to train with');
      }

      if (this.isRetrainMode() && this.retrainObject()) {
        // Add images to existing object
        const objectId = this.retrainObject()!.id;
        await this.objectsService.addTrainingImages(objectId, images);
      } else {
        // Create new object and train
        const description = this.objectDescription() || `Trained with ${images.length} images`;
        await this.objectsService.trainObject(
          this.objectName(),
          description,
          images
        );
      }

      this.isTraining.set(false);
      this.nextStep();

    } catch (error: any) {
      console.error('Training failed:', error);
      this.errorMessage.set(error.message || 'Training failed');
      this.isTraining.set(false);
    }
  }

  private prepareTrainingImages(): Array<{ data: string; bbox?: { x: number; y: number; width: number; height: number } }> {
    const images: Array<{ data: string; bbox?: { x: number; y: number; width: number; height: number } }> = [];

    if (this.learningMode() === 'camera') {
      // Camera mode: use cropped preview images (already cropped to detection bbox)
      // Do NOT use fullFrame as it contains the entire scene, not just the object
      const captured = this.capturedImages();
      for (const img of captured) {
        images.push({
          data: img.preview, // Use cropped image, not full frame
        });
      }
    } else {
      // Image upload mode: use annotations as bboxes
      const uploaded = this.uploadedImages();
      for (const img of uploaded) {
        if (img.annotations.length > 0) {
          // Use first annotation as primary bbox
          const annotation = img.annotations[0];
          images.push({
            data: img.preview,
            bbox: {
              x: annotation.x,
              y: annotation.y,
              width: annotation.width,
              height: annotation.height,
            },
          });
        } else {
          // No annotation - use full image
          images.push({
            data: img.preview,
          });
        }
      }
    }

    return images;
  }

  resetWizard(): void {
    this.stopCamera();
    this.currentStep.set('upload');
    this.uploadedImages.set([]);
    this.capturedImages.set([]);
    this.selectedImage.set(null);
    this.selectedDetection.set(null);
    this.objectName.set('');
    this.trainingProgress.set(0);
    this.errorMessage.set(null);
  }

  getImageCount(): number {
    return this.learningMode() === 'camera'
      ? this.capturedImages().length
      : this.uploadedImages().length;
  }
}

interface UploadedImage {
  id: string;
  file: File;
  preview: string;
  annotations: Annotation[];
}

interface Annotation {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
}

interface Detection {
  id: string;
  label: string;
  confidence: number;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  color?: string;
}

interface CapturedImage {
  id: string;
  preview: string;
  fullFrame: string;
  bbox: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
  label: string;
  confidence: number;
}
