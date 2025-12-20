/**
 * Objects service.
 *
 * Handles communication with the backend objects API for catalog management.
 */

import { Injectable, inject, signal } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, tap, catchError, of, forkJoin } from 'rxjs';
import { environment } from '@env';

export interface CatalogObject {
  id: string;
  name: string;
  description?: string;
  reference?: string;
  status: 'draft' | 'active' | 'archived' | 'training';
  categoryId?: string;
  thumbnailPath?: string;
  thumbnailUrl?: string;
  trainingSamples: number;
  modelConfidence?: number;
  createdAt: string;
  updatedAt?: string;
  width?: number;
  height?: number;
  depth?: number;
  weight?: number;
  price?: number;
  color?: string;
  materials?: string[];
  images?: ObjectImage[];
}

export interface ObjectImage {
  id: string;
  file_path: string;
  file_name: string;
  file_size: number;
  mime_type: string;
  width?: number;
  height?: number;
  is_primary: boolean;
  url?: string;
  bbox_x?: number;
  bbox_y?: number;
  bbox_width?: number;
  bbox_height?: number;
}

export interface CreateObjectRequest {
  name: string;
  description?: string;
  reference?: string;
  category_id?: string;
  width?: number;
  height?: number;
  depth?: number;
  weight?: number;
  price?: number;
  color?: string;
  materials?: string[];
}

export interface ObjectListResponse {
  items: CatalogObject[];
  total: number;
  page: number;
  page_size: number;
}

export interface ImageUploadResponse {
  id: string;
  file_name: string;
  file_size: number;
  url: string;
}

export interface TrainingProgress {
  object_id: string;
  status: 'uploading' | 'processing' | 'complete' | 'error';
  progress: number;
  message?: string;
  images_uploaded: number;
  total_images: number;
}

