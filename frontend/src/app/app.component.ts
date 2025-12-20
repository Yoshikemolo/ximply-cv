/**
 * Root application component.
 *
 * Provides the main application layout with header, content area, and footer.
 * Manages theme and language initialization.
 */

import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterOutlet } from '@angular/router';
import { TranslateModule } from '@ngx-translate/core';

import { HeaderComponent } from '@core/components/header/header.component';
import { FooterComponent } from '@core/components/footer/footer.component';
import { SideMenuComponent } from '@core/components/side-menu/side-menu.component';
import { ThemeService } from '@core/services/theme.service';
import { I18nService } from '@core/services/i18n.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    CommonModule,
    RouterOutlet,
    TranslateModule,
    HeaderComponent,
    FooterComponent,
    SideMenuComponent,
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent implements OnInit {
  private readonly themeService = inject(ThemeService);
  private readonly i18nService = inject(I18nService);

  /** Whether the side menu is open (mobile). */
  isSideMenuOpen = false;

  ngOnInit(): void {
    // Initialize theme from stored preference or system preference
    this.themeService.initializeTheme();

    // Initialize language
    this.i18nService.initializeLanguage();
  }

  /**
   * Toggle the side menu open/closed state.
   */
  toggleSideMenu(): void {
    this.isSideMenuOpen = !this.isSideMenuOpen;
  }

  /**
   * Close the side menu.
   */
  closeSideMenu(): void {
    this.isSideMenuOpen = false;
  }
}
