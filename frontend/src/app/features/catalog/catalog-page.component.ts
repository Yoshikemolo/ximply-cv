import { Component, inject, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { ObjectsService, CatalogObject as BackendObject } from '@core/services/objects.service';
import { environment } from '@env';

// Local interface for catalog display
interface CatalogObject {
  id: string;
  name: string;
  description: string;
  category: string;
  imageUrl: string;
  createdAt: Date;
  trainingImages: number;
  accuracy: number;
  isActive: boolean;
}

@Component({
  selector: 'app-catalog-page',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './catalog-page.component.html',
  styleUrl: './catalog-page.component.scss',
})
export class CatalogPageComponent implements OnInit {
  private readonly objectsService = inject(ObjectsService);

  allObjects = signal<CatalogObject[]>([]);
  filteredObjects = signal<CatalogObject[]>([]);
  searchQuery = signal('');
  selectedCategory = signal<string>('all');
  viewMode = signal<'grid' | 'list'>('grid');
  isLoading = signal(true);
  selectedObject = signal<CatalogObject | null>(null);
  showDeleteModal = signal(false);
  objectToDelete = signal<CatalogObject | null>(null);
  showForgetAllModal = signal(false);
  isDeleting = signal(false);

  categories = signal<string[]>(['all', 'trained', 'imported', 'system']);

  ngOnInit(): void {
    this.loadObjects();
  }

  private loadObjects(): void {
    this.isLoading.set(true);

    this.objectsService.getObjects({ page_size: 100 }).subscribe({
      next: (response) => {
        const objects = response.items.map(obj => this.mapToDisplayObject(obj));
        this.allObjects.set(objects);
        this.applyFilters();
        this.isLoading.set(false);
      },
      error: (err) => {
        console.error('Failed to load objects:', err);
        this.isLoading.set(false);
      },
    });
  }

  private mapToDisplayObject(obj: BackendObject): CatalogObject {
    // Extract base URL from apiUrl (remove /api suffix)
    const baseUrl = environment.apiUrl.replace(/\/api$/, '');
    const thumbnailUrl = obj.thumbnailUrl || obj.thumbnailPath || '';
    // Prepend base URL if it's a relative path
    const imageUrl = thumbnailUrl.startsWith('/') ? `${baseUrl}${thumbnailUrl}` : thumbnailUrl;

    return {
      id: obj.id,
      name: obj.name,
      description: obj.description || '',
      category: 'trained', // Objects from backend are trained
      imageUrl,
      createdAt: new Date(obj.createdAt),
      trainingImages: obj.trainingSamples,
      accuracy: obj.modelConfidence || 0.85,
      isActive: obj.status === 'active',
    };
  }

  onSearchChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.searchQuery.set(input.value);
    this.applyFilters();
  }

  onCategoryChange(category: string): void {
    this.selectedCategory.set(category);
    this.applyFilters();
  }

  toggleViewMode(): void {
    this.viewMode.update(mode => mode === 'grid' ? 'list' : 'grid');
  }

  private applyFilters(): void {
    let filtered = this.allObjects();

    // Apply search filter
    const query = this.searchQuery().toLowerCase();
    if (query) {
      filtered = filtered.filter(obj =>
        obj.name.toLowerCase().includes(query) ||
        obj.description.toLowerCase().includes(query)
      );
    }

    // Apply category filter
    const category = this.selectedCategory();
    if (category !== 'all') {
      filtered = filtered.filter(obj => obj.category === category);
    }

    this.filteredObjects.set(filtered);
  }

  selectObject(obj: CatalogObject): void {
    this.selectedObject.set(obj);
  }

  closeDetails(): void {
    this.selectedObject.set(null);
  }

  confirmDelete(obj: CatalogObject): void {
    this.objectToDelete.set(obj);
    this.showDeleteModal.set(true);
  }

  cancelDelete(): void {
    this.objectToDelete.set(null);
    this.showDeleteModal.set(false);
  }

  deleteObject(): void {
    const obj = this.objectToDelete();
    if (!obj) return;

    this.objectsService.deleteObject(obj.id).subscribe({
      next: () => {
        // Remove from local list
        this.allObjects.update(objects => objects.filter(o => o.id !== obj.id));
        this.applyFilters();

        if (this.selectedObject()?.id === obj.id) {
          this.selectedObject.set(null);
        }
        this.cancelDelete();
      },
      error: (err) => {
        console.error('Failed to delete object:', err);
        this.cancelDelete();
      },
    });
  }

  toggleObjectStatus(obj: CatalogObject): void {
    const newStatus = obj.isActive ? 'archived' : 'active';

    this.objectsService.setObjectStatus(obj.id, newStatus).subscribe({
      next: (updated) => {
        // Update in local list
        this.allObjects.update(objects =>
          objects.map(o =>
            o.id === obj.id ? { ...o, isActive: updated.status === 'active' } : o
          )
        );
        this.applyFilters();

        // Update selected object if it was toggled
        if (this.selectedObject()?.id === obj.id) {
          this.selectedObject.update(selected =>
            selected ? { ...selected, isActive: updated.status === 'active' } : null
          );
        }
      },
      error: (err) => {
        console.error('Failed to update object status:', err);
      },
    });
  }

  getAccuracyClass(accuracy: number): string {
    if (accuracy >= 0.9) return 'high';
    if (accuracy >= 0.7) return 'medium';
    return 'low';
  }

  // Forget All functionality
  confirmForgetAll(): void {
    this.showForgetAllModal.set(true);
  }

  cancelForgetAll(): void {
    this.showForgetAllModal.set(false);
  }

  forgetAll(): void {
    this.isDeleting.set(true);

    this.objectsService.deleteAllObjects().subscribe({
      next: () => {
        // Clear local state
        this.allObjects.set([]);
        this.filteredObjects.set([]);
        this.selectedObject.set(null);
        this.showForgetAllModal.set(false);
        this.isDeleting.set(false);
      },
      error: (err) => {
        console.error('Failed to delete all objects:', err);
        this.isDeleting.set(false);
        this.showForgetAllModal.set(false);
      },
    });
  }
}