@Injectable({
  providedIn: 'root',
})
export class ObjectsService {
  private readonly http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiUrl}/${environment.apiVersion}/objects`;
  private readonly detectionUrl = `${environment.apiUrl}/${environment.apiVersion}/detection`;

  // Training progress signal
  readonly trainingProgress = signal<TrainingProgress | null>(null);

  /**
   * Get paginated list of catalog objects.
   */
  getObjects(params?: {
    page?: number;
    page_size?: number;
    search?: string;
    status?: string;
    category_id?: string;
  }): Observable<ObjectListResponse> {
    let httpParams = new HttpParams();
    if (params?.page) httpParams = httpParams.set('page', params.page.toString());
    if (params?.page_size) httpParams = httpParams.set('page_size', params.page_size.toString());
    if (params?.search) httpParams = httpParams.set('search', params.search);
    if (params?.status) httpParams = httpParams.set('status', params.status);
    if (params?.category_id) httpParams = httpParams.set('category_id', params.category_id);

    return this.http.get<ObjectListResponse>(this.apiUrl, { params: httpParams });
  }

  /**
   * Get a single object by ID.
   */
  getObject(id: string): Observable<CatalogObject> {
    return this.http.get<CatalogObject>(`${this.apiUrl}/${id}`);
  }

  /**
   * Create a new catalog object.
   */
  createObject(request: CreateObjectRequest): Observable<CatalogObject> {
    return this.http.post<CatalogObject>(this.apiUrl, request);
  }

  /**
   * Update an existing object.
   */
  updateObject(id: string, updates: Partial<CreateObjectRequest>): Observable<CatalogObject> {
    return this.http.put<CatalogObject>(`${this.apiUrl}/${id}`, updates);
  }

  /**
   * Delete an object.
   */
  deleteObject(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${id}`);
  }

  /**
   * Upload a training image for an object.
   */
  uploadImage(
    objectId: string,
    imageData: string | Blob,
    isPrimary = false,
    bbox?: { x: number; y: number; width: number; height: number }
  ): Observable<ImageUploadResponse> {
    const formData = new FormData();

    // Handle base64 string or Blob
    if (typeof imageData === 'string') {
      const blob = this.base64ToBlob(imageData);
      formData.append('file', blob, `image_${Date.now()}.jpg`);
    } else {
      formData.append('file', imageData);
    }

    formData.append('is_primary', isPrimary.toString());

    if (bbox) {
      formData.append('bbox_x', bbox.x.toString());
      formData.append('bbox_y', bbox.y.toString());
      formData.append('bbox_width', bbox.width.toString());
      formData.append('bbox_height', bbox.height.toString());
    }

    return this.http.post<ImageUploadResponse>(
      `${this.apiUrl}/${objectId}/images`,
      formData
    );
  }

  /**
   * Get all images for an object.
   */
  getObjectImages(objectId: string): Observable<ObjectImage[]> {
    return this.http.get<ObjectImage[]>(`${this.apiUrl}/${objectId}/images`);
  }

  /**
   * Delete an image from an object.
   */
  deleteImage(objectId: string, imageId: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/${objectId}/images/${imageId}`);
  }

  /**
   * Train an object with multiple images.
   * Creates the object and uploads all images, then refreshes features.
   */
  async trainObject(
    name: string,
    description: string,
    images: Array<{ data: string; bbox?: { x: number; y: number; width: number; height: number } }>
  ): Promise<CatalogObject> {
    // Reset progress
    this.trainingProgress.set({
      object_id: '',
      status: 'uploading',
      progress: 0,
      message: 'Creating object...',
      images_uploaded: 0,
      total_images: images.length,
    });

    try {
      // Step 1: Create the object
      const object = await this.createObject({
        name,
        description,
      }).toPromise();

      if (!object) {
        throw new Error('Failed to create object');
      }

      this.trainingProgress.update(p => p ? {
        ...p,
        object_id: object.id,
        progress: 5,
        message: 'Uploading images...',
      } : null);

      // Step 2: Upload all images
      for (let i = 0; i < images.length; i++) {
        const img = images[i];
        const isPrimary = i === 0;

        await this.uploadImage(object.id, img.data, isPrimary, img.bbox).toPromise();

        const uploadProgress = 5 + ((i + 1) / images.length) * 70;
        this.trainingProgress.update(p => p ? {
          ...p,
          progress: uploadProgress,
          images_uploaded: i + 1,
          message: `Uploading image ${i + 1}/${images.length}...`,
        } : null);
      }

      // Step 3: Activate the object
      this.trainingProgress.update(p => p ? {
        ...p,
        progress: 80,
        message: 'Activating object...',
      } : null);

      await this.updateObject(object.id, { status: 'active' } as any).toPromise();

      // Step 4: Refresh catalog features
      this.trainingProgress.update(p => p ? {
        ...p,
        progress: 90,
        message: 'Extracting features...',
      } : null);

      await this.refreshObjectFeatures(object.id).toPromise();

      // Complete
      this.trainingProgress.update(p => p ? {
        ...p,
        status: 'complete',
        progress: 100,
        message: 'Training complete!',
      } : null);

      // Return updated object
      const updatedObject = await this.getObject(object.id).toPromise();
      return updatedObject || object;

    } catch (error: any) {
      this.trainingProgress.update(p => p ? {
        ...p,
        status: 'error',
        message: error.message || 'Training failed',
      } : null);
      throw error;
    }
  }

  /**
   * Add more training images to an existing object.
   */
  async addTrainingImages(
    objectId: string,
    images: Array<{ data: string; bbox?: { x: number; y: number; width: number; height: number } }>
  ): Promise<CatalogObject> {
    this.trainingProgress.set({
      object_id: objectId,
      status: 'uploading',
      progress: 0,
      message: 'Uploading new images...',
      images_uploaded: 0,
      total_images: images.length,
    });

    try {
      // Upload all new images
      for (let i = 0; i < images.length; i++) {
        const img = images[i];
        await this.uploadImage(objectId, img.data, false, img.bbox).toPromise();

        const uploadProgress = ((i + 1) / images.length) * 80;
        this.trainingProgress.update(p => p ? {
          ...p,
          progress: uploadProgress,
          images_uploaded: i + 1,
          message: `Uploading image ${i + 1}/${images.length}...`,
        } : null);
      }

      // Refresh features
      this.trainingProgress.update(p => p ? {
        ...p,
        progress: 90,
        message: 'Updating features...',
      } : null);

      await this.refreshObjectFeatures(objectId).toPromise();

      // Complete
      this.trainingProgress.update(p => p ? {
        ...p,
        status: 'complete',
        progress: 100,
        message: 'Images added successfully!',
      } : null);

      const updatedObject = await this.getObject(objectId).toPromise();
      if (!updatedObject) {
        throw new Error('Failed to fetch updated object');
      }
      return updatedObject;

    } catch (error: any) {
      this.trainingProgress.update(p => p ? {
        ...p,
        status: 'error',
        message: error.message || 'Failed to add images',
      } : null);
      throw error;
    }
  }

  /**
   * Load all catalog features for detection.
   */
  loadCatalogFeatures(): Observable<{ status: string; objectsLoaded: number }> {
    return this.http.post<{ status: string; objectsLoaded: number }>(
      `${this.detectionUrl}/catalog/load`,
      {}
    );
  }

  /**
   * Refresh features for a specific object.
   */
  refreshObjectFeatures(objectId: string): Observable<{ status: string }> {
    return this.http.post<{ status: string }>(
      `${this.detectionUrl}/catalog/refresh/${objectId}`,
      {}
    );
  }

  /**
   * Set object status (active/archived/draft).
   */
  setObjectStatus(id: string, status: 'active' | 'archived' | 'draft'): Observable<CatalogObject> {
    return this.http.put<CatalogObject>(`${this.apiUrl}/${id}`, { status });
  }

  /**
   * Convert base64 data URL to Blob.
   */
  private base64ToBlob(base64: string): Blob {
    // Remove data URL prefix if present
    const base64Data = base64.includes(',') ? base64.split(',')[1] : base64;
    const byteCharacters = atob(base64Data);
    const byteNumbers = new Array(byteCharacters.length);

    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }

    const byteArray = new Uint8Array(byteNumbers);
    return new Blob([byteArray], { type: 'image/jpeg' });
  }
}
