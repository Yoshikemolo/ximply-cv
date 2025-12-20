/**
 * Theme management service.
 *
 * Handles theme switching between light and dark modes.
 * Persists theme preference to localStorage.
 */

import { Injectable, signal, computed } from '@angular/core';

export type Theme = 'light' | 'dark' | 'system';

const THEME_STORAGE_KEY = 'ximply-vision-theme';

@Injectable({
  providedIn: 'root',
})
export class ThemeService {
  /** Current theme setting. */
  private readonly _theme = signal<Theme>('system');

  /** Current theme setting (readonly). */
  readonly theme = this._theme.asReadonly();

  /** Whether dark mode is active. */
  readonly isDarkMode = computed(() => {
    const theme = this._theme();
    if (theme === 'system') {
      return this.getSystemPreference() === 'dark';
    }
    return theme === 'dark';
  });

  /**
   * Initialize theme from stored preference or system preference.
   */
  initializeTheme(): void {
    const stored = localStorage.getItem(THEME_STORAGE_KEY) as Theme | null;
    if (stored && ['light', 'dark', 'system'].includes(stored)) {
      this._theme.set(stored);
    }
    this.applyTheme();

    // Listen for system preference changes
    if (window.matchMedia) {
      window
        .matchMedia('(prefers-color-scheme: dark)')
        .addEventListener('change', () => {
          if (this._theme() === 'system') {
            this.applyTheme();
          }
        });
    }
  }

  /**
   * Set the theme.
   *
   * @param theme - Theme to apply.
   */
  setTheme(theme: Theme): void {
    this._theme.set(theme);
    localStorage.setItem(THEME_STORAGE_KEY, theme);
    this.applyTheme();
  }

  /**
   * Toggle between light and dark themes.
   */
  toggleTheme(): void {
    const current = this._theme();
    if (current === 'system') {
      // When system, toggle to opposite of current system preference
      const systemPref = this.getSystemPreference();
      this.setTheme(systemPref === 'dark' ? 'light' : 'dark');
    } else {
      this.setTheme(current === 'dark' ? 'light' : 'dark');
    }
  }

  /**
   * Get system color scheme preference.
   */
  private getSystemPreference(): 'light' | 'dark' {
    if (
      window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches
    ) {
      return 'dark';
    }
    return 'light';
  }

  /**
   * Apply current theme to document.
   */
  private applyTheme(): void {
    const theme = this._theme();
    const effectiveTheme =
      theme === 'system' ? this.getSystemPreference() : theme;

    document.documentElement.setAttribute('data-theme', effectiveTheme);
  }
}
