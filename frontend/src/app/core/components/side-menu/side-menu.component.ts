/**
 * Side menu component for mobile navigation.
 *
 * Provides a slide-out menu with navigation and user actions.
 */

import {
  Component,
  EventEmitter,
  Input,
  Output,
  inject,
  computed,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

import { AuthService } from '@core/services/auth.service';
import { ThemeService } from '@core/services/theme.service';
import { I18nService } from '@core/services/i18n.service';
import { environment } from '@env';

@Component({
  selector: 'app-side-menu',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive, TranslateModule],
  templateUrl: './side-menu.component.html',
  styleUrl: './side-menu.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SideMenuComponent {
  private readonly authService = inject(AuthService);
  private readonly themeService = inject(ThemeService);
  private readonly i18nService = inject(I18nService);

  /** Whether the menu is open. */
  @Input() isOpen = false;

  /** Emitted when menu should close. */
  @Output() closed = new EventEmitter<void>();

  /** Current user. */
  readonly user = this.authService.user;

  /** Whether user is authenticated. */
  readonly isAuthenticated = this.authService.isAuthenticated;

  /** Current theme. */
  readonly isDarkMode = this.themeService.isDarkMode;

  /** Current language. */
  readonly currentLanguage = this.i18nService.currentLanguage;

  /** Logo path based on theme. */
  readonly logoPath = computed(() =>
    this.isDarkMode()
      ? 'assets/images/dark-color-x-icon.svg'
      : 'assets/images/light-color-x-icon.svg'
  );

  /** Available languages. */
  readonly languages = this.i18nService.languages;

  /** App version. */
  readonly version = environment.appVersion;

  /** Current year. */
  readonly currentYear = new Date().getFullYear();

  /** Navigation items. */
  readonly navItems = [
    {
      path: '/view',
      labelKey: 'nav.view',
      icon: 'eye',
      permission: 'detection:view',
    },
    {
      path: '/learn',
      labelKey: 'nav.learn',
      icon: 'book',
      permission: 'objects:write',
    },
    {
      path: '/catalog',
      labelKey: 'nav.catalog',
      icon: 'grid',
      permission: 'objects:read',
    },
    {
      path: '/integrations',
      labelKey: 'nav.integrations',
      icon: 'link',
      permission: 'events:manage',
    },
    {
      path: '/admin',
      labelKey: 'nav.admin',
      icon: 'settings',
      permission: 'admin:full',
    },
  ];

  /**
   * Get filtered navigation items based on user permissions.
   */
  get visibleNavItems() {
    return this.navItems.filter((item) =>
      this.authService.hasPermission(item.permission)
    );
  }

  /**
   * Close the menu.
   */
  close(): void {
    this.closed.emit();
  }

  /**
   * Handle backdrop click.
   */
  onBackdropClick(): void {
    this.close();
  }

  /**
   * Handle nav link click.
   */
  onNavClick(): void {
    this.close();
  }

  /**
   * Toggle theme.
   */
  toggleTheme(): void {
    this.themeService.toggleTheme();
  }

  /**
   * Set language.
   */
  setLanguage(code: string): void {
    this.i18nService.setLanguage(code);
  }

  /**
   * Logout user.
   */
  logout(): void {
    this.close();
    this.authService.logout();
  }
}
