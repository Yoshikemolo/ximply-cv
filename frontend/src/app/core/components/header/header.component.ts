/**
 * Application header component.
 *
 * Provides navigation, branding, and user actions.
 */

import {
  Component,
  EventEmitter,
  Input,
  Output,
  inject,
  ChangeDetectionStrategy,
  computed,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

import { AuthService } from '@core/services/auth.service';
import { ThemeService } from '@core/services/theme.service';
import { I18nService } from '@core/services/i18n.service';
import { AccelerationBadgeComponent } from '@shared/components/acceleration-badge/acceleration-badge.component';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive, TranslateModule, AccelerationBadgeComponent],
  templateUrl: './header.component.html',
  styleUrl: './header.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HeaderComponent {
  private readonly authService = inject(AuthService);
  private readonly themeService = inject(ThemeService);
  private readonly i18nService = inject(I18nService);

  /** Whether the side menu is open. */
  @Input() isSideMenuOpen = false;

  /** Emitted when menu toggle button is clicked. */
  @Output() menuToggle = new EventEmitter<void>();

  /** Current user. */
  readonly user = this.authService.user;

  /** Whether user is authenticated. */
  readonly isAuthenticated = this.authService.isAuthenticated;

  /** Current theme. */
  readonly isDarkMode = this.themeService.isDarkMode;

  /** Logo path based on current theme. */
  readonly logoPath = computed(() =>
    this.isDarkMode()
      ? 'assets/images/dark-color-x-icon.svg'
      : 'assets/images/light-color-x-icon.svg'
  );

  /** Current language. */
  readonly currentLanguage = this.i18nService.currentLanguage;

  /** Available languages. */
  readonly languages = this.i18nService.languages;

  /** Navigation items. */
  readonly navItems = [
    { path: '/view', labelKey: 'nav.view', permission: 'detection:view' },
    { path: '/learn', labelKey: 'nav.learn', permission: 'objects:write' },
    { path: '/catalog', labelKey: 'nav.catalog', permission: 'objects:read' },
    { path: '/admin', labelKey: 'nav.admin', permission: 'admin:full' },
  ];

  /**
   * Get filtered navigation items based on user permissions.
   * If user has no permissions, show all items (route guards handle access).
   */
  get visibleNavItems() {
    const userPermissions = this.authService.permissions();

    // If user has no permissions assigned, show all nav items
    // Route guards will handle actual access control
    if (userPermissions.length === 0) {
      return this.navItems;
    }

    return this.navItems.filter((item) =>
      this.authService.hasPermission(item.permission)
    );
  }

  /**
   * Toggle theme between light and dark.
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
    this.authService.logout();
  }

  /**
   * Emit menu toggle event.
   */
  onMenuToggle(): void {
    this.menuToggle.emit();
  }
}
