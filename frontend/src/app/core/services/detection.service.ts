/**
 * Detection service.
 *
 * Handles communication with the backend detection API.
 */

import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '@env';
import { LoadCatalogResponse, RefreshFeaturesResponse } from './objects.service';

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DetectionResult {
  label: string;
  /** How sure the detector is that something is there. */
  confidence: number;
  bbox: BoundingBox;
  classId?: number;
  objectId?: string;
  objectName?: string;
  /**
   * How sure the matcher is that it is this particular catalog entry.
   *
   * Separate from `confidence` on purpose: a bus detected at 92% can still be a
   * poor match for a phone in the catalog, and showing the detector's number
   * next to the wrong name would state a guess as a fact.
   */
  matchConfidence?: number;
  /**
   * Outline of the object as [x, y] pixel pairs, when segmentation ran.
   *
   * Absent means there is no silhouette for this detection and the bounding box
   * is what should be drawn.
   */
  polygon?: number[][];
}

export interface BarcodeResult {
  barcodeType: string;  // EAN13, EAN8, UPC, QR, Code128, etc.
  data: string;  // The decoded barcode value
  bbox: BoundingBox;
  quality: number;
}

/** One joint of a skeleton, in pixel coordinates of the source frame. */
export interface SkeletonKeypoint {
  name: string;
  x: number;
  y: number;
  /** Depth relative to the subject, for shading the mesh instead of drawing it flat. */
  z?: number;
  score: number;
}

/** One bone, joining two keypoints by their index in the keypoint array. */
export interface SkeletonEdge {
  from: number;
  to: number;
  part: string;
}

/**
 * A wireframe over one body or one hand.
 *
 * Bodies use the 33 point BlazePose layout, hands the 21 landmark layout and
 * faces the 478 point mesh. The edges arrive with the skeleton, so drawing
 * never needs to know which layout it is looking at. They are sent once per
 * kind per frame, since the face mesh runs to thousands of edges that never
 * change, so the client caches the last set it saw for each kind.
 */
export interface SkeletonResult {
  kind: 'body' | 'hand' | 'face';
  label?: string;
  score: number;
  bbox: BoundingBox;
  keypoints: SkeletonKeypoint[];
  edges: SkeletonEdge[];
}

export interface DetectionResponse {
  detections: DetectionResult[];
  barcodes: BarcodeResult[];
  skeletons?: SkeletonResult[];
  frameWidth: number;
  frameHeight: number;
  processingTimeMs: number;
  timestamp: string;
}

export interface DetectRequest {
  image: string;
  confidenceThreshold?: number;
  iouThreshold?: number;
  hidePersonDetections?: boolean;
  showOnlyCustomObjects?: boolean;
  includeSkeletons?: boolean;
  includeFaceMesh?: boolean;
  detectionModel?: 'yolo' | 'sam';
  segmentationTightness?: number;
  segmentationExcludeSiblings?: boolean;
}

export interface CaptureDetectionRequest {
  image: string;
  bbox: BoundingBox;
  name: string;
  description?: string;
  categoryId?: string;
}

export interface CapturedObject {
  id: string;
  name: string;
  description?: string;
  status: string;
  thumbnailPath?: string;
  trainingSamples: number;
  createdAt: string;
}

