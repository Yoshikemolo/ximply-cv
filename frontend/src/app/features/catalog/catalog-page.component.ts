import { Component, inject, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';

@Component({
  selector: 'app-catalog-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './catalog-page.component.html',
  styleUrl: './catalog-page.component.scss',
})
export class CatalogPageComponent implements OnInit {
  objects = signal<CatalogObject[]>([]);
  filteredObjects = signal<CatalogObject[]>([]);
  searchQuery = signal('');
  selectedCategory = signal<string>('all');
  viewMode = signal<'grid' | 'list'>('grid');
  isLoading = signal(true);
  selectedObject = signal<CatalogObject | null>(null);
  showDeleteModal = signal(false);
  objectToDelete = signal<CatalogObject | null>(null);

  categories = signal<string[]>(['all', 'trained', 'imported', 'system']);

  ngOnInit(): void {
    this.loadObjects();
  }

  private async loadObjects(): Promise<void> {
    this.isLoading.set(true);

    // Mock data - will be replaced with real API call
    setTimeout(() => {
      const mockObjects: CatalogObject[] = [
        {
          id: '1',
          name: 'Product Box A',
          description: 'Standard product box for shipping',
          category: 'trained',
          imageUrl: '',
          createdAt: new Date('2024-01-15'),
          trainingImages: 25,
          accuracy: 0.95,
          isActive: true,
        },
        {
          id: '2',
          name: 'Warehouse Label',
          description: 'QR code label for inventory tracking',
          category: 'trained',
          imageUrl: '',
          createdAt: new Date('2024-01-20'),
          trainingImages: 50,
          accuracy: 0.98,
          isActive: true,
        },
        {
          id: '3',
          name: 'Safety Equipment',
          description: 'PPE detection for safety compliance',
          category: 'imported',
          imageUrl: '',
          createdAt: new Date('2024-02-01'),
          trainingImages: 0,
          accuracy: 0.92,
          isActive: true,
        },
      ];

      this.objects.set(mockObjects);
      this.applyFilters();
      this.isLoading.set(false);
    }, 500);
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
    let filtered = this.objects();

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

  async deleteObject(): Promise<void> {
    const obj = this.objectToDelete();
    if (!obj) return;

    // Mock delete - will be replaced with real API call
    this.objects.update(objects => objects.filter(o => o.id !== obj.id));
    this.applyFilters();

    if (this.selectedObject()?.id === obj.id) {
      this.selectedObject.set(null);
    }

    this.cancelDelete();
  }

  toggleObjectStatus(obj: CatalogObject): void {
    this.objects.update(objects =>
      objects.map(o =>
        o.id === obj.id ? { ...o, isActive: !o.isActive } : o
      )
    );
    this.applyFilters();
  }

  getAccuracyClass(accuracy: number): string {
    if (accuracy >= 0.9) return 'high';
    if (accuracy >= 0.7) return 'medium';
    return 'low';
  }
}

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
