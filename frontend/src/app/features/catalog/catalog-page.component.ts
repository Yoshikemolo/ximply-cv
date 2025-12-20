import { Component, inject, signal, OnInit, effect } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';
import { CatalogService, CatalogObject } from '@core/services/catalog.service';

@Component({
  selector: 'app-catalog-page',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TranslateModule],
  templateUrl: './catalog-page.component.html',
  styleUrl: './catalog-page.component.scss',
})
export class CatalogPageComponent implements OnInit {
  private readonly catalogService = inject(CatalogService);

  filteredObjects = signal<CatalogObject[]>([]);
  searchQuery = signal('');
  selectedCategory = signal<string>('all');
  viewMode = signal<'grid' | 'list'>('grid');
  isLoading = signal(true);
  selectedObject = signal<CatalogObject | null>(null);
  showDeleteModal = signal(false);
  objectToDelete = signal<CatalogObject | null>(null);

  categories = signal<string[]>(['all', 'trained', 'imported', 'system']);

  constructor() {
    // React to changes in catalog service
    effect(() => {
      const objects = this.catalogService.objects();
      this.applyFilters();
    });
  }

  ngOnInit(): void {
    this.loadObjects();
  }

  private async loadObjects(): Promise<void> {
    this.isLoading.set(true);

    // Small delay to show loading state
    setTimeout(() => {
      this.applyFilters();
      this.isLoading.set(false);
    }, 300);
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
    let filtered = this.catalogService.objects();

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

    this.catalogService.deleteObject(obj.id);

    if (this.selectedObject()?.id === obj.id) {
      this.selectedObject.set(null);
    }

    this.cancelDelete();
  }

  toggleObjectStatus(obj: CatalogObject): void {
    this.catalogService.toggleStatus(obj.id);

    // Update selected object if it was toggled
    if (this.selectedObject()?.id === obj.id) {
      const updated = this.catalogService.getObjectById(obj.id);
      if (updated) {
        this.selectedObject.set(updated);
      }
    }
  }

  getAccuracyClass(accuracy: number): string {
    if (accuracy >= 0.9) return 'high';
    if (accuracy >= 0.7) return 'medium';
    return 'low';
  }
}
