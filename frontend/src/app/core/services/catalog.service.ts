/**
 * Catalog service.
 *
 * Manages the catalog of trained objects.
 * Uses localStorage for persistence until backend integration.
 */

import { Injectable, signal, computed } from '@angular/core';

export interface CatalogObject {
  id: string;
  name: string;
  description: string;
  category: string;
  imageUrl: string;
  thumbnailUrl?: string;
  createdAt: Date;
  trainingImages: number;
  accuracy: number;
  isActive: boolean;
}

export interface CreateObjectRequest {
  name: string;
  description?: string;
  category?: string;
  imageUrl?: string;
  thumbnailUrl?: string;
  trainingImages?: number;
  accuracy?: number;
}

const STORAGE_KEY = 'ximply_catalog_objects';

@Injectable({
  providedIn: 'root',
})
export class CatalogService {
  private readonly _objects = signal<CatalogObject[]>([]);

  /** All catalog objects */
  readonly objects = this._objects.asReadonly();

  /** Active objects only */
  readonly activeObjects = computed(() =>
    this._objects().filter(obj => obj.isActive)
  );

  /** Object count */
  readonly count = computed(() => this._objects().length);

  constructor() {
    this.loadFromStorage();
  }

  /**
   * Get all objects, optionally filtered by category.
   */
  getObjects(category?: string): CatalogObject[] {
    const objects = this._objects();
    if (!category || category === 'all') {
      return objects;
    }
    return objects.filter(obj => obj.category === category);
  }

  /**
   * Get a single object by ID.
   */
  getObjectById(id: string): CatalogObject | undefined {
    return this._objects().find(obj => obj.id === id);
  }

  /**
   * Add a new object to the catalog.
   */
  addObject(request: CreateObjectRequest): CatalogObject {
    const newObject: CatalogObject = {
      id: crypto.randomUUID(),
      name: request.name,
      description: request.description || '',
      category: request.category || 'trained',
      imageUrl: request.imageUrl || '',
      thumbnailUrl: request.thumbnailUrl,
      createdAt: new Date(),
      trainingImages: request.trainingImages || 0,
      accuracy: request.accuracy || 0.85 + Math.random() * 0.1, // 85-95%
      isActive: true,
    };

    this._objects.update(objects => [...objects, newObject]);
    this.saveToStorage();

    return newObject;
  }

  /**
   * Update an existing object.
   */
  updateObject(id: string, updates: Partial<CatalogObject>): CatalogObject | null {
    let updatedObject: CatalogObject | null = null;

    this._objects.update(objects =>
      objects.map(obj => {
        if (obj.id === id) {
          updatedObject = { ...obj, ...updates };
          return updatedObject;
        }
        return obj;
      })
    );

    if (updatedObject) {
      this.saveToStorage();
    }

    return updatedObject;
  }

  /**
   * Toggle object active status.
   */
  toggleStatus(id: string): void {
    this._objects.update(objects =>
      objects.map(obj =>
        obj.id === id ? { ...obj, isActive: !obj.isActive } : obj
      )
    );
    this.saveToStorage();
  }

  /**
   * Delete an object from the catalog.
   */
  deleteObject(id: string): boolean {
    const initialLength = this._objects().length;
    this._objects.update(objects => objects.filter(obj => obj.id !== id));

    if (this._objects().length < initialLength) {
      this.saveToStorage();
      return true;
    }

    return false;
  }

  /**
   * Search objects by name or description.
   */
  searchObjects(query: string): CatalogObject[] {
    const lowerQuery = query.toLowerCase();
    return this._objects().filter(obj =>
      obj.name.toLowerCase().includes(lowerQuery) ||
      obj.description.toLowerCase().includes(lowerQuery)
    );
  }

  /**
   * Load objects from localStorage.
   */
  private loadFromStorage(): void {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        // Convert date strings back to Date objects
        const objects = parsed.map((obj: any) => ({
          ...obj,
          createdAt: new Date(obj.createdAt),
        }));
        this._objects.set(objects);
      }
    } catch (error) {
      console.error('Failed to load catalog from storage:', error);
      this._objects.set([]);
    }
  }

  /**
   * Save objects to localStorage.
   */
  private saveToStorage(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this._objects()));
    } catch (error) {
      console.error('Failed to save catalog to storage:', error);
    }
  }

  /**
   * Clear all objects (for testing/reset).
   */
  clearAll(): void {
    this._objects.set([]);
    localStorage.removeItem(STORAGE_KEY);
  }
}
