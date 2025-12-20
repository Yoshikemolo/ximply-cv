/**
 * Detection service.
 *
 * Handles communication with the backend detection API.
 */

import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '@env';

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface DetectionResult {
  label: string;
  confidence: number;
  bbox: BoundingBox;
  classId?: number;
  objectId?: string;
  objectName?: string;
}

export interface DetectionResponse {
  detections: DetectionResult[];
  frameWidth: number;
  frameHeight: number;
  processingTimeMs: number;
  timestamp: string;
}

export interface DetectRequest {
  image: string;
  confidenceThreshold?: number;
  iouThreshold?: number;
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
    confidenceThreshold?: number
  ): Observable<DetectionResponse> {
    const request: DetectRequest = {
      image,
      confidenceThreshold,
    };

    return this.http.post<DetectionResponse>(`${this.apiUrl}/detect`, request);
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
   * @returns Observable with load status.
   */
  loadCatalogFeatures(): Observable<{ status: string; objectsLoaded: number }> {
    return this.http.post<{ status: string; objectsLoaded: number }>(
      `${this.apiUrl}/catalog/load`,
      {}
    );
  }

  /**
   * Refresh features for a specific catalog object.
   *
   * @param objectId - Object UUID to refresh.
   * @returns Observable with refresh status.
   */
  refreshObjectFeatures(objectId: string): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(
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
