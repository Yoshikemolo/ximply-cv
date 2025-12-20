import { Component, OnInit, OnDestroy, inject, signal, ElementRef, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';
import { DetectionService, DetectionResult, CaptureDetectionRequest } from '@core/services/detection.service';
import { Subscription } from 'rxjs';

// Color palette for different detection classes
const DETECTION_COLORS = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6',
  '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1',
];

@Component({
  selector: 'app-view-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './view-page.component.html',
  styleUrl: './view-page.component.scss',
})
export class ViewPageComponent implements OnInit, OnDestroy {
  @ViewChild('videoElement') videoElement!: ElementRef<HTMLVideoElement>;
  @ViewChild('canvasElement') canvasElement!: ElementRef<HTMLCanvasElement>;

  private readonly detectionService = inject(DetectionService);

  isStreaming = signal(false);
  isLoading = signal(false);
  detections = signal<Detection[]>([]);
  selectedCamera = signal<string>('');
  availableCameras = signal<MediaDeviceInfo[]>([]);
  errorMessage = signal<string | null>(null);
  confidenceThreshold = signal(0.5);
  fps = signal(0);

  // Capture modal state
  showCaptureModal = signal(false);
  selectedDetection = signal<Detection | null>(null);
  captureObjectName = signal('');
  captureObjectDescription = signal('');
  isSaving = signal(false);
  lastFrameBase64 = signal<string>('');

  private mediaStream: MediaStream | null = null;
  private animationFrameId: number | null = null;
  private detectionInterval: ReturnType<typeof setInterval> | null = null;
  private lastFrameTime = 0;
  private frameCount = 0;
  private isDetecting = false;
  private currentSubscription: Subscription | null = null;

  async ngOnInit(): Promise<void> {
    await this.loadCameras();
  }

  ngOnDestroy(): void {
    this.stopStream();
  }

  private async loadCameras(): Promise<void> {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoDevices = devices.filter(d => d.kind === 'videoinput');
      this.availableCameras.set(videoDevices);

      if (videoDevices.length > 0) {
        this.selectedCamera.set(videoDevices[0].deviceId);
      }
    } catch (error) {
      this.errorMessage.set('view.errors.cameraPermission');
    }
  }

  async startStream(): Promise<void> {
    if (this.isStreaming()) return;

    this.isLoading.set(true);
    this.errorMessage.set(null);

    try {
      // Load catalog features for custom object recognition
      this.detectionService.loadCatalogFeatures().subscribe({
        next: response => {
          console.log(`Loaded ${response.objectsLoaded} catalog objects for recognition`);
        },
        error: err => {
          console.warn('Could not load catalog features:', err);
        },
      });

      const constraints: MediaStreamConstraints = {
        video: {
          deviceId: this.selectedCamera() ? { exact: this.selectedCamera() } : undefined,
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 30 },
        },
      };

      this.mediaStream = await navigator.mediaDevices.getUserMedia(constraints);

      if (this.videoElement?.nativeElement) {
        this.videoElement.nativeElement.srcObject = this.mediaStream;
        await this.videoElement.nativeElement.play();
        this.isStreaming.set(true);
        this.startDetectionLoop();
      }
    } catch (error: any) {
      this.errorMessage.set('view.errors.streamFailed');
    } finally {
      this.isLoading.set(false);
    }
  }

  stopStream(): void {
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
    this.fps.set(0);
    this.isDetecting = false;
  }

  onCameraChange(event: Event): void {
    const select = event.target as HTMLSelectElement;
    this.selectedCamera.set(select.value);

    if (this.isStreaming()) {
      this.stopStream();
      this.startStream();
    }
  }

  onThresholdChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.confidenceThreshold.set(parseFloat(input.value));
  }

  private startDetectionLoop(): void {
    // Start rendering loop for drawing
    const renderFrame = (timestamp: number): void => {
      if (!this.isStreaming()) return;

      // Calculate FPS
      this.frameCount++;
      if (timestamp - this.lastFrameTime >= 1000) {
        this.fps.set(this.frameCount);
        this.frameCount = 0;
        this.lastFrameTime = timestamp;
      }

      // Draw video and detections
      this.renderDetections();

      this.animationFrameId = requestAnimationFrame(renderFrame);
    };

    this.animationFrameId = requestAnimationFrame(renderFrame);

    // Start detection interval (send frames to backend every 200ms)
    this.detectionInterval = setInterval(() => {
      this.sendFrameForDetection();
    }, 200);
  }

  private sendFrameForDetection(): void {
    if (this.isDetecting || !this.isStreaming()) return;

    const video = this.videoElement?.nativeElement;
    if (!video || video.videoWidth === 0) return;

    this.isDetecting = true;

    try {
      // Capture frame from video
      const imageBase64 = this.detectionService.captureFrame(video, 0.7);

      // Send to backend for detection
      this.currentSubscription = this.detectionService
        .detect(imageBase64, this.confidenceThreshold())
        .subscribe({
          next: (response) => {
            // Convert response to local Detection format with colors
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
          error: (err) => {
            console.error('Detection error:', err);
            this.isDetecting = false;
          },
        });
    } catch (error) {
      console.error('Failed to capture frame:', error);
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

    // Draw video frame
    ctx.drawImage(video, 0, 0);

    // Draw detections
    this.drawDetections(ctx);
  }

  private drawDetections(ctx: CanvasRenderingContext2D): void {
    const detections = this.detections();

    detections.forEach(detection => {
      if (detection.confidence < this.confidenceThreshold()) return;

      const { x, y, width, height } = detection.bbox;

      // Draw bounding box
      ctx.strokeStyle = detection.color || '#22c55e';
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, width, height);

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

  openCaptureModal(detection: Detection): void {
    // Capture current frame before opening modal
    const video = this.videoElement?.nativeElement;
    if (video) {
      this.lastFrameBase64.set(this.detectionService.captureFrame(video, 0.9));
    }

    this.selectedDetection.set(detection);
    this.captureObjectName.set('');
    this.captureObjectDescription.set('');
    this.showCaptureModal.set(true);
  }

  closeCaptureModal(): void {
    this.showCaptureModal.set(false);
    this.selectedDetection.set(null);
    this.captureObjectName.set('');
    this.captureObjectDescription.set('');
  }

  saveDetectionAsObject(): void {
    const detection = this.selectedDetection();
    const name = this.captureObjectName().trim();

    if (!detection || !name || !this.lastFrameBase64()) return;

    this.isSaving.set(true);

    const request: CaptureDetectionRequest = {
      image: this.lastFrameBase64(),
      bbox: detection.bbox,
      name,
      description: this.captureObjectDescription().trim() || undefined,
    };

    this.detectionService.captureDetection(request).subscribe({
      next: response => {
        console.log('Object saved to catalog:', response);

        // Refresh features so the new object can be recognized
        this.detectionService.refreshObjectFeatures(response.id).subscribe({
          next: () => console.log('Object features refreshed'),
          error: err => console.warn('Could not refresh features:', err),
        });

        this.isSaving.set(false);
        this.closeCaptureModal();
      },
      error: err => {
        console.error('Failed to save object:', err);
        this.isSaving.set(false);
        this.errorMessage.set('view.errors.saveFailed');
      },
    });
  }
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