@Injectable({
  providedIn: 'root',
})
export class DetectionService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiUrl}/${environment.apiVersion}/detection`;

  /**
   * Detect objects in a base64 encoded image.
   *
   * @param image - Base64 encoded image (with or without data URI prefix).
   * @param confidenceThreshold - Minimum confidence for detections.
   * @returns Observable of detection results.
   */
  detect(
    image: string,
    confidenceThreshold?: number,
    options?: {
      hidePersonDetections?: boolean;
      showOnlyCustomObjects?: boolean;
      includeSkeletons?: boolean;
      includeFaceMesh?: boolean;
      detectionModel?: 'yolo' | 'sam';
      segmentationTightness?: number;
      segmentationExcludeSiblings?: boolean;
    }
  ): Observable<DetectionResponse> {
    const request: DetectRequest = {
      image,
      confidenceThreshold,
      // The view toggles travel with the request because the backend resolves
      // overlapping boxes before answering. Filtering only on arrival would let
      // a hidden box suppress a visible one and leave a gap on screen.
      hidePersonDetections: options?.hidePersonDetections ?? false,
      showOnlyCustomObjects: options?.showOnlyCustomObjects ?? false,
      // Sent rather than filtered on arrival: the landmark models are the
      // expensive part of a frame, so an overlay that is switched off should
      // not be computed at all.
      includeSkeletons: options?.includeSkeletons ?? true,
      includeFaceMesh: options?.includeFaceMesh ?? true,
      detectionModel: options?.detectionModel ?? 'yolo',
      segmentationTightness: options?.segmentationTightness,
      segmentationExcludeSiblings: options?.segmentationExcludeSiblings,
    };

    return this.http.post<DetectionResponse>(`${this.apiUrl}/detect`, request);
  }

  /**
   * Ask for a written description of a frame.
   *
   * The detections already on screen travel with the request, so the model is
   * told what was found rather than left to rediscover it, and the prose uses
   * the same names the rest of the interface shows.
   *
   * @param image - Base64 encoded frame.
   * @param detections - Detections the client is currently displaying.
   */
  describeScene(image: string, detections: DetectionResult[]): Observable<SceneDescription> {
    return this.http.post<SceneDescription>(`${this.apiUrl}/describe`, {
      image,
      detections,
    });
  }

  /**
   * Capture a detected object and add it to the catalog.
   *
   * @param request - Capture request with image, bounding box, and object name.
   * @returns Observable of the created catalog object.
   */
  captureDetection(request: CaptureDetectionRequest): Observable<CapturedObject> {
    return this.http.post<CapturedObject>(`${this.apiUrl}/capture`, request);
  }

  /**
   * Load catalog features for custom object recognition.
   *
   * Loads features from all catalog objects to enable matching
   * during detection.
   *
   * @returns Observable with detailed load status.
   */
  loadCatalogFeatures(): Observable<LoadCatalogResponse> {
    return this.http.post<LoadCatalogResponse>(
      `${this.apiUrl}/catalog/load`,
      {}
    );
  }

  /**
   * Read the state a camera is wanted in.
   *
   * The camera itself is ours: it is opened here with the browser device APIs
   * and nothing on the server can touch it. This is how a request made
   * somewhere else, by an agent or another service, reaches the page that can
   * actually honour it.
   *
   * @param cameraId - Which camera, when the deployment has more than one.
   * @returns Observable with the camera state.
   */
  getCameraState(cameraId = 'default'): Observable<CameraState> {
    return this.http.get<CameraState>(`${this.apiUrl}/camera`, {
      params: { camera_id: cameraId },
    });
  }

  /**
   * Record the state a camera should be in.
   *
   * Called when somebody presses the button here, so that a state chosen at the
   * screen and a state asked for elsewhere never disagree. Without it a camera
   * stopped by hand would be started again by a request made minutes ago that
   * nothing ever cleared.
   *
   * @param on - Whether the camera should be running.
   * @param cameraId - Which camera.
   * @returns Observable with the camera state after the request.
   */
  setCameraState(on: boolean, cameraId = 'default'): Observable<CameraState> {
    return this.http.put<CameraState>(`${this.apiUrl}/camera`, {
      on,
      cameraId,
    });
  }

  /**
   * Refresh features for a specific catalog object.
   *
   * @param objectId - Object UUID to refresh.
   * @returns Observable with detailed refresh status.
   */
  refreshObjectFeatures(objectId: string): Observable<RefreshFeaturesResponse> {
    return this.http.post<RefreshFeaturesResponse>(
      `${this.apiUrl}/catalog/refresh/${objectId}`,
      {}
    );
  }

  /**
   * Convert a canvas to base64 string.
   *
   * @param canvas - HTML canvas element.
   * @param quality - JPEG quality (0-1).
   * @returns Base64 encoded image.
   */
  canvasToBase64(canvas: HTMLCanvasElement, quality = 0.8): string {
    return canvas.toDataURL('image/jpeg', quality);
  }

  /**
   * Capture a frame from a video element to base64.
   *
   * @param video - HTML video element.
   * @param quality - JPEG quality (0-1).
   * @returns Base64 encoded image.
   */
  captureFrame(video: HTMLVideoElement, quality = 0.8): string {
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    const ctx = canvas.getContext('2d');
    if (!ctx) {
      throw new Error('Failed to get canvas context');
    }

    ctx.drawImage(video, 0, 0);
    return canvas.toDataURL('image/jpeg', quality);
  }
}

/** What the description endpoint answers. */
export interface SceneDescription {
  description: string | null;
  available: boolean;
  processingTimeMs?: number;
  status?: {
    enabled: boolean;
    available: boolean;
    loaded: boolean;
    loading: boolean;
    model: string;
    error: string | null;
  };
}

/**
 * Whether a camera is wanted on, and whether it is actually running.
 *
 * The two are separate answers on purpose. `desiredOn` is a wish recorded on
 * the server; `running` is decided by frames arriving for detection, so a
 * camera asked to start with no page open reads as `pending` rather than
 * claiming to be on.
 */
export interface CameraState {
  cameraId: string;
  desiredOn: boolean;
  running: boolean;
  pending: boolean;
  requestedBy: string | null;
  requestedAt: string | null;
  lastFrameAt: string | null;
  /**
   * How many subscribers are watching this camera live.
   *
   * Shown on the video itself, so that being watched from somewhere else is
   * visible to whoever is in the room. It counts connections to the stream
   * endpoint on the worker that answered; a viewer reading frames off the
   * broker cannot be counted at all, which is written down as a gap in
   * SEC-0011.
   */
  viewers: number;
}
