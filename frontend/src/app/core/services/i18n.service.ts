/**
 * Internationalization service.
 *
 * Manages language selection and translation loading.
 */

import { Injectable, inject, signal, computed } from '@angular/core';
import { TranslateService } from '@ngx-translate/core';
import { environment } from '@env';

const LANGUAGE_STORAGE_KEY = 'ximply-vision-language';

export interface Language {
  code: string;
  name: string;
  nativeName: string;
}

@Injectable({
  providedIn: 'root',
})
export class I18nService {
  private readonly translate = inject(TranslateService);

  /** Available languages. */
  readonly languages: Language[] = [
    { code: 'en', name: 'English', nativeName: 'English' },
    { code: 'es', name: 'Spanish', nativeName: 'Espanol' },
  ];

  /** Current language code. */
  private readonly _currentLanguage = signal<string>(
    environment.defaultLanguage
  );

  /** Current language code (readonly). */
  readonly currentLanguage = this._currentLanguage.asReadonly();

  /** Current language object. */
  readonly currentLanguageInfo = computed(() =>
    this.languages.find((l) => l.code === this._currentLanguage())
  );

  /**
   * Initialize language from stored preference or browser setting.
   */
  initializeLanguage(): void {
    // Set available languages
    this.translate.addLangs(environment.supportedLanguages);
    this.translate.setDefaultLang(environment.defaultLanguage);

    // Try to get stored preference
    const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (stored && environment.supportedLanguages.includes(stored)) {
      this.setLanguage(stored);
      return;
    }

    // Try to detect browser language
    const browserLang = this.translate.getBrowserLang();
    if (browserLang && environment.supportedLanguages.includes(browserLang)) {
      this.setLanguage(browserLang);
      return;
    }

    // Fall back to default
    this.setLanguage(environment.defaultLanguage);
  }

  /**
   * Set the current language.
   *
   * @param languageCode - ISO language code.
   */
  setLanguage(languageCode: string): void {
    if (!environment.supportedLanguages.includes(languageCode)) {
      console.warn(`Language ${languageCode} is not supported`);
      return;
    }

    this._currentLanguage.set(languageCode);
    this.translate.use(languageCode);
    localStorage.setItem(LANGUAGE_STORAGE_KEY, languageCode);

    // Update HTML lang attribute
    document.documentElement.setAttribute('lang', languageCode);
  }

  /**
   * Get instant translation for a key.
   *
   * @param key - Translation key.
   * @param params - Optional interpolation parameters.
   * @returns Translated string.
   */
  instant(key: string, params?: object): string {
    return this.translate.instant(key, params);
  }
}
