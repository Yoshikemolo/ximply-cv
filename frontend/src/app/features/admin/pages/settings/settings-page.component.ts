import { Component, inject, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TranslateModule, TranslateService } from '@ngx-translate/core';
import { ThemeService } from '@core/services/theme.service';

@Component({
  selector: 'app-settings-page',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslateModule],
  templateUrl: './settings-page.component.html',
  styleUrl: './settings-page.component.scss',
})
export class SettingsPageComponent implements OnInit {
  private readonly themeService = inject(ThemeService);
  private readonly translate = inject(TranslateService);

  currentTheme = signal<'light' | 'dark' | 'system'>('system');
  currentLanguage = signal<string>('en');
  detectionSettings = signal<DetectionSettings>({
    defaultConfidenceThreshold: 0.5,
    maxDetectionsPerFrame: 100,
    enableGpuAcceleration: true,
  });
  storageSettings = signal<StorageSettings>({
    maxStorageSize: 10,
    autoCleanupEnabled: true,
    retentionDays: 30,
  });
  isSaving = signal(false);
  saveSuccess = signal(false);

  ngOnInit(): void {
    this.loadSettings();
  }

  private loadSettings(): void {
    // Load theme
    const savedTheme = localStorage.getItem('theme') as 'light' | 'dark' | 'system' || 'system';
    this.currentTheme.set(savedTheme);

    // Load language
    this.currentLanguage.set(this.translate.currentLang || 'en');
  }

  onThemeChange(theme: 'light' | 'dark' | 'system'): void {
    this.currentTheme.set(theme);
    this.themeService.setTheme(theme);
  }

  onLanguageChange(lang: string): void {
    this.currentLanguage.set(lang);
    this.translate.use(lang);
    localStorage.setItem('language', lang);
  }

  async saveDetectionSettings(): Promise<void> {
    this.isSaving.set(true);
    this.saveSuccess.set(false);

    // Mock save - will be replaced with real API call
    await new Promise(resolve => setTimeout(resolve, 500));

    this.isSaving.set(false);
    this.saveSuccess.set(true);
    setTimeout(() => this.saveSuccess.set(false), 3000);
  }

  async saveStorageSettings(): Promise<void> {
    this.isSaving.set(true);
    this.saveSuccess.set(false);

    // Mock save - will be replaced with real API call
    await new Promise(resolve => setTimeout(resolve, 500));

    this.isSaving.set(false);
    this.saveSuccess.set(true);
    setTimeout(() => this.saveSuccess.set(false), 3000);
  }
}

interface DetectionSettings {
  defaultConfidenceThreshold: number;
  maxDetectionsPerFrame: number;
  enableGpuAcceleration: boolean;
}

interface StorageSettings {
  maxStorageSize: number;
  autoCleanupEnabled: boolean;
  retentionDays: number;
}
