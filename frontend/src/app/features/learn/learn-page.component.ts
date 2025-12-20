import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule } from '@ngx-translate/core';

@Component({
  selector: 'app-learn-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './learn-page.component.html',
  styleUrl: './learn-page.component.scss',
})
export class LearnPageComponent {
  currentStep = signal<'upload' | 'annotate' | 'train' | 'complete'>('upload');
  uploadedImages = signal<UploadedImage[]>([]);
  selectedImage = signal<UploadedImage | null>(null);
  objectName = signal('');
  isTraining = signal(false);
  trainingProgress = signal(0);
  errorMessage = signal<string | null>(null);

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = input.files;

    if (!files || files.length === 0) return;

    const newImages: UploadedImage[] = [];

    Array.from(files).forEach(file => {
      if (!file.type.startsWith('image/')) return;

      const reader = new FileReader();
      reader.onload = (e) => {
        const image: UploadedImage = {
          id: crypto.randomUUID(),
          file,
          preview: e.target?.result as string,
          annotations: [],
        };
        newImages.push(image);
        this.uploadedImages.update(imgs => [...imgs, image]);
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
  }

  nextStep(): void {
    const steps: Array<'upload' | 'annotate' | 'train' | 'complete'> = [
      'upload', 'annotate', 'train', 'complete'
    ];
    const currentIndex = steps.indexOf(this.currentStep());
    if (currentIndex < steps.length - 1) {
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
    switch (this.currentStep()) {
      case 'upload':
        return this.uploadedImages().length >= 5 && this.objectName().trim().length > 0;
      case 'annotate':
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

    // Simulate training progress
    const interval = setInterval(() => {
      this.trainingProgress.update(p => {
        const newProgress = p + Math.random() * 10;
        if (newProgress >= 100) {
          clearInterval(interval);
          this.isTraining.set(false);
          this.nextStep();
          return 100;
        }
        return newProgress;
      });
    }, 500);
  }

  resetWizard(): void {
    this.currentStep.set('upload');
    this.uploadedImages.set([]);
    this.selectedImage.set(null);
    this.objectName.set('');
    this.trainingProgress.set(0);
    this.errorMessage.set(null);
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
