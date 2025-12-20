/**
 * Application footer component.
 *
 * Displays copyright and version information.
 */

import { Component, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TranslateModule } from '@ngx-translate/core';
import { environment } from '@env';

@Component({
  selector: 'app-footer',
  standalone: true,
  imports: [CommonModule, TranslateModule],
  templateUrl: './footer.component.html',
  styleUrl: './footer.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FooterComponent {
  /** Current year. */
  readonly currentYear = new Date().getFullYear();

  /** Application version. */
  readonly version = environment.appVersion;
}
